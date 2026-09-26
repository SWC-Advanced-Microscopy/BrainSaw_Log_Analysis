#!/usr/bin/env python3
"""
Stage 09 (not part of the pipeline): the plots in ../validation.md,
written to readme_images/, and every number it quotes.

Each check re-derives a quantity by a route the pipeline does not use and
compares the two. Nothing reads the output. Run any time after 01-08; it
takes a few minutes, mostly re-hashing MERGED_LOGS.

  1  deduplication        re-hash every file and re-apply stage 01's rules
  2  grouping             acquisitions from recipes (02) vs from logs (05)
  3  duration parsing     parsed durations vs each section's own timestamps
  4  imaging time         imaging vs wall-clock hours per acquisition
  5  restart detection    restarts vs the "(X of Y)" section counter resetting
  6  coverage             samples per month; tile logging per year
  7  resolution bands     stage 06's bands vs the pixel-size distribution
  8  depth normalisation  scaled vs measured time, for runs reaching 12.5 mm
"""

import bisect
import csv
import gzip
import hashlib
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from paths import MERGED, data, readme_image, lab_of, abs_log
import recipes
import resumes

# The pipeline's own parser, so that check 3 tests it.
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "_metrics", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "05_extract_acquisition_metrics.py"))
_metrics = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_metrics)
parse_duration = _metrics.parse_duration
MAX_PLAUSIBLE_SECTION_SECONDS = _metrics.MAX_PLAUSIBLE_SECTION_SECONDS

# --- style ---------------------------------------------------------------
# Three categorical hues, in fixed order, validated for all-pairs use in
# light mode (CVD dE >= 8, normal-vision dE >= 15). Greys carry anything
# that is context rather than a series.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e7e6e1"
GREY = "#b3b3b3"

plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.edgecolor": MUTED,
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "axes.axisbelow": True,
    "font.size": 9,
    "axes.titlesize": 9.5,
    "figure.dpi": 110,
    "savefig.dpi": 110,
})

STATS = {}          # every number validation.md quotes, printed at the end


def note(key, value, comment=""):
    STATS[key] = value
    print(f"  {key:38s} {value}{('   # ' + comment) if comment else ''}")


def save(fig, name):
    path = readme_image(name)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  -> readme_images/{name}")


def title(ax, text):
    ax.set_title(text, loc="left", pad=6)


def rows(name):
    with open(data(name)) as f:
        return list(csv.DictReader(f))


FMT = "%Y/%m/%d %H:%M:%S"

# The duration wording is not consistent across ten years of logs. These
# are the shapes actually present, keyed by the units the parser found.
EXAMPLE_OF = {
    "mins+secs": '"2 mins 33 secs"',
    "min+sec": '"1 min 32 sec"',
    "mins": '"4 mins"',
    "secs": '"44 secs"',
    "sec": '"52 sec"',
    "s": '"467.5 s"  (2016)',
    "hrs+mins+secs": '"1 hrs 5 mins 2 secs"',
}


