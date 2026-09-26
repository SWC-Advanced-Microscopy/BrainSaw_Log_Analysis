#!/usr/bin/env python3
"""
Stage 06: the tables ../acquisition_stats.py plots, so the figure script
does no analysis of its own.

Reads sample_acquisition_groups.csv (02), restart_events_full.csv (03),
acquisition_metrics.csv and acquisition_metrics_per_logfile.csv (05), and
new_directory_resumes.csv (01).

Writes:
  fig_samples_dated.csv    one row per sample: lab, acquisition key, date
  fig_acq_resolution.csv   one row per acquisition: XY pixel size and band
  fig_failures.csv         one row per restart per log file
  fig_per_year.csv         restarts by category, with acquisitions, imaging
                           hours and tile positions as denominators

Restart categories (from 03) and how they are grouped:
  manual abort         53   user-originated
  planned stop         29   user-originated (stopped cleanly, restarted)
  natural completion    5   user-originated
  laser fault          39   unplanned
  true unknown         85   unplanned
  total               211   in 180 of 3,251 acquisitions
The columns fail_* and *_per_failure count the unplanned ones.

A restart is counted once per event_key (rig, restart time), however many
co-imaged logs recorded it; acq_key names the acquisition it belongs to.
"""

import re
import csv
from collections import defaultdict, Counter
from datetime import datetime

from paths import data, abs_log
import resumes

FAILURE_CATEGORIES = {"laser fault", "true unknown"}

FMT = "%Y/%m/%d %H:%M:%S"


def event_key_for(row):
    """(rig, restart time): one restart, however many co-imaged logs
    recorded it."""
    ts = row["restart_timestamp"]
    if ts:
        return f"{row['system']}|{ts}"
    # No time: unique to this row, so unrelated events are not merged.
    return f"{row['system']}|NO_TS|{row['file']}|{row['block_start_line']}"


# XY voxel size, from the recipe ("VoxelSize: {X: ..." or, in a few,
# "voxelsize: {x: ...").
VOXEL_RE = re.compile(r"voxelsize:\s*\{\s*x:\s*([0-9.eE+-]+)", re.I)

# Resolution bands, [lo, hi) in um/pixel, set from the measured pixel sizes
# and covering every acquisition. The "1.6 um" mode is 1.648-1.690, so its
# edge is 1.7; the coarse end reaches 10.0 (28 acquisitions at 8.70). The
# sparse bands between the modes are kept, so the gaps stay visible.
RESOLUTION_BANDS = [
    ("<0.7",     0.0,  0.7),
    ("0.7-1.7",  0.7,  1.7),
    ("1.7-2.7",  1.7,  2.7),
    ("2.7-3.9",  2.7,  3.9),
    ("3.9-4.8",  3.9,  4.8),
    ("4.8-7.5",  4.8,  7.5),
    ("7.5-10",   7.5, 10.0),
]


def resolution_band(v):
    """Band label for an XY voxel size, or None if it falls outside."""
    for name, lo, hi in RESOLUTION_BANDS:
        # The last band includes its upper edge.
        if lo <= v < hi or (name == RESOLUTION_BANDS[-1][0] and v == hi):
            return name
    return None


def build_resolution(samples):
    """XY voxel size and band per acquisition: the modal value over its
    samples' recipes, which guards against a malformed file."""
    by_acq = defaultdict(list)
    for s in samples:
        try:
            with open(abs_log(s["sample_path"]), errors="replace") as f:
                m = VOXEL_RE.search(f.read())
        except OSError:
            continue
        if m:
            try:
                by_acq[s["acq_key"]].append(round(float(m.group(1)), 3))
            except ValueError:
                pass

    rows = []
    for key, vals in by_acq.items():
        v = Counter(vals).most_common(1)[0][0]
        rows.append({
            "acq_key": key,
            "voxel_x_um": v,
            "band": resolution_band(v) or "",
        })
    return rows


