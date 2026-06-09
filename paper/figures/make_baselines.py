"""Figure: 4-baseline comparison on a single 6-worker fleet.

Bar chart (grouped) for three metrics across the four placement
baselines (greedy / uniform / jupiter_dp / ours):
  - aggregate throughput (tok/s, higher = better)
  - TBT p50 (ms, lower = better)
  - TBT p95 (ms, lower = better)

Data source: experiments/results/a3b_d28_4baseline_n30.json — the live
4-baseline cell sweep on the D2.8 fleet (1 AGX MAXN + 3 Nano CUDA +
2 Nano CPU). Each baseline cell is one deploy + 30 streams × 30 tokens
(n=900 TBT samples).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _common import save, PALETTE  # noqa: E402

RESULTS = Path(__file__).parent.parent.parent / "experiments" / "results"
DATA = RESULTS / "a3b_d28_4baseline_n30.json"

# Display order + label
BASELINES = [
    ("greedy",     "greedy"),
    ("uniform",    "uniform"),
    ("jupiter_dp", "Jupiter-DP"),
    ("ours",       "RADP (ours)"),
]


def load_metrics() -> dict[str, dict[str, float]]:
    d = json.loads(DATA.read_text())
    out: dict[str, dict[str, float]] = {}
    for cell in d["cells"]:
        name = cell["name"]
        nm = cell.get("normal") or {}
        if not nm:
            continue
        out[name] = {
            "tok_s": nm["throughput_tokens_per_sec"]["mean"],
            "tbt_p50_ms": nm["tbt_seconds"]["p50"] * 1000.0,
            "tbt_p95_ms": nm["tbt_seconds"]["p95"] * 1000.0,
        }
    return out


def main() -> None:
    m = load_metrics()
    names = [n for n, _ in BASELINES if n in m]
    labels = [lbl for n, lbl in BASELINES if n in m]
    n = len(names)
    if n == 0:
        raise RuntimeError(f"No baselines found in {DATA}")

    tok = np.array([m[n_]["tok_s"] for n_ in names])
    p50 = np.array([m[n_]["tbt_p50_ms"] for n_ in names])
    p95 = np.array([m[n_]["tbt_p95_ms"] for n_ in names])

    fig, axes = plt.subplots(1, 3, figsize=(6.5, 2.4))
    x = np.arange(n)
    # Highlight 'ours' in primary color, others muted.
    colors = [PALETTE["muted"] if name != "ours" else PALETTE["primary"]
              for name in names]

    def _bar(ax, vals, title, ylabel, higher_better):
        bars = ax.bar(x, vals, color=colors, edgecolor="black", linewidth=0.6)
        # Best-of-group annotation
        best_idx = int(np.argmax(vals) if higher_better else np.argmin(vals))
        for i, (b, v) in enumerate(zip(bars, vals)):
            txt = f"{v:.1f}"
            ax.text(
                b.get_x() + b.get_width() / 2, v,
                txt, ha="center", va="bottom",
                fontsize=6.5,
                weight="bold" if i == best_idx else "normal",
            )
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=6.5)
        ax.set_title(title, fontsize=8)
        ax.set_ylabel(ylabel, fontsize=7)
        # Y-axis: extend by 12% so the value label has room above tallest bar
        ax.set_ylim(0, max(vals) * 1.18)
        ax.tick_params(axis="y", labelsize=6.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    _bar(axes[0], tok, "Throughput", "tok/s", higher_better=True)
    _bar(axes[1], p50, "TBT p50",   "ms",     higher_better=False)
    _bar(axes[2], p95, "TBT p95",   "ms",     higher_better=False)

    fig.tight_layout()
    save(fig, "fig_baselines")
    print("Figure baselines done.")
    print("metrics:")
    for n_, lbl in BASELINES:
        if n_ in m:
            v = m[n_]
            print(f"  {lbl:<14} tok/s={v['tok_s']:.2f}  "
                  f"p50={v['tbt_p50_ms']:.1f}ms  p95={v['tbt_p95_ms']:.1f}ms")


if __name__ == "__main__":
    main()
