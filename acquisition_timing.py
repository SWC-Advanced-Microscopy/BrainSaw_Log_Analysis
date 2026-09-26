#!/usr/bin/env python3
"""
acquisition_timing.py
=====================

Draws **acquisition_timing.eps** / **acquisition_timing.png** -- how long an
acquisition takes.

    A, B  Time to 12.5 mm against brains on the block, for each of the two
          voxel categories
    C     The same, divided by brains on the block
    D-F   Time against frame averaging, at 1, 2 and 4 brains

Every panel plots the individual acquisitions, not only a summary. Several
rest on fewer than ten runs, which a reader can only judge if the points
are visible -- and one 51 h acquisition was hidden behind a legend box in
an early draft, which is exactly the failure this convention prevents.
Legends and count labels are therefore placed only where the data is not.

This script does NO analysis: the cohort it draws is selected by
``raw/08_build_timing_figure_data.py``, so a panel cannot quietly disagree
with the cohort it claims to show. It does not import ``figure_style.py``
either -- the supplementary figure has its own layout conventions, and
tying it to the module used by ``acquisition_stats.py`` would mean every
change made for that figure had to be checked against this one too.

Reads     raw/derived_data/fig_timing_cohort.csv
          raw/derived_data/fig_timing_averaging.csv
Writes    acquisition_timing.eps, acquisition_timing.png

    python3 acquisition_timing.py
"""

import os
import sys

# The pipeline, its shared figure styling and the derived tables all live
# in raw/. Put it on the import path so this script can be run from
# anywhere, then import from it exactly as the pipeline scripts do.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw"))

import csv

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from paths import data, figure

TARGET_DEPTH = 12.5
BRAIN_COUNTS = [1, 2, 4, 6]      # panels A/B/C
AVG_BRAIN_COUNTS = [1, 2, 4]     # panels D/E/F
MAX_AVG_SHOWN = 4                # averaging levels above this are too sparse
MIN_PER_LEVEL = 5                # acquisitions needed before a summary point
MIN_FOR_BOX = 3                  # below this, points only -- no box
C_YMAX = 36                      # panel C's y-limit, hours per brain

# --- palette (matches figure_style.py, so the two figures pair) ----------
BLACK = "#000000"
GREY50 = "#808080"
INK = "#0b0b0b"
MUTED = "#52514e"
REFLINE = "#bfbfbf"              # lighter than any data series

CAT_COLOUR = {"2x2x5": BLACK, "4x4x20": GREY50}
# An opaque white box, not a transparent one: the 24 h reference line runs
# behind C's legend, and EPS cannot fade it out with alpha. Only C gets a
# legend -- see `count_labels` for why D-F do not.
LEGEND_KW = dict(frameon=True, facecolor="white", edgecolor="none",
                 borderpad=0.2, labelspacing=0.25, framealpha=1.0)
CAT_ORDER = ["4x4x20", "2x2x5"]

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
    "axes.grid": False,
    "axes.axisbelow": True,
    "font.size": 7,
    "axes.titlesize": 7,
    "axes.labelsize": 6.0,
    "legend.fontsize": 6.0,
    "xtick.labelsize": 5.2,
    "ytick.labelsize": 5.2,
    "lines.linewidth": 1.4,
    "ps.fonttype": 42,
    "pdf.fonttype": 42,
})


# --- helpers --------------------------------------------------------------
def load(name):
    with open(data(name)) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["n_brains"] = int(r["n_brains"])
        r["average_n_frames"] = float(r["average_n_frames"])
        r["h_at_target"] = float(r["h_at_target"])
    return rows


def panel_label(ax, letter, x, y=1.125):
    ax.text(x, y, letter, transform=ax.transAxes,
            fontsize=9, fontweight="bold", va="top", ha="left", color=INK)


