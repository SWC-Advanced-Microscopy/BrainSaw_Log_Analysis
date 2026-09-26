"""
Runs resumed into a new directory, and test runs.

A stopped run is usually resumed into the same directory and log. A user
can instead start it again under a new name (AB_rab0405 ->
AB_rab0405_NEWLASER), giving it its own directory, recipe and log. Such a
pair is one acquisition with one restart (find). Stage 01 keeps the
samples of one run of the pair, 03 counts the stop as a restart, and 05,
06 and 07 merge the two runs.

A test run is an acquisition of MAX_TEST_SECTIONS or fewer sections in
total (find_test_runs). It is not counted as an acquisition or a sample.
"""
import csv
import re
from collections import defaultdict
from datetime import datetime

from paths import data, rel_log, abs_log
from recipes import system_of_acqlog

MAX_GAP_H = 24
PARTIAL_RUN_SECTIONS = 80
DEPTH_TOL_MM = 0.002

FMT = "%Y/%m/%d %H:%M:%S"
START_RE = re.compile(r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) -- STARTING NEW ACQUISITION")
ANY_TS_RE = re.compile(r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})")
FIN_RE = re.compile(r"FINISHED section number (\d+)")
PC_DIR_RE = re.compile(r"in directory ([A-Za-z]:\\[^\\\s]+)")
SECTION_Z_RE = re.compile(r"STARTING section number (\d+) .*?at z=([-\d.]+)")

TABLE = "new_directory_resumes.csv"
FIELDS = ["system", "first_key", "resumed_key", "first_log", "resumed_log",
          "first_pc_dir", "resumed_pc_dir", "first_sections",
          "first_last_section", "resumed_first_section", "gap_hours", "why"]


def summarise(path):
    """Start, end, PC directory, section count and numbers, first depth and
    the depth of the next section it would have cut, for one acqLog."""
    start = end = pc_dir = None
    fins = []
    zs = []
    with open(path, errors="replace") as fh:
        for line in fh:
            m = SECTION_Z_RE.search(line)
            if m:
                zs.append((int(m.group(1)), float(m.group(2))))
            m = ANY_TS_RE.match(line)
            if m:
                end = m.group(1)
                if start is None and START_RE.match(line):
                    start = m.group(1)
            m = FIN_RE.search(line)
            if m:
                fins.append(int(m.group(1)))
            if pc_dir is None:
                m = PC_DIR_RE.search(line)
                if m:
                    pc_dir = m.group(1).split("\\")[-1]
    if start is None:
        return None
    # Next depth: the unfinished section's, else one step past the last.
    next_z = None
    if zs:
        n_last, z_last = zs[-1]
        if n_last not in fins:
            next_z = z_last
        elif len(zs) >= 2:
            next_z = z_last + (z_last - zs[-2][1])
    return dict(path=path, start=start, end=end, pc_dir=pc_dir,
                n=len(fins), first=fins[0] if fins else None,
                last=fins[-1] if fins else None,
                first_z=zs[0][1] if zs else None, next_z=next_z)


def related(a, b):
    """Same name, or one is the other plus a suffix not starting with a digit."""
    a, b = a.lower(), b.lower()
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return long_.startswith(short) and not long_[len(short)].isdigit()


def summarise_runs(acqlog_paths):
    """{"rig|first start": summary} for every run among the given acqLogs,
    keeping the most complete of co-imaged copies."""
    runs = {}
    for p in acqlog_paths:
        s = summarise(p)
        if s is None:
            continue
        key = f"{system_of_acqlog(p)}|{s['start']}"
        if key not in runs or s["n"] > runs[key]["n"]:
            runs[key] = s
    return runs


