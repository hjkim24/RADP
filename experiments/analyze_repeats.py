"""Summarize a --repeats sweep: pooled OLS fit with standard errors per mode,
per-repeat slopes (mean +- sd), and per-position mean +- sd of TTR.

    .venv/bin/python experiments/analyze_repeats.py experiments/results/b1_ft_fleet_7b_rep3.json
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict

from experiments.b1_ft_fleet import _linfit


def valid(t: dict) -> bool:
    m = t["mode"]
    fired = t.get("fired", t.get("v1_fired", False))
    if m == "reactive_replacement":
        return bool(fired and t.get("sequence_match") and t.get("reconfigured"))
    return bool(fired and t.get("recovery_visible", True) and t.get("sequence_match")
                and t.get(f"{m}_branch_ran", True))


def main(path: str) -> None:
    d = json.load(open(path))
    trials = d["trials"]
    by_mode: dict[str, list[dict]] = defaultdict(list)
    for t in trials:
        by_mode[t["mode"]].append(t)
    for mode, rows in by_mode.items():
        ok = [t for t in rows if valid(t)]
        print(f"\n== {mode}: {len(ok)}/{len(rows)} valid")
        if len(ok) < 3:
            continue
        f = _linfit([t["position"] for t in ok], [t["ttr_seconds"] for t in ok])
        print(f"  pooled fit: {f['intercept']*1e3:7.1f} ms (SE {f['intercept_se']*1e3:5.1f}) + "
              f"{f['slope']*1e3:7.2f} ms/pos (SE {f['slope_se']*1e3:5.2f})  n={len(ok)}")
        reps = defaultdict(list)
        for t in ok:
            reps[t.get("repeat", 0)].append(t)
        slopes = []
        for r, rr in sorted(reps.items()):
            if len(rr) >= 2:
                fr = _linfit([t["position"] for t in rr], [t["ttr_seconds"] for t in rr])
                slopes.append(fr["slope"] * 1e3)
        if len(slopes) > 1:
            print(f"  per-repeat slope: {statistics.mean(slopes):.2f} +- {statistics.stdev(slopes):.2f} ms/pos over {len(slopes)} repeats")
        byp = defaultdict(list)
        for t in ok:
            byp[t["position"]].append(t["ttr_seconds"])
        print("  per-position TTR (s): " + "  ".join(
            f"P={p}: {statistics.mean(v):.2f}" + (f"+-{statistics.stdev(v):.2f}" if len(v) > 1 else "")
            + f" (n={len(v)})" for p, v in sorted(byp.items())))


if __name__ == "__main__":
    main(sys.argv[1])