# ===================================================================== 1
def check_dedup():
    """Re-hash MERGED_LOGS and re-apply stage 01's rules. Also shows that
    deduplicating on path alone counts samples twice, and on content alone
    merges co-imaged samples with byte-identical files."""
    print("\n[1] deduplication -- re-hashing MERGED_LOGS ...")
    RECIPE_NAME_RE = re.compile(r"^recipe_(.+?)(?:_\d{6}_\d{6})?\.yml$", re.I)
    ACQLOG_NAME_RE = re.compile(r"^acqLog_(.+)\.txt$", re.I)

    def sha1(path):
        h = hashlib.sha1()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    results = {}
    for label, is_recipe in (("recipe", True), ("acqLog", False)):
        files = []
        for dirpath, _d, filenames in os.walk(MERGED):
            for fn in filenames:
                low = fn.lower()
                hit = (low.startswith("recipe") and low.endswith(".yml")) if is_recipe \
                    else ("acqlog" in low and low.endswith(".txt"))
                if hit:
                    files.append(os.path.join(dirpath, fn))

        by_hash_name = defaultdict(list)
        by_hash = defaultdict(set)
        for full in files:
            fn = os.path.basename(full)
            m = (RECIPE_NAME_RE if is_recipe else ACQLOG_NAME_RE).match(fn)
            name = m.group(1) if m else fn
            h = sha1(full)
            by_hash_name[(h, name)].append(full)
            by_hash[h].add(name)

        # How much a content-only rule would over-merge: every extra name
        # sharing a hash is a distinct sample it would have swallowed.
        overmerged = sum(len(names) - 1 for names in by_hash.values())
        results[label] = {
            "raw": len(files),
            "hash_name": len(by_hash_name),
            "hash_only": len(by_hash),
            "overmerged": overmerged,
            "group_sizes": Counter(len(v) for v in by_hash_name.values()),
        }
        note(f"{label}_raw_files", len(files))
        note(f"{label}_unique_hash_name", len(by_hash_name), "the rule used")
        note(f"{label}_unique_hash_only", len(by_hash))
        note(f"{label}_samples_lost_to_hash_only", overmerged)

        if is_recipe:
            # Stage 01's rules 1-7, in order.
            def backup(p):
                parts = os.path.relpath(os.path.dirname(p), MERGED).split(os.sep)
                return any(x.lower().startswith("logfiles") for x in parts)
            live = [f for f in files if not backup(f)]
            in_dir = defaultdict(list)
            for f in live:
                in_dir[os.path.dirname(f)].append(f)
            chosen = {d: recipes.original_recipe(sorted(v)) for d, v in in_dir.items()}
            key_of = {p: k for k, v in by_hash_name.items() for p in v}
            copies = defaultdict(list)
            for d, p in chosen.items():
                copies[key_of[p]].append(p)
            # Rule 4 matches copies by the run their log records; which
            # copy is kept does not change the count.
            same = {}
            for (h, name), v in sorted(copies.items()):
                rep = sorted(v)[0]
                st = recipes.run_start(rep)
                same.setdefault((recipes.system(recipes.read(rep)), name, st)
                                if st else (rep,), rep)
            samples = sorted(same.values())
            # Rule 5: a sample whose run (rig, acqStartTime) also has a
            # member in a subdirectory of its directory.
            by_acq = defaultdict(set)
            for p in samples:
                t = recipes.read(p)
                st = recipes.acq_start(t)
                by_acq[(recipes.system(t), st) if st else (p,)].add(os.path.dirname(p))
            parents = {d for ds in by_acq.values() for d in ds
                       if any(o.startswith(d + os.sep) for o in ds)}
            samples = [p for p in samples if os.path.dirname(p) not in parents]
            # Rule 6: the pairs are taken from the pipeline's table, since
            # finding them needs the acqLogs.
            by_run = defaultdict(list)
            for p in samples:
                t0 = recipes.log_first_start(os.path.dirname(p))
                if t0 is not None:
                    by_run[f"{recipes.system(recipes.read(p))}|{t0.strftime(FMT)}"].append(p)
            n_resumed = 0
            for r in rows("new_directory_resumes.csv"):
                a, b = by_run.get(r["first_key"], []), by_run.get(r["resumed_key"], [])
                if a and b:
                    n_resumed += min(len(a), len(b))
            # Rule 7: test runs (five or fewer sections), also taken from
            # the pipeline's table.
            n_test = sum(len(by_run.get(k, [])) for k in resumes.test_run_keys())
            results[label]["expected"] = len(samples) - n_resumed - n_test
            note("recipe_backups_ignored", len(files) - len(live))
            note("recipe_extra_per_directory_dropped", len(live) - len(chosen))
            note("recipe_copies_in_other_directories", len(chosen) - len(copies))
            note("recipe_same_sample_collapsed", len(copies) - len(same))
            note("recipe_unsplit_parents_dropped", len(same) - len(samples))
            note("recipe_new_directory_resumes_dropped", n_resumed)
            note("recipe_test_runs_dropped", n_test)
        else:
            results[label]["expected"] = len(by_hash_name)

    # Cross-check against what 01 actually wrote.
    for label, fname in (("recipe", "unique_recipes.txt"),
                         ("acqLog", "unique_acqlogs.txt")):
        with open(data(fname)) as f:
            n = sum(1 for l in f if l.strip())
        agree = (n == results[label]["expected"])
        note(f"{label}_matches_pipeline", agree, f"{n} lines in {fname}")
        if not agree:
            print(f"  !! {fname} disagrees with the re-derivation", file=sys.stderr)

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))

    ax = axes[0]
    sizes = sorted(set(results["recipe"]["group_sizes"]) |
                   set(results["acqLog"]["group_sizes"]))
    sizes = [s for s in sizes if s > 1]
    x = np.arange(len(sizes))
    w = 0.38
    ax.bar(x - w / 2, [results["recipe"]["group_sizes"].get(s, 0) for s in sizes],
           w, color=BLUE, label="recipe files (samples)")
    ax.bar(x + w / 2, [results["acqLog"]["group_sizes"].get(s, 0) for s in sizes],
           w, color=ORANGE, label="acqLog files")
    ax.set_xticks(x)
    ax.set_xticklabels([str(s) for s in sizes])
    ax.set_yscale("log")
    ax.set_xlabel("copies of the same file found in MERGED_LOGS")
    ax.set_ylabel("groups (log scale)")
    title(ax, "A  Redundant copies collapsed by the dedup pass")
    ax.legend(frameon=False, fontsize=8)

    ax = axes[1]
    labels = ["raw files\non disk", "dedup on\ncontent + name\n(used)",
              "dedup on\ncontent only\n(rejected)"]
    vals = [results["recipe"]["raw"], results["recipe"]["hash_name"],
            results["recipe"]["hash_only"]]
    colors = [GREY, BLUE, ORANGE]
    bars = ax.bar(labels, vals, color=colors, width=0.6)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:,}",
                ha="center", va="bottom", fontsize=8.5, color=INK)
    lost = results["recipe"]["overmerged"]
    ax.annotate(f"content-only dedup would lose\n{lost:,} distinct samples: co-imaged\n"
                "organs share one byte-identical file",
                xy=(2, vals[2] * 0.80), xytext=(0.38, 0.78),
                textcoords="axes fraction", fontsize=8, color=MUTED,
                ha="left", va="bottom",
                arrowprops=dict(arrowstyle="->", color=MUTED, lw=0.9))
    ax.set_ylabel("recipe files")
    title(ax, "B  Why the dedup key is (content, sample name)")
    ax.set_ylim(0, max(vals) * 1.35)

    fig.tight_layout()
    save(fig, "01_deduplication.png")


