"""Shared matplotlib styling for paper figures.

흑백(grayscale) baseline + multi-baseline 비교 시에만 색 추가.
PDF (paper용 vector) + PNG @ 300dpi (ppt용 raster) 동시 출력.
"""
from __future__ import annotations
import matplotlib as mpl
import matplotlib.pyplot as plt
from pathlib import Path

FIG_DIR = Path(__file__).parent

# 본문 폰트 크기: acmart sigconf 의 9-10pt 캡션과 잘 어울리도록 8pt
mpl.rcParams.update({
    "font.size": 8,
    "axes.labelsize": 8,
    "axes.titlesize": 9,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 7,
    "axes.linewidth": 0.6,
    "lines.linewidth": 1.2,
    "patch.linewidth": 0.5,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
    "pdf.fonttype": 42,            # TrueType (paper 호환)
    "ps.fonttype": 42,
})

# Multi-baseline 비교용 컬러 (color-blind safe, paper-friendly)
PALETTE = {
    "primary":  "#1f77b4",         # blue
    "secondary":"#d62728",         # red
    "tertiary": "#2ca02c",         # green
    "muted":    "#7f7f7f",         # gray
}


def save(fig: plt.Figure, name: str) -> None:
    """Save fig as both PDF (paper) and PNG (ppt) under paper/figures/."""
    pdf = FIG_DIR / f"{name}.pdf"
    png = FIG_DIR / f"{name}.png"
    fig.savefig(pdf)
    fig.savefig(png, dpi=300)
    print(f"  wrote {pdf.name} + {png.name}")