def ylabel_x(fig, ax):
    """Axes-fraction x of the left edge of `ax`'s y-axis label.

    Used to line the panel letters up with the y-label rather than hanging
    them out at a fixed offset, which left them adrift in the margin. The
    position is only known after a draw, because it depends on how wide the
    tick labels turn out to be, so this must be called on a laid-out figure.
    """
    fig.canvas.draw()
    bb = ax.yaxis.label.get_window_extent()
    return ax.transAxes.inverted().transform((bb.x0, 0))[0]


def day_line(ax, label=False):
    """One working day. Above it, a run can no longer be started and
    collected on consecutive mornings, which is the practical constraint
    that decides how much can go on the block."""
    ax.axhline(24, color=REFLINE, ls="--", lw=0.8, zorder=0)
    if label:
        ax.annotate("24 h", xy=(0.03, 24.6),
                    xycoords=("axes fraction", "data"),
                    va="bottom", fontsize=5.2, color=MUTED)


# Corners tried for the count labels, in order of preference:
# (x, y of the first line, ha, va, direction of the next line).
COUNT_CORNERS = [(0.97, 0.97, "right", "top", -1),
                 (0.03, 0.97, "left", "top", -1),
                 (0.97, 0.03, "right", "bottom", +1),
                 (0.03, 0.03, "left", "bottom", +1)]


def count_labels(ax, counts):
    """Per-category sample sizes, printed inside the axes in a corner that
    no acquisition falls under.

    D-F carry no legend box. An opaque one sits where the tallest
    acquisitions are -- an early draft hid a 51 h point behind the legend in
    F, which is the opposite of the point of drawing every acquisition. Bare
    text in a fixed corner is not safe either: which corner is empty depends
    on the cohort (with runs from 2020 a 4-frame, 4-brain point lands in the
    top right of F). So each corner is tried in turn, and the first whose
    text covers no plotted point is kept. Call after the axis limits are set.
    """
    fig = ax.figure
    pts = [np.column_stack(l.get_data()) for l in ax.lines
           if l.get_linestyle() == "None"]
    pts = ax.transData.transform(np.vstack(pts)) if pts else np.empty((0, 2))
    for i, (x, y, ha, va, step) in enumerate(COUNT_CORNERS):
        texts = [ax.annotate(f"{cat}  n={n}", xy=(x, y + step * 0.085 * j),
                             xycoords="axes fraction", fontsize=5.2,
                             color=CAT_COLOUR[cat], va=va, ha=ha)
                 for j, (cat, n) in enumerate(counts)]
        fig.canvas.draw()
        boxes = [t.get_window_extent().expanded(1.05, 1.2) for t in texts]
        clear = not any(b.contains(px, py) for b in boxes for px, py in pts)
        if clear or i == len(COUNT_CORNERS) - 1:
            return
        for t in texts:
            t.remove()


def jitter(rng, n, w=0.13):
    return rng.uniform(-w, w, n)


def points(ax, xs, ys, colour, rng, w=0.13, ms=3.2):
    """Individual acquisitions. Drawn in every panel: a box or an error bar
    alone would hide how few acquisitions some of these rest on."""
    ax.plot(np.asarray(xs, float) + jitter(rng, len(xs), w), ys, ".",
            color=colour, ms=ms, mew=0, zorder=2)


def quartiles(vals):
    a = np.asarray(vals, float)
    return np.percentile(a, 25), np.median(a), np.percentile(a, 75)


def save(fig, stem, tight=True):
    eps = figure(stem + ".eps")
    png = figure(stem + ".png")
    bbox = "tight" if tight else None
    fig.savefig(eps, format="eps", bbox_inches=bbox)
    fig.savefig(png, format="png", dpi=300, bbox_inches=bbox)
    plt.close(fig)
    print(f"Wrote {eps}")
    print(f"Wrote {png}")


