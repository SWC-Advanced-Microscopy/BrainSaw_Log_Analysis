#!/usr/bin/env python3
"""
Stage 07: per-section time series for every acquisition, with its imaging
settings, for the supplementary timing figure.

Each acquisition's sections are kept in order, with the settings from the
recipe beside the log (the log records no voxel size, slice thickness or
averaging). Co-imaged samples share a log, so logs are grouped into runs
by (rig, first start). A run resumed into a new directory is joined to the
run it resumed (resumes.py). Test runs are left out.

Times are for the whole run, all brains together. Two time bases are
written per section: cum_imaging_h, the summed logged durations, which
excludes downtime; and cum_wallclock_h, time since the first section.
Depth is sections cut times sliceThickness (mm).

Writes, unfiltered (stage 08 selects the cohort):
  acq_timing_index.csv          one row per acquisition: settings and totals
  acq_timing_sections.csv.gz    one row per section: cumulative time, depth
"""

import csv
import gzip
import io
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

from paths import data, lab_of, log_list
import recipes
import resumes

ACQ_START_RE = re.compile(
    r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) -- STARTING NEW ACQUISITION")
SECTION_DONE_RE = re.compile(
    r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) -- FINISHED section number (\d+), "
    r"section completed in (.+?)\s*$")
TILES_RE = re.compile(r"acquired\s+(\d+)\s+tile positions")

