#!/usr/bin/env python3
"""
Stage 01: one recipe per sample, one copy of each acqLog.

acqLogs are deduplicated on (content hash, sample name). Content alone is
not enough: co-imaged samples share a byte-identical log (VP_CAP66/heart
and VP_CAP66/liver), and often a byte-identical recipe too. The name comes
from the file name: recipe_<name>[_YYMMDD_HHMMSS].yml, acqLog_<name>.txt.

Recipes go through seven rules, in this order:
  1. ignore BakingTray's backups in logfiles*/           is_backup
  2. keep one recipe per sample directory                one_per_directory
  3. collapse identical copies of a sample               collapse_same_sample
  4. collapse differing copies of the same run           collapse_same_sample
  5. drop uncropped parent recipes                       drop_unsplit_parents
  6. drop one run of each pair resumed into a new dir    drop_new_directory_resumes
  7. drop test runs                                      drop_test_runs
Rule 2 must come before rule 3. Otherwise a directory can lose its original
recipe as a copy of another directory's and keep a false start instead
(MH_1106265).

Writes to derived_data/, with paths relative (MERGED_LOGS/<lab>/...):
  unique_recipes.txt, unique_acqlogs.txt   the files kept
  duplicate_groups.csv        every group collapsed by content, and by rule 4
  resume_recipes.csv          recipes dropped by rules 2 and 6, with one kept
  unsplit_recipes.csv         recipes dropped by rule 5
  new_directory_resumes.csv   resumed pairs (resumes.py)
  test_runs.csv               test runs (resumes.py)
"""
import os
import re
import csv
import hashlib
from collections import defaultdict
from datetime import datetime

from paths import MERGED, data, rel_log
import recipes
from recipes import original_recipe
import resumes

RECIPE_NAME_RE = re.compile(r"^recipe_(.+?)(?:_\d{6}_\d{6})?\.yml$", re.I)
ACQLOG_NAME_RE = re.compile(r"^acqLog_(.+)\.txt$", re.I)


def is_backup(path):
    """Rule 1: inside a BakingTray logfiles*/ backup directory. BakingTray
    copies the recipes there when a run is resumed; some are the recipe of a
    multi-sample run from before it was cropped. No acqLog is stored there."""
    parts = os.path.relpath(os.path.dirname(path), MERGED).split(os.sep)
    return any(p.lower().startswith("logfiles") for p in parts)


def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def extract_name(fn, is_recipe):
    m = (RECIPE_NAME_RE if is_recipe else ACQLOG_NAME_RE).match(fn)
    return m.group(1) if m else fn


def collect_and_dedup(is_recipe, label):
    """Every recipe (or acqLog) in MERGED_LOGS, grouped by (content hash,
    sample name). A group is one file stored under several paths, e.g.
    akrami's data, later reorganised into a BIDS layout. Returns (files,
    groups)."""
    files = []
    for dirpath, _dirnames, filenames in os.walk(MERGED):
        for fn in filenames:
            is_match = (fn.lower().startswith("recipe") and fn.lower().endswith(".yml")) if is_recipe \
                else ("acqlog" in fn.lower() and fn.lower().endswith(".txt"))
            if is_match:
                files.append(os.path.join(dirpath, fn))

    if is_recipe:
        n_backup = sum(is_backup(f) for f in files)
        files = [f for f in files if not is_backup(f)]
        print(f"{label}: {n_backup} BakingTray backup copies in logfiles/ ignored")

    groups = defaultdict(list)
    for full in files:
        fn = os.path.basename(full)
        name = extract_name(fn, is_recipe)
        h = sha1(full)
        groups[(h, name)].append(full)

    print(f"{label}: {len(files)} raw files -> {len(groups)} unique (content+name) files")
    n_dupe_groups = sum(1 for v in groups.values() if len(v) > 1)
    n_dupe_files = sum(len(v) - 1 for v in groups.values() if len(v) > 1)
    print(f"  {n_dupe_groups} groups had duplicate copies ({n_dupe_files} redundant files collapsed)")
    return files, groups


