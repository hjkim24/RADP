"""Slide version of the recovery TTR(P) figure (ppt/DESIGN_SYSTEM.md §7).

Same data as `make_recovery_ttr.py`, built at slide scale with the deck palette.

**"position", not "depth".** P is how far into the generation the crash
happened — the token index the victim died on — not how deep in the pipeline the
victim sat. We vary the victim's chain position separately, so the two must not
share a word.

**Log y-axis on purpose.** On a linear axis Recompute reaches 6 s and squashes
Petals and parity into the bottom 5% of the plot — the very contrast the
figure exists to show. Log keeps a flat line flat (parity's ~0 slope still reads
as flat) while letting all three separate. The normal-decode-step line gives the
audience an absolute anchor so the log axis can't overstate the win.

Display names (paper-facing, via _slide.NAME): Recompute (full_replay), Petals
(surgical), DejaVu (replicate), Reconfigure (reactive_replacement), KV-CARE
(parity). The lowercase keys below (STYLE, the dy dict) are the INTERNAL
recovery_mode identifiers that match the results-JSON ``t["mode"]`` strings and
must NOT be renamed — only the rendered labels come from NAME.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _slide import BODY, NAME, SLIDE_FULL, SUBJECT, save_slide  # noqa: E402

RESULTS = Path(__file__).parent.parent.parent / "experiments" / "results"

d = json.load(open(RESULTS / "b1_ft_fleet_parity.json"))
trials, fits = list(d["trials"]), dict(d["fits"])

# DejaVu (replicate) JSON lands after the controller-run fleet sweep (Task 6).
# Guard so this script still renders the 3-line parity figure until it exists.
replicate_path = RESULTS / "b1_ft_fleet_replicate.json"
if replicate_path.exists():
    rep = json.load(open(replicate_path))
    trials += rep["trials"]
    fits.update(rep["fits"])

# Reconfigure: the 2026-08-30 client-observed re-measurement (§B1-REACTIVE).
# The older b1_ft_fleet_reactive.json (~53 s) used a different wall-time
# definition and is a historical record only. The victim differs per P in this
# sweep, so its fit is NOT drawn — only the points, labelled by median + range.
reactive_path = RESULTS / "b1_ft_fleet_reactive_client_interval_20260830.json"
if reactive_path.exists():
    rea = json.load(open(reactive_path))
    trials += rea["trials"]

STYLE = {
    "full_replay": (SUBJECT["full_replay"], "o", NAME["full_replay"]),
    "surgical":    (SUBJECT["surgical"],    "s", NAME["surgical"]),
    "parity":      (SUBJECT["parity"],      "^", NAME["parity"]),
    "replicate":   (SUBJECT["replicate"],   "D", NAME["replicate"]),
    "reactive_replacement": (SUBJECT["reactive_replacement"], "v", NAME["reactive_replacement"]),
}


def valid(t):
    return (t["fired"]
            and (t.get("recovery_visible", t.get("index_ok"))
                 or t["mode"] == "reactive_replacement")
            and t["sequence_match"]
            and (t["mode"] != "parity" or t.get("parity_branch_ran"))
            and (t["mode"] != "replicate" or t.get("replicate_branch_ran"))
            and (t["mode"] != "reactive_replacement" or t.get("reconfigured")))


median_step = statistics.median(
    t["median_tbt_seconds"] for t in trials
    if valid(t) and "median_tbt_seconds" in t
)

fig, ax = plt.subplots(figsize=SLIDE_FULL)
xline = np.linspace(0, 36, 60)

# 정상 decode 스텝 = 절대 기준. 로그축이 차이를 과장하지 않게 붙잡아 준다.
ax.axhline(median_step, color=BODY, linewidth=1.1, linestyle=":", zorder=1)
ax.annotate(f"normal decode step  {median_step * 1e3:.0f} ms",
            xy=(0.4, median_step), xytext=(0, -6), textcoords="offset points",
            va="top", ha="left", fontsize=11, color=BODY)

for mode, (color, marker, label) in STYLE.items():
    pts = [(t["position"], t["ttr_seconds"]) for t in trials
           if t["mode"] == mode and valid(t)]
    if not pts:
        continue
    ax.plot([p for p, _ in pts], [y for _, y in pts], marker=marker,
            linestyle="none", color=color, zorder=4)
    f = fits.get(mode)
    if mode == "reactive_replacement":
        # victim differs per P (ao-2/on-6/on-6/on-1/on-1): no slope claim.
        ys = [y for _, y in pts]
        med = statistics.median(ys)
        ax.axhline(med, color=color, linewidth=1.4, linestyle=":", zorder=2)
        ax.annotate(f"{label}\nmedian {med:.2f} s\n({min(ys):.2f}\u2013{max(ys):.2f} s)",
                    xy=(36, med), xytext=(8, 0), textcoords="offset points",
                    va="center", ha="left", fontsize=12.5, color=color,
                    fontweight="bold", linespacing=1.4, annotation_clip=False)
        continue
    if not f or f["n_points"] < 2:
        continue
    ax.plot(xline, f["intercept"] + f["slope"] * xline, "--",
            color=color, linewidth=1.8, alpha=0.9, zorder=3)

    # 범례 대신 선 끝에 직접 이름을 붙인다. 눈이 범례와 선을 오갈 일이 없다.
    # parity/DejaVu 는 둘 다 평평해 선 끝(≈0.3s)에서 라벨이 겹친다 —
    # 세로로 살짝 벌려 둘 다 읽히게 한다 (offset points 로 픽셀 단위 이동).
    slope_ms = f["slope"] * 1e3
    tail = f["intercept"] + f["slope"] * 36
    # 오른쪽 아래는 Petals(0.83s)·parity·DejaVu(둘 다 ≈0.32s) 세 라벨이 몰린다.
    # Petals 바로 위(Recompute 6.2s까지)는 비어 있으므로 Petals 를 위로 올려 공간을
    # 내고, parity(위)·DejaVu(아래)를 그 밑에서 크게 벌린다 — 2줄 라벨이 안 겹치게.
    # (키는 내부 recovery_mode 식별자 — 유지; 표시 이름은 STYLE 의 NAME[...] 에서.)
    dy = {"surgical": 20, "parity": 16, "replicate": -28}.get(mode, 0)
    if slope_ms < 10:
        text = f"{label}\n{slope_ms:.2f} ms/pos"
    else:
        text = f"{label}\n{slope_ms:.0f} ms/pos"
    ax.annotate(text,
                xy=(36, tail), xytext=(8, dy), textcoords="offset points",
                va="center", ha="left", fontsize=12.5, color=color,
                fontweight="bold", linespacing=1.4, annotation_clip=False)

ax.set_xlabel("failure position  P   (tokens generated before the crash)")
ax.set_ylabel("recovery time (s, log)")
ax.set_yscale("log")
ax.set_xlim(0, 36)
# Reconfigure lands at 18.6–39.4 s — the axis must span from KV-CARE's ~0.3 s up
# to it, so the two-order-of-magnitude gap is the story the plot tells.
ax.set_ylim(0.12, 60)
ax.set_xticks([0, 8, 16, 24, 32])
ax.set_yticks([0.2, 0.5, 1, 2, 5, 10, 20, 50])
ax.set_yticklabels(["0.2", "0.5", "1", "2", "5", "10", "20", "50"])
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.grid(True, axis="y", alpha=0.3)
ax.set_axisbelow(True)

# 오른쪽에 이름표가 나가므로 그만큼 자리를 비운다 (tight_layout이 잘라먹지 않게)
fig.subplots_adjust(left=0.11, right=0.76, top=0.96, bottom=0.14)
save_slide(fig, "fig_recovery_ttr_slide")
