"""Figure: recovery time vs failure depth (TTR(P)) on the live fleet.

surgical vs full-replay recovery, OPT-350M, sync chain, 5-stage heterogeneous
Jetson fleet (ao-2 head, on-1/on-6/ao-1 interior, on-2 tail). One chain-interior
compute-time crash injected at decode position P; y = the recovery step's wall.

Data: experiments/results/b1_ft_fleet.json (experiments.b1_ft_fleet sweep).
The linear fits show full-replay pays ~one full chain forward per replayed
position (~150 ms, ≈ steady decode step) while surgical pays only the dead
stage's fraction (~15 ms), a ~10x slope gap that widens with failure depth.
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

d = json.load(open(RESULTS / "b1_ft_fleet_parity.json"))
trials = d["trials"]
fits = d["fits"]

STYLE = {
    "full_replay": (PALETTE["secondary"], "o", "full-replay (evict all, replay whole chain)"),
    "surgical":    (PALETTE["primary"],   "s", "surgical (rebuild only dead stage's backup)"),
    "parity":      (PALETTE["tertiary"],  "^", "parity (XOR-reconstruct, zero recompute)"),
}

fig, ax = plt.subplots(figsize=(5.0, 3.2))

xline = np.linspace(0, 34, 50)
for mode, (color, marker, label) in STYLE.items():
    pts = [(t["position"], t["ttr_seconds"]) for t in trials
           if t["mode"] == mode and t["fired"] and t.get("recovery_visible", t.get("index_ok"))
           and t["sequence_match"]
           and (mode != "parity" or t.get("parity_branch_ran"))]
    xs = [p for p, _ in pts]
    ys = [y for _, y in pts]
    if not xs:
        continue
    ax.plot(xs, ys, marker=marker, linestyle="none", color=color, markersize=5,
            label=label, zorder=3)
    f = fits.get(mode)
    if not f or f["n_points"] < 2:
        continue
    ax.plot(xline, f["intercept"] + f["slope"] * xline, linestyle="--",
            color=color, linewidth=1.0, alpha=0.8, zorder=2)
    # slope annotation
    slope_ms = f["slope"] * 1e3
    ax.annotate(
        f"{slope_ms:.1f} ms / pos" if slope_ms < 10 else f"{slope_ms:.0f} ms / pos",
        xy=(34, f["intercept"] + f["slope"] * 34),
        xytext=(-2, 3), textcoords="offset points",
        ha="right", va="bottom", color=color, fontsize=7,
    )

ax.set_xlabel("failure depth  P  (decode position at crash)")
ax.set_ylabel("recovery time  TTR  (s)")
ax.set_xlim(0, 36)
ax.set_ylim(0, None)
ax.grid(True, linewidth=0.3, alpha=0.4)
ax.legend(loc="upper left", frameon=False)

# slope-ratio callout
# Parity-focused callout: its slope is what "zero recompute" buys.
if "parity" in fits and fits["parity"].get("n_points", 0) >= 2:
    vs_surg = fits["surgical"]["slope"] / fits["parity"]["slope"]
    vs_full = fits["full_replay"]["slope"] / fits["parity"]["slope"]
    note = (f"parity slope is {vs_surg:.0f}x flatter\n"
            f"than surgical, {vs_full:.0f}x than full-replay")
else:
    note = f"slope ratio  {fits['full_replay']['slope'] / fits['surgical']['slope']:.1f}x"
ax.text(0.04, 0.72, note, transform=ax.transAxes,
        ha="left", va="top", fontsize=7.5, style="italic", color=PALETTE["muted"])

fig.tight_layout()
save(fig, "fig_recovery_ttr")
