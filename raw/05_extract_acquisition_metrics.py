#!/usr/bin/env python3
"""
Stage 05: imaging time, tile positions and sections per acquisition, from
unique_acqlogs.txt. These are the denominators for the restart rates.

Imaging time is the sum of the per-section durations the log prints
("FINISHED section number 1, section completed in 2 mins 33 secs"), not
the span from first to last timestamp, so downtime after a stop is
excluded. The span is written too (wallclock_seconds) for comparison.

Co-imaged samples share one log, so logs are collapsed to one row per
acquisition, keyed by (rig, first "STARTING NEW ACQUISITION" time). A run
resumed into a new directory is merged into the acquisition it resumed
(resumes.py). Test runs are left out.

Writes:
  acquisition_metrics.csv            one row per acquisition
  acquisition_metrics_per_logfile.csv  one row per acqLog, before collapsing
In acquisition_metrics.csv, n_starts counts every start header (a restart
after five or fewer sections is not a counted restart; see 03) and
n_logfiles is the number of co-imaged samples.
"""

import re
import csv
from collections import defaultdict
from datetime import datetime

from paths import data, lab_of, log_list, rel_log
from recipes import system_of_acqlog
import resumes

ACQ_START_RE = re.compile(r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) -- STARTING NEW ACQUISITION")

SECTION_DONE_RE = re.compile(r"FINISHED section number \d+, section completed in (.+?)\s*$")

TILES_RE = re.compile(r"acquired\s+(\d+)\s+tile positions")

ANY_TS_RE = re.compile(r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})")

# One <number><unit> token of a duration. Long spellings come first because
# alternation is first-match-wins.
DUR_TOKEN_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", re.I)

FMT = "%Y/%m/%d %H:%M:%S"
UNIT_SECONDS = {"h": 3600, "m": 60, "s": 1}

# A section reported as longer than this is discarded as a parsing artefact;
# real sections take minutes.
MAX_PLAUSIBLE_SECTION_SECONDS = 3 * 3600


def parse_duration(text):
    """A logged duration in seconds, or None. The wording varies over the
    years ("2 mins 33 secs", "1 min 32 sec", "44 secs", "467.5 s",
    "1 hrs 5 mins 2 secs"), so the <number><unit> tokens are summed rather
    than one template matched."""
    total = None
    for value, unit in DUR_TOKEN_RE.findall(text):
        mult = UNIT_SECONDS[unit[0].lower()]
        total = (total or 0) + float(value) * mult
    return total


