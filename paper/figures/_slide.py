"""Slide-scale matplotlib styling (ppt/DESIGN_SYSTEM.md §7).

`_common.py` targets the paper: 8pt fonts sized for a two-column ACM layout.
Dropping those figures straight into a slide makes the text unreadable, so this
module is the deck-side counterpart:

  * figures are built at the size they will occupy on the slide (1:1, no scaling
    in PowerPoint), so their text lands at the deck's own type scale;
  * colors come from the deck palette, not matplotlib defaults, so the figure
    and the slide look like one document;
  * recurring subjects keep the SAME color every week (SUBJECT), so the audience
    learns the code instead of re-reading the legend.

Usage:
    from _slide import save_slide, SUBJECT, SLIDE_FULL
    fig, ax = plt.subplots(figsize=SLIDE_FULL)
    ax.plot(x, y, color=SUBJECT["parity"], label="parity")
    save_slide(fig, "fig_recovery_ttr_slide")
"""
from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

FIG_DIR = Path(__file__).parent

# --- deck palette (ppt/DESIGN_SYSTEM.md §4) --------------------------------
BODY = "#404040"      # dk1     — text, axes, ticks
ACCENT = "#0070C0"    # accent3 — title emphasis
GRID = "#E5E8E8"      # lt2

# Same subject → same color every week. Do not reassign casually.
SUBJECT = {
    "full_replay": "#CB3E3A",   # accent6
    "surgical":    "#F08F1E",   # accent5
    "parity":      "#77B142",   # accent1
    "baseline":    "#808080",
}

# --- slide-content geometry (inches, from DESIGN_SYSTEM.md §2) -------------
SLIDE_FULL = (7.4, 4.6)    # P2 그림 우선: 우측 대형 영역
SLIDE_HALF = (5.9, 4.4)    # P3 2단 비교: 좌/우 각각
SLIDE_WIDE = (12.05, 3.6)  # 가로로 넓게 쓸 때

# 한글 라벨이 tofu 로 깨지지 않게: matplotlib 기본 DejaVu Sans 에는 한글이 없다.
# 설치된 것 중 첫 번째를 쓰고, 라틴 문자는 뒤의 폰트로 폴백한다.
_KR = [f for f in ("Apple SD Gothic Neo", "Noto Sans KR", "AppleGothic",
                   "NanumBarunGothic")
       if f in {x.name for x in mpl.font_manager.fontManager.ttflist}]

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": _KR + ["DejaVu Sans"],
    "axes.unicode_minus": False,     # 한글 폰트에서 마이너스 기호 깨짐 방지
    "font.size": 13,
    "axes.labelsize": 14,
    "axes.titlesize": 14,
    "xtick.labelsize": 12,
    "ytick.labelsize": 12,
    "legend.fontsize": 12,
    "lines.linewidth": 2.0,
    "lines.markersize": 7,
    "axes.linewidth": 0.8,
    "axes.edgecolor": BODY,
    "axes.labelcolor": BODY,
    "text.color": BODY,
    "xtick.color": BODY,
    "ytick.color": BODY,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})


def save_slide(fig: plt.Figure, name: str) -> None:
    """Write <name>.png (300 dpi) + <name>.pdf under paper/figures/.

    The PNG is what goes on the slide; the PDF is kept so the same figure can
    be reused in the paper without regenerating.
    """
    png = FIG_DIR / f"{name}.png"
    pdf = FIG_DIR / f"{name}.pdf"
    fig.savefig(png, dpi=300)
    fig.savefig(pdf)
    print(f"  wrote {png.name} + {pdf.name}")


def strip_chrome(ax: plt.Axes) -> None:
    """Remove what a slide doesn't need: top/right spines, heavy grid.

    No figure title — the slide title already says what this is (§7.2).
    """
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, alpha=0.3)
    ax.set_axisbelow(True)