# --- panels ---------------------------------------------------------------
def panel_by_brains(ax, rows, cat, rng, ymax):
    """A/B: time to 12.5 mm against brains on the block, one category."""
    colour = CAT_COLOUR[cat]
    labels = []
    for i, nb in enumerate(BRAIN_COUNTS, 1):
        vals = [r["h_at_target"] for r in rows
                if r["res"] == cat and r["n_brains"] == nb]
        labels.append(f"{nb}\nn={len(vals)}")
        if not vals:
            continue
        points(ax, [i] * len(vals), vals, colour, rng)
        # A box over three points would imply a precision that is not there.
        if len(vals) >= MIN_FOR_BOX:
            q25, med, q75 = quartiles(vals)
            ax.add_patch(plt.Rectangle((i - 0.28, q25), 0.56, q75 - q25,
                                       facecolor="none", edgecolor=colour,
                                       lw=0.8, zorder=3))
            ax.plot([i - 0.28, i + 0.28], [med, med],
                    color=colour, lw=1.4, zorder=4)
    day_line(ax, label=(cat == CAT_ORDER[0]))
    ax.set_xticks(range(1, len(BRAIN_COUNTS) + 1))
    ax.set_xticklabels(labels)
    ax.set_xlim(0.4, len(BRAIN_COUNTS) + 0.6)
    ax.set_ylim(0, ymax)
    ax.set_xlabel("Num brains in acquisition")
    ax.set_title(f"{cat} µm", fontsize=7)


def panel_per_brain(ax, rows, rng, ymax):
    """C: the same quantity divided by brains on the block.

    Flat would mean every extra brain costs its own imaging time and nothing
    else. The fall is the fixed per-section overhead -- cutting, stage moves,
    ROI finding -- being shared across more tissue.

    Drawn on a fixed 0-36 h scale (C_YMAX): per-brain times top out near
    26 h, so the shared 0-55 h scale of the other panels squashed the data
    into the bottom half, while an automatic limit (about 23 h) made the
    1-brain column look taller than the same numbers in A and B.
    """
    for cat in CAT_ORDER:
        colour = CAT_COLOUR[cat]
        xs, ys = [], []
        for nb in BRAIN_COUNTS:
            vals = [r["h_at_target"] / nb for r in rows
                    if r["res"] == cat and r["n_brains"] == nb]
            if not vals:
                continue
            # Offset the two categories slightly so their points do not
            # land on top of each other at the same brain count.
            off = -0.09 if cat == CAT_ORDER[0] else 0.09
            points(ax, [nb + off] * len(vals), vals, colour, rng, w=0.07)
            if len(vals) >= MIN_FOR_BOX:
                xs.append(nb + off)
                ys.append(np.median(vals))
        ax.plot(xs, ys, marker="o", ms=4, lw=1.4, color=colour,
                zorder=5, label=cat)
    day_line(ax)
    ax.set_xticks(BRAIN_COUNTS)
    ax.set_xlim(0.4, max(BRAIN_COUNTS) + 0.6)
    ax.set_ylim(0, ymax)
    ax.set_xlabel("Num brains in acquisition")
    ax.set_ylabel(f"Time per brain to {TARGET_DEPTH} mm (h)")
    ax.set_title("Acquisition time per brain", fontsize=7)
    ax.legend(loc="upper right", handlelength=1.4, **LEGEND_KW)


def panel_averaging(ax, rows, nb, rng, ymax, label_day):
    """D/E/F: time to 12.5 mm against frame averaging, at one brain count.

    Categories are identified by the legend in C, not repeated here: a legend
    box in these panels would cover data (see `count_labels`).
    """
    counts = []
    for cat in CAT_ORDER:
        colour = CAT_COLOUR[cat]
        sub = [r for r in rows if r["res"] == cat and r["n_brains"] == nb]
        if not sub:
            continue
        shown = [r for r in sub if r["average_n_frames"] <= MAX_AVG_SHOWN]
        points(ax, [r["average_n_frames"] for r in shown],
               [r["h_at_target"] for r in shown], colour, rng, w=0.1)
        xs, ys = [], []
        for lvl in sorted({r["average_n_frames"] for r in shown}):
            vals = [r["h_at_target"] for r in shown
                    if r["average_n_frames"] == lvl]
            if len(vals) >= MIN_PER_LEVEL:
                xs.append(lvl)
                ys.append(np.median(vals))
        if xs:
            ax.plot(xs, ys, marker="o", ms=4, lw=1.4, color=colour, zorder=5)
        counts.append((cat, len(sub)))
    day_line(ax, label=label_day)
    ax.set_xticks([1, 2, 3, 4])
    ax.set_xlim(0.5, MAX_AVG_SHOWN + 0.5)
    ax.set_ylim(0, ymax)
    count_labels(ax, counts)
    ax.set_xlabel("Frames averaged")
    ax.set_title(f"{nb} brain" + ("s" if nb > 1 else ""), fontsize=7)