# ===================================================================== 2
def check_grouping():
    """Acquisitions from the recipes (02) against those from the acqLog
    headers (05): different files, different parsers."""
    print("\n[2] acquisition grouping -- recipes vs acqLogs ...")
    samples = rows("fig_samples_dated.csv")
    metrics = rows("acquisition_metrics.csv")

    per_acq = Counter(s["acq_key"] for s in samples)
    note("samples_total", len(samples))
    note("acquisitions_from_recipes", len(per_acq))
    note("acquisitions_from_acqlogs", len(metrics))

    # Both key formats to (system, datetime).
    def norm_recipe(k):
        system, _, ts = k.partition("|")
        try:
            return (system, datetime.strptime(ts, "%y%m%d_%H%M%S"))
        except ValueError:
            return None

    def norm_log(k):
        system, _, ts = k.partition("|")
        try:
            return (system, datetime.strptime(ts, FMT))
        except ValueError:
            return None

    # The recipe and the log header are written at slightly different
    # moments, so the check is the distribution of offsets.
    rec_by_lab = defaultdict(list)
    for k in per_acq:
        n = norm_recipe(k)
        if n:
            rec_by_lab[n[0]].append(n[1])
    for lab in rec_by_lab:
        rec_by_lab[lab] = sorted(set(rec_by_lab[lab]))

    offsets, unmatched = [], 0
    for m in metrics:
        n = norm_log(m["acq_key"])
        if not n:
            continue
        arr = rec_by_lab.get(n[0], [])
        if not arr:
            unmatched += 1
            continue
        i = bisect.bisect_left(arr, n[1])
        cands = [arr[j] for j in (i - 1, i) if 0 <= j < len(arr)]
        offsets.append(min(abs((c - n[1]).total_seconds()) for c in cands))

    off = np.array(offsets)
    note("acqs_with_both_file_types", len(off))
    note("offset_median_s", float(np.median(off)))
    note("matched_within_60s", int((off <= 60).sum()))
    note("matched_within_60s_pct", round(float(100 * (off <= 60).mean()), 1))
    note("offset_over_1h", int((off > 3600).sum()))

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))

    ax = axes[0]
    counts = Counter(per_acq.values())
    ks = sorted(counts)
    ax.bar([str(k) for k in ks], [counts[k] for k in ks], color=BLUE, width=0.65)
    for i, k in enumerate(ks):
        ax.text(i, counts[k], f"{counts[k]:,}", ha="center", va="bottom",
                fontsize=7.5, color=INK)
    ax.set_yscale("log")
    ax.set_xlabel("samples imaged in one acquisition")
    ax.set_ylabel("acquisitions (log scale)")
    title(ax, "A  Co-imaging is common, so samples != acquisitions")

    ax = axes[1]
    clipped = np.clip(off, 0, 120)
    ax.hist(clipped, bins=np.arange(0, 122, 2), color=BLUE)
    ax.set_yscale("log")
    ax.set_xlabel("|recipe start − acqLog start| (s, clipped at 120)")
    ax.set_ylabel("acquisitions (log scale)")
    title(ax, "B  Two independent clocks describe the same run")
    ax.text(0.97, 0.94,
            f"median {np.median(off):.0f} s\n"
            f"{100 * (off <= 60).mean():.1f}% within 60 s\n"
            f"{(off > 3600).sum()} beyond an hour",
            transform=ax.transAxes, ha="right", va="top", fontsize=8,
            color=MUTED)

    fig.tight_layout()
    save(fig, "02_acquisition_grouping.png")


