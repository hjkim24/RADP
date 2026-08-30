"""Fig. DejaVu-minus-KV-CARE retained state vs context length, per model size.

Derived projection (layer shape x bytes per layer-token x context), not a
live run: for a balanced 5-stage pipeline the gap is (N-2)/N of the full KV
cache, so it scales with model width/depth and with context. The one measured
point (OPT-350M, 2048 tokens, our head-heavy placement: 72 MB vs 32 MB = 40 MB)
is marked in red; it sits below the balanced OPT-350M line, i.e. the projection
is conservative for that fleet.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from _paper import COL, EMPH, GRAY, INK, NAME, clean, label, save  # noqa: E402
from experiments.storage_scaling_models import MODELS, per_layer_token_bytes  # noqa: E402

N = 5
GAP_FRAC = (N - 2) / N
CTX = np.array([1, 128, 512, 2048, 8192, 32768])
# fixed marker per model (shape carries identity; all ink)
SERIES = [("OPT-350M", "o", "white"), ("OPT-1.3B", "s", "white"),
          ("OPT-6.7B", "D", "white"), ("OPT-13B", "^", INK)]
KB, MB, GB = 1024, 1024**2, 1024**3

fig, ax = plt.subplots(figsize=COL)
for name, marker, mfc in SERIES:
    L, kvh, hd = MODELS[name]
    gap = L * per_layer_token_bytes(kvh, hd) * GAP_FRAC * CTX
    ax.plot(CTX, gap, marker=marker, mfc=mfc, color=INK, linewidth=0.8, label=name, zorder=3)

meas = 20480 * 2048     # measured OPT-350M fleet at 2048 tokens: 72 MB - 32 MB
ax.plot([2048], [meas], linestyle="", marker="o", mfc="white", color=EMPH,
        markersize=6, markeredgewidth=1.2, zorder=5)
label(ax, "measured OPT-350M\n(2K tokens): 40 MB", xy=(2048, meas), dx=0, dy=-9,
      ha="center", va="top", color=EMPH, bold=True, size=6.5)

ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xlabel("context length (prompt + generated tokens)")
ax.set_ylabel("retained state, DejaVu $-$ KV-CARE")
ax.set_xticks(CTX)
ax.set_xticklabels(["1", "128", "512", "2K", "8K", "32K"])
ax.set_yticks([100 * KB, MB, 10 * MB, 100 * MB, GB, 10 * GB])
ax.set_yticklabels(["100 KB", "1 MB", "10 MB", "100 MB", "1 GB", "10 GB"])
ax.set_xlim(0.6, 70000)
ax.set_ylim(30 * KB, 30 * GB)
clean(ax, grid_axis="both")
ax.legend(loc="upper left", ncol=1, handlelength=1.8)
fig.subplots_adjust(left=0.24, right=0.97, top=0.97, bottom=0.19)
save(fig, "fig_storage_scaling")