# =========================================================================
def main():
    cohort = load("fig_timing_cohort.csv")
    averaging = load("fig_timing_averaging.csv")
    rng = np.random.default_rng(0)

    # ONE y-limit for A, B and D-F, so any two can be compared by eye rather
    # than by reading their axes. The limit is the slowest acquisition drawn
    # anywhere, rounded up to 5 h, so nothing is clipped. C plots a
    # different quantity (hours per brain) on its own fixed scale, C_YMAX.
    def top(rows, brain_counts):
        vals = [r["h_at_target"] for r in rows if r["n_brains"] in brain_counts]
        return 5 * np.ceil(max(vals) / 5)

    ymax = max(top(cohort, BRAIN_COUNTS),
               top([r for r in averaging
                    if r["average_n_frames"] <= MAX_AVG_SHOWN],
                   AVG_BRAIN_COUNTS))

    # Explicit axes positions rather than subplots: bbox_inches="tight"
    # crops to the ink and would silently change the print width (see
    # figure_style.save). Laid out for a 7.0 in column.
    fig = plt.figure(figsize=(7.0, 4.3))
    W, H = 0.245, 0.325
    TOP, BOT = 0.605, 0.095
    lefts = [0.075, 0.400, 0.725]

    ax_a = fig.add_axes([lefts[0], TOP, W, H])
    ax_b = fig.add_axes([lefts[1], TOP, W, H])
    ax_c = fig.add_axes([lefts[2], TOP, W, H])
    ax_d = fig.add_axes([lefts[0], BOT, W, H])
    ax_e = fig.add_axes([lefts[1], BOT, W, H])
    ax_f = fig.add_axes([lefts[2], BOT, W, H])

    panel_by_brains(ax_a, cohort, "4x4x20", rng, ymax)
    panel_by_brains(ax_b, cohort, "2x2x5", rng, ymax)
    panel_per_brain(ax_c, cohort, rng, C_YMAX)
    for ax, nb in zip((ax_d, ax_e, ax_f), AVG_BRAIN_COUNTS):
        panel_averaging(ax, averaging, nb, rng, ymax, label_day=(nb == 1))

    ylab = f"Imaging time to {TARGET_DEPTH} mm (h)"
    ax_a.set_ylabel(ylab)
    ax_d.set_ylabel(ylab)
    # B shares A's scale and D/E/F share it too; drop the repeated tick
    # labels so the numbers are not read as different axes.
    for ax in (ax_b, ax_e, ax_f):
        ax.set_yticklabels([])

    # Line every panel letter up with the y-label of the panel that has one,
    # so the letters sit against the left edge of the figure's text column
    # rather than floating in the margin. B/E/F carry no y-label (they share
    # A's and D's scale), so they borrow the offset from their row leader.
    x_top = ylabel_x(fig, ax_a)
    x_bot = ylabel_x(fig, ax_d)
    for ax, letter, x in ((ax_a, "A", x_top), (ax_b, "B", x_top),
                          (ax_c, "C", ylabel_x(fig, ax_c)),
                          (ax_d, "D", x_bot), (ax_e, "E", x_bot),
                          (ax_f, "F", x_bot)):
        panel_label(ax, letter, x)

    save(fig, "acquisition_timing", tight=False)


if __name__ == "__main__":
    main()
