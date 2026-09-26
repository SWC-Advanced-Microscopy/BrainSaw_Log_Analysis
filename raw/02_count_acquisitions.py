#!/usr/bin/env python3
"""
Stage 02: group samples (unique_recipes.txt) into acquisitions.

Co-imaged samples share an acqStartTime, so an acquisition is keyed by
(rig, acqStartTime). The file-name timestamp is not used for grouping:
it is when each file was saved, seconds apart for co-imaged samples. The
rig, not the lab, is in the key because one run can be filed under two labs.

Writes sample_acquisition_groups.csv (lab, acquisition key, sample path).
"""
import re
import csv
from collections import defaultdict
from datetime import datetime

from paths import data, lab_of, log_list, rel_log
import recipes

# Full timestamp suffix: recipe_<name>_<YYMMDD>_<HHMMSS>.yml
FNAME_TS_RE = re.compile(r"_(\d{6}_\d{6})\.yml$", re.I)
# Date-only suffix: recipe_<name>_<YYMMDD>.yml (2016). A last resort: it
# cannot separate two acquisitions on the same day.
FNAME_DATE_ONLY_RE = re.compile(r"_(\d{6})\.yml$", re.I)


def _is_real_timestamp(ts):
    """Is "YYMMDD_HHMMSS" a real date and time? Rejects the wrong pair
    matched in a doubled timestamp, e.g. recipe_sample_171116_152632_171116.yml
    gives "152632_171116" (month 26)."""
    try:
        datetime.strptime(ts, "%y%m%d_%H%M%S")
        return True
    except ValueError:
        return False


def get_timestamp(path, content):
    """Acquisition start as "YYMMDD_HHMMSS", or None. Taken from, in order:
    the acqStartTime field (every recipe in the corpus has one), a full
    _YYMMDD_HHMMSS file-name suffix, a date-only _YYMMDD suffix. The whole
    file is searched: 2016 recipes put acqStartTime on line 21."""
    ts = recipes.acq_start(content)
    if ts:
        # normalize "2022/08/26 16:26:07" -> "220826_162607"
        try:
            date_part, time_part = ts.split(" ")
            y, mo, d = date_part.split("/")
            ts = f"{y[2:]}{mo}{d}_{time_part.replace(':', '')}"
            if _is_real_timestamp(ts):
                return ts
        except ValueError:
            pass

    m = FNAME_TS_RE.search(path)
    if m and _is_real_timestamp(m.group(1)):
        return m.group(1)  # e.g. "240410_123149"

    # Midnight stands in for the missing time.
    m = FNAME_DATE_ONLY_RE.search(path)
    if m and _is_real_timestamp(f"{m.group(1)}_000000"):
        return f"{m.group(1)}_000000"

    return None


paths = log_list("unique_recipes.txt")

no_ts = []
groups = defaultdict(list)     # "<system>|<YYMMDD_HHMMSS>" -> sample paths
for p in paths:
    content = recipes.read(p)
    system = recipes.system(content) or "unknown"
    ts = get_timestamp(p, content)
    if ts is None:
        no_ts.append(p)
        # each of these counts as its own singleton acquisition
        groups[f"{system}|NO_TS:{rel_log(p)}"].append(p)
    else:
        groups[f"{system}|{ts}"].append(p)

print(f"Total unique samples (recipe files): {len(paths)}")
print(f"Samples with no parseable timestamp (treated as singleton acquisitions): {len(no_ts)}")
print(f"Unique acquisitions: {len(groups)}\n")

# A run with samples filed under two labs appears in both labs' rows, so
# the per-lab acquisition column can sum to more than the total above.
by_lab_samples = defaultdict(int)
by_lab_acqs = defaultdict(set)
for key, members in groups.items():
    for m in members:
        by_lab_samples[lab_of(m)] += 1
        by_lab_acqs[lab_of(m)].add(key)

print(f"{'lab':20s} {'samples':>8s} {'acquisitions':>13s}")
for lab in sorted(by_lab_samples, key=lambda l: -by_lab_samples[l]):
    print(f"{lab:20s} {by_lab_samples[lab]:8d} {len(by_lab_acqs[lab]):13d}")

with open(data("sample_acquisition_groups.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["lab", "acquisition_key", "sample_path"])
    for key, members in groups.items():
        for m in members:
            w.writerow([lab_of(m), key, rel_log(m)])

print(f"\nWrote group membership -> sample_acquisition_groups.csv")
