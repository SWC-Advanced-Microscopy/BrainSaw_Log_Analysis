#!/usr/bin/env python3
"""
Stage 03: find and classify restarts in unique_acqlogs.txt.

A resumed run appends a new "STARTING NEW ACQUISITION" block to its log,
so every such line after the first is a restart. A run resumed into a new
directory (resumes.py) has its own log; there the restart is the second
run's start and the stop is the end of the first run's log.

A stop is classified from its own block only (classify), so a short block
cannot inherit the end message of the block before it. A restart after
MAX_SETUP_SECTIONS or fewer sections in its block is a setup restart,
whatever the reason, and is not counted.

One row per (acqLog, restart): co-imaged samples share a log, so one
restart appears once per sample. Stage 06 collapses them by (rig, time).

Writes restart_events_full.csv (counted) and setup_restarts.csv.
"""
import re
import csv
from collections import Counter
from datetime import datetime

from paths import data, lab_of, log_list, rel_log
from recipes import system_of_acqlog
import resumes

MAX_SETUP_SECTIONS = 5

START_RE = re.compile(r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) -- STARTING NEW ACQUISITION")
ANY_TS_RE = re.compile(r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})")
FINISHED_RE = re.compile(r"FINISHED section number \d+")
FMT = "%Y/%m/%d %H:%M:%S"

FIRST_PASS = [
    (re.compile(r"abortAfterSectionComplete"), "manual abort"),
    (re.compile(r"STOPPING ACQUISITION DUE TO LASER"), "laser fault"),
]
SECOND_PASS = [
    (re.compile(r"FINISHED AND COMPLETED ACQUISITION"), "planned stop"),
    (re.compile(r"Found no tissue"), "natural completion"),
    (re.compile(r"LASER NOT RUNNING"), "laser fault"),
]

FIELDS = ["file", "lab", "system", "block_start_line", "restart_timestamp",
          "sections_before", "category", "gap_seconds", "source"]


def classify(block):
    """Why the run stopped, from the end of its block. Last 15 lines:
    abortAfterSectionComplete (manual abort) or STOPPING ACQUISITION DUE TO
    LASER. Else last 60 lines: FINISHED AND COMPLETED ACQUISITION (planned
    stop), Found no tissue (natural completion) or LASER NOT RUNNING. Else
    "true unknown"."""
    for n, patterns in ((15, FIRST_PASS), (60, SECOND_PASS)):
        text = "".join(block[-n:])
        for pat, label in patterns:
            if pat.search(text):
                return label
    return "true unknown"


def last_timestamp(block):
    for line in reversed(block):
        m = ANY_TS_RE.search(line)
        if m:
            return m.group(1)
    return None


def gap(t_stop, t_restart):
    """Downtime in seconds, or "" if either time is missing."""
    if not (t_stop and t_restart):
        return ""
    return round((datetime.strptime(t_restart, FMT)
                  - datetime.strptime(t_stop, FMT)).total_seconds(), 0)


def event(path, system, block, restart_ts, line_no, source):
    """One output row: the restart at restart_ts, after the given block."""
    return {
        "file": rel_log(path),
        "lab": lab_of(path),
        "system": system,
        "block_start_line": line_no,
        "restart_timestamp": restart_ts,
        "sections_before": sum(1 for l in block if FINISHED_RE.search(l)),
        "category": classify(block),
        "gap_seconds": gap(last_timestamp(block), restart_ts),
        "source": source,
    }


def read_lines(path):
    with open(path, errors="replace") as fh:
        return fh.readlines()


def main():
    paths = log_list("unique_acqlogs.txt")
    print(f"Analyzing {len(paths)} deduplicated acqLog files...")

    events = []
    for i, path in enumerate(paths, 1):
        try:
            lines = read_lines(path)
        except OSError:
            continue
        starts = [j for j, l in enumerate(lines) if START_RE.match(l)]
        if len(starts) < 2:
            continue
        system = system_of_acqlog(path)
        for lo, hi in zip(starts, starts[1:]):
            events.append(event(path, system, lines[lo:hi],
                                START_RE.match(lines[hi]).group(1), hi + 1,
                                "same log"))
        if i % 1000 == 0:
            print(f"  ...{i}/{len(paths)}")

    for r in resumes.load():
        lines = read_lines(resumes.first_log(r))
        starts = [j for j, l in enumerate(lines) if START_RE.match(l)] or [0]
        events.append(event(resumes.first_log(r), r["system"], lines[starts[-1]:],
                            r["resumed_key"].split("|", 1)[1], "",
                            "new directory"))

    counted = [e for e in events if e["sections_before"] > MAX_SETUP_SECTIONS]
    setup = [e for e in events if e["sections_before"] <= MAX_SETUP_SECTIONS]

    def n_events(rows):
        return len({(e["system"], e["restart_timestamp"]) for e in rows})

    print(f"\nRestarts found: {n_events(events)} "
          f"({n_events([e for e in events if e['source'] == 'new directory'])} "
          f"into a new directory)")
    print(f"Setup restarts (<= {MAX_SETUP_SECTIONS} sections), not counted: {n_events(setup)}")
    print(f"Counted restarts: {n_events(counted)}")
    by_cat = Counter()
    for c, _s, _t in {(e["category"], e["system"], e["restart_timestamp"]) for e in counted}:
        by_cat[c] += 1
    for c, n in by_cat.most_common():
        print(f"  {n:4d}  {c}")

    for name, rows in (("restart_events_full.csv", counted),
                       ("setup_restarts.csv", setup)):
        with open(data(name), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
    print(f"\nWrote {len(counted)} rows -> restart_events_full.csv")
    print(f"Wrote {len(setup)} rows -> setup_restarts.csv")


if __name__ == "__main__":
    main()