# ============================================================ 3, 4, 5, 6
SECTION_START_RE = re.compile(
    r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) -- STARTING section number (\d+)"
    r"(?:\s*\((\d+) of \d+\))?")
SECTION_DONE_RE = re.compile(
    r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) -- FINISHED section number (\d+), "
    r"section completed in (.+?)\s*$")
FINISHED_ANY_RE = re.compile(r"FINISHED section number \d+, section completed in")


def scan_logs():
    """One pass over every deduplicated acqLog, collecting what checks
    3 and 5 need: per-section (parsed duration, timestamp-derived
    duration) pairs, and the section counter around each restart."""
    print("\n[3/5] re-reading the deduplicated acqLogs ...")
    with open(data("unique_acqlogs.txt")) as f:
        paths = [l.strip() for l in f if l.strip()]

    # Restarts by (file, block start line).
    restarts = defaultdict(list)
    # Restarts into a new directory have no line to check, so are skipped.
    for e in rows("restart_events_full.csv"):
        if e["block_start_line"]:
            restarts[e["file"]].append(int(e["block_start_line"]))

    pairs = []           # (parsed_seconds, timestamp_delta_seconds, year)
    unparsed = []        # timestamps of lines with an empty duration field
    n_finished = n_parsed = n_dropped = 0
    per_year_lines = Counter()
    per_year_parsed = Counter()
    shapes = Counter()
    corroborated = uncorroborated = no_counter = 0

    for i, path in enumerate(paths, 1):
        try:
            with open(abs_log(path), errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue

        counters = {}     # line index -> "(X of Y)" X value
        last_start = None
        for j, line in enumerate(lines):
            m = SECTION_START_RE.match(line)
            if m:
                last_start = (m.group(1), j)
                if m.group(3):
                    counters[j] = int(m.group(3))
                continue

            if FINISHED_ANY_RE.search(line):
                n_finished += 1
                m2 = SECTION_DONE_RE.match(line)
                if not m2:
                    # Empty duration: all fall on the night UK clocks go
                    # back (a negative elapsed time). Reported, not skipped.
                    unparsed.append(line.strip()[:19])
                    continue
                year = int(m2.group(1)[:4])
                per_year_lines[year] += 1
                secs = parse_duration(m2.group(3))
                # Record the SHAPE of the duration string, units only.
                shapes["+".join(u.lower() for _v, u in
                                _metrics.DUR_TOKEN_RE.findall(m2.group(3)))] += 1
                if secs is None:
                    continue
                n_parsed += 1
                per_year_parsed[year] += 1
                if secs > MAX_PLAUSIBLE_SECTION_SECONDS:
                    n_dropped += 1
                    continue
                # The same duration from the section's own timestamps.
                if last_start is not None:
                    try:
                        t0 = datetime.strptime(last_start[0], FMT)
                        t1 = datetime.strptime(m2.group(1), FMT)
                    except ValueError:
                        continue
                    delta = (t1 - t0).total_seconds()
                    if 0 < delta <= MAX_PLAUSIBLE_SECTION_SECONDS:
                        pairs.append((secs, delta, year))

        # Does the "(X of Y)" counter reset to 1 after each restart?
        for start_line in restarts.get(path, []):
            after = [v for j, v in counters.items() if start_line - 1 <= j < start_line + 60]
            before = [v for j, v in counters.items() if j < start_line - 1]
            if not after or not before:
                no_counter += 1
            elif after[0] <= before[-1]:
                corroborated += 1
            else:
                uncorroborated += 1

        if i % 2000 == 0:
            print(f"    ...{i}/{len(paths)}")

    return dict(pairs=pairs, n_finished=n_finished, n_parsed=n_parsed,
                unparsed=unparsed,
                n_dropped=n_dropped, per_year_lines=per_year_lines,
                per_year_parsed=per_year_parsed, shapes=shapes,
                corroborated=corroborated, uncorroborated=uncorroborated,
                no_counter=no_counter)


def check_durations(scan):
    """Parsed section durations against the log's own timestamps."""
    print("\n[3] duration parsing")
    parsed = np.array([p[0] for p in scan["pairs"]])
    delta = np.array([p[1] for p in scan["pairs"]])
    resid = parsed - delta

    note("finished_section_lines", scan["n_finished"])
    note("durations_parsed", scan["n_parsed"])
    note("lines_with_empty_duration", len(scan["unparsed"]))
    note("empty_duration_dates",
         sorted({t[:10] for t in scan["unparsed"]}),
         "all the night the UK clock goes back")
    note("parse_failures_with_text", scan["n_finished"] - scan["n_parsed"]
         - len(scan["unparsed"]), "must be 0")
    note("sections_over_3h_dropped", scan["n_dropped"])
    note("sections_cross_checked", len(parsed))
    note("median_abs_residual_s", round(float(np.median(np.abs(resid))), 1))
    note("max_abs_residual_s", round(float(np.max(np.abs(resid))), 1))
    note("sections_off_by_over_5s", int((np.abs(resid) > 5).sum()))
    note("pct_within_5s", round(float(100 * np.mean(np.abs(resid) <= 5)), 3))
    note("pct_within_60s", round(float(100 * np.mean(np.abs(resid) <= 60)), 3))

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.0))

    ax = axes[0]
    lim = np.percentile(delta, 99.5)
    hb = ax.hexbin(delta / 60, parsed / 60, gridsize=90, bins="log",
                   extent=(0, lim / 60, 0, lim / 60), cmap="Blues", mincnt=1)
    ax.plot([0, lim / 60], [0, lim / 60], color=ORANGE, lw=1.2, ls="--",
            label="y = x")
    ax.set_xlabel("section duration from the log timestamps (min)")
    ax.set_ylabel("duration parsed from the text (min)")
    title(ax, "A  The parser agrees with the clock")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.text(0.03, 0.80,
            f"{len(parsed):,} sections\n"
            f"median difference {np.median(np.abs(resid)):.0f} s\n"
            f"{int((np.abs(resid) > 5).sum())} differ by more than 5 s",
            transform=ax.transAxes, va="top", fontsize=7.5, color=MUTED)
    cb = fig.colorbar(hb, ax=ax, pad=0.02)
    cb.set_label("sections", fontsize=8)
    cb.ax.tick_params(labelsize=7)
    ax.grid(False)

    # B -- every wording the parser has to cope with, and how common it is.
    ax = axes[1]
    shapes = [(k, v) for k, v in scan["shapes"].most_common() if k]
    labels = [EXAMPLE_OF.get(k, k) for k, _ in shapes][::-1]
    counts = [v for _, v in shapes][::-1]
    ax.barh(labels, counts, color=BLUE, height=0.62)
    ax.set_xscale("log")
    ax.set_xlim(1, max(counts) * 8)
    for i, c in enumerate(counts):
        ax.text(c * 1.3, i, f"{c:,}", va="center", fontsize=7.5, color=INK)
    ax.set_xlabel("sections (log scale)")
    ax.tick_params(axis="y", labelsize=7.5)
    ax.grid(axis="y", visible=False)
    title(ax, "B  Seven wordings, all handled")

    # C -- a parser failing in one era would separate the curves.
    ax = axes[2]
    years = sorted({p[2] for p in scan["pairs"]})
    med_parsed = [np.median([p[0] for p in scan["pairs"] if p[2] == y]) / 60
                  for y in years]
    med_clock = [np.median([p[1] for p in scan["pairs"] if p[2] == y]) / 60
                 for y in years]
    ax.plot(years, med_clock, marker="o", ms=6, color=BLUE, lw=2,
            label="from the log timestamps")
    ax.plot(years, med_parsed, marker="s", ms=4.5, color=ORANGE, lw=1.2,
            ls="--", label="parsed from the text")
    ax.set_ylim(0, max(med_clock) * 1.35)
    ax.set_xlabel("year")
    ax.set_ylabel("median section duration (min)")
    ax.set_xticks(years)
    ax.tick_params(axis="x", rotation=45, labelsize=7.5)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    title(ax, "C  No era is parsed wrongly")
    ax.annotate("2016 logs write '467.5 s'.\nAn earlier parser scored\nthis year as zero hours.",
                xy=(years[0], med_parsed[0] * 0.98), xytext=(0.45, 0.86),
                textcoords="axes fraction", fontsize=7.5, color=MUTED,
                va="top", arrowprops=dict(arrowstyle="->", color=MUTED, lw=0.9))

    fig.tight_layout()
    save(fig, "03_duration_parsing.png")

    print("\n  duration-string shapes actually present:")
    for shape, n in scan["shapes"].most_common():
        print(f"    {shape or '(unparsed)':22s} {n:9,}")
    STATS["duration_shapes"] = scan["shapes"].most_common()


