"""Figure: 4-baseline comparison on a single 6-worker fleet, N=3 trials.

Bar chart (grouped, with std error bars) for three metrics across four
placement baselines (greedy / uniform / jupiter_dp / ours):
  - aggregate throughput (tok/s, higher = better)
  - TBT p50 (ms, lower = better)
  - TBT p95 (ms, lower = better)

Data sources combined:
  - experiments/results/a3b_d28_4baseline_N3_n30.json       (greedy×3, uniform×3, jupiter_dp×2)
  - experiments/results/a3b_d28_4baseline_N3_n30_part2.json (jupiter_dp×1, ours×3)

Live 4-baseline sweep on the 6-worker D2.8 fleet (1 AGX MAXN + 3 Nano CUDA +
2 Nano CPU). Each cell is one fresh deploy + 30 streams × 30 tokens.
"""
from __future__ import annotations
import json
import statistics as st
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _common import save, PALETTE  # noqa: E402

RESULTS = Path(__file__).parent.parent.parent / "experiments" / "results"
SOURCES = [
    RESULTS / "a3b_d28_4baseline_N3_n30.json",
    RESULTS / "a3b_d28_4baseline_N3_n30_part2.json",
]

# Display order + label
BASELINES = [
    ("greedy",     "greedy"),
    ("uniform",    "uniform"),
    ("jupiter_dp", "Jupiter-DP"),
    ("ours",       "RADP (ours)"),
]


def load_metrics() -> dict[str, dict[str, tuple[float, float, int]]]:
    """For each baseline → metric → (mean, std, n_trials)."""
    rows: dict[str, list[dict[str, float]]] = {}
    for src in SOURCES:
        d = json.loads(src.read_text())
        for cell in d["cells"]:
            name = cell["name"]
            nm = cell.get("normal") or {}
            if not nm:
                continue
            rows.setdefault(name, []).append({
                "tok_s": nm["throughput_tokens_per_sec"]["mean"],
                "tbt_p50_ms": nm["tbt_seconds"]["p50"] * 1000.0,
                "tbt_p95_ms": nm["tbt_seconds"]["p95"] * 1000.0,
            })

    out: dict[str, dict[str, tuple[float, float, int]]] = {}
    for name, trials in rows.items():
        n = len(trials)
        agg = {}
        for k in ["tok_s", "tbt_p50_ms", "tbt_p95_ms"]:
            vals = [t[k] for t in trials]
            agg[k] = (st.mean(vals), st.stdev(vals) if n >= 2 else 0.0, n)
        out[name] = agg
    return out


def main() -> None:
    m = load_metrics()
    names = [n for n, _ in BASELINES if n in m]
    labels = [lbl for n, lbl in BASELINES if n in m]
    n_bars = len(names)
    if n_bars == 0:
        raise RuntimeError("No baselines found")

    def col(metric):
        vals = np.array([m[n_][metric][0] for n_ in names])
        stds = np.array([m[n_][metric][1] for n_ in names])
        return vals, stds

    tok_v, tok_s = col("tok_s")
    p50_v, p50_s = col("tbt_p50_ms")
    p95_v, p95_s = col("tbt_p95_ms")

    fig, axes = plt.subplots(1, 3, figsize=(6.5, 2.4))
    x = np.arange(n_bars)
    colors = [PALETTE["muted"] if name != "ours" else PALETTE["primary"]
              for name in names]

    def _bar(ax, vals, stds, title, ylabel, higher_better):
        bars = ax.bar(
            x, vals, color=colors, edgecolor="black", linewidth=0.6,
            yerr=stds, capsize=3,
            error_kw={"elinewidth": 0.7, "ecolor": "black"},
        )
        best_idx = int(np.argmax(vals) if higher_better else np.argmin(vals))
        for i, (b, v, s_) in enumerate(zip(bars, vals, stds)):
            txt = f"{v:.1f}"
            ax.text(
                b.get_x() + b.get_width() / 2, v + s_,
                txt, ha="center", va="bottom",
                fontsize=6.5,
                weight="bold" if i == best_idx else "normal",
            )
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=6.5)
        ax.set_title(title, fontsize=8)
        ax.set_ylabel(ylabel, fontsize=7)
        ax.set_ylim(0, max(vals + stds) * 1.20)
        ax.tick_params(axis="y", labelsize=6.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    _bar(axes[0], tok_v, tok_s, "Throughput", "tok/s", higher_better=True)
    _bar(axes[1], p50_v, p50_s, "TBT p50",    "ms",    higher_better=False)
    _bar(axes[2], p95_v, p95_s, "TBT p95",    "ms",    higher_better=False)

    # Subtle caption noting N=3
    fig.text(0.5, -0.04, "N=3 trials; error bars = ±1 std",
             ha="center", fontsize=6.5, color="#555", style="italic")

    fig.tight_layout()
    save(fig, "fig_baselines")
    print("Figure baselines done.")
    print("metrics (mean ± std, N=3 trials):")
    for n_, lbl in BASELINES:
        if n_ not in m:
            continue
        v = m[n_]
        print(f"  {lbl:<14} N={v['tok_s'][2]} "
              f"tok/s={v['tok_s'][0]:.2f}±{v['tok_s'][1]:.2f}  "
              f"p50={v['tbt_p50_ms'][0]:.1f}±{v['tbt_p50_ms'][1]:.1f}ms  "
              f"p95={v['tbt_p95_ms'][0]:.1f}±{v['tbt_p95_ms'][1]:.1f}ms")


if __name__ == "__main__":
    main()
