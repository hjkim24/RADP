"""Fig. recovery latency at P=32 (log x) vs retained recovery state per token (y).

Only KV-CARE sits in the low-latency AND low-storage corner. Latency from the
measured JSONs (mean of valid P=32 trials); storage from the placement
geometry in b1_ft_overhead.json (kB per KV token: DejaVu = sum of non-head
stages, KV-CARE = largest non-head stage). Reconfigure's victim differs per P,
so its x is the median over all positions, not the P=32 sample.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent))
from _paper import COL, EMPH, GRAY, INK, NAME, RESULTS, STYLE, clean, label, save  # noqa: E402

par = json.load(open(RESULTS / "b1_ft_fleet_parity.json"))
rep = json.load(open(RESULTS / "b1_ft_fleet_replicate.json"))
rea = json.load(open(RESULTS / "b1_ft_fleet_reactive_client_interval_20260830.json"))
ovh = json.load(open(RESULTS / "b1_ft_overhead.json"))
KB = 1024


def ttr_at(d, mode, P=32):
    xs = [t["ttr_seconds"] for t in d["trials"]
          if t["mode"] == mode and t["position"] == P and t.get("recovery_visible")
          and t["sequence_match"] and t.get(f"{mode}_branch_ran", True)]
    return sum(xs) / len(xs)


rea_med = statistics.median(t["ttr_seconds"] for t in rea["trials"]
                            if t["fired"] and t["sequence_match"] and t.get("reconfigured"))

#            mode, x (s), y (KB/token), label placement
PTS = [
    ("reactive_replacement", rea_med,                    0,                          dict(dx=0, dy=6, ha="center", va="bottom")),
    ("full_replay",          ttr_at(par, "full_replay"), 0,                          dict(dx=0, dy=6, ha="center", va="bottom")),
    ("surgical",             ttr_at(par, "surgical"),    0,                          dict(dx=0, dy=6, ha="center", va="bottom")),
    ("replicate",            ttr_at(rep, "replicate"),   ovh["replicate_bytes"] / KB, dict(dx=6, dy=0, ha="left")),
    ("parity",               ttr_at(par, "parity"),      ovh["parity_bytes"] / KB,    dict(dx=6, dy=0, ha="left")),
]

fig, ax = plt.subplots(figsize=COL)
for mode, x, y, place in PTS:
    st = STYLE[mode]
    ax.plot([x], [y], linestyle="", marker=st["marker"], color=st["color"],
            mfc=st["mfc"], markersize=5.5, zorder=4)
    text = NAME[mode]
    if mode == "reactive_replacement":
        text += "\n(median)"
    label(ax, text, xy=(x, y), color=st["color"], bold=(mode == "parity"), **place)

ax.set_xscale("log")
ax.set_xlim(0.2, 60)
ax.set_xticks([0.2, 0.5, 1, 2, 5, 10, 20, 50])
ax.set_xticklabels(["0.2", "0.5", "1", "2", "5", "10", "20", "50"])
ax.set_ylim(-1.5, 42)
ax.set_yticks([0, 10, 20, 30, 40])
ax.set_xlabel("recovery latency at $P=32$ (s)")
ax.set_ylabel("retained recovery state\n(kB per KV token)")
clean(ax, grid_axis="both")
fig.subplots_adjust(left=0.17, right=0.98, top=0.97, bottom=0.19)
save(fig, "fig_recovery_pareto")
