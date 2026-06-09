"""Figure B: per-tier per-layer compute time bar chart.

Decode 단계 (seq=64) per-layer 시간을 tier 별로 비교. AGX Orin MAXN 의 우위가
두 profiler 버그 fix 후 처음 노출된 점을 시각화 (paper §10.1 의 "16× faster").

Source: paper/sections/evaluation.tex §10.1 + PHASES.md EXP-D2.2.
"""
from __future__ import annotations
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from _common import save, PALETTE  # noqa: E402

# 4 tier 측정값 (paper §10.1 기준, seq=64 decode)
TIERS = [
    ("Nano CPU",   42.0,  "gray"),
    ("AGX CPU",    17.6,  "gray"),
    ("Nano CUDA",   1.5,  "gray"),
    ("AGX MAXN",    1.5 / 16,  PALETTE["secondary"]),  # ~0.094, highlight
]

fig, ax = plt.subplots(figsize=(4.0, 2.6))

labels = [t[0] for t in TIERS]
values = [t[1] for t in TIERS]
colors = [t[2] for t in TIERS]

bars = ax.bar(labels, values, color=colors, edgecolor="black", linewidth=0.6, width=0.65)

# 막대 위에 정확 수치
for bar, v in zip(bars, values):
    if v >= 1:
        text = f"{v:.1f} ms"
    else:
        text = f"{v*1000:.0f} µs"
    ax.text(
        bar.get_x() + bar.get_width() / 2, v * 1.15,
        text, ha="center", va="bottom", fontsize=7.5,
    )

# AGX MAXN 위에 16× 발견 annotation
ax.annotate(
    "16× faster than\nNano CUDA",
    xy=(3, TIERS[3][1] * 1.6), xytext=(2.4, 6),
    fontsize=7, color=PALETTE["secondary"], ha="center",
    arrowprops=dict(arrowstyle="->", color=PALETTE["secondary"], lw=0.8),
)

ax.set_yscale("log")
ax.set_ylabel("Per-layer time (ms, log scale)", fontsize=8)
ax.set_ylim(0.03, 100)

# Tier 그룹화: CPU vs CUDA 시각 분리
ax.axvline(1.5, color="black", linestyle=":", linewidth=0.5, alpha=0.5)
ax.text(0.5, 0.04, "CPU tier", ha="center", fontsize=6.5, color="#555", style="italic")
ax.text(2.5, 0.04, "CUDA tier", ha="center", fontsize=6.5, color="#555", style="italic")

ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.tick_params(axis="x", which="both", length=0)

fig.tight_layout()
save(fig, "fig_tiers")
print("Figure B done.")