def check_imaging_time():
    """Imaging hours vs wall-clock hours, per acquisition."""
    print("\n[4] imaging time vs wall-clock")
    m = rows("acquisition_metrics.csv")
    img = np.array([float(r["imaging_seconds"]) for r in m]) / 3600
    wall = np.array([float(r["wallclock_seconds"]) for r in m]) / 3600
    restarted = np.array([int(r["n_starts"]) > 1 for r in m])

    # Imaging time exceeds wall-clock only through a clock change (the span
    # loses an hour) or rounding of the printed durations.
    excess = img - wall
    over = excess > 1e-6
    dst = over & (excess > 0.5)
    note("acqs_imaging_gt_wallclock", int(over.sum()))
    note("of_those_clock_change", int(dst.sum()))
    note("clock_change_dates", sorted(m[i]["start"][:10] for i in np.where(dst)[0]))
    note("other_excess_max_s", round(float(excess[over & ~dst].max() * 3600), 1),
         "rounding, spread over hundreds of sections")
    note("total_imaging_h", round(float(img.sum())))
    note("total_wallclock_h", round(float(wall.sum())))
    note("idle_h", round(float(wall.sum() - img.sum())))
    note("idle_pct_of_wallclock",
         round(float(100 * (wall.sum() - img.sum()) / wall.sum()), 1))
    gap = wall - img
    note("median_gap_h_no_restart", round(float(np.median(gap[~restarted])), 2))
    note("median_gap_h_restarted", round(float(np.median(gap[restarted])), 2))
    note("n_restarted_acqs", int(restarted.sum()))

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9))

    ax = axes[0]
    ax.scatter(wall[~restarted], img[~restarted], s=5, color=BLUE,
               linewidths=0, label="ran without a restart")
    ax.scatter(wall[restarted], img[restarted], s=11, color=ORANGE,
               linewidths=0, label="stopped and resumed")
    top = float(np.percentile(wall, 99.7))
    ax.plot([0, top], [0, top], color=MUTED, lw=1.0, ls="--", label="y = x")
    ax.set_xlim(0, top)
    ax.set_ylim(0, top)
    ax.set_xlabel("wall-clock span of the log (h)")
    ax.set_ylabel("summed section durations (h)")
    title(ax, "A  Imaging time stays under elapsed time")
    ax.legend(frameon=False, fontsize=8, loc="upper left",
              bbox_to_anchor=(0.0, 0.78))
    ax.text(0.03, 0.95,
            f"{int(over.sum())} acquisitions sit just above the line:\n"
            f"{int(dst.sum())} ran through the autumn clock change,\n"
            f"the rest are <{excess[over & ~dst].max()*3600:.0f} s of rounding",
            transform=ax.transAxes, va="top", fontsize=7.5, color=MUTED)

    ax = axes[1]
    bins = np.arange(0, 24.5, 0.5)
    ax.hist([np.clip(gap[~restarted], 0, 24), np.clip(gap[restarted], 0, 24)],
            bins=bins, stacked=True, color=[BLUE, ORANGE],
            label=["ran without a restart", "stopped and resumed"])
    ax.set_yscale("log")
    ax.set_xlabel("idle time: wall-clock − imaging (h, clipped at 24)")
    ax.set_ylabel("acquisitions (log scale)")
    title(ax, "B  Idle time is concentrated in the runs that stopped")
    ax.legend(frameon=False, fontsize=8)

    fig.tight_layout()
    save(fig, "04_imaging_vs_wallclock.png")


