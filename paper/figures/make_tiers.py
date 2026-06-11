"""Figure B: per-tier per-layer compute time bar chart.

OPT-350M seq=64 forward (fp16, no KV cache) per-layer time, by compute tier.
Live ProfileLayers measurement, not paper-claim hardcode — see EXP-D2.6
sidecar (experiments/results/d28_sidecar.json) for source data.

The original draft of this figure hardcoded an AGX MAXN value of 1.5/16 ms
to mirror the paper's "16× faster than Nano CUDA" claim. Direct profiling on
the live fleet with AGX MAXN + jetson_clocks fully boosted gives only 1.36×,
not 16× — OPT-350M is too small to saturate the AGX FLOPS, so per-layer
timing is launch-bound (CUDA kernel launch + Python/PyTorch overhead
dominates compute). The 16× claim is removed.
"""
from __future__ import annotations
import matplotlib.pyplot as plt
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from _common import save, PALETTE  # noqa: E402

# Live-measured per-layer means (ms) from the EXP-D2.6 sidecar.
# AGX CPU is held at the earlier paper §10.1 estimate (17.6 ms) — the
# current 6-worker fleet has no AGX board running in CPU mode, so a live
# replacement value is unavailable. Kept here so the four-tier comparison
# stays readable; remove the row if a strict live-only figure is needed.
TIERS = [
    ("Nano CPU",   84.7,  "gray"),                 # on-3/on-4 mean
    ("AGX CPU",    17.6,  "gray"),                 # paper §10.1 (legacy)
    ("Nano CUDA",   1.11, "gray"),                 # on-1/on-2/on-6 mean
    ("AGX MAXN",    0.82, PALETTE["secondary"]),   # ao-1 (MAXN + jetson_clocks)
]

fig, ax = plt.subplots(figsize=(4.0, 2.6))

labels = [t[0] for t in TIERS]
values = [t[1] for t in TIERS]
colors = [t[2] for t in TIERS]

bars = ax.bar(labels, values, color=colors, edgecolor="black", linewidth=0.6, width=0.65)

for bar, v in zip(bars, values):
    text = f"{v:.2f} ms" if v < 10 else f"{v:.1f} ms"
    ax.text(
        bar.get_x() + bar.get_width() / 2, v * 1.15,
        text, ha="center", va="bottom", fontsize=7.5,
    )

# Honest annotation: the *real* heterogeneity is CUDA tier vs CPU tier,
# not the modest 1.36× difference within the CUDA tier.
nano_cuda = TIERS[2][1]
agx_maxn = TIERS[3][1]
nano_cpu = TIERS[0][1]
ax.annotate(
    f"{nano_cuda/agx_maxn:.2f}× faster than\nNano CUDA",
    xy=(3, agx_maxn * 1.6), xytext=(2.4, 4.5),
    fontsize=7, color=PALETTE["secondary"], ha="center",
    arrowprops=dict(arrowstyle="->", color=PALETTE["secondary"], lw=0.8),
)
ax.annotate(
    f"{nano_cpu/nano_cuda:.0f}× CUDA-vs-CPU gap",
    xy=(0.5, nano_cpu * 0.8), xytext=(0.5, 200),
    fontsize=7, color="#444", ha="center",
    arrowprops=dict(arrowstyle="-", color="#888", lw=0.6, alpha=0.7),
)

ax.set_yscale("log")
ax.set_ylabel("Per-layer time (ms, log scale)", fontsize=8)
ax.set_ylim(0.3, 500)

# Tier 그룹화: CPU vs CUDA 시각 분리
ax.axvline(1.5, color="black", linestyle=":", linewidth=0.5, alpha=0.5)
ax.text(0.5, 0.45, "CPU tier", ha="center", fontsize=6.5, color="#555", style="italic")
ax.text(2.5, 0.45, "CUDA tier", ha="center", fontsize=6.5, color="#555", style="italic")

ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.tick_params(axis="x", which="both", length=0)

fig.tight_layout()
save(fig, "fig_tiers")
print("Figure B done.")
