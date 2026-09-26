#!/usr/bin/env python3
"""
acquisition_stats.py
====================

Draws **acquisition_stats.eps** / **acquisition_stats.png** -- throughput
(row 1) and restarts (rows 2-3) in a single near-square figure.

    A  Cumulative samples (line, left axis) over samples per year (bars,
       right axis)
    B  Distribution of samples per acquisition
    C  XY resolution of acquisitions
    D  Why the 211 restarts happened, as a pie
    E  Restarts per year, absolute, split laser vs. all other causes
    F  Downtime before resumption, excluding deliberate user aborts
    G  Acquisitions per unplanned restart, by year   (higher = better)
    H  Imaging hours per unplanned restart, by year  (higher = better)
    I  Restart rate per year as a percentage of that year's acquisitions,
       split user-originated vs. unplanned

Different panels take different slices of the 211 restarts, and each says
which: D and E use all 211; F uses the 158 that were not a deliberate user
abort; G and H use the 124 "unplanned" ones (laser + unexplained); I uses
all 211 split two ways. The unit throughout D-I is the restart: the 211
fall in 180 acquisitions, as some were restarted more than once.

LAYOUT
------
The canvas is 7.5 x 6.4 in. Inside it the nine panels sit on a plain
3 x 3 grid of equal cells, sized by ``_layout`` from the margin and gutter
constants below, so any space not claimed by a label goes to the panels.
Cells come out at 1.98 x 1.43 in, with each gap set from the measured ink
of whatever has to fit in it:

    gutter     0.52 in  y label plus tick labels of the panel to its
                        right (0.34 measured), and clearance
    row 1 -> 2 0.79 in  panel C's angled tick labels and axis title
                        (0.47), then row 2's panel letters and titles
                        (0.20)
    row 2 -> 3 0.72 in  panel F's angled tick labels (0.40), then the
                        same 0.20 above row 3

Two panels are not plain cells. Panel A is 0.33 in narrower so that the
tick labels of its right-hand twin axis clear panel B's y label -- the
constraint the row-1 layout is built around. Panel D is square,
because a pie is: 1.62 in on a side, so TALLER than the cell, and
TOP-aligned with the row so that its panel letter still sits level with
E's and F's and the surplus hangs downwards into the gap below, which is
empty anyway (D has no x axis to label). That makes the circle roughly the
height of the plotting boxes beside it, against two thirds of it before.

This script does NO analysis. Every value it draws is read straight from a
CSV in ``raw/derived_data/``, written by the pipeline in ``raw/``. If a
panel looks wrong, the fix belongs in ``raw/05_extract_acquisition_metrics.py``
or ``raw/06_build_figure_data.py``, not here.

Reads     raw/derived_data/fig_samples_dated.csv
          raw/derived_data/acquisition_metrics.csv
          raw/derived_data/fig_acq_resolution.csv
          raw/derived_data/fig_per_year.csv
          raw/derived_data/fig_failures.csv
Writes    acquisition_stats.eps, acquisition_stats.png

Run it on its own to restyle the figure -- it needs nothing but the CSVs:

    python3 acquisition_stats.py
"""

import os
import sys

# The pipeline, its shared figure styling and the derived tables all live
# in raw/. Put it on the import path so this script can be run from
# anywhere, then import from it exactly as the pipeline scripts do.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw"))

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from figure_style import (BLACK, GREY50, GREY30, GREY70, YELLOW, VIOLET,
                          AQUA, ORANGE, INK, MUTED, FMT, load, fnum, save,
                          panel_label, bar_value_labels, mark_partial_year,
                          year_ticks, record_end)
from datetime import datetime


# --- canvas ---------------------------------------------------------------
FIG_W, FIG_H = 7.5, 6.4

