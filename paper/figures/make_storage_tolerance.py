"""Storage cost to tolerate f simultaneous non-head failures — parity vs DéjàVu.

The honest home for double-parity: its live TTR is contaminated by this fleet's
concentrated recovery table (§B1-RAID6 in REPORT.md), so it does NOT go on the
TTR Pareto. Its real, clean advantage is storage. Cross-stage parity stores f
parity blobs (f × max non-head stage KV) to tolerate f simultaneous failures;
DéjàVu stores every stage's KV (Σ) and tolerates any number. So parity is
cheaper only while f < Σ/max (= non-head count when balanced). On this fleet
Σ/max = 2.25, so single-parity (f=1) and double-parity (f=2) sit below DéjàVu
while f≥3 crosses above — exactly why we stop at k=2. Geometry (per KV token),
not a live run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _slide import ACCENT, BODY, NAME, SLIDE_FULL, SUBJECT, save_slide  # noqa: E402

# raid6-run placement geometry (OPT-350M fp16): non-head stages 1/3/4/1 layers,
# per-layer KV = 2·16·64·2 = 4096 B -> max = 4L = 16384, Σ = 9L = 36864 B/token.
MAX_STAGE = 16384                    # one parity blob (max non-head stage)
SUM_STAGE = 36864                    # DéjàVu (Σ non-head)
CROSSOVER = SUM_STAGE / MAX_STAGE    # = 2.25
KB = 1024

fig, ax = plt.subplots(figsize=SLIDE_FULL)

# DéjàVu: flat — stores everything, tolerates any f.
ax.axhline(SUM_STAGE / KB, color=SUBJECT["replicate"], linestyle="--", linewidth=2, zorder=2)
ax.annotate(f"{NAME['replicate']}  —  stores all Σ, tolerates any f",
            xy=(4.4, SUM_STAGE / KB), xytext=(0, 5), textcoords="offset points",
            ha="right", color=SUBJECT["replicate"], fontsize=11, fontweight="bold")

# Cross-stage parity: f parity blobs = f × max non-head stage.
fs = np.array([1, 2, 3, 4])
ax.plot(fs, fs * MAX_STAGE / KB, color=ACCENT, linewidth=2, marker="o",
        markersize=6, zorder=3, alpha=0.5)

# The two IMPLEMENTED points, highlighted.
ax.scatter([1], [MAX_STAGE / KB], s=160, color=SUBJECT["parity"], marker="^", zorder=5)
ax.scatter([2], [2 * MAX_STAGE / KB], s=160, color=SUBJECT["raid6"], marker="^", zorder=5)
ax.annotate(f"{NAME['parity']}\n(1 blob, f=1)", xy=(1, MAX_STAGE / KB),
            xytext=(9, -2), textcoords="offset points", color=SUBJECT["parity"],
            fontsize=11, fontweight="bold", va="center")
ax.annotate(f"{NAME['raid6']}\n(2 blobs, f=2)", xy=(2, 2 * MAX_STAGE / KB),
            xytext=(9, -2), textcoords="offset points", color=SUBJECT["raid6"],
            fontsize=11, fontweight="bold", va="center")

# f>=3: parity crosses above DéjàVu — dominated (more storage, less tolerance).
ax.annotate("f≥3: dominated by DejaVu\n(more storage, less tolerance)",
            xy=(3, 3 * MAX_STAGE / KB), xytext=(-6, 8), textcoords="offset points",
            ha="right", color=BODY, fontsize=9.5, alpha=0.8)

# Crossover at f = Σ/max.
ax.axvline(CROSSOVER, color=BODY, linestyle=":", linewidth=1.2, alpha=0.6, zorder=1)
ax.annotate(f"crossover  f = Σ/max = {CROSSOVER:.2f}", xy=(CROSSOVER, 62),
            xytext=(6, 0), textcoords="offset points", ha="left", va="center",
            color=BODY, fontsize=10)

ax.set_xlabel("simultaneous non-head failures tolerated  (f)")
ax.set_ylabel("steady-state storage  (KB / KV token)")
ax.set_xticks([1, 2, 3, 4])
ax.set_ylim(0, 70)
ax.set_xlim(0.6, 4.4)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.grid(True, axis="y", alpha=0.25)
ax.set_axisbelow(True)
fig.subplots_adjust(left=0.11, right=0.97, top=0.95, bottom=0.14)
save_slide(fig, "fig_storage_tolerance")
