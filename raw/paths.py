#!/usr/bin/env python3
"""
Where things live. Every script takes its paths from here.

MERGED_LOGS/ is looked for in this order:
  1. $MERGED_LOGS, if set
  2. raw/MERGED_LOGS (where `tar -xjf MERGED_LOGS.tar.bz2` in raw/ puts it)
  3. MERGED_LOGS beside raw/
  4. MERGED_LOGS one level above that
The pipeline only reads it.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))     # .../raw
ROOT = os.path.dirname(HERE)                          # the manuscript folder

_CANDIDATES = [
    os.path.join(HERE, "MERGED_LOGS"),
    os.path.join(ROOT, "MERGED_LOGS"),
    os.path.join(os.path.dirname(ROOT), "MERGED_LOGS"),
]


def _find_merged():
    """MERGED_LOGS, by the order in the module docstring. If none exists,
    the first candidate, which write_derived_data.py reports as missing."""
    env = os.environ.get("MERGED_LOGS")
    if env:
        return env
    for path in _CANDIDATES:
        if os.path.isdir(path):
            return path
    return _CANDIDATES[0]


MERGED = _find_merged()

DATA_DIR = os.path.join(HERE, "derived_data")
README_IMG_DIR = os.path.join(HERE, "readme_images")
# Manuscript figures sit beside the scripts that draw them.
FIG_DIR = ROOT


def data(name):
    """Absolute path to a derived table, creating ``derived_data/`` if needed."""
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, name)


def figure(name):
    """Absolute path to a manuscript figure at the top level."""
    return os.path.join(FIG_DIR, name)


def readme_image(name):
    """Absolute path to a validation plot, creating readme_images/ if needed."""
    os.makedirs(README_IMG_DIR, exist_ok=True)
    return os.path.join(README_IMG_DIR, name)


def lab_of(path):
    """The lab: a path's top-level directory under MERGED_LOGS."""
    return os.path.relpath(path, MERGED).split(os.sep)[0]


# Tables store log paths relative, as "MERGED_LOGS/<lab>/...", so a rebuild
# from anywhere reproduces them byte for byte.
LOG_PREFIX = "MERGED_LOGS"


def rel_log(path):
    """Absolute path under MERGED -> "MERGED_LOGS/<lab>/..." (always '/')."""
    return "/".join([LOG_PREFIX] + os.path.relpath(path, MERGED).split(os.sep))


def abs_log(rel):
    """Inverse of rel_log: an openable path under MERGED."""
    head, _, tail = rel.partition("/")
    if head != LOG_PREFIX:
        raise ValueError(f"not a {LOG_PREFIX}-relative path: {rel!r}")
    return os.path.join(MERGED, *tail.split("/"))


def log_list(name):
    """A unique_*.txt list from 01, resolved to openable absolute paths."""
    with open(data(name)) as f:
        return [abs_log(l.strip()) for l in f if l.strip()]