# --- the grid, in inches --------------------------------------------------
# Each margin and gap is the ink that has to fit in it plus a little
# clearance, measured off a rendered draft (see LAYOUT in the module
# docstring). The CELL SIZE is then whatever is left over, so any space not
# claimed by a label ends up inside a panel rather than around it.
M_L, M_R = 0.45, 0.07      # canvas edge -> outer axes edge, left / right
M_T, M_B = 0.24, 0.36      # top: a panel letter; bottom: angled year labels
GUT      = 0.52            # between columns
GAP12    = 0.79            # row 1 -> row 2
GAP23    = 0.72            # row 2 -> row 3

COL_W = (FIG_W - M_L - M_R - 2 * GUT) / 3.0            # 1.980
ROW_H = (FIG_H - M_T - M_B - GAP12 - GAP23) / 3.0      # 1.430

A_W   = COL_W - 0.33       # panel A: clearance for its right-hand twin axis

# Panel D's square box. Its wedge labels sit OUTSIDE the axes and overhang
# it by about 0.4 in on each side, so what has to fit the column is not the
# box but the box plus 0.8 in -- which is why the square is smaller than
# the cell is wide, and why it is nudged left rather than centred on the
# box: 1.62 + 0.8 fills the 2.5 in of clear width between the canvas edge
# and panel E's y label almost exactly, and PIE_DX centres the LABEL INK in
# it. Both numbers were read off a rendered draft; if the wedge labels are
# reworded, re-measure them.
PIE_S  = 1.62
PIE_DX = 0.08              # box left edge, relative to the column left


def _axes_inches(fig, left, bottom, width, height):
    """add_axes taking INCHES rather than figure fractions.

    The grid above is specified in inches because that is what the
    constraints are in: a tick label is 0.34 in wide whatever the panel it
    belongs to, so gaps have to be reasoned about in physical units and the
    fractions derived from them, not the other way round.
    """
    return fig.add_axes([left / FIG_W, bottom / FIG_H,
                         width / FIG_W, height / FIG_H])


def _panel_label(ax, letter, dx=0.30, dy=0.20):
    """Panel letter, dx and dy INCHES from the axes' top-left corner.

    ``figure_style.panel_label`` places the letter in AXES FRACTIONS, so
    panels of different sizes put their letters at different distances --
    visibly so between the narrowed panel A, the square panel D and the
    full-width cells. Converting here keeps all nine letters on the same
    two lines.
    """
    p = ax.get_position()
    panel_label(ax, letter,
                x=-dx / (p.width * FIG_W),
                y=1.0 + dy / (p.height * FIG_H))


def _layout(fig):
    """The nine axes, positioned in inches. Returns (row1, row2, row3)."""
    col_l = [M_L + i * (COL_W + GUT) for i in range(3)]
    r3_b = M_B
    r2_b = r3_b + ROW_H + GAP23
    r1_b = r2_b + ROW_H + GAP12

    row1 = [_axes_inches(fig, col_l[0], r1_b, A_W, ROW_H),
            _axes_inches(fig, col_l[1], r1_b, COL_W, ROW_H),
            _axes_inches(fig, col_l[2], r1_b, COL_W, ROW_H)]

    # D hangs below its row: the box is square and taller than the cell, so
    # top-aligning it with E and F pushes the surplus downwards into the
    # empty gap rather than up through the panel letters.
    row2 = [_axes_inches(fig, col_l[0] + PIE_DX,
                         r2_b + ROW_H - PIE_S, PIE_S, PIE_S),
            _axes_inches(fig, col_l[1], r2_b, COL_W, ROW_H),
            _axes_inches(fig, col_l[2], r2_b, COL_W, ROW_H)]

    row3 = [_axes_inches(fig, l, r3_b, COL_W, ROW_H) for l in col_l]
    return row1, row2, row3