def find(runs):
    """Pairs (first run, resumed run) among runs from summarise_runs.
    Consecutive runs on one rig are a pair if either test holds.

    Depth: the second starts within DEPTH_TOL_MM of the depth ("at z=...")
    at which the first would have cut its next section. Only resumptions
    match this across the corpus, so there is no time limit
    (ML159_..._JK_2_B -> _JK_2_C was resumed 54 h later).

    Name: all of
      * the second starts within MAX_GAP_H hours of the first ending;
      * its acquisition-PC directory ("in directory F:\\NAME\\...") is the
        first's, or that name plus a suffix not starting with a digit
        (SP55 -> SP556 is not a match), either way round (related);
      * it continues the section numbering, or the first run cut fewer
        than PARTIAL_RUN_SECTIONS sections. Whole brains re-imaged under a
        related name all had 93 or more; resumed partial runs had 76 or
        fewer.
    The name test finds runs restarted a few sections higher up, and those
    whose first run cut one section, giving no step to predict depth from.
    """
    by_rig = defaultdict(list)
    for key, s in runs.items():
        by_rig[key.split("|")[0]].append((s["start"], key))

    pairs = []
    for system, lst in by_rig.items():
        lst.sort()
        for (_, ka), (_, kb) in zip(lst, lst[1:]):
            a, b = runs[ka], runs[kb]
            gap = (datetime.strptime(b["start"], FMT)
                   - datetime.strptime(a["end"], FMT)).total_seconds() / 3600
            named = bool(a["pc_dir"] and b["pc_dir"]
                         and related(a["pc_dir"], b["pc_dir"])
                         and 0 <= gap <= MAX_GAP_H)
            if a["next_z"] is not None and b["first_z"] is not None \
                    and abs(b["first_z"] - a["next_z"]) <= DEPTH_TOL_MM:
                why = "depth continues"
            elif named and a["last"] is not None and b["first"] is not None \
                    and 1 < b["first"] <= a["last"] + 1:
                why = "section numbering continues"
            elif named and a["n"] < PARTIAL_RUN_SECTIONS:
                why = f"first run partial ({a['n']} sections)"
            else:
                continue
            pairs.append(dict(system=system, first_key=ka, resumed_key=kb,
                              first_log=rel_log(a["path"]),
                              resumed_log=rel_log(b["path"]),
                              first_pc_dir=a["pc_dir"], resumed_pc_dir=b["pc_dir"],
                              first_sections=a["n"], first_last_section=a["last"],
                              resumed_first_section=b["first"],
                              gap_hours=round(gap, 2), why=why))
    return sorted(pairs, key=lambda r: r["first_key"])


def write(pairs):
    """Write pairs to new_directory_resumes.csv."""
    with open(data(TABLE), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(pairs)


def load():
    """The pairs from new_directory_resumes.csv."""
    with open(data(TABLE)) as f:
        return list(csv.DictReader(f))


def merge_map():
    """{resumed run's key: key of its acquisition}, following chains (a run
    resumed twice into new directories)."""
    parent = {r["resumed_key"]: r["first_key"] for r in load()}

    def root(k):
        while k in parent:
            k = parent[k]
        return k
    return {k: root(k) for k in parent}


def first_log(row):
    """The first run's acqLog, as an openable path."""
    return abs_log(row["first_log"])


MAX_TEST_SECTIONS = 5
TEST_TABLE = "test_runs.csv"
TEST_FIELDS = ["key", "log", "pc_dir", "sections"]


def find_test_runs(runs, pairs):
    """Every acquisition of MAX_TEST_SECTIONS or fewer sections in total,
    counting both runs of a resumed pair: a test or failed setup, e.g.
    three one-section runs imaging one plane of RR25_s04s06 at three laser
    powers."""
    parent = {r["resumed_key"]: r["first_key"] for r in pairs}

    def root(k):
        while k in parent:
            k = parent[k]
        return k
    total = defaultdict(int)
    for key, s in runs.items():
        total[root(key)] += s["n"]
    return [dict(key=k, log=rel_log(runs[k]["path"]), pc_dir=runs[k]["pc_dir"],
                 sections=n)
            for k, n in sorted(total.items()) if n <= MAX_TEST_SECTIONS]


def write_test_runs(rows):
    """Write test runs to test_runs.csv."""
    with open(data(TEST_TABLE), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TEST_FIELDS)
        w.writeheader()
        w.writerows(rows)


def test_run_keys():
    """Keys of the test runs and of any run merged into one."""
    with open(data(TEST_TABLE)) as f:
        tests = {r["key"] for r in csv.DictReader(f)}
    merge = merge_map()
    return tests | {k for k, root in merge.items() if root in tests}