def build_samples():
    """One row per sample from 02's table, dated from its acquisition key
    ("<system>|YYMMDD_HHMMSS"; undated keys are "<system>|NO_TS:<path>")."""
    rows = []
    with open(data("sample_acquisition_groups.csv")) as f:
        for r in csv.DictReader(f):
            key = r["acquisition_key"]
            ts = key.partition("|")[2]
            ts = None if ts.startswith("NO_TS") else ts
            dt = None
            if ts and re.fullmatch(r"\d{6}_\d{6}", ts):
                try:
                    dt = datetime.strptime(ts, "%y%m%d_%H%M%S")
                except ValueError:
                    dt = None
            rows.append({
                "lab": r["lab"],
                "acq_key": key,
                "sample_path": r["sample_path"],
                "datetime": dt.strftime(FMT) if dt else "",
                "year": dt.year if dt else "",
            })
    return rows


def main():
    samples = build_samples()
    dated = [s for s in samples if s["datetime"]]
    print(f"Samples: {len(samples)} total, {len(dated)} dated, "
          f"{len(set(s['acq_key'] for s in samples))} acquisitions")

    with open(data("fig_samples_dated.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["lab", "acq_key", "sample_path", "datetime", "year"])
        w.writeheader()
        w.writerows(samples)

    res_rows = build_resolution(samples)
    with open(data("fig_acq_resolution.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["acq_key", "voxel_x_um", "band"])
        w.writeheader()
        w.writerows(res_rows)

    band_counts = Counter(r["band"] for r in res_rows)
    n_res = len(res_rows)
    print(f"\nXY resolution bands ({n_res} acquisitions):")
    for name, _lo, _hi in RESOLUTION_BANDS:
        n = band_counts.get(name, 0)
        print(f"  {name:>9s} um/pix  {n:5d}  ({n / n_res:5.1%})")
    unbinned = band_counts.get("", 0)
    print(f"  {'unbinned':>9s}         {unbinned:5d}  ({unbinned / n_res:5.1%})")

    with open(data("restart_events_full.csv")) as f:
        events = list(csv.DictReader(f))
    # An event's acquisition is its log's first start, merged through any
    # resume into a new directory.
    with open(data("acquisition_metrics_per_logfile.csv")) as f:
        log_start = {r["path"]: r["start"] for r in csv.DictReader(f)}

    merge = resumes.merge_map()
    out_events = []
    for e in events:
        ts = e["restart_timestamp"]
        acq = f"{e['system']}|{log_start[e['file']]}"
        category = e["category"]
        out_events.append({
            "file": e["file"],
            "lab": e["lab"],
            "system": e["system"],
            "acq_key": merge.get(acq, acq),
            "event_key": event_key_for(e),
            "restart_timestamp": ts,
            "year": ts[:4] if ts else "",
            "category": category,
            "is_failure": int(category in FAILURE_CATEGORIES),
            "gap_seconds": e["gap_seconds"],
        })

    with open(data("fig_failures.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_events[0].keys()))
        w.writeheader()
        w.writerows(out_events)

    cat_events = defaultdict(set)
    for e in out_events:
        cat_events[e["category"]].add(e["event_key"])
    print("\nRestart events by final category:")
    for c in sorted(cat_events, key=lambda c: -len(cat_events[c])):
        flag = "unplanned" if c in FAILURE_CATEGORIES else "user-originated"
        print(f"  {len(cat_events[c]):4d}  {c:20s} ({flag})")
    print(f"  {len({e['event_key'] for e in out_events}):4d}  events, in "
          f"{len({e['acq_key'] for e in out_events})} acquisitions")

    with open(data("acquisition_metrics.csv")) as f:
        metrics = list(csv.DictReader(f))

    per_year = defaultdict(lambda: {
        "acquisitions": 0, "imaging_hours": 0.0, "tile_positions": 0,
        "acqs_with_tile_logging": 0,
        "fail_laser": set(), "fail_unknown": set(), "fail_all": set(),
        "restarts_all": set(),
        "user_abort": set(), "user_natural": set(), "user_all": set(),
    })

    for m in metrics:
        y = int(m["year"])
        d = per_year[y]
        d["acquisitions"] += 1
        d["imaging_hours"] += float(m["imaging_hours"])
        d["tile_positions"] += int(m["tile_positions"])
        # 2016 logs have no tile counts; such years get a blank tile rate.
        if int(m["tile_positions"]) > 0:
            d["acqs_with_tile_logging"] += 1

    for e in out_events:
        if not e["year"]:
            continue
        y = int(e["year"])
        d = per_year[y]
        d["restarts_all"].add(e["event_key"])
        if e["category"] == "laser fault":
            d["fail_laser"].add(e["event_key"])
        elif e["category"] == "true unknown":
            d["fail_unknown"].add(e["event_key"])
        elif e["category"] == "manual abort":
            d["user_abort"].add(e["event_key"])
            d["user_all"].add(e["event_key"])
        else:  # planned stop / natural completion
            d["user_natural"].add(e["event_key"])
            d["user_all"].add(e["event_key"])
        if e["is_failure"]:
            d["fail_all"].add(e["event_key"])

    years = sorted(per_year)
    rows = []
    for y in years:
        d = per_year[y]
        n_fail = len(d["fail_all"])
        acqs = d["acquisitions"]
        hours = d["imaging_hours"]
        tiles = d["tile_positions"]
        has_tiles = d["acqs_with_tile_logging"] > 0
        rows.append({
            "year": y,
            "acquisitions": acqs,
            "imaging_hours": round(hours, 1),
            "tile_positions": tiles,
            "tile_logging_coverage": round(d["acqs_with_tile_logging"] / acqs, 3) if acqs else 0,
            "fail_laser": len(d["fail_laser"]),
            "fail_unknown": len(d["fail_unknown"]),
            "fail_all": n_fail,
            "user_abort": len(d["user_abort"]),
            "user_natural": len(d["user_natural"]),
            "user_all": len(d["user_all"]),
            "restarts_all": len(d["restarts_all"]),
            # Percentages of that year's acquisitions.
            "pct_restarted": round(100 * len(d["restarts_all"]) / acqs, 2) if acqs else "",
            "pct_failed": round(100 * n_fail / acqs, 2) if acqs else "",
            "pct_user": round(100 * len(d["user_all"]) / acqs, 2) if acqs else "",
            # Unplanned restarts per unit of work; blank, not zero, where
            # there is no denominator.
            "fail_per_100_acq": round(100 * n_fail / acqs, 2) if acqs else "",
            "fail_per_1000_hours": round(1000 * n_fail / hours, 2) if hours else "",
            "fail_per_million_tiles": round(1e6 * n_fail / tiles, 2) if (tiles and has_tiles) else "",
            # Work per unplanned restart (panels G and H).
            "acqs_per_failure": round(acqs / n_fail, 1) if n_fail else "",
            "hours_per_failure": round(hours / n_fail, 1) if n_fail else "",
            "tiles_per_failure": round(tiles / n_fail, 0) if (n_fail and has_tiles and tiles) else "",
        })

    with open(data("fig_per_year.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\n{'year':>6} {'acqs':>6} {'hours':>8} {'tiles':>12} "
          f"{'laser':>6} {'unkn':>5} {'fail':>5} {'h/fail':>8}")
    for r in rows:
        print(f"{r['year']:6d} {r['acquisitions']:6d} {r['imaging_hours']:8.0f} "
              f"{r['tile_positions']:12,} {r['fail_laser']:6d} {r['fail_unknown']:5d} "
              f"{r['fail_all']:5d} {str(r['hours_per_failure']):>8}")

    print("\nWrote fig_samples_dated.csv, fig_failures.csv, fig_per_year.csv")


if __name__ == "__main__":
    main()