def one_per_directory(files):
    """Rule 2: one recipe per sample directory. BakingTray writes a new
    recipe into the directory each time a run is resumed (AR__EC22 has one
    for section 1 and one for section 10); a directory may also hold an
    unsplit multi-sample recipe or a false start. Keep the one closest to
    the log's first start (recipes.original_recipe).
    Returns (kept, {dropped: kept})."""
    by_dir = defaultdict(list)
    for p in files:
        by_dir[os.path.dirname(p)].append(p)
    kept, discarded = [], {}
    for paths in by_dir.values():
        orig = original_recipe(sorted(paths))
        kept.append(orig)
        for r in paths:
            if r != orig:
                discarded[r] = orig
    print(f"recipe: {len(discarded)} resume or other extra recipes discarded "
          f"-> {len(kept)} sample directories")
    return sorted(kept), discarded


def collapse_same_sample(kept, key_of):
    """Rule 3: one recipe per (content hash, sample name). Rule 4: then one
    per (rig, sample name, run), for copies that are not byte-identical
    (e.g. a corrupted VoxelSize line). The run is the log's first start
    (recipes.run_start), not the recipe's acqStartTime, because a copy may
    hold only the resume recipe (s047_..._rg1). Keeps the recipe whose
    acqStartTime is closest to the run's start.
    Returns (kept [(path, name)], {rule-4 key: [paths]})."""
    copies = defaultdict(list)
    for p in kept:
        copies[key_of[p]].append(p)
    print(f"recipe: {len(kept) - len(copies)} copies of a sample in another "
          f"directory collapsed (identical content and name)")
    by_key = defaultdict(list)
    for (h, name), paths in copies.items():
        rep = sorted(paths)[0]
        start = recipes.run_start(rep)
        # Without a start time there is nothing safe to match on.
        key = (recipes.system(recipes.read(rep)), name, start) if start else (rep,)
        by_key[key].append((rep, name))

    def closeness(rep_name, start):
        t = recipes.acq_start(recipes.read(rep_name[0]))
        off = abs((datetime.strptime(t, recipes.FMT)
                   - datetime.strptime(start, recipes.FMT)).total_seconds()) \
            if t and start else float("inf")
        return (off, rep_name[0])
    out, collapsed = [], {}
    for key, reps in by_key.items():
        reps.sort(key=lambda rn: closeness(rn, key[2] if len(key) == 3 else None))
        out.append(reps[0])
        if len(reps) > 1:
            collapsed[key] = [r for r, _ in reps]
    print(f"recipe: {sum(len(v) - 1 for v in collapsed.values())} copies of "
          f"the same sample (same rig, name and run) collapsed "
          f"-> {len(out)} samples")
    return out, collapsed


def drop_unsplit_parents(kept):
    """Rule 5: within one acquisition (rig, acqStartTime), drop a recipe
    whose directory contains another member's directory: the uncropped
    recipe left above the per-sample directories (CR_OKRound_Andre, above
    CRteen1-3). Returns (kept, {dropped: remaining members})."""
    by_acq = defaultdict(list)
    for p in kept:
        text = recipes.read(p)
        start = recipes.acq_start(text)
        by_acq[(recipes.system(text), start) if start else (p,)].append(p)
    discarded = {}
    for members in by_acq.values():
        dirs = [os.path.dirname(m) + os.sep for m in members]
        parents = [m for m, d in zip(members, dirs)
                   if any(o != d and o.startswith(d) for o in dirs)]
        for m in parents:
            discarded[m] = [x for x in members if x not in parents]
    print(f"recipe: {len(discarded)} unsplit parent recipes discarded "
          f"-> {len(kept) - len(discarded)} samples")
    return sorted(p for p in kept if p not in discarded), discarded


def drop_new_directory_resumes(kept, pairs):
    """Rule 6: both runs of a pair resumed into a new directory describe
    the same brains. Drop the recipes of the run with fewer samples (the
    resumed run's on a tie), so an uncropped first attempt does not replace
    a cropped resumed run (AF_PCA_19_20_22_25). A recipe belongs to the run
    its directory's acqLog records.
    Returns (kept, {dropped: a recipe of the run kept})."""
    by_run = defaultdict(list)
    for p in kept:
        t0 = recipes.log_first_start(os.path.dirname(p))
        if t0 is not None:
            by_run[f"{recipes.system(recipes.read(p))}|{t0.strftime(recipes.FMT)}"].append(p)
    root = {r["resumed_key"]: r["first_key"] for r in pairs}
    discarded = {}
    for resumed, first in root.items():
        while first in root:
            first = root[first]
        a, b = by_run.get(first, []), by_run.get(resumed, [])
        if a and b:
            drop, keep = (a, b) if len(b) > len(a) else (b, a)
            for p in drop:
                discarded[p] = sorted(keep)[0]
    print(f"recipe: {len(discarded)} recipes of {len(pairs)} runs resumed into a "
          f"new directory discarded -> {len(kept) - len(discarded)} samples")
    return sorted(p for p in kept if p not in discarded), discarded


