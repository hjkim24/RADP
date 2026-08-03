"""replicate-vs-parity storage gap vs context length, per model size.

The per-token gap looks tiny (OPT-350M: 20 KB), but KV backup accumulates over
the sequence and grows with the model, so at realistic context lengths the gap
is MB-to-GB. Pure geometry (see experiments/storage_scaling_models.py) — no model
is run. Balanced N=5 pipeline; the measured OPT-350M point (our head-heavy fleet,
ratio 2.25) is marked as the conservative anchor.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from _slide import BODY, SLIDE_FULL, save_slide  # noqa: E402
from experiments.storage_scaling_models import MODELS, per_layer_token_bytes  # noqa: E402

N = 5                       # balanced pipeline stages; gap = (N-2)/N of full KV
GAP_FRAC = (N - 2) / N
PLOT = ["OPT-350M", "OPT-1.3B", "OPT-6.7B", "OPT-13B"]
# light -> dark blue as the model grows
COLORS = ["#9ecae1", "#4292c6", "#08519c", "#08306b"]
CTX = np.array([1, 128, 512, 2048, 8192, 32768])

fig, ax = plt.subplots(figsize=SLIDE_FULL)
for name, color in zip(PLOT, COLORS):
    L, kvh, hd = MODELS[name]
    full_tok = L * per_layer_token_bytes(kvh, hd)
    gap = full_tok * GAP_FRAC * CTX          # bytes
    ax.plot(CTX, gap, marker="o", color=color, linewidth=2.2, label=name, zorder=3)

# measured OPT-350M anchor (real fleet, head-heavy: gap 20480 B/token)
ax.scatter([2048], [20480 * 2048], s=90, facecolor="white",
           edgecolor="#CB3E3A", linewidth=2.2, zorder=5)
ax.annotate("measured OPT-350M\n(our fleet, 40 MB)", xy=(2048, 20480 * 2048),
            xytext=(-8, -46), textcoords="offset points", ha="center",
            fontsize=10, color="#CB3E3A")

KB, MB, GB = 1024, 1024**2, 1024**3
ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlabel("context length  (tokens: prompt + generated)")
ax.set_ylabel("storage gap (replicate minus parity)")
ax.set_xticks([1, 128, 512, 2048, 8192, 32768])
ax.set_xticklabels(["1", "128", "512", "2K", "8K", "32K"])
ax.set_yticks([10 * KB, 100 * KB, MB, 10 * MB, 100 * MB, GB, 10 * GB])
ax.set_yticklabels(["10KB", "100KB", "1MB", "10MB", "100MB", "1GB", "10GB"])
ax.grid(True, which="major", alpha=0.25)
ax.set_axisbelow(True)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

# raid6 keeps 2/N vs replicate (N-1)/N -> gap (N-3)/N (dashed, model-agnostic ref
# using the largest plotted model so it sits in range).
RAID6_GAP_FRAC = (N - 3) / N   # replicate - raid6, balanced N=5 -> 2/5
Lb, kvhb, hdb = MODELS[PLOT[-1]]
full_tok_b = Lb * per_layer_token_bytes(kvhb, hdb)
ax.plot(CTX, full_tok_b * RAID6_GAP_FRAC * CTX, linestyle="--", color="#888888",
        linewidth=1.8, label=f"{PLOT[-1]} raid6 gap", zorder=2)

ax.legend(loc="upper left", fontsize=11, frameon=False, title="model size")
fig.subplots_adjust(left=0.13, right=0.97, top=0.96, bottom=0.14)
save_slide(fig, "fig_storage_scaling_models")
