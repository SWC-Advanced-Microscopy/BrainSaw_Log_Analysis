#!/usr/bin/env python3
"""
Stage 08: select the supplementary figure's cohort from stage 07's
acq_timing_index.csv, for ../acquisition_timing.py.

An acquisition is kept if it:
  1. started on or after 1 Jan 2020;
  2. ran on NeuroVision or BrainSaw (baker is BrainSaw; see recipes.system);
  3. falls in one of the voxel categories, in Z as well as XY, since Z sets
     the number of optical planes and so the time per section;
  4. is not a rat brain: sample names start with the initials of a user
     known to image rats (VP, CM or TBM in any lab; AR, ATL, DO, EC, EM,
     HAA, LP or LSA in the akrami lab, where EM and LP are not the mouse
     users of the same initials in other labs). Initials are read from the
     sample directory names and the recipes' sample IDs;
  5. cut at least MIN_DEPTH mm;
  6. if counted as one brain, is not oversized: its mean tile positions
     per section are at most MAX_TILE_RATIO times the median for
     single-brain runs in its voxel category. A larger value means the run
     held more tissue than one mouse brain: usually several brains left in
     one uncropped directory, which stage 07 counts as one (the recipe's
     sample ID often names them all, e.g. SL_1095774_1111674_1111678_1112061).
     Such runs stay in the sample counts as single samples, since how many
     brains they held is not known; they are left out here only because
     their time per brain would be wrong. Runs counted as two or more
     brains are not tested: their count comes from cropped directories.
Imaging time is scaled to TARGET_DEPTH mm, so at most 3 mm of any value is
extrapolated.

Writes:
  fig_timing_cohort.csv          frame averaging capped (MAX_AVERAGING)
  fig_timing_averaging.csv       averaging uncapped, for the averaging panels
  timing_oversized_runs.csv      runs dropped by criterion 6, for audit
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
# Rat users identified only within one lab, since their initials are shared
# with mouse users elsewhere.
RAT_INITIALS_BY_LAB = {"akrami": {"AR", "ATL", "DO", "EC", "EM", "HAA",
                                  "LP", "LSA"}}
TARGET_DEPTH = 12.5   # mm, the depth every run is scaled to
MIN_DEPTH = 9.5       # mm, shallower runs are dropped
# Criterion 6. One brain gives ~60 tile positions per section and two give
# ~120 in both voxel categories, so 1.6 sits between one and two brains.
MAX_TILE_RATIO = 1.6

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
        initials = set(r["initials"].split(";"))
        rat = set(RAT_INITIALS)
        for lab in r["labs"].split(";"):
            rat |= RAT_INITIALS_BY_LAB.get(lab, set())
        if initials & rat:
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
            "tiles_per_section": round(int(r["tile_positions"])
                                       / max(1, int(r["n_sections"])), 1),
            "sample_dirs": r["sample_dirs"],
        })

    print(f"{len(kept)} after criteria 1-5 (averaging cap not yet applied)",
          file=sys.stderr)

    # Criterion 6, against the single-brain median of each voxel category.
    single_median = {cat: median([r["tiles_per_section"] for r in kept
                                  if r["res"] == cat and r["n_brains"] == 1])
                     for cat in VOXEL_BANDS}
    oversized = [r for r in kept if r["n_brains"] == 1
                 and r["tiles_per_section"]
                 > MAX_TILE_RATIO * single_median[r["res"]]]
    kept = [r for r in kept if r not in oversized]
    for cat in VOXEL_BANDS:
        n = sum(r["res"] == cat for r in oversized)
        print(f"  {cat}: single-brain median {single_median[cat]:.0f} tile "
              f"positions per section; {n} oversized runs dropped",
              file=sys.stderr)
    print(f"{len(kept)} after criterion 6", file=sys.stderr)

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
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(sorted(rows_out, key=lambda r: r["start"]))
        print(f"Wrote {path}", file=sys.stderr)

    path = data("timing_oversized_runs.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["acq_key", "start", "system", "res",
                                          "n_brains", "tiles_per_section",
                                          "ratio_to_single_median",
                                          "sample_dirs"],
                           extrasaction="ignore")
        w.writeheader()
        for r in sorted(oversized, key=lambda r: r["start"]):
            w.writerow({**r, "ratio_to_single_median": round(
                r["tiles_per_section"] / single_median[r["res"]], 2)})
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