def parse_logfile(path):
    """Metrics of one acqLog, or None if it cannot be read or dated."""
    try:
        with open(path, errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return None

    imaging_seconds = 0.0
    tile_positions = 0
    n_sections = 0
    n_dropped_sections = 0
    starts = []          # every "STARTING NEW ACQUISITION" timestamp
    first_ts = last_ts = None

    for line in lines:
        m = ANY_TS_RE.match(line)
        if m:
            if first_ts is None:
                first_ts = m.group(1)
            last_ts = m.group(1)

        m = ACQ_START_RE.match(line)
        if m:
            starts.append(m.group(1))
            continue

        m = SECTION_DONE_RE.search(line)
        if m:
            secs = parse_duration(m.group(1))
            if secs is None:
                continue
            if secs > MAX_PLAUSIBLE_SECTION_SECONDS:
                n_dropped_sections += 1
                continue
            imaging_seconds += secs
            n_sections += 1
            continue

        m = TILES_RE.search(line)
        if m:
            tile_positions += int(m.group(1))

    if not starts:
        # No start header: date it from the first timestamp.
        if first_ts is None:
            return None
        starts = [first_ts]

    try:
        start_dt = datetime.strptime(starts[0], FMT)
        end_dt = datetime.strptime(last_ts, FMT) if last_ts else start_dt
    except (ValueError, TypeError):
        return None

    return {
        "path": rel_log(path),
        "lab": lab_of(path),
        "system": system_of_acqlog(path),
        "start": starts[0],
        "end": last_ts,
        "start_dt": start_dt,
        "year": start_dt.year,
        "imaging_seconds": imaging_seconds,
        "wallclock_seconds": max(0.0, (end_dt - start_dt).total_seconds()),
        "tile_positions": tile_positions,
        "n_sections": n_sections,
        "n_dropped_sections": n_dropped_sections,
        "n_starts": len(starts),
    }


def main():
    paths = log_list("unique_acqlogs.txt")

    print(f"Parsing {len(paths)} deduplicated acqLog files...")
    per_file = []
    for i, p in enumerate(paths, 1):
        rec = parse_logfile(p)
        if rec is not None:
            per_file.append(rec)
        if i % 1000 == 0:
            print(f"  ...{i}/{len(paths)}")

    print(f"Parsed {len(per_file)} files ({len(paths) - len(per_file)} unparseable/skipped)")

    # Co-imaged samples share one log: take the metrics from one copy, not
    # the sum, or the same hours would be counted once per sample.
    by_acq = defaultdict(list)
    for r in per_file:
        by_acq[(r["system"], r["start"])].append(r)

    # A run resumed into a new directory joins the acquisition it resumed:
    # hours, tiles, sections and starts are summed; end is the last run's.
    merge = resumes.merge_map()
    tests = resumes.test_run_keys()
    runs = defaultdict(list)
    for (system, start), members in by_acq.items():
        # The most complete copy, in case a partial one survived dedup.
        best = max(members, key=lambda r: (r["n_sections"], r["tile_positions"]))
        key = f"{system}|{start}"
        if key in tests:
            continue
        runs[merge.get(key, key)].append((best, members))

    acqs = []
    for key, parts in runs.items():
        parts.sort(key=lambda bm: bm[0]["start"])
        first, last = parts[0][0], parts[-1][0]
        members = [m for _b, ms in parts for m in ms]
        system, start = key.split("|", 1)
        img = sum(b["imaging_seconds"] for b, _ms in parts)
        wall = (datetime.strptime(last["end"], FMT)
                - datetime.strptime(first["start"], FMT)).total_seconds() \
            if len(parts) > 1 else first["wallclock_seconds"]
        acqs.append({
            "acq_key": key,
            "system": system,
            "labs": ";".join(sorted({r["lab"] for r in members})),
            "start": start,
            "end": last["end"],
            "year": first["year"],
            "imaging_seconds": round(img, 1),
            "imaging_hours": round(img / 3600.0, 4),
            "wallclock_seconds": round(max(0.0, wall), 1),
            "tile_positions": sum(b["tile_positions"] for b, _ms in parts),
            "n_sections": sum(b["n_sections"] for b, _ms in parts),
            "n_starts": sum(b["n_starts"] for b, _ms in parts),
            "n_logfiles": max(len(ms) for _b, ms in parts),
        })

    acqs.sort(key=lambda r: r["start"])

    out = data("acquisition_metrics.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(acqs[0].keys()))
        w.writeheader()
        w.writerows(acqs)

    out2 = data("acquisition_metrics_per_logfile.csv")
    with open(out2, "w", newline="") as f:
        cols = ["path", "lab", "system", "start", "end", "year", "imaging_seconds",
                "wallclock_seconds", "tile_positions", "n_sections",
                "n_dropped_sections", "n_starts"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(per_file)

    tot_img = sum(a["imaging_seconds"] for a in acqs) / 3600
    tot_wall = sum(a["wallclock_seconds"] for a in acqs) / 3600
    tot_tiles = sum(a["tile_positions"] for a in acqs)
    print(f"\nUnique acquisitions (rig + log start time): {len(acqs)}")
    print(f"Total imaging time  : {tot_img:,.0f} h  ({tot_img/24:,.0f} days)")
    print(f"Total wall-clock    : {tot_wall:,.0f} h  "
          f"(idle/crash time excluded from the above: {tot_wall - tot_img:,.0f} h)")
    print(f"Total tile positions: {tot_tiles:,}")

    print(f"\n{'year':>6s} {'acqs':>6s} {'imaging_h':>11s} {'tile_positions':>15s}")
    by_year = defaultdict(lambda: [0, 0.0, 0])
    for a in acqs:
        b = by_year[a["year"]]
        b[0] += 1
        b[1] += a["imaging_seconds"] / 3600
        b[2] += a["tile_positions"]
    for y in sorted(by_year):
        n, h, t = by_year[y]
        print(f"{y:6d} {n:6d} {h:11,.0f} {t:15,}")

    print(f"\nWrote {out}")
    print(f"Wrote {out2}")


if __name__ == "__main__":
    main()
