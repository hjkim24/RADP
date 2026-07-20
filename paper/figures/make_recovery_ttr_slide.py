"""Slide version of the recovery TTR(P) figure (ppt/DESIGN_SYSTEM.md §7).

Same data as `make_recovery_ttr.py`, but built at slide scale with the deck
palette so it can be dropped into the P2 "그림 우선" slide without scaling.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _slide import SLIDE_FULL, SUBJECT, save_slide, strip_chrome  # noqa: E402

RESULTS = Path(__file__).parent.parent.parent / "experiments" / "results"

d = json.load(open(RESULTS / "b1_ft_fleet_parity.json"))
trials, fits = d["trials"], d["fits"]

STYLE = {
    "full_replay": (SUBJECT["full_replay"], "o", "full-replay"),
    "surgical":    (SUBJECT["surgical"],    "s", "surgical"),
    "parity":      (SUBJECT["parity"],      "^", "parity"),
}

fig, ax = plt.subplots(figsize=SLIDE_FULL)
xline = np.linspace(0, 34, 50)

for mode, (color, marker, label) in STYLE.items():
    pts = [(t["position"], t["ttr_seconds"]) for t in trials
           if t["mode"] == mode and t["fired"]
           and t.get("recovery_visible", t.get("index_ok"))
           and t["sequence_match"]
           and (mode != "parity" or t.get("parity_branch_ran"))]
    if not pts:
        continue
    ax.plot([p for p, _ in pts], [y for _, y in pts], marker=marker,
            linestyle="none", color=color, label=label, zorder=3)
    f = fits.get(mode)
    if not f or f["n_points"] < 2:
        continue
    ax.plot(xline, f["intercept"] + f["slope"] * xline, "--",
            color=color, linewidth=1.6, alpha=0.85, zorder=2)
    slope_ms = f["slope"] * 1e3
    ax.annotate(f"{slope_ms:.1f} ms/pos" if slope_ms < 10 else f"{slope_ms:.0f} ms/pos",
                xy=(34, f["intercept"] + f["slope"] * 34),
                xytext=(-2, 4), textcoords="offset points",
                ha="right", va="bottom", color=color, fontsize=13)

# No figure title: the slide title carries it (DESIGN_SYSTEM §7.2).
ax.set_xlabel("failure depth  P")
ax.set_ylabel("recovery time (s)")
ax.set_xlim(0, 36)
ax.set_ylim(0, None)
strip_chrome(ax)
ax.legend(loc="upper left", frameon=False)

fig.tight_layout()
save_slide(fig, "fig_recovery_ttr_slide")