def check_restarts(scan):
    """Restart detection, its corroborating signal, and the categories."""
    print("\n[5] restart detection")
    ev = rows("fig_failures.csv")
    tot = scan["corroborated"] + scan["uncorroborated"] + scan["no_counter"]
    note("restart_events", len(ev))
    note("restart_counter_reset_confirmed", scan["corroborated"])
    note("restart_counter_not_reset", scan["uncorroborated"])
    note("restart_no_counter_in_log", scan["no_counter"])
    note("restart_corroborated_pct",
         round(100 * scan["corroborated"] / max(tot - scan["no_counter"], 1), 1))

    # Categories are counted per restart EVENT, as in the figure; an
    # acquisition restarted twice contributes two.
    cat_acqs = defaultdict(set)
    for e in ev:
        cat_acqs[e["category"]].add(e["event_key"])
    note("restart_events_unique", len({e["event_key"] for e in ev}))
    note("restart_acquisitions", len({e["acq_key"] for e in ev}))
    for c, s in sorted(cat_acqs.items(), key=lambda kv: -len(kv[1])):
        note(f"cat_{c.replace(' ', '_')}", len(s))

    gaps = np.array([float(e["gap_seconds"]) for e in ev
                     if e["gap_seconds"] not in ("", None)])
    gaps = gaps[gaps > 0]

    fig, axes = plt.subplots(1, 3, figsize=(13.5, 3.8))

    ax = axes[0]
    vals = [scan["corroborated"], scan["uncorroborated"], scan["no_counter"]]
    labels = ["counter\nrestarted", "counter did\nnot restart",
              "log has no\n'(X of Y)' counter"]
    bars = ax.bar(labels, vals, color=[AQUA, ORANGE, GREY], width=0.6)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:,}", ha="center",
                va="bottom", fontsize=8.5, color=INK)
    ax.set_ylabel("detected restart events")
    title(ax, "A  An independent signal confirms the detection")

    ax = axes[1]
    n_unplanned = len(cat_acqs["true unknown"] | cat_acqs["laser fault"])
    n_user = sum(len(cat_acqs[c]) for c in
                 ("manual abort", "planned stop", "natural completion"))
    order = ["true unknown", "manual abort", "laser fault",
             "planned stop", "natural completion"]
    order = [c for c in order if c in cat_acqs]
    vals = [len(cat_acqs[c]) for c in order]
    colours = ["#4a3aa7" if c == "true unknown" else
               ORANGE if c == "laser fault" else AQUA for c in order]
    bars = ax.barh(order[::-1], vals[::-1], color=colours[::-1], height=0.6)
    for b, v in zip(bars, vals[::-1]):
        ax.text(v, b.get_y() + b.get_height() / 2, f" {v}", va="center",
                fontsize=8.5, color=INK)
    ax.set_xlabel("restart events")
    title(ax, "B  Why each restart happened")
    ax.grid(axis="y", visible=False)
    ax.text(0.98, 0.06,
            f"green: the user's own choice ({n_user})\n"
            f"orange / violet: unplanned ({n_unplanned})",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=7.5,
            color=MUTED)

    ax = axes[2]
    ax.hist(np.log10(gaps / 60), bins=40, color=BLUE)
    ax.set_xlabel("downtime before resumption (min, log scale)")
    ax.set_ylabel("restart events")
    ticks = [0, 1, 2, 3]
    ax.set_xticks(ticks)
    ax.set_xticklabels(["1", "10", "100", "1000"])
    ax.axvline(np.log10(np.median(gaps) / 60), color=ORANGE, lw=1.2, ls="--")
    ax.text(np.log10(np.median(gaps) / 60), ax.get_ylim()[1] * 0.95,
            f" median {np.median(gaps)/60:.0f} min", fontsize=8, color=MUTED,
            va="top")
    title(ax, "C  Most stops were caught quickly")
    note("median_downtime_min", round(float(np.median(gaps) / 60), 1))

    fig.tight_layout()
    save(fig, "05_restart_detection.png")


