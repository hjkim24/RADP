"""2-D Pareto: recovery time at P=32 (x) vs steady-state storage (y). Only
KV-CARE sits in the low-TTR AND low-storage corner. TTR from measured JSON;
storage from computed overhead (state the split in the caption).

Reconfigure uses the 2026-08-30 client-observed re-measurement; because its
victim differs per P, its point is the MEDIAN over positions (24.25 s), not the
P=32 sample. The old ~53 s figure was a different wall-time definition."""
import json
import statistics
import sys
from pathlib import Path
import matplotlib.pyplot as plt
sys.path.insert(0, str(Path(__file__).parent))
from _slide import BODY, NAME, SLIDE_FULL, SUBJECT, save_slide, strip_chrome  # noqa: E402

RESULTS = Path(__file__).parent.parent.parent / "experiments" / "results"
par = json.load(open(RESULTS / "b1_ft_fleet_parity.json"))
rep = json.load(open(RESULTS / "b1_ft_fleet_replicate.json"))
ovh = json.load(open(RESULTS / "b1_ft_overhead.json"))  # {"replicate_bytes","parity_bytes",...}

def ttr_at(d, mode, P=32):
    xs = [t for t in d["trials"] if t["mode"] == mode and t["position"] == P
          and t.get("recovery_visible") and t["sequence_match"]
          and t.get(f"{mode}_branch_ran", True)]
    if not xs:
        return float("nan")
    return sum(t["ttr_seconds"] for t in xs) / len(xs)


def reactive_median(d):
    ys = [t["ttr_seconds"] for t in d["trials"]
          if t["mode"] == "reactive_replacement" and t["fired"]
          and t["sequence_match"] and t.get("reconfigured")]
    return statistics.median(ys) if ys else float("nan")

pts = [
    (NAME["full_replay"], ttr_at(par, "full_replay"), 0,                      SUBJECT["full_replay"], "o"),
    (NAME["surgical"],    ttr_at(par, "surgical"),    0,                      SUBJECT["surgical"],    "s"),
    (NAME["replicate"],   ttr_at(rep, "replicate"),   ovh["replicate_bytes"], SUBJECT["replicate"],   "D"),
    (NAME["parity"],      ttr_at(par, "parity"),      ovh["parity_bytes"],    SUBJECT["parity"],      "^"),
]

reactive_path = RESULTS / "b1_ft_fleet_reactive_client_interval_20260830.json"
if reactive_path.exists():
    rea = json.load(open(reactive_path))
    pts.append((NAME["reactive_replacement"], reactive_median(rea), 0,
                SUBJECT["reactive_replacement"], "v"))

fig, ax = plt.subplots(figsize=SLIDE_FULL)
# Log X: TTR spans 0.3 s (parity/replicate) to ~24 s (reactive) — 80x. On a
# linear axis reactive shoves the whole low-TTR cluster (where the parity-vs-
# replicate domination lives) into a sliver at x≈0. Log spreads all five so
# each is legible; Pareto dominance is scale-invariant, so the frontier reads
# the same. Y stays linear — full-replay and reactive store 0 bytes (log(0)).
for name, x, y, color, marker in pts:
    ax.scatter(x, y, s=140, color=color, marker=marker, zorder=3)
    # Recompute (5.6 s) and Reconfigure (24 s) sit on the same baseline; labels
    # to the right would collide, so both go centred ABOVE their marker.
    if name in (NAME["reactive_replacement"], NAME["full_replay"]):
        dx, dy, ha = 0, 12, "center"
    else:
        dx, dy, ha = 8, 6, "left"
    ax.annotate(name, xy=(x, y), xytext=(dx, dy), textcoords="offset points",
                color=color, fontsize=13, fontweight="bold", ha=ha)
ax.set_xlabel("recovery time at P=32  (s, log)")
ax.set_ylabel("steady-state storage  (bytes)")
ax.set_xscale("log")
ax.set_xlim(0.2, 60)
ax.set_xticks([0.2, 0.5, 1, 2, 5, 10, 20, 50])
ax.set_xticklabels(["0.2", "0.5", "1", "2", "5", "10", "20", "50"])
ax.set_ylim(0, None)
strip_chrome(ax)
ax.grid(True, axis="x", alpha=0.25)
ax.set_axisbelow(True)
fig.tight_layout()
save_slide(fig, "fig_recovery_2d")
