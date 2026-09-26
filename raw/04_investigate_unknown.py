#!/usr/bin/env python3
"""
Stage 04 (optional): summarise the unexplained restarts from stage 03.

Prints their share of acquisitions, their split by lab, the downtime
before each was resumed and the hour of day the log went silent. Counts
are per restart event unless labelled samples. Writes nothing.
"""
import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from paths import data


FMT = "%Y/%m/%d %H:%M:%S"


def acq_key(row):
    """One restart event: (rig, restart time)."""
    return (row["system"], row["restart_timestamp"])


# The denominator: every acquisition 02 found.
with open(data("sample_acquisition_groups.csv")) as f:
    TOTAL_ACQUISITIONS = len({r["acquisition_key"] for r in csv.DictReader(f)})


with open(data("restart_events_full.csv")) as f:
    still_unknown = [r for r in csv.DictReader(f) if r["category"] == "true unknown"]

true_unknown_acqs = set(acq_key(r) for r in still_unknown)
print(f"Unexplained restarts: {len(still_unknown)} samples, {len(true_unknown_acqs)} events")
print(f"As a fraction of all {TOTAL_ACQUISITIONS} acquisitions: "
      f"{len(true_unknown_acqs)}/{TOTAL_ACQUISITIONS} = {len(true_unknown_acqs)/TOTAL_ACQUISITIONS:.1%}\n")

lab_samples = Counter(r["lab"] for r in still_unknown)
lab_acqs = defaultdict(set)
for r in still_unknown:
    lab_acqs[r["lab"]].add(acq_key(r))
print(f"{'lab':16s} {'samples':>8s} {'acquisitions':>13s}")
for lab in sorted(lab_samples, key=lambda l: -lab_samples[l]):
    print(f"{lab:16s} {lab_samples[lab]:8d} {len(lab_acqs[lab]):13d}")

# Downtime per event, not per sample's copy of the log.
gaps_by_acq = {}
for row in still_unknown:
    if row["gap_seconds"] in ("", None):
        continue
    g = float(row["gap_seconds"])
    t2 = datetime.strptime(row["restart_timestamp"], FMT)
    gaps_by_acq[acq_key(row)] = (t2 - timedelta(seconds=g), g)

gaps = list(gaps_by_acq.values())
print(f"\nGap between last log line and resumed header ({len(gaps)} unique acquisitions):")
buckets = Counter()
for _, g in gaps:
    if g < 1800:
        buckets["<30 min"] += 1
    elif g < 3600:
        buckets["30-60 min"] += 1
    elif g < 3600 * 6:
        buckets["1-6 hours"] += 1
    elif g < 3600 * 24:
        buckets["6-24 hours"] += 1
    else:
        buckets[">24 hours"] += 1

for k in ["<30 min", "30-60 min", "1-6 hours", "6-24 hours", ">24 hours"]:
    print(f"  {buckets.get(k, 0):4d}  {k}")

gap_secs = sorted(g for _, g in gaps)
if gap_secs:
    print(f"\nmedian gap: {gap_secs[len(gap_secs)//2]/60:.1f} min")
    print(f"max gap: {max(gap_secs)/3600:.1f} hours")

long_gap_hours = [t1.hour for t1, g in gaps if g >= 3600]
hour_counter = Counter(long_gap_hours)
print(f"\nHour-of-day the log went silent, for the {len(long_gap_hours)} acquisitions with a >=1hr gap:")
for h in range(24):
    n = hour_counter.get(h, 0)
    if n:
        print(f"  {h:02d}:00  {n:3d}  {'#'*n}")
