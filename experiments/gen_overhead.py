"""Regenerate b1_ft_overhead.json: storage (replication_overhead) + steady-state
network shipping (shipping_overhead) + bandwidth from the measured decode rate.
Placement + rate come from the SAME parity execution (never mix runs)."""
from __future__ import annotations
import json
import re
import statistics
from pathlib import Path

from experiments._harness import RESULTS_DIR, replication_overhead, shipping_overhead
from radp.common.types import Stage, LayerIdx, DeviceId

# OPT-350M fp16 geometry (fixed for the B1 experiments).
N_HEADS, HEAD_DIM, ITEMSIZE = 16, 64, 2
MODEL = "facebook/opt-350m"


def parse_placement(s: str) -> list[Stage]:
    """'ao-2[1-15]/on-1[16-17]/...' -> [Stage(1,15,'ao-2'), ...]."""
    stages = []
    for part in s.split("/"):
        # Handle both ranges like [1-15] and single layers like [24]
        m = re.fullmatch(r"(.+?)\[(\d+)(?:-(\d+))?\]", part.strip())
        if not m:
            raise ValueError(f"bad placement segment: {part!r}")
        dev = m.group(1)
        a = int(m.group(2))
        b = int(m.group(3)) if m.group(3) else a
        stages.append(Stage(LayerIdx(a), LayerIdx(b), DeviceId(dev)))
    return stages


def median_tbt() -> float:
    d = json.loads((RESULTS_DIR / "b1_ft_fleet_parity.json").read_text())
    vals = [t["median_tbt_seconds"] for t in d["trials"]
            if t.get("sequence_match") and "median_tbt_seconds" in t]
    return statistics.median(vals)


def main() -> None:
    path = RESULTS_DIR / "b1_ft_overhead.json"
    existing = json.loads(path.read_text())
    placement = parse_placement(existing["placement"])
    storage = replication_overhead(placement, N_HEADS, HEAD_DIM, ITEMSIZE)
    ship = shipping_overhead(placement, N_HEADS, HEAD_DIM, ITEMSIZE)
    tbt = median_tbt()
    bandwidth = {f: b / tbt for f, b in ship["shipping_bytes_per_step"].items()}
    out = {
        "model": MODEL,
        "placement": existing["placement"],
        # storage
        "replicate_bytes": storage["replicate_bytes"],
        "parity_bytes": storage["parity_bytes"],
        "ratio": storage["ratio"],
        "per_stage": storage["per_stage"],
        # network (new)
        "input_mirror_bytes_per_step": ship["input_mirror_bytes_per_step"],
        "kv_column_bytes_per_step": ship["kv_column_bytes_per_step"],
        "shipping_bytes_per_step": ship["shipping_bytes_per_step"],
        "median_tbt_seconds": tbt,
        "bandwidth_bytes_per_s": bandwidth,
    }
    path.write_text(json.dumps(out, indent=2))
    print(f"wrote {path}")
    print(f"  parity/replicate ship {ship['shipping_bytes_per_step']['parity']} B/step "
          f"= {bandwidth['parity']/1024:.1f} KB/s")
    print(f"  surgical/full_replay/reactive ship {ship['shipping_bytes_per_step']['surgical']} "
          f"B/step = {bandwidth['surgical']/1024:.1f} KB/s")


if __name__ == "__main__":
    main()