def acquisition_stats(samples, metrics, resolution, per_year, failures,
                      data_end, partial_year):
    """Throughput (A-C) and restarts (D-I) on one canvas.

    Terminology note for D-I. Nothing there is called a "failure". Every
    event is an acquisition that STOPPED AND WAS RESTARTED, and a good
    number are exactly that and nothing more -- the user aborting
    deliberately, or a clean stop the user chose to resume.

    The five categories, disjoint, 211 restarts in total:

        manual abort         53   user stopped it on purpose
        planned stop         29   stopped cleanly, user restarted it
        natural completion    5   (grouped with planned stop in panel D)
        laser fault          39   serial-comms dropout
        true unknown         85   no explanation in the surrounding log

    Different panels take different slices of that set, and each says which:
      D  all 211, split five ways
      E  all 211, split laser vs. everything else
      F  the 158 that were not a deliberate user abort
      G/H  the 124 "unplanned" ones (laser + true unknown)
      I  all 211, split user-originated vs. unplanned
    """
    # ===== shared quantities =============================================
    # Samples on a time axis, chronologically ordered for the cumulative curve.
    s_dt = sorted(datetime.strptime(s["datetime"], FMT)
                  for s in samples if s["datetime"])

    # Imaging hours accumulate in acquisition-start order.
    m_sorted = sorted(metrics, key=lambda r: r["start"])
    cum_hours = np.cumsum([float(r["imaging_hours"]) for r in m_sorted])

    # NOTE ON UNITS: panel A is in SAMPLES (7,090); panels B and C are in
    # ACQUISITIONS (3,251). They are different units and are not meant to
    # agree -- an acquisition can carry several co-imaged samples, which is
    # exactly what panel B measures. The same count is the denominator for
    # the restart rates in panel I.
    n_acquisitions = len(set(s["acq_key"] for s in samples))

    years = [int(r["year"]) for r in per_year]
    yr_idx = np.arange(len(years))
    ylabels = [str(y) for y in years]

    # Whole-record category totals, used by several of D-I.
    n_abort   = sum(int(r["user_abort"]) for r in per_year)
    n_natural = sum(int(r["user_natural"]) for r in per_year)
    n_laser   = sum(int(r["fail_laser"]) for r in per_year)
    n_unknown = sum(int(r["fail_unknown"]) for r in per_year)
    n_restart = n_abort + n_natural + n_laser + n_unknown

    fig = plt.figure(figsize=(FIG_W, FIG_H))
    (ax_a, ax_b, ax_c), row2, row3 = _layout(fig)

    # ===== A: cumulative samples over per-year bars ======================
    # Two different quantities share this panel, so they get separate axes:
    # the running total on the left, the annual increment on the right. The
    # bars are drawn on the BACKGROUND axis so the cumulative line reads on
    # top of them.
    ax = ax_a
    _panel_label(ax, "A")
    yr_counts = {}
    for s in samples:
        if s["year"]:
            yr_counts[int(s["year"])] = yr_counts.get(int(s["year"]), 0) + 1
    d_years = sorted(yr_counts)
    d_vals = [yr_counts[y] for y in d_years]

    axb = ax.twinx()
    # Bars sit at mid-year so they line up with the right part of the curve
    # rather than being offset by six months.
    axb.bar([datetime(y, 7, 1) for y in d_years], d_vals,
            width=270, color=GREY50, edgecolor="none", zorder=1)
    axb.set_ylabel("Samples per year", color=MUTED, labelpad=2)
    axb.spines["right"].set_visible(True)
    axb.spines["top"].set_visible(False)

    ax.plot(s_dt, np.arange(1, len(s_dt) + 1), color=BLACK, zorder=3)
    ax.set_ylabel("Cum. samples")
    # BOTH y axes are pinned to zero at the axes floor and given four
    # intervals up to a rounded top. Two things follow. The left axis loses
    # matplotlib's 5% margin, which had put its zero line ABOVE the twin
    # axis's, making the bars behind the curve look as though they started
    # below the baseline. And the left and right tick marks then land on
    # the same rows instead of interleaving. Labels are in thousands, as in
    # B and C -- four-digit labels here are the widest text in the figure's
    # left margin and would otherwise set the margin on their own.
    cum_top = 2000 * int(np.ceil(len(s_dt) / 2000))
    yr_top = 400 * int(np.ceil(max(d_vals) * 1.05 / 400))
    cum_ticks = np.linspace(0, cum_top, 5)
    ax.set_ylim(0, cum_top)
    ax.set_yticks(cum_ticks)
    ax.set_yticklabels(["0"] + [f"{t / 1000:g}k" for t in cum_ticks[1:]])
    axb.set_ylim(0, yr_top)
    axb.set_yticks(np.linspace(0, yr_top, 5))
    ax.set_zorder(axb.get_zorder() + 1)   # line axis above bar axis ...
    ax.patch.set_visible(False)           # ... but let the bars show through
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.tick_params(axis="x", rotation=45)
    # Gridlines are switched off here: with bars behind a line on twin axes
    # they add a third layer of horizontal rules that cannot align to both
    # y-scales at once, so they read as clutter.
    ax.grid(False)
    axb.grid(False)
    ax.annotate(f"{len(s_dt):,} samples", xy=(0.03, 0.92),
                xycoords="axes fraction", fontsize=5, color=MUTED)

    # ===== B: samples per acquisition ====================================
    ax = ax_b
    _panel_label(ax, "B")
    per_acq = {}
    for s in samples:
        per_acq[s["acq_key"]] = per_acq.get(s["acq_key"], 0) + 1
    hist = {}
    for v in per_acq.values():
        hist[v] = hist.get(v, 0) + 1
    ks = sorted(hist)
    vals = [float(hist[k]) for k in ks]
    ax.bar([str(k) for k in ks], vals, color=GREY50, width=0.7)
    ax.set_xlabel("Samples per acquisition")
    ax.set_ylabel("Acquisitions")
    # Linear y: the counts are labelled directly, so the long thin tail does
    # not need a log axis to stay readable.
    bar_value_labels(ax, np.arange(len(ks)), vals, fontsize=4.4)
    ax.set_ylim(0, max(vals) * 1.18)
    # Tick POSITIONS are left as matplotlib chose them; only the labels are
    # thinned, to declutter an axis whose bars already carry exact counts.
    ax.set_yticks([0, 500, 1000, 1500, 2000])
    ax.set_yticklabels(["0", "", "1k", "", "2k"])
    # Every acquisition contributes to exactly one bar, so the bars sum to
    # the full 3,251 (verified: 1575+660+338+402+137+92+42+3+2). Annotation
    # sits top-RIGHT here because the tallest bar occupies the top left.
    ax.annotate(f"{n_acquisitions:,} acquisitions", xy=(0.97, 0.92),
                xycoords="axes fraction", ha="right",
                fontsize=5, color=MUTED)

    # ===== C: XY resolution ==============================================
    # Band membership is decided in 06_build_figure_data.py (see
    # RESOLUTION_BANDS there for how the edges were chosen and checked);
    # this panel only counts and draws.
    ax = ax_c
    _panel_label(ax, "C")
    band_order = ["<0.7", "0.7-1.7", "1.7-2.7", "2.7-3.9",
                  "3.9-4.8", "4.8-7.5", "7.5-10"]
    bcount = {b: 0 for b in band_order}
    for r in resolution:
        if r["band"]:
            bcount[r["band"]] += 1
    cvals = [float(bcount[b]) for b in band_order]
    ax.bar(np.arange(len(band_order)), cvals, color=GREY50, width=0.7)
    ax.set_xticks(np.arange(len(band_order)))
    ax.set_xticklabels(band_order, rotation=45, ha="right")
    ax.set_xlabel("Pixel size (µm/pixel)")
    ax.set_ylabel("Acquisitions")
    bar_value_labels(ax, np.arange(len(band_order)), cvals, fontsize=4.4)
    ax.set_ylim(0, max(cvals) * 1.18)
    ax.set_yticks([0, 500, 1000, 1500, 2000])
    ax.set_yticklabels(["0", "", "1k", "", "2k"])
    # Bands are contiguous and cover the whole measured range, so these also
    # sum to 3,251 (4+336+1750+7+1077+13+64) with nothing unbinned.
    ax.annotate(f"{n_acquisitions:,} acquisitions", xy=(0.97, 0.92),
                xycoords="axes fraction", ha="right",
                fontsize=5, color=MUTED)

    # ===== D: why acquisitions restarted, as a pie =======================
    # The whole event set and its composition, which is why it leads the
    # restart rows.
    #
    # This pie shows the 211 RESTARTS, not all 3,251 acquisitions. A pie of
    # all 3,251 is unreadable: "never restarted" is 94.5% of the circle,
    # leaving the four restart categories about 20 degrees between them --
    # slivers whose labels overlap and whose relative sizes cannot be
    # judged. The completion rate is stated in the caption instead, where
    # it is legible.
    ax = row2[0]
    _panel_label(ax, "D", dx=0.30 + PIE_DX)
    wedges_spec = [
        ("Unexplained",  n_unknown, BLACK),
        ("Laser",        n_laser,   GREY50),
        ("User aborted", n_abort,   "#d0d0d0"),
        ("Stopped cleanly,\nuser restarted", n_natural, "#eaeaea"),
    ]
    ax.pie([w[1] for w in wedges_spec], colors=[w[2] for w in wedges_spec],
           startangle=90, counterclock=False,
           wedgeprops={"edgecolor": "white", "linewidth": 0.8},
           labels=[f"{w[0]}\n{w[1]} ({w[1]/n_restart:.0%})" for w in wedges_spec],
           labeldistance=1.18,
           textprops={"fontsize": 5.0, "color": INK})
    # Same corner and style as panel F's count, so the two read as a pair.
    ax.annotate(f"n = {n_restart}", xy=(0.99, 0.97), xycoords="axes fraction",
                ha="right", va="top", fontsize=6, color=INK)
    ax.set_aspect("equal")
    ax.set_axis_off()

    # ===== E: all restarts per year, laser vs. everything else ===========
    # The black segment is every restart that was NOT a laser fault, so it
    # mixes user-originated stops with unexplained ones -- hence "Other"
    # rather than "Unexplained". Laser is split out because it is the one
    # category with a known cause and a known fix, and the point of the
    # panel is that it disappears.
    ax = row2[1]
    _panel_label(ax, "E")
    other = np.array([int(r["fail_unknown"]) + int(r["user_abort"])
                      + int(r["user_natural"]) for r in per_year], dtype=float)
    las = np.array([int(r["fail_laser"]) for r in per_year], dtype=float)
    ax.bar(yr_idx, other, color=BLACK, width=0.7, label="Other")
    ax.bar(yr_idx, las, bottom=other, color=GREY50, width=0.7, label="Laser")
    year_ticks(ax, yr_idx, ylabels)
    ax.set_ylabel("Acquisitions affected")
    ax.set_title("Restarts per year")
    ax.legend(frameon=False, loc="upper left")
    bar_value_labels(ax, yr_idx, other + las)
    ax.set_ylim(0, (other + las).max() * 1.32)
    # The record stops mid-2026, so that bar is hatched to show it covers a
    # partial year. No asterisk: the hatch carries the meaning on its own.
    mark_partial_year(ax, years.index(partial_year) if partial_year in years else None,
                      other + las, ylabels, asterisk=False)

    # ===== F: downtime before resumption =================================
    # Every restart EXCEPT a deliberate user abort: unexplained stops, laser
    # faults, and clean stops the user chose to resume. A deliberate abort
    # is excluded because its "downtime" measures how long the user chose to
    # wait, which is not the same quantity as how long a stopped rig sat
    # before anyone noticed.
    ax = row2[2]
    _panel_label(ax, "F")
    F_CATEGORIES = {"true unknown", "laser fault",
                    "planned stop", "natural completion"}
    # One downtime per restart EVENT (co-imaged logs record the same one).
    gap_by_event = {}
    for e in failures:
        if e["category"] not in F_CATEGORIES or e["gap_seconds"] == "":
            continue
        gap_by_event[e["event_key"]] = float(e["gap_seconds"])
    order = ["<30 min", "30-60 min", "1-6 h", "6-24 h", ">24 h"]

    def bucket(g):
        if g < 1800: return order[0]
        if g < 3600: return order[1]
        if g < 3600 * 6: return order[2]
        if g < 3600 * 24: return order[3]
        return order[4]

    bcounts = {k: 0 for k in order}
    for g in gap_by_event.values():
        bcounts[bucket(g)] += 1
    vals = [float(bcounts[k]) for k in order]
    ax.bar(order, vals, color=BLACK, width=0.7)
    ax.set_ylabel("Acquisitions")
    ax.set_title("Downtime before resumption")
    ax.tick_params(axis="x", rotation=45)
    for lbl in ax.get_xticklabels():
        lbl.set_ha("right")
    bar_value_labels(ax, np.arange(len(order)), vals)
    ax.set_ylim(0, max(vals) * 1.22)
    ax.annotate(f"n = {len(gap_by_event)}", xy=(0.97, 0.94),
                xycoords="axes fraction", ha="right", va="top",
                fontsize=6, color=INK)

    # ===== G/H: mean exposure between unplanned restarts =================
    # Absolute counts confound reliability with how much the rig was used.
    # These express the unplanned events (laser + unexplained) as the mean
    # amount of work done BETWEEN them, so higher always means more
    # reliable. G normalises by acquisitions, H by imaging hours.
    for ax, letter, col, title, ylab in [
        (row3[0], "G", "acqs_per_failure",
         "Acquisitions per unplanned restart", "Acquisitions"),
        (row3[1], "H", "hours_per_failure",
         "Imaging hours per unplanned restart", "Imaging hours"),
    ]:
        _panel_label(ax, letter)
        vals = np.array([fnum(r[col]) for r in per_year], dtype=float)
        ax.bar(yr_idx, vals, color=BLACK, width=0.7)
        year_ticks(ax, yr_idx, ylabels)
        ax.set_ylabel(ylab)
        ax.set_title(title)
        bar_value_labels(ax, yr_idx, vals)
        finite = vals[np.isfinite(vals)]
        if len(finite):
            ax.set_ylim(0, finite.max() * 1.30)

    # ===== I: restart rate per year, as a percentage =====================
    # The same events as E, normalised by that year's acquisition count.
    ax = row3[2]
    _panel_label(ax, "I")
    pct_user = np.array([fnum(r["pct_user"]) for r in per_year], dtype=float)
    pct_fail = np.array([fnum(r["pct_failed"]) for r in per_year], dtype=float)
    ax.bar(yr_idx, pct_fail, color=BLACK, width=0.7, label="Unplanned")
    ax.bar(yr_idx, pct_user, bottom=pct_fail, color=GREY50, width=0.7,
           label="User-originated")
    year_ticks(ax, yr_idx, ylabels)
    ax.set_ylabel("% of acquisitions", labelpad=2)
    ax.set_title("Restart rate per year")
    ax.legend(frameon=False, loc="upper right")
    ax.set_ylim(0, np.nanmax(pct_user + pct_fail) * 1.30)

    # NOTE: the earliest years rest on very few acquisitions (11 in 2016,
    # 40 in 2017, 75 in 2018), so one or two events move their percentage by
    # several points. That caveat is not marked on the panel itself; it is
    # carried in the figure caption.

    # tight=False: the layout is in explicit inches to hit a target print
    # size, and bbox_inches="tight" would crop to the ink and silently
    # change it.
    save(fig, "acquisition_stats", tight=False)


def main():
    samples = load("fig_samples_dated.csv")
    metrics = load("acquisition_metrics.csv")
    resolution = load("fig_acq_resolution.csv")
    per_year = load("fig_per_year.csv")
    failures = load("fig_failures.csv")

    data_end, partial_year = record_end(metrics)
    print(f"Record ends {data_end:%Y-%m-%d}; marking {partial_year} as a partial year")

    print(f"Total acquisitions (denominator): "
          f"{len(set(s['acq_key'] for s in samples)):,}")

    acquisition_stats(samples, metrics, resolution, per_year, failures,
                      data_end, partial_year)


if __name__ == "__main__":
    main()