# As in stage 05: sum <number><unit> tokens, long spellings first.
DUR_TOKEN_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", re.I)
UNIT_SECONDS = {"h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
                "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
                "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1}

# A longer section is a garbled duration and is dropped.
MAX_PLAUSIBLE_SECTION_SECONDS = 3 * 3600


def parse_duration(s):
    """A logged duration in seconds, or None."""
    total, matched = 0.0, False
    for value, unit in DUR_TOKEN_RE.findall(s):
        mult = UNIT_SECONDS.get(unit.lower())
        if mult is None:
            continue
        total += float(value) * mult
        matched = True
    return total if matched else None


def parse_acqlog(path):
    """(first start, [sections in file order]), or (None, []). Sections
    from every block of a restarted run are kept."""
    start = None
    sections = []
    pending_tiles = 0
    try:
        fh = open(path, errors="replace")
    except OSError:
        return None, []
    with fh:
        for line in fh:
            m = ACQ_START_RE.match(line)
            if m:
                if start is None:
                    start = m.group(1)
                continue
            m = TILES_RE.search(line)
            if m:
                # Logged before the section's FINISHED line.
                pending_tiles += int(m.group(1))
                continue
            m = SECTION_DONE_RE.match(line)
            if m:
                secs = parse_duration(m.group(3))
                if secs is None or secs > MAX_PLAUSIBLE_SECTION_SECONDS:
                    pending_tiles = 0
                    continue
                sections.append({
                    "ts": m.group(1),
                    "section_number": int(m.group(2)),
                    "seconds": secs,
                    "tiles": pending_tiles,
                })
                pending_tiles = 0
    return start, sections


def _num(text, key):
    """A numeric recipe field, inline ("mosaic: {sliceThickness: 0.05, ...")
    or as a block key."""
    m = re.search(key + r"\s*:\s*([0-9.eE+-]+)", text, re.I)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


# VoxelSize appears twice: X/Y under StitchingParameters, X/Y/Z at top
# level. The one with a Z is the acquisition's.
VOXEL_XYZ_RE = re.compile(
    r"voxelsize:\s*\{\s*x:\s*([0-9.eE+-]+)\s*,\s*y:\s*([0-9.eE+-]+)\s*,"
    r"\s*z:\s*([0-9.eE+-]+)", re.I)
VOXEL_XY_RE = re.compile(r"voxelsize:\s*\{\s*x:\s*([0-9.eE+-]+)", re.I)
SAMPLE_ID_RE = re.compile(r"sample:\s*\{[^}]*?\bID:\s*([^,}\n]+)", re.I)


def parse_recipe(path):
    """The imaging settings of one recipe, or None if unreadable."""
    try:
        text = open(path, errors="replace").read()
    except OSError:
        return None
    m = VOXEL_XYZ_RE.search(text)
    if m:
        vx, vy, vz = (float(m.group(i)) for i in (1, 2, 3))
    else:
        m = VOXEL_XY_RE.search(text)
        vx = float(m.group(1)) if m else None
        vy, vz = None, None

    system = recipes.system(text)

    m = SAMPLE_ID_RE.search(text)
    sample_id = m.group(1).strip().strip("'\"") if m else ""

    return {
        "sample_id": sample_id,
        "system": system,
        "voxel_x_um": vx,
        "voxel_y_um": vy,
        "voxel_z_um": vz,
        "slice_thickness_mm": _num(text, "sliceThickness"),
        "requested_sections": _num(text, "numSections"),
        "n_optical_planes": _num(text, "numOpticalPlanes"),
        "average_n_frames": _num(text, "averageEveryNframes"),
        "objective_resolution": _num(text, "objectiveResolution"),
        "zoom_factor": _num(text, "zoomFactor"),
        "pixels_per_line": _num(text, "pixelsPerLine"),
        "lines_per_frame": _num(text, "linesPerFrame"),
    }


def sibling_recipe(acqlog_path):
    """The recipe in the acqLog's directory. Of several, the newest whose
    name contains the log's sample name, else the newest."""
    d = os.path.dirname(acqlog_path)
    try:
        names = [f for f in os.listdir(d)
                 if f.lower().startswith("recipe") and f.lower().endswith(".yml")]
    except OSError:
        return None
    if not names:
        return None
    if len(names) == 1:
        return os.path.join(d, names[0])
    stem = os.path.basename(acqlog_path)
    stem = re.sub(r"^acqLog_", "", stem, flags=re.I)
    stem = re.sub(r"\.txt$", "", stem, flags=re.I)
    exact = [n for n in names if stem and stem in n]
    pick = exact or names
    pick.sort(key=lambda n: os.path.getmtime(os.path.join(d, n)))
    return os.path.join(d, pick[-1])


def main():
    paths = log_list("unique_acqlogs.txt")
    print(f"Parsing {len(paths)} deduplicated acqLog files...", file=sys.stderr)

    # The rig is in the recipe, so every log is read before grouping.
    parsed = []
    n_nostart = n_norecipe = 0
    for i, p in enumerate(paths, 1):
        if i % 1000 == 0:
            print(f"  ...{i}/{len(paths)}", file=sys.stderr)
        start, sections = parse_acqlog(p)
        if start is None or not sections:
            n_nostart += 1
            continue
        rp = sibling_recipe(p)
        r = parse_recipe(rp) if rp else None
        if r is None or not r["system"]:
            n_norecipe += 1
            continue
        parsed.append((p, start, sections, r))

    groups = defaultdict(lambda: {"dirs": {}, "labs": set(),
                                  "sections": None, "recipes": []})
    for p, start, sections, r in parsed:
        g = groups[f"{r['system']}|{start}"]
        # Brains are counted as sample directories, keyed by the directory's
        # basename and the acqLog's file name: one directory filed under two
        # labs is one brain, but sample directories that share a generic
        # name (the BIDS-style ".../sub-056_id-CAP56/.../2pe/") stay
        # separate. A run with several brains in one uncropped directory is
        # still counted as one brain; stage 08 drops such runs from the
        # timing figure by their tile count.
        g["dirs"][(os.path.basename(os.path.dirname(p)),
                   os.path.basename(p).lower())] = True
        g["labs"].add(lab_of(p))
        # The longest copy, in case one is incomplete.
        if g["sections"] is None or len(sections) > len(g["sections"]):
            g["sections"] = sections
        g["recipes"].append(r)

    for key in resumes.test_run_keys():
        groups.pop(key, None)

    # Join a run resumed into a new directory to the run it resumed:
    # sections concatenated, brains and settings from the longer run.
    for resumed, first in resumes.merge_map().items():
        if resumed not in groups:
            continue
        g_b = groups.pop(resumed)
        if first not in groups:
            groups[first] = g_b
            continue
        g_a = groups[first]
        longer = g_a if len(g_a["sections"]) >= len(g_b["sections"]) else g_b
        groups[first] = {
            "dirs": longer["dirs"],
            "labs": g_a["labs"] | g_b["labs"],
            "sections": sorted(g_a["sections"] + g_b["sections"],
                               key=lambda x: x["ts"]),
            "recipes": longer["recipes"],
        }

    print(f"{len(groups)} acquisitions "
          f"({n_nostart} logs skipped: no start line or no completed section; "
          f"{n_norecipe} skipped: no readable recipe or no SYSTEM id)",
          file=sys.stderr)

    idx_path = data("acq_timing_index.csv")
    # Gzipped: 54 MB as text.
    sec_path = data("acq_timing_sections.csv.gz")

    idx_fields = [
        "acq_key", "labs", "start", "year", "system", "n_brains",
        "sample_dirs", "recipe_sample_ids", "initials",
        "voxel_x_um", "voxel_y_um", "voxel_z_um",
        "slice_thickness_mm", "n_optical_planes", "average_n_frames",
        "requested_sections", "n_sections", "depth_mm",
        "imaging_hours", "wallclock_hours", "tile_positions",
        "config_uniform",
    ]
    sec_fields = ["acq_key", "section_index", "depth_mm",
                  "cum_imaging_h", "cum_wallclock_h", "cum_tiles"]

    # mtime=0 keeps the file byte-reproducible.
    with open(idx_path, "w", newline="") as fi, \
            gzip.GzipFile(sec_path, "wb", compresslevel=6, mtime=0) as gz, \
            io.TextIOWrapper(gz, newline="") as fs:
        wi = csv.DictWriter(fi, fieldnames=idx_fields)
        wi.writeheader()
        ws = csv.DictWriter(fs, fieldnames=sec_fields)
        ws.writeheader()

        for key, g in sorted(groups.items()):
            recs = g["recipes"]
            if not recs:
                continue
            dirs = sorted(d for d, _log in g["dirs"])
            ids = sorted({r["sample_id"] for r in recs if r["sample_id"]})
            r0 = recs[0]

            def agree(field):
                vals = {r[field] for r in recs if r[field] is not None}
                return len(vals) <= 1

            # Co-imaged brains share one set of settings; flag any that don't.
            uniform = all(agree(f) for f in
                          ("voxel_x_um", "average_n_frames", "slice_thickness_mm"))

            sections = g["sections"]
            t0 = datetime.strptime(sections[0]["ts"], "%Y/%m/%d %H:%M:%S")
            slice_mm = r0["slice_thickness_mm"] or float("nan")

            cum_s = cum_tiles = 0.0
            for n, s in enumerate(sections, 1):
                cum_s += s["seconds"]
                cum_tiles += s["tiles"]
                wall = (datetime.strptime(s["ts"], "%Y/%m/%d %H:%M:%S")
                        - t0).total_seconds()
                ws.writerow({
                    "acq_key": key,
                    "section_index": n,
                    "depth_mm": round(n * slice_mm, 5),
                    "cum_imaging_h": round(cum_s / 3600.0, 5),
                    "cum_wallclock_h": round(wall / 3600.0, 5),
                    "cum_tiles": int(cum_tiles),
                })

            start = key.split("|", 1)[1]
            wi.writerow({
                "acq_key": key,
                "labs": ";".join(sorted(g["labs"])),
                "start": start,
                "year": int(start[:4]),
                "system": r0["system"],
                "n_brains": len(dirs),
                "sample_dirs": ";".join(dirs),
                "recipe_sample_ids": ";".join(ids),
                # Sample names start with the user's initials ("VP_CAP56").
                # Taken from both the directory names and the recipes'
                # sample IDs, since a directory may have a generic name
                # ("2pe") that hides them.
                "initials": ";".join(sorted({n.split("_")[0]
                                             for n in dirs + ids if n})),
                "voxel_x_um": r0["voxel_x_um"],
                "voxel_y_um": r0["voxel_y_um"],
                "voxel_z_um": r0["voxel_z_um"],
                "slice_thickness_mm": r0["slice_thickness_mm"],
                "n_optical_planes": r0["n_optical_planes"],
                "average_n_frames": r0["average_n_frames"],
                "requested_sections": r0["requested_sections"],
                "n_sections": len(sections),
                "depth_mm": round(len(sections) * slice_mm, 5),
                "imaging_hours": round(cum_s / 3600.0, 5),
                "wallclock_hours": round(
                    (datetime.strptime(sections[-1]["ts"], "%Y/%m/%d %H:%M:%S")
                     - t0).total_seconds() / 3600.0, 5),
                "tile_positions": int(cum_tiles),
                "config_uniform": int(uniform),
            })

    print(f"Wrote {idx_path}", file=sys.stderr)
    print(f"Wrote {sec_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