def check_coverage():
    """Where the record is thick, where it is thin, and what is missing."""
    print("\n[6] coverage over time")
    samples = [s for s in rows("fig_samples_dated.csv") if s["datetime"]]
    per_year = rows("fig_per_year.csv")

    months = Counter(s["datetime"][:7] for s in samples)
    keys = sorted(months)
    xs = [datetime.strptime(k, "%Y/%m") for k in keys]
    note("dated_samples", len(samples))
    note("undated_samples", len(rows("fig_samples_dated.csv")) - len(samples))
    note("first_month", keys[0])
    note("last_month", keys[-1])

    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))

    ax = axes[0]
    ax.bar(xs, [months[k] for k in keys], width=22, color=BLUE)
    ax.set_ylabel("samples imaged")
    ax.set_xlabel("month")
    title(ax, "A  Ten unbroken years of acquisition")

    ax = axes[1]
    years = [r["year"] for r in per_year]
    cov = [100 * float(r["tile_logging_coverage"]) for r in per_year]
    bars = ax.bar(years, cov, color=[GREY if c < 50 else BLUE for c in cov],
                  width=0.65)
    ax.set_ylim(0, 150)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel("% of acquisitions logging tile positions")
    ax.tick_params(axis="x", rotation=45, labelsize=7.5)
    title(ax, "B  Tile-position logging starts in 2017")
    ax.annotate("BakingTray did not log tile positions\nuntil 2017. Every tile-normalised\n"
                "number for 2016 is drawn as n/a,\nnever as zero.",
                xy=(0, 3), xytext=(0.07, 0.74), textcoords="axes fraction",
                fontsize=8, color=MUTED, va="center",
                arrowprops=dict(arrowstyle="->", color=MUTED, lw=0.9))
    ax.text(0, 2, "0", ha="center", va="bottom", fontsize=8, color=INK)
    note("tile_coverage_2016_pct", round(cov[0], 1))
    note("tile_coverage_2017_pct", round(cov[1], 1))

    fig.tight_layout()
    save(fig, "06_coverage.png")


