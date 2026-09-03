"""Offline reanalysis (no fleet): does a headroom heuristic rescue the
sequential place-then-reserve procedure where the joint search succeeds?

Runs decoupled (m=0), decoupled_margin (m=0.25, 0.5) and joint over a short cap
grid on a saved cluster snapshot. Usage:
    .venv/bin/python experiments/d29_margin_baseline.py <snapshot.json> <label> <caps_mb...>
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from experiments.d29_coupling_threshold import build_spec, decoupled, decoupled_margin, joint, MB

snap = json.loads(Path(sys.argv[1]).read_text()); label = sys.argv[2]
caps = [int(c) for c in sys.argv[3:]]
rows = []
for scope in ("pipeline", "fleet"):
    print(f"\n=== {label} scope={scope} ===")
    print(f"{'cap':>7} {'seq m=0':>8} {'seq m=.25':>10} {'seq m=.5':>9} {'joint':>6}")
    for cap in caps:
        spec = build_spec(snap, None if cap == 0 else cap * MB)
        d0 = decoupled(spec, scope)[2] is None
        d25 = decoupled_margin(spec, scope, 0.25)[2] is None
        d50 = decoupled_margin(spec, scope, 0.50)[2] is None
        j = joint(spec, scope)[2] is None
        ok = lambda b: "ok" if b else "FAIL"
        print(f"{(cap or 'uncap'):>7} {ok(d0):>8} {ok(d25):>10} {ok(d50):>9} {ok(j):>6}")
        rows.append({"label": label, "scope": scope, "cap_mb": cap, "seq_m0": d0, "seq_m25": d25, "seq_m50": d50, "joint": j})
out = Path("experiments/results") / f"d29_margin_baseline_{label}.json"
out.write_text(json.dumps(rows, indent=2)); print("wrote", out)