def drop_test_runs(kept):
    """Rule 7: drop the recipes of test runs, acquisitions of five or fewer
    sections (resumes.find_test_runs)."""
    tests = resumes.test_run_keys()
    dropped = []
    for p in kept:
        t0 = recipes.log_first_start(os.path.dirname(p))
        if t0 is not None and \
                f"{recipes.system(recipes.read(p))}|{t0.strftime(recipes.FMT)}" in tests:
            dropped.append(p)
    print(f"recipe: {len(dropped)} recipes of test runs discarded "
          f"-> {len(kept) - len(dropped)} samples")
    return sorted(set(kept) - set(dropped)), dropped


if __name__ == "__main__":
    recipe_files, recipe_groups = collect_and_dedup(True, "recipe")
    acqlog_files, acqlog_groups = collect_and_dedup(False, "acqLog")
    key_of = {p: k for k, paths in recipe_groups.items() for p in paths}
    per_dir, extra = one_per_directory(recipe_files)
    same_sample_kept, same_sample = collapse_same_sample(per_dir, key_of)
    no_parents, unsplit = drop_unsplit_parents([p for p, _n in same_sample_kept])
    acqlog_reps = sorted(sorted(paths)[0] for paths in acqlog_groups.values())
    runs = resumes.summarise_runs(acqlog_reps)
    pairs = resumes.find(runs)
    resumes.write(pairs)
    tests = resumes.find_test_runs(runs, pairs)
    resumes.write_test_runs(tests)
    no_resumed, resumed = drop_new_directory_resumes(no_parents, pairs)
    kept_recipes, tested = drop_test_runs(no_resumed)

    with open(data("unique_recipes.txt"), "w") as f:
        for p in kept_recipes:
            f.write(rel_log(p) + "\n")

    with open(data("resume_recipes.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["discarded_resume_recipe", "original_recipe"])
        for r, orig in sorted({**extra, **resumed}.items()):
            w.writerow([rel_log(r), rel_log(orig)])

    with open(data("unsplit_recipes.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["discarded_unsplit_recipe", "kept_recipes_same_acquisition"])
        for r, others in sorted(unsplit.items()):
            w.writerow([rel_log(r), " | ".join(rel_log(o) for o in sorted(others))])

    with open(data("unique_acqlogs.txt"), "w") as f:
        for (h, name), paths in sorted(acqlog_groups.items()):
            f.write(rel_log(sorted(paths)[0]) + "\n")

    with open(data("duplicate_groups.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file_type", "sample_name", "content_hash", "n_copies", "paths"])
        for label, groups in [("recipe", recipe_groups), ("acqLog", acqlog_groups)]:
            for (h, name), paths in groups.items():
                if len(paths) > 1:
                    rels = [rel_log(p) for p in sorted(paths)]
                    w.writerow([label, name, h[:10], len(paths), " | ".join(rels)])
        for (system, name, start), paths in sorted(same_sample.items()):
            rels = [rel_log(p) for p in paths]
            w.writerow(["recipe (same sample)", name, "differs", len(paths),
                        " | ".join(rels)])

    print(f"\nWrote unique_recipes.txt ({len(kept_recipes)} entries)")
    print(f"Wrote unique_acqlogs.txt ({len(acqlog_groups)} entries)")
    print(f"Wrote duplicate_groups.csv (audit trail of every collapsed group)")
    print(f"Wrote resume_recipes.csv ({len(extra) + len(resumed)} discarded extra recipes, audit only)")
    print(f"Wrote new_directory_resumes.csv ({len(pairs)} runs resumed into a new directory)")
    print(f"Wrote test_runs.csv ({len(tests)} test runs, {len(tested)} recipes)")
    print(f"Wrote unsplit_recipes.csv ({len(unsplit)} discarded unsplit recipes, audit only)")
