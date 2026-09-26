#!/usr/bin/env python3
"""
Rebuild derived_data/ from the raw logs by running stages 01-08 in order.

Not needed to draw the figures: derived_data/ is in the repository, and a
rebuild reproduces it byte for byte. Unpack the logs first:

    cd raw
    tar -xjf MERGED_LOGS.tar.bz2      # about 1.3 GB
    python3 write_derived_data.py

or point at them elsewhere with MERGED_LOGS=/path/to/MERGED_LOGS.

Each stage runs as its own process; the run stops at the first failure
and says how to resume. It draws no figures (../acquisition_stats.py,
../acquisition_timing.py) and no validation plots (09_make_readme_figures.py).

Options:
  --from NN             resume at stage NN
  --with-diagnostics    also run 04, which only prints
  --list                print the stages and exit
  --quiet               hide each stage's own output
"""

import argparse
import os
import subprocess
import sys
import time

from paths import MERGED, DATA_DIR, HERE

ARCHIVE = "MERGED_LOGS.tar.bz2"

# (number, script, one-line purpose, files it writes into derived_data/)
STAGES = [
    ("01", "01_dedup_merged_logs.py",
     "deduplicate MERGED_LOGS; one recipe per sample; find runs resumed into a new directory",
     ["unique_recipes.txt", "unique_acqlogs.txt", "duplicate_groups.csv",
      "resume_recipes.csv", "unsplit_recipes.csv", "new_directory_resumes.csv",
      "test_runs.csv"]),
    ("02", "02_count_acquisitions.py",
     "group samples into acquisitions by (rig, acqStartTime)",
     ["sample_acquisition_groups.csv"]),
    ("03", "03_classify_restarts.py",
     "find and classify restarts; set aside setup restarts (<= 5 sections)",
     ["restart_events_full.csv", "setup_restarts.csv"]),
    ("04", "04_investigate_unknown.py",
     "diagnostic summary of the unexplained restarts (prints only)",
     []),
    ("05", "05_extract_acquisition_metrics.py",
     "imaging hours, tile positions and sections per acquisition",
     ["acquisition_metrics.csv", "acquisition_metrics_per_logfile.csv"]),
    ("06", "06_build_figure_data.py",
     "tables for the main figure; restart categories grouped",
     ["fig_samples_dated.csv", "fig_acq_resolution.csv",
      "fig_failures.csv", "fig_per_year.csv"]),
    ("07", "07_extract_acquisition_timing.py",
     "per-section time series joined to each run's recipe",
     ["acq_timing_index.csv", "acq_timing_sections.csv.gz"]),
    ("08", "08_build_timing_figure_data.py",
     "select the published timing cohort",
     ["fig_timing_cohort.csv", "fig_timing_averaging.csv"]),
]

# 04 writes nothing, so it runs only on request.
OPTIONAL = {"04": "--with-diagnostics"}


def preflight():
    """Exit with a clear message if the logs are missing or still packed."""
    problems = []
    if not os.path.isdir(MERGED):
        archive = os.path.join(HERE, ARCHIVE)
        if os.path.exists(archive):
            problems.append(
                f"the raw logs are still packed.\n"
                f"    Unpack them first -- about 1.3 GB, a minute or two:\n\n"
                f"        cd {HERE}\n"
                f"        tar -xjf {ARCHIVE}\n")
        else:
            problems.append(
                f"MERGED_LOGS not found at {MERGED}, and {ARCHIVE}\n"
                f"    is not here either. Point at the logs with:\n\n"
                f"        export MERGED_LOGS=/path/to/MERGED_LOGS\n")
    else:
        labs = [d for d in os.listdir(MERGED)
                if os.path.isdir(os.path.join(MERGED, d))]
        if not labs:
            problems.append(f"{MERGED} exists but contains no lab directories")

    if problems:
        print("Cannot start:\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)


def human(seconds):
    """A duration for display."""
    return f"{seconds:.0f} s" if seconds < 90 else f"{seconds / 60:.1f} min"


def manifest():
    """Print derived_data/ with file sizes."""
    print("\n" + "=" * 70)
    print(f"derived_data/  ({DATA_DIR})")
    print("=" * 70)
    for name in sorted(os.listdir(DATA_DIR)):
        mb = os.path.getsize(os.path.join(DATA_DIR, name)) / 1e6
        print(f"  {name:38s} {mb:8.1f} MB")
    print("\nThe manuscript figures are drawn from these by\n"
          "acquisition_stats.py and acquisition_timing.py one level up; this\n"
          "script does not touch them.")


def main():
    ap = argparse.ArgumentParser(
        description="Rebuild derived_data/ from the raw instrument logs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Unpack MERGED_LOGS.tar.bz2 in this directory first.")
    ap.add_argument("--from", dest="start", metavar="NN",
                    help="resume at this stage number, e.g. --from 05")
    ap.add_argument("--with-diagnostics", action="store_true",
                    help="also run 04, the console-only restart diagnostic")
    ap.add_argument("--list", action="store_true",
                    help="print the stages and exit")
    ap.add_argument("--quiet", action="store_true",
                    help="hide each script's own output")
    args = ap.parse_args()

    if args.list:
        for num, script, purpose, _ in STAGES:
            flag = f"  [{OPTIONAL[num]}]" if num in OPTIONAL else ""
            print(f"{num}  {script:34s} {purpose}{flag}")
        return 0

    # "--from 5" and "--from 05" both work; an unknown stage is an error.
    start_at = 0
    if args.start:
        key = args.start.zfill(2)
        ids = [num for num, *_ in STAGES]
        if key not in ids:
            print(f"--from {args.start}: no such stage. "
                  "Run --list to see them.", file=sys.stderr)
            return 1
        start_at = ids.index(key)

    selected = [(pos, s) for pos, s in enumerate(STAGES)
                if pos >= start_at
                and (s[0] not in OPTIONAL or args.with_diagnostics)]

    preflight()

    print(f"MERGED_LOGS   {MERGED}")
    print(f"writing to    {DATA_DIR}")
    print(f"{len(selected)} stages to run\n")

    t_all = time.time()
    for i, (_pos, (num, script, purpose, outputs)) in enumerate(selected, 1):
        print("-" * 70)
        print(f"[{i}/{len(selected)}]  {script}")
        print(f"          {purpose}")
        print("-" * 70)
        t0 = time.time()
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, script)],
            cwd=HERE,
            stdout=subprocess.DEVNULL if args.quiet else None)
        elapsed = time.time() - t0

        if result.returncode != 0:
            print(f"\n*** {script} failed (exit {result.returncode}) "
                  f"after {human(elapsed)}.", file=sys.stderr)
            print("*** Stopping. Nothing after this stage has run; fix the\n"
                  f"*** problem and resume with:\n"
                  f"***     python3 write_derived_data.py --from {num}",
                  file=sys.stderr)
            return result.returncode

        missing = [f for f in outputs
                   if not os.path.exists(os.path.join(DATA_DIR, f))]
        if missing:
            print(f"\n*** {script} exited cleanly but did not write: "
                  f"{', '.join(missing)}", file=sys.stderr)
            return 1

        print(f"\n  done in {human(elapsed)}"
              + (f" -> {', '.join(outputs)}" if outputs else ""))
        print()

    manifest()
    print(f"\nAll {len(selected)} stages completed in {human(time.time() - t_all)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
