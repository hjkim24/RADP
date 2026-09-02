"""Fig. failure-free cost of protection — throughput loss and TBT p50 increase vs protection off.

Data: experiments/results/b1_steady_modes_n3_20260830.json (OPT-350M, async
chain, 3 rounds with interleaved order, 30 requests x 20 tokens per mode).
Bars are the mean delta vs the same round's protection-off run; error bars are
the sample standard deviation over the 3 rounds. Absolute protection-off values
(5.24 tok/s, TBT p50 183 ms) belong in the caption.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _paper import COL, EMPH, GRAY, INK, LIGHT, NAME, RESULTS, clean, save  # noqa: E402

MODEL = os.environ.get("RADP_FIG_MODEL", "350m")   # 350m (default) | 7b
if MODEL == "7b":
    agg = json.load(open(RESULTS / "b1_steady_7b_n3.json"))["aggregate"]
    YLIM, SUFFIX = (-4, 12), "_7b"
else:
    agg = json.load(open(RESULTS / "b1_steady_modes_n3_20260830.json"))["aggregate"]
    YLIM, SUFFIX = (0, 12), ""
MODES = [("single_parity", f"{NAME['parity']}\n($k$=1)"),
         ("double_parity", f"{NAME['parity']}\n($k$=2)"),
         ("replication",   f"{NAME['replicate']}\n(replication)")]
METRICS = [("throughput_delta_vs_off_pct", "throughput loss", -1, "white", ""),
           ("tbt_p50_delta_vs_off_pct",    "TBT p50 increase", +1, LIGHT, "////")]

fig, ax = plt.subplots(figsize=COL)
x = np.arange(len(MODES))
w = 0.36
for j, (key, name, sign, face, hatch) in enumerate(METRICS):
    means = np.array([sign * agg[m][f"{key}_mean"] for m, _ in MODES])
    stds = np.array([agg[m][f"{key}_sample_std"] for m, _ in MODES])
    xs = x + (j - 0.5) * w
    ax.bar(xs, means, w, yerr=stds, color=face, edgecolor=INK, linewidth=0.6,
           hatch=hatch, capsize=2, error_kw=dict(linewidth=0.6), label=name, zorder=3)
    for xi, m, s in zip(xs, means, stds):
        ax.annotate(f"{m:.1f}%", xy=(xi, m + s), xytext=(0, 2), textcoords="offset points",
                    ha="center", va="bottom", fontsize=6)

ax.set_xticks(x)
ax.set_xticklabels([lbl for _, lbl in MODES])
ax.set_ylabel("overhead vs. protection off (%)")
ax.set_ylim(*YLIM)
if YLIM[0] < 0:
    ax.axhline(0, color=INK, linewidth=0.5, zorder=2)
clean(ax)
ax.legend(loc="upper left", ncol=2)
fig.subplots_adjust(left=0.14, right=0.98, top=0.97, bottom=0.2)
save(fig, "fig_protection_cost" + SUFFIX)
