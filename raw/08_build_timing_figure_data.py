#!/usr/bin/env python3
"""
Stage 08: select the supplementary figure's cohort from stage 07's
acq_timing_index.csv, for ../acquisition_timing.py.

An acquisition is kept if it:
  1. started on or after 1 Jan 2020;
  2. ran on NeuroVision or BrainSaw (baker is BrainSaw; see recipes.system);
  3. falls in one of the voxel categories, in Z as well as XY, since Z sets
     the number of optical planes and so the time per section;
  4. is not a rat brain (initials VP, CM or TBM);
  5. cut at least MIN_DEPTH mm.
Imaging time is scaled to TARGET_DEPTH mm, so at most 3 mm of any value is
extrapolated.

Writes:
  fig_timing_cohort.csv     frame averaging capped (MAX_AVERAGING)
  fig_timing_averaging.csv  averaging uncapped, for the averaging panels
"""

import csv
import os
import sys
from statistics import median

from paths import data

SRC = data("acq_timing_index.csv")

START_DATE = "2020/01/01"
SYSTEMS = {"neurovision", "brainsaw"}
RAT_INITIALS = {"VP", "CM", "TBM"}
TARGET_DEPTH = 12.5   # mm, the depth every run is scaled to
MIN_DEPTH = 9.5       # mm, shallower runs are dropped

# category -> (XY min, XY max, Z min, Z max), micrometres, inclusive
VOXEL_BANDS = {
    "4x4x20": (3.9, 5.0, 18.0, 22.0),
    "2x2x5":  (1.9, 2.6,  4.5,  5.5),
}
# Heavier averaging is a different experiment.
MAX_AVERAGING = {"4x4x20": 4, "2x2x5": 2}


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def voxel_category(vx, vz):
    if vx is None or vz is None:
        return None
    for name, (xlo, xhi, zlo, zhi) in VOXEL_BANDS.items():
        if xlo <= vx <= xhi and zlo <= vz <= zhi:
            return name
    return None


def main():
    with open(SRC) as f:
        rows = list(csv.DictReader(f))
    print(f"{len(rows)} acquisitions in {os.path.basename(SRC)}", file=sys.stderr)

    kept = []
    for r in rows:
        if r["start"] < START_DATE:
            continue
        if r["system"] not in SYSTEMS:
            continue
        cat = voxel_category(fnum(r["voxel_x_um"]), fnum(r["voxel_z_um"]))
        if cat is None:
            continue
        if r["initials"] in RAT_INITIALS:
            continue
        avg = fnum(r["average_n_frames"])
        if avg is None:
            continue
        depth = fnum(r["depth_mm"])
        hours = fnum(r["imaging_hours"])
        if depth is None or hours is None or depth < MIN_DEPTH:
            continue
        kept.append({
            "acq_key": r["acq_key"],
            "start": r["start"],
            "system": r["system"],
            "res": cat,
            "n_brains": int(r["n_brains"]),
            "average_n_frames": avg,
            "n_optical_planes": fnum(r["n_optical_planes"]),
            "depth_mm": round(depth, 3),
            "imaging_hours": round(hours, 3),
            # hours per mm, scaled to a common depth
            "h_at_target": round(hours / depth * TARGET_DEPTH, 4),
            "reached_target": int(depth >= TARGET_DEPTH),
        })

    print(f"{len(kept)} after selection (averaging cap not yet applied)",
          file=sys.stderr)

    capped = [r for r in kept
              if r["average_n_frames"] <= MAX_AVERAGING[r["res"]]]
    print(f"{len(capped)} after the per-category averaging cap", file=sys.stderr)

    fields = ["acq_key", "start", "system", "res", "n_brains",
              "average_n_frames", "n_optical_planes", "depth_mm",
              "imaging_hours", "h_at_target", "reached_target"]
    for name, rows_out in (("fig_timing_cohort.csv", capped),
                           ("fig_timing_averaging.csv", kept)):
        path = data(name)
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(sorted(rows_out, key=lambda r: r["start"]))
        print(f"Wrote {path}", file=sys.stderr)

    # Only runs that reached TARGET_DEPTH can check the scaling (stage 09).
    n_reached = sum(r["reached_target"] for r in capped)
    print(f"\n{n_reached}/{len(capped)} "
          f"({100 * n_reached / len(capped):.0f}%) reached {TARGET_DEPTH} mm",
          file=sys.stderr)

    print("\nCohort by category and brains on the block:", file=sys.stderr)
    for cat in VOXEL_BANDS:
        counts = {}
        for r in capped:
            if r["res"] == cat:
                counts[r["n_brains"]] = counts.get(r["n_brains"], 0) + 1
        line = "  ".join(f"{k}:{counts[k]}" for k in sorted(counts))
        med = median([r["h_at_target"] for r in capped if r["res"] == cat])
        print(f"  {cat:<8} {line}   median {med:.1f} h", file=sys.stderr)


if __name__ == "__main__":
    main()
