# Generate after the fleet replicate sweep produces b1_ft_fleet_replicate.json + b1_ft_overhead.json (controller-run).
# reactive point generated after the controller-run reactive sweep produces b1_ft_fleet_reactive.json
"""2-D Pareto: recovery time at P=32 (x) vs steady-state storage (y). Only
parity sits in the low-TTR AND low-storage corner. TTR from measured JSON;
storage from computed overhead (state the split in the caption)."""
import json
import sys
from pathlib import Path
import matplotlib.pyplot as plt
sys.path.insert(0, str(Path(__file__).parent))
from _slide import BODY, SLIDE_FULL, SUBJECT, save_slide, strip_chrome  # noqa: E402

RESULTS = Path(__file__).parent.parent.parent / "experiments" / "results"
par = json.load(open(RESULTS / "b1_ft_fleet_parity.json"))
rep = json.load(open(RESULTS / "b1_ft_fleet_replicate.json"))
ovh = json.load(open(RESULTS / "b1_ft_overhead.json"))  # {"replicate_bytes","parity_bytes",...}

def ttr_at(d, mode, P=32):
    xs = [t for t in d["trials"] if t["mode"] == mode and t["position"] == P
          and (t.get("recovery_visible") or mode == "reactive_replacement")
          and t["sequence_match"]
          and t.get(f"{mode}_branch_ran", True)
          and (mode != "reactive_replacement" or t.get("reconfigured"))]
    if not xs:
        return float("nan")
    return sum(t["ttr_seconds"] for t in xs) / len(xs)

pts = [
    ("full-replay", ttr_at(par, "full_replay"), 0,                      SUBJECT["full_replay"], "o"),
    ("surgical",    ttr_at(par, "surgical"),    0,                      SUBJECT["surgical"],    "s"),
    ("replicate",   ttr_at(rep, "replicate"),   ovh["replicate_bytes"], SUBJECT["replicate"],   "D"),
    ("parity",      ttr_at(par, "parity"),      ovh["parity_bytes"],    SUBJECT["parity"],      "^"),
]

# reactive JSON lands after the controller-run reactive sweep (Task 6). Guard
# so this script still renders the existing 4-point figure until it exists.
reactive_path = RESULTS / "b1_ft_fleet_reactive.json"
if reactive_path.exists():
    rea = json.load(open(reactive_path))
    pts.append(("reactive", ttr_at(rea, "reactive_replacement"), 0,
                SUBJECT["reactive_replacement"], "v"))

fig, ax = plt.subplots(figsize=SLIDE_FULL)
# Log X: TTR spans 0.3 s (parity/replicate) to ~53 s (reactive) — 170x. On a
# linear axis reactive shoves the whole low-TTR cluster (where the parity-vs-
# replicate domination lives) into a sliver at x≈0. Log spreads all five so
# each is legible; Pareto dominance is scale-invariant, so the frontier reads
# the same. Y stays linear — full-replay and reactive store 0 bytes (log(0)).
for name, x, y, color, marker in pts:
    ax.scatter(x, y, s=140, color=color, marker=marker, zorder=3)
    # reactive is the rightmost point — flip its label to the left so it does
    # not run off the axis; the others sit above-right of their marker.
    dx = -8 if name == "reactive" else 8
    ha = "right" if name == "reactive" else "left"
    ax.annotate(name, xy=(x, y), xytext=(dx, 6), textcoords="offset points",
                color=color, fontsize=13, fontweight="bold", ha=ha)
ax.set_xlabel("recovery time at P=32  (s, log)")
ax.set_ylabel("steady-state storage  (bytes)")
ax.set_xscale("log")
ax.set_xlim(0.2, 90)
ax.set_xticks([0.2, 0.5, 1, 2, 5, 10, 50])
ax.set_xticklabels(["0.2", "0.5", "1", "2", "5", "10", "50"])
ax.set_ylim(0, None)
strip_chrome(ax)
ax.grid(True, axis="x", alpha=0.25)
ax.set_axisbelow(True)
fig.tight_layout()
save_slide(fig, "fig_recovery_2d")
