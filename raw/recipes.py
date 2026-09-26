#!/usr/bin/env python3
"""
Recipe fields and lookups shared by the stages, so they cannot disagree.

A run is identified by (rig, acqStartTime). acqStartTime is the same in
every co-imaged sample's recipe; the file-name timestamp is not (each file
is saved seconds apart). The rig, not the lab, is in the key, since one
run can be filed under two labs.
"""

import os
import re
from datetime import datetime

ACQ_START_RE = re.compile(r"acqStartTime:\s*'?([\d/]+ [\d:]+)'?")
LOG_START_RE = re.compile(
    r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) -- STARTING NEW ACQUISITION", re.M)
FMT = "%Y/%m/%d %H:%M:%S"
# SYSTEM is inline ("SYSTEM: {ID: brainsaw, ...}") or, in newer recipes, a
# block ("SYSTEM:\n  ID: neurovision").
SYSTEM_INLINE_RE = re.compile(r"SYSTEM:\s*\{[^}]*?\bID:\s*([^,}\n]+)")
SYSTEM_BLOCK_RE = re.compile(r"^SYSTEM:\s*$\s*^\s+ID:\s*(.+?)\s*$", re.M)


def read(path):
    """A recipe's text, or "" if unreadable."""
    try:
        with open(path, errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def acq_start(text):
    """``acqStartTime`` as "YYYY/MM/DD HH:MM:SS", or None."""
    m = ACQ_START_RE.search(text)
    return m.group(1) if m else None


def system(text):
    """The rig's SYSTEM id, lower case, or "" if the recipe has none."""
    m = SYSTEM_BLOCK_RE.search(text) or SYSTEM_INLINE_RE.search(text)
    s = m.group(1).strip().strip("'\"").lower() if m else ""
    # "baker" was brainsaw's name until late 2016.
    return "brainsaw" if s == "baker" else s


def recipes_in(directory):
    """Every recipe file in a directory, sorted."""
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    return sorted(os.path.join(directory, n) for n in names
                  if n.lower().startswith("recipe") and n.lower().endswith(".yml"))


def log_first_start(directory):
    """First ``STARTING NEW ACQUISITION`` time of the acqLog in a
    directory, as a datetime, or None if there is no log or no start."""
    try:
        names = os.listdir(directory)
    except OSError:
        return None
    for n in sorted(names):
        low = n.lower()
        if "acqlog" in low and low.endswith(".txt"):
            m = LOG_START_RE.search(read(os.path.join(directory, n)))
            if m:
                return datetime.strptime(m.group(1), FMT)
    return None


NAME_RE = re.compile(r"^recipe_(.+?)(?:_\d{6}_\d{6})?\.yml$", re.I)


def named_for_directory(path):
    """Is the recipe named after the directory it is in (the sample)?"""
    m = NAME_RE.match(os.path.basename(path))
    return bool(m) and m.group(1).lower() == os.path.basename(os.path.dirname(path)).lower()


def original_recipe(paths):
    """Of the recipes in one directory, the one for the run its acqLog
    records: acqStartTime closest to the log's first start (without a log,
    the earliest). Ties go to the recipe named after the directory, then
    the path. The others are resume recipes, written each time a stopped run
    is resumed (sectionStartNum > 1), or false starts abandoned before
    anything was logged."""
    starts = {p: acq_start(read(p)) for p in paths}
    log_t0 = log_first_start(os.path.dirname(paths[0]))

    def rank(p):
        t = starts[p]
        if t is None:
            return (float("inf"), "9999", True, p)
        off = abs((datetime.strptime(t, FMT) - log_t0).total_seconds()) \
            if log_t0 else 0.0
        return (off, t, not named_for_directory(p), p)
    return min(paths, key=rank)


def run_start(path):
    """Start of the run a recipe belongs to: its directory's acqLog first
    start, or the recipe's own acqStartTime if there is no log. A resume
    recipe and the original of the same run share it."""
    t0 = log_first_start(os.path.dirname(path))
    return t0.strftime(FMT) if t0 else acq_start(read(path))


def system_of_acqlog(path):
    """The rig that wrote an acqLog, from the recipe beside it."""
    recs = recipes_in(os.path.dirname(path))
    return system(read(original_recipe(recs))) if recs else ""
