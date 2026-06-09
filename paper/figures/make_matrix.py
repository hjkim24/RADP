"""Figure A: 24-cell OPT-350M matrix + 9-cell Llama-3.2-1B sub-matrix.

Rows = (chain_length × placement × chain_mode), Cols = concurrency C.
색은 grayscale gradient (높은 throughput = 어두움). 각 셀에 tok/s 와 [TBT p50 ms] 텍스트.
"""
from __future__ import annotations
import json
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from _common import save, FIG_DIR  # noqa: E402

RESULTS = Path(__file__).parent.parent.parent / "experiments" / "results"

# Row spec: (label, file_stem, model_chain_group)
ROWS = [
    ("T+sync",  "concurrent_phaseF_sync_3stage",          "OPT-350M, 3-stage"),
    ("T+async", "concurrent_phaseF_async_3stage",         "OPT-350M, 3-stage"),
    ("L+sync",  "concurrent_phaseF_latency_sync_3stage",  "OPT-350M, 3-stage"),
    ("L+async", "concurrent_phaseF_latency_async_3stage", "OPT-350M, 3-stage"),
    ("T+sync",  "concurrent_phaseF_4stage_T_sync",        "OPT-350M, 4-stage"),
    ("T+async", "concurrent_phaseF_4stage_T_async",       "OPT-350M, 4-stage"),
    ("L+sync",  "concurrent_phaseF_4stage_L_sync",        "OPT-350M, 4-stage"),
    ("L+async", "concurrent_phaseF_4stage_L_async",       "OPT-350M, 4-stage"),
    ("T+sync",  "concurrent_llama1b_4stage_T_sync",       "Llama-3.2-1B, 4-stage"),
    ("T+async", "concurrent_llama1b_4stage_T_async",      "Llama-3.2-1B, 4-stage"),
    ("L+sync",  None,                                      "Llama-3.2-1B, 4-stage"),  # missing
    ("L+async", "concurrent_llama1b_4stage_L_async",      "Llama-3.2-1B, 4-stage"),
]
COLS = ["1", "4", "16"]

def load_cell(stem, c):
    if stem is None:
        return (np.nan, np.nan)
    p = RESULTS / f"{stem}.json"
    d = json.load(open(p))
    s = d["sweep"][c][0]["summary"]
    return (s["aggregate_tok_per_sec"], s["tbt_p50_all_streams"] * 1000)

throughput = np.full((len(ROWS), len(COLS)), np.nan)
tbt = np.full((len(ROWS), len(COLS)), np.nan)
for i, (_, stem, _) in enumerate(ROWS):
    for j, c in enumerate(COLS):
        throughput[i, j], tbt[i, j] = load_cell(stem, c)

# --- plot ---
fig, ax = plt.subplots(figsize=(5.5, 4.6))

# Grayscale: higher throughput = darker (cmap inverted so dark = good)
# vmin/vmax across non-nan values
vmin, vmax = np.nanmin(throughput), np.nanmax(throughput)
norm = plt.Normalize(vmin=vmin, vmax=vmax)
cmap = plt.get_cmap("Greys")

# Mask NaN cells for hatching
masked = np.ma.masked_invalid(throughput)
im = ax.imshow(masked, aspect="auto", cmap=cmap, norm=norm)

# NaN cells: light gray fill + "—"
for i in range(len(ROWS)):
    for j in range(len(COLS)):
        if np.isnan(throughput[i, j]):
            ax.add_patch(plt.Rectangle(
                (j - 0.5, i - 0.5), 1, 1,
                facecolor="#eeeeee", edgecolor="none", zorder=1,
            ))
            ax.text(j, i, "—", ha="center", va="center", fontsize=8, color="#888")
            continue
        # Text color depends on cell darkness
        val = throughput[i, j]
        text_color = "white" if (val - vmin) / (vmax - vmin) > 0.55 else "black"
        ax.text(
            j, i - 0.18,
            f"{throughput[i, j]:.1f}",
            ha="center", va="center", fontsize=7.5, color=text_color, weight="bold",
        )
        ax.text(
            j, i + 0.22,
            f"[{tbt[i, j]:.0f}]",
            ha="center", va="center", fontsize=6.5, color=text_color,
        )

# Group separators (between OPT 3-stage / OPT 4-stage / Llama)
for sep in [3.5, 7.5]:
    ax.axhline(sep, color="black", linewidth=0.8)

# Row labels (placement+mode)
row_labels = [r[0] for r in ROWS]
ax.set_yticks(range(len(ROWS)))
ax.set_yticklabels(row_labels)

# Column labels
ax.set_xticks(range(len(COLS)))
ax.set_xticklabels([f"C={c}" for c in COLS])

# Group annotations on the right
groups = ["OPT-350M, 3-stage", "OPT-350M, 4-stage", "Llama-3.2-1B, 4-stage"]
group_rows = [(0, 3), (4, 7), (8, 11)]
for grp, (top, bot) in zip(groups, group_rows):
    mid = (top + bot) / 2
    ax.text(
        len(COLS) - 0.4 + 0.7, mid, grp,
        ha="left", va="center", fontsize=7.5, rotation=-90,
    )

ax.set_xlim(-0.5, len(COLS) - 0.5)
ax.set_ylim(len(ROWS) - 0.5, -0.5)
ax.tick_params(axis="both", which="both", length=0)
for spine in ax.spines.values():
    spine.set_visible(False)

# Colorbar
cbar = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.18, shrink=0.6)
cbar.set_label("Aggregate throughput (tok/s)", fontsize=7)
cbar.ax.tick_params(labelsize=6)

# Caption note: each cell shows tok/s with [TBT p50 ms] underneath
ax.set_xlabel("Concurrency", fontsize=8)
fig.text(
    0.02, -0.02,
    "Each cell: aggregate tok/s (top) · TBT p50 ms in brackets (bottom). "
    "Darker = higher throughput.",
    fontsize=6.5, color="#555",
)

fig.tight_layout()
save(fig, "fig_matrix")
print("Figure A done.")