def check_resolution_bands():
    """The resolution binning against the distribution it bins."""
    print("\n[7] resolution bands")
    res = rows("fig_acq_resolution.csv")
    v = np.array([float(r["voxel_x_um"]) for r in res])
    band = [r["band"] for r in res]
    note("acqs_with_voxel_size", len(v))
    note("acqs_unbinned", sum(1 for b in band if not b), "must be 0")

    bands = [("<0.7", 0.3, 0.7), ("0.7-1.7", 0.7, 1.7), ("1.7-2.7", 1.7, 2.7),
             ("2.7-3.9", 2.7, 3.9), ("3.9-4.8", 3.9, 4.8),
             ("4.8-7.5", 4.8, 7.5), ("7.5-10", 7.5, 10.0)]
    counts = Counter(band)

    fig, ax = plt.subplots(figsize=(10, 4.0))
    bins = np.logspace(np.log10(0.4), np.log10(10.5), 110)
    for i, (name, lo, hi) in enumerate(bands):
        if i % 2:
            ax.axvspan(lo, hi, color="#f2f4f7", zorder=0)
        ax.axvline(hi, color=MUTED, lw=0.7, ls="--", zorder=1)
    ax.hist(v, bins=bins, color=BLUE, zorder=2)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(0.4, 10.5)
    ax.set_ylim(0.7, 3000)
    for name, lo, hi in bands:
        ax.text(np.sqrt(lo * hi), 1600, f"{name}\nn={counts.get(name, 0)}",
                ha="center", va="center", fontsize=7.5, color=MUTED)
    ax.set_xlabel("XY voxel size from the recipe (µm/pixel), log scale")
    ax.set_ylabel("acquisitions (log scale)")
    title(ax, "Bands follow the measured modes, and nothing falls outside one")
    ax.set_xticks([0.5, 1, 2, 4, 8])
    ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    ax.grid(False)
    fig.tight_layout()
    save(fig, "07_resolution_bands.png")


def check_depth_normalisation():
    """Scaled-to-12.5 mm times against the measured value, where measured."""
    print("\n[8] depth normalisation")
    cohort = rows("fig_timing_cohort.csv")
    keys = {r["acq_key"]: r for r in cohort if r["reached_target"] == "1"}

    # Measured time at exactly 12.5 mm: the last section at or before that
    # depth, from the per-section table.
    measured = {}
    with gzip.open(data("acq_timing_sections.csv.gz"), "rt") as f:
        for s in csv.DictReader(f):
            if s["acq_key"] in keys and float(s["depth_mm"]) <= 12.5:
                measured[s["acq_key"]] = float(s["cum_imaging_h"])

    ks = [k for k in keys if k in measured]
    meas = np.array([measured[k] for k in ks])
    scaled = np.array([float(keys[k]["h_at_target"]) for k in ks])
    pct = 100 * (scaled - meas) / meas

    note("cohort_acquisitions", len(cohort))
    note("cohort_reached_12.5mm", len(keys))
    note("cohort_checked", len(ks))
    note("median_scaling_error_pct", round(float(np.median(pct)), 1))
    note("iqr_scaling_error_pct",
         [round(float(np.percentile(pct, 25)), 1),
          round(float(np.percentile(pct, 75)), 1)])

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    ax = axes[0]
    ax.scatter(meas, scaled, s=14, color=BLUE, linewidths=0)
    top = max(meas.max(), scaled.max()) * 1.05
    ax.plot([0, top], [0, top], color=ORANGE, lw=1.1, ls="--", label="y = x")
    ax.set_xlim(0, top)
    ax.set_ylim(0, top)
    ax.set_xlabel("measured hours to 12.5 mm")
    ax.set_ylabel("hours scaled from hours-per-mm")
    title(ax, "A  Scaling reproduces the measured time")
    ax.legend(frameon=False, fontsize=8, loc="upper left")

    ax = axes[1]
    ax.hist(pct, bins=25, color=BLUE)
    ax.axvline(0, color=MUTED, lw=0.9)
    ax.axvline(float(np.median(pct)), color=ORANGE, lw=1.2, ls="--")
    ax.set_xlabel("scaled − measured (% of measured)")
    ax.set_ylabel("acquisitions")
    title(ax, f"B  Median error {np.median(pct):+.1f}%")
    fig.tight_layout()
    save(fig, "08_depth_normalisation.png")


def main():
    print(f"MERGED_LOGS : {MERGED}")
    print(f"derived_data: {os.path.dirname(data('x'))}")
    check_dedup()
    check_grouping()
    scan = scan_logs()
    check_durations(scan)
    check_imaging_time()
    check_restarts(scan)
    check_coverage()
    check_resolution_bands()
    check_depth_normalisation()

    print("\n" + "=" * 68)
    print("Every number quoted in validation.md, in one place:")
    print("=" * 68)
    for k, v in STATS.items():
        if k == "duration_shapes":
            continue
        print(f"{k:38s} {v}")


if __name__ == "__main__":
    main()
