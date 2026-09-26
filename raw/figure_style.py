#!/usr/bin/env python3
"""
Palette, matplotlib settings and panel helpers for ../acquisition_stats.py.
No analysis. acquisition_timing.py has its own styling and does not use this.

EPS has no alpha channel, so everything is drawn opaque. ps.fonttype = 42
embeds TrueType, so text stays editable in Illustrator or Inkscape.
"""

import csv
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from paths import data, figure

FMT = "%Y/%m/%d %H:%M:%S"


# Mostly monochrome; hue only where a split must be told apart.
BLACK  = "#000000"
GREY50 = "#808080"   # 50% grey -- bars
GREY30 = "#b3b3b3"   # lighter grey -- secondary stack segment
GREY70 = "#4d4d4d"   # darker grey
YELLOW = "#eda100"   # laser-fault category
VIOLET = "#4a3aa7"   # unexplained-failure category
AQUA   = "#1baf7a"   # imaging-hours measures
ORANGE = "#eb6834"   # acquisition-count measures
INK    = "#0b0b0b"
MUTED  = "#52514e"

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
    "grid.color": "#e7e6e1",
    "grid.linewidth": 0.6,
    "axes.axisbelow": True,      # gridlines behind the data, not through it
    "font.size": 7,
    "axes.titlesize": 7,
    "axes.labelsize": 6.0,
    "legend.fontsize": 6.5,
    "xtick.labelsize": 5.2,
    "ytick.labelsize": 5.2,
    "lines.linewidth": 1.4,
    "ps.fonttype": 42,           # embed TrueType -> editable text in EPS
    "pdf.fonttype": 42,
})


def load(name):
    """A derived table as a list of dicts."""
    with open(data(name)) as f:
        return list(csv.DictReader(f))


def fnum(v, default=float("nan")):
    """CSV cell to float. Stage 06 leaves undefined rates blank; they become
    NaN, which matplotlib leaves as a gap rather than a zero."""
    if v is None or v == "":
        return default
    return float(v)


def panel_label(ax, letter, x=-0.19, y=1.16):
    """Bold panel letter, top left, outside the axes (x, y in axes units)."""
    ax.text(x, y, letter, transform=ax.transAxes,
            fontsize=9, fontweight="bold", va="top", ha="left", color=INK)


def bar_value_labels(ax, xs, values, fmt="{:.0f}", dy=0.02, fontsize=5.5):
    """Print each bar's value above it."""
    finite = [v for v in values if np.isfinite(v)]
    if not finite:
        return
    span = max(finite) if max(finite) > 0 else 1
    for x, v in zip(xs, values):
        if not np.isfinite(v):
            continue
        ax.text(x, v + span * dy, fmt.format(v), ha="center", va="bottom",
                fontsize=fontsize, color=MUTED)


def mark_partial_year(ax, idx, values, labels, asterisk=True):
    """Hatch the bar at idx, and optionally asterisk its label, to mark an
    incomplete final year. For count panels only; rates are unaffected."""
    if idx is None:
        return
    v = values[idx]
    if np.isfinite(v) and v > 0:
        ax.bar(idx, v, width=0.7, facecolor="none", edgecolor=INK,
               hatch="////", linewidth=0.5)
    if asterisk:
        labels = list(labels)
        labels[idx] = labels[idx] + "*"
        ax.set_xticklabels(labels, rotation=45, ha="right")


def year_ticks(ax, idx, labels):
    """Angled year tick labels, the same on every per-year panel."""
    ax.set_xticks(idx)
    ax.set_xticklabels(labels, rotation=45, ha="right")


def save(fig, stem, tight=True):
    """Write <stem>.eps and a 300 dpi <stem>.png. tight=False keeps the
    canvas at exactly figsize; bbox_inches="tight" would change it."""
    eps = figure(stem + ".eps")
    png = figure(stem + ".png")
    bbox = "tight" if tight else None
    fig.savefig(eps, format="eps", bbox_inches=bbox)
    fig.savefig(png, format="png", dpi=300, bbox_inches=bbox)
    plt.close(fig)
    print(f"Wrote {eps}")
    print(f"Wrote {png}")


def record_end(metrics):
    """(last acquisition start, its year): the year that is incomplete."""
    data_end = max(datetime.strptime(r["start"], FMT) for r in metrics)
    return data_end, data_end.year
