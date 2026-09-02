"""Fig. recovery latency vs failure position P — five recovery families (paper, B&W).

Data: experiments/results/b1_ft_fleet_parity.json (Recompute, Petals, KV-CARE),
b1_ft_fleet_replicate.json (DejaVu), and the 2026-08-30 client-observed
Reconfigure re-measurement. The four same-victim families get their fitted
line; Reconfigure's victim differs per P, so it is drawn as points plus its
median only (no slope claim). Log y so a flat line stays flat while the 100x
spread between KV-CARE and Reconfigure still fits.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _paper import COL_TALL, EMPH, GRAY, INK, LIGHT, NAME, RESULTS, STYLE, clean, label, save  # noqa: E402

MODEL = os.environ.get("RADP_FIG_MODEL", "350m")   # 350m (default) | 7b
if MODEL == "7b":
    # OPT-6.7B: canonical 3-family sweep + part-2 (DejaVu, k=2) + Reconfigure
    # (log-extracted n=2 run and the pinned-placement top-up run, when present)
    core = json.load(open(RESULTS / "b1_ft_fleet_7b.json"))
    p2 = json.load(open(RESULTS / "b1_ft_fleet_7b_part2.json"))
    rea_trials = []
    for name in ("b1_ft_fleet_7b_reactive_log_20260901.json", "b1_ft_fleet_7b_reactive_p2.json"):
        if (RESULTS / name).exists():
            rea_trials += json.load(open(RESULTS / name))["trials"]
    trials = core["trials"] + p2["trials"] + rea_trials
    fits = {**core["fits"], **p2["fits"]}
    fits.pop("reactive_replacement", None)     # median + band, never a fit
    ORDER = ["reactive_replacement", "full_replay", "surgical", "replicate", "raid6", "parity"]
    YLIM, YTICKS = (0.3, 900), [0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500]
    SUFFIX = "_7b"
else:
    par = json.load(open(RESULTS / "b1_ft_fleet_parity.json"))
    rep = json.load(open(RESULTS / "b1_ft_fleet_replicate.json"))
    rea = json.load(open(RESULTS / "b1_ft_fleet_reactive_client_interval_20260830.json"))
    trials = par["trials"] + rep["trials"] + rea["trials"]
    fits = {**par["fits"], **rep["fits"]}          # reactive fit deliberately excluded
    ORDER = ["reactive_replacement", "full_replay", "surgical", "replicate", "parity"]
    YLIM, YTICKS = (0.11, 60), [0.2, 0.5, 1, 2, 5, 10, 20, 50]
    SUFFIX = ""


def valid(t):
    m = t["mode"]
    if m == "reactive_replacement":
        return t["fired"] and t["sequence_match"] and t.get("reconfigured")
    fired = t.get("fired", t.get("v1_fired", False))   # raid6 rows carry v1/v2
    return (fired and t.get("recovery_visible", t.get("index_ok"))
            and t["sequence_match"] and t.get(f"{m}_branch_ran", True))


median_step = statistics.median(t["median_tbt_seconds"] for t in trials
                                if valid(t) and "median_tbt_seconds" in t)

fig, ax = plt.subplots(figsize=COL_TALL)
xline = np.linspace(0, 36, 50)
handles = []
for mode in ORDER:
    st = STYLE[mode]
    pts = sorted((t["position"], t["ttr_seconds"]) for t in trials
                 if t["mode"] == mode and valid(t))
    xs, ys = zip(*pts)
    if mode == "reactive_replacement":
        med = statistics.median(ys)
        # no fit (victim differs per P): draw the level as median + min–max band
        ax.axhspan(min(ys), max(ys), color=LIGHT, alpha=0.35, linewidth=0, zorder=1)
        ax.axhline(med, color=st["color"], linewidth=0.7, linestyle=(0, (1, 2)), zorder=2)
        text = f"{NAME[mode]} (median {med:.2f} s, band {min(ys):.2f}–{max(ys):.2f} s)"
        h, = ax.plot(xs, ys, linestyle="", marker=st["marker"], color=st["color"],
                     mfc=st["mfc"], zorder=4, label=text)
    else:
        f = fits[mode]
        slope_ms = f["slope"] * 1e3
        text = f"{NAME[mode]} ({slope_ms:.2f} ms/pos)" if slope_ms < 10 else \
               f"{NAME[mode]} ({slope_ms:.0f} ms/pos)"
        ax.plot(xline, f["intercept"] + f["slope"] * xline, linestyle=st["ls"],
                color=st["color"], linewidth=0.9, zorder=3)
        h, = ax.plot(xs, ys, linestyle="", marker=st["marker"], color=st["color"],
                     mfc=st["mfc"], zorder=4, label=text)
        # legend handle carries both the marker and the line style
        h.set_linestyle(st["ls"])
    handles.append(h)

# absolute anchor: one normal decode step
ax.axhline(median_step, color=INK, linewidth=0.5, linestyle=":", zorder=1)
label(ax, f"one decode step ({median_step*1e3:.0f} ms)", xy=(35.5, median_step),
      dy=-2, ha="right", va="top", color=INK, size=6)

ax.set_xlabel("failure position $P$ (tokens generated before the failure)")
ax.set_ylabel("recovery latency (s)")
ax.set_yscale("log")
ax.set_xlim(0, 36)
ax.set_ylim(*YLIM)
ax.set_xticks([0, 4, 8, 16, 24, 32])
ax.set_yticks(YTICKS)
ax.set_yticklabels([f"{v:g}" for v in YTICKS])
clean(ax)
leg = ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.2),
                ncol=2, columnspacing=1.0, handletextpad=0.5)
for t, h in zip(leg.get_texts(), handles):
    if h.get_label().startswith("KV-CARE"):
        t.set_color(EMPH)
fig.subplots_adjust(left=0.13, right=0.98, top=0.98, bottom=0.36)
save(fig, "fig_recovery_latency" + SUFFIX)
