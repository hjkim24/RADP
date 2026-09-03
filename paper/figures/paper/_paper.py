"""Paper-scale (IEEE IoT-J, IEEEtran two-column) matplotlib styling — black and white.

Rules (2026-08-30):
  * grayscale only; series are told apart by MARKER SHAPE + line style, never hue;
  * ONE exception: the thing the figure exists to emphasise (our method, or the
    measured anchor) may be red (EMPH). Nothing else is coloured;
  * built at the width it will be printed (3.5 in column / 7.16 in text width),
    Times to match IEEEtran, 8 pt text, so it is placed at 100 % (no scaling);
  * `save()` writes PDF (paper) + PNG (preview) and then runs a layout check that
    reports overlapping text and text that falls outside the figure, so a label
    collision is a printed warning rather than something a reviewer finds.

Rebuild everything:  for f in paper/make_*.py; do .venv/bin/python "$f"; done
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

FIG_DIR = Path(__file__).parent
sys.path.insert(0, str(FIG_DIR.parent))
from _names import NAME  # noqa: E402,F401

RESULTS = FIG_DIR.parent.parent.parent / "experiments" / "results"

# --- geometry (inches). IEEEtran: \columnwidth = 3.5 in, \textwidth = 7.16 in.
COL = (3.45, 2.35)
COL_TALL = (3.45, 2.75)
WIDE = (7.1, 2.4)

# --- ink ------------------------------------------------------------------
INK = "#000000"
GRAY = "#6E6E6E"
LIGHT = "#B4B4B4"
GRID = "#DCDCDC"
EMPH = "#CC0000"     # the single allowed colour: what the figure is about

# Same recovery family -> same marker + line style in every figure.
# Keys are the internal recovery_mode identifiers (do not rename).
STYLE = {
    "full_replay":          dict(marker="o", ls="--", color=INK,  mfc="white"),
    "surgical":             dict(marker="s", ls="-.", color=INK,  mfc="white"),
    "replicate":            dict(marker="D", ls=":",  color=GRAY, mfc="white"),
    "reactive_replacement": dict(marker="v", ls="",   color=GRAY, mfc="white"),
    "parity":               dict(marker="^", ls="-",  color=EMPH, mfc=EMPH),
    "raid6":                dict(marker="^", ls="--", color=EMPH, mfc="white"),
}

mpl.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Times", "STIXGeneral", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "font.size": 8,
    "axes.labelsize": 8,
    "axes.titlesize": 8,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 6.5,
    "legend.frameon": False,
    "legend.handlelength": 2.2,
    "legend.borderaxespad": 0.3,
    "lines.linewidth": 0.9,
    "lines.markersize": 4,
    "lines.markeredgewidth": 0.8,
    "axes.linewidth": 0.6,
    "axes.edgecolor": INK,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "xtick.direction": "out",
    "ytick.direction": "out",
    "grid.color": GRID,
    "grid.linewidth": 0.4,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.01,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})


def clean(ax: plt.Axes, grid_axis: str = "y") -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if grid_axis:
        ax.grid(True, axis=grid_axis, alpha=0.8)
    ax.set_axisbelow(True)


def label(ax: plt.Axes, text: str, xy, dx=0, dy=0, ha="left", va="center",
          color=INK, size=7, bold=False, **kw):
    """Direct label anchored to a data point; offset in points so it survives
    axis-limit changes."""
    return ax.annotate(text, xy=xy, xytext=(dx, dy), textcoords="offset points",
                       ha=ha, va=va, color=color, fontsize=size,
                       fontweight="bold" if bold else "normal",
                       annotation_clip=False, **kw)


def _texts(fig: plt.Figure):
    out = []
    for t in fig.findobj(mpl.text.Text):
        if not t.get_visible() or not t.get_text().strip():
            continue
        try:
            bb = t.get_window_extent(fig.canvas.get_renderer())
        except Exception:
            continue
        if bb.width <= 0 or bb.height <= 0:
            continue
        out.append((t, bb))
    return out


def check_layout(fig: plt.Figure, name: str) -> int:
    """Print every pair of overlapping text boxes. Returns the number found.

    Entries inside one legend never overlap each other (matplotlib lays them
    out), so those pairs are skipped; everything else that intersects is
    reported with both strings. A slight shrink keeps mere touching silent.
    """
    fig.canvas.draw()
    legend_of = {}
    for lg in fig.findobj(mpl.legend.Legend):
        for t in lg.get_texts():
            legend_of[id(t)] = id(lg)
        legend_of[id(lg.get_title())] = id(lg)
    texts = _texts(fig)
    n = 0
    for (a, ba), (b, bb) in itertools.combinations(texts, 2):
        if id(a) in legend_of and legend_of[id(a)] == legend_of.get(id(b)):
            continue
        if ba.shrunk(0.9, 0.9).overlaps(bb.shrunk(0.9, 0.9)):
            n += 1
            print(f"  OVERLAP [{name}]: {a.get_text()!r}  <->  {b.get_text()!r}")
    if n == 0:
        print(f"  layout OK [{name}]: {len(texts)} text boxes, no overlap")
    return n


def save(fig: plt.Figure, name: str) -> None:
    """Write <name>.pdf (paper) + <name>.png (preview) under paper/figures/paper/."""
    n = check_layout(fig, name)
    fig.savefig(FIG_DIR / f"{name}.pdf")
    fig.savefig(FIG_DIR / f"{name}.png", dpi=300)
    print(f"  wrote {name}.pdf + {name}.png" + ("" if n == 0 else f"  ({n} overlaps!)"))
