# FT overhead + fidelity metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two FT evaluation axes — steady-state network overhead (①) and cross-tier recovery bit-fidelity (②) — beyond the existing TTR × storage.

**Architecture:** ① is a pure arithmetic function (`shipping_overhead`) plus a generator that writes it into `b1_ft_overhead.json` using the already-measured decode rate — no fleet run, no coordinator change. ② is probe-first: a standalone script recomputes a fixed stage on ≥2 device tiers and bit-compares the KV, reporting whatever is true. The comparison logic is pure/unit-tested; the board-side forward is live.

**Tech Stack:** Python, PyTorch, transformers `DynamicCache`, numpy, pytest, ansible (fleet fan-out).

## Global Constraints

- No new recovery mechanism. No gateway/coordinator change for ①. ② touches only a standalone probe + read-only reuse of `radp.worker.stage_runner.StageRunner`.
- Model geometry OPT-350M: `n_heads=16, head_dim=64, hidden_dim = n_heads×head_dim = 1024`, fp16 `itemsize=2`. KV column = `n_layers × 2 × n_heads × head_dim × itemsize` = `n_layers × 4096 B`. Input mirror = `hidden_dim × itemsize` = `2048 B/stage`.
- Verified worker shipping gates: input mirror is always-on for every mode (`radp/worker/server.py:438-451`, gated only on `_mirror is not None` + `start_layer > 1` + `not replay_only`); KV column is `RADP_PARITY`-gated (`radp/worker/server.py:473-484`). So mirror is the shared baseline; the KV column is the delta parity/replicate pay on top.
- `experiments/results/*.json` are gitignored; figure PNG/PDF are tracked. Do NOT `git add` results JSON.
- Never mix runs: overhead placement and the `median_tbt` used for its bandwidth come from the same parity execution.
- Commit trailer on every commit:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FfKQPAstkv5E1GtvR5op9j
  ```
- Commits go on `main` (repo convention).

## File Structure

- `experiments/_harness.py` — add `shipping_overhead()` (sibling to `replication_overhead`, line 323).
- `experiments/gen_overhead.py` — NEW: parse deployed placement, compute storage+shipping, read `median_tbt`, write `b1_ft_overhead.json`.
- `experiments/fidelity_compare.py` — NEW: pure KV hash + bit-diff functions.
- `experiments/probe_recompute_fidelity.py` — NEW: board-mode forward + controller-mode fan-out/compare.
- `tests/test_shipping_overhead.py`, `tests/test_fidelity_compare.py` — NEW unit tests.
- `experiments/results/b1_ft_overhead.json` (regenerated), `experiments/results/b1_ft_fidelity.json` (new) — gitignored.
- `experiments/REPORT.md`, `PHASES.md`, `/Users/hjkim24/Obsidian/Brain/topics/radp-fault-tolerance.md` — write-ups.

---

### Task 1: `shipping_overhead()` pure function

**Files:**
- Modify: `experiments/_harness.py` (add after `replication_overhead`, ~line 345)
- Test: `tests/test_shipping_overhead.py`

**Interfaces:**
- Consumes: `Placement` (list of `radp.common.types.Stage`), same type `replication_overhead` takes. `Stage(LayerIdx, LayerIdx, DeviceId)` with `.start_layer`, `.end_layer`.
- Produces: `shipping_overhead(placement, n_heads, head_dim, itemsize) -> dict` with keys `input_mirror_bytes_per_step` (int), `kv_column_bytes_per_step` (int), `shipping_bytes_per_step` (dict of the 5 family names → int), `per_stage_kv` (list), `per_stage_mirror` (list).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_shipping_overhead.py
def test_shipping_overhead_families():
    from experiments._harness import shipping_overhead, replication_overhead
    from radp.common.types import Stage, DeviceId, LayerIdx
    # head [1..15] excluded; non-head layer counts 2,2,4,1 → 4 non-head stages
    placement = [
        Stage(LayerIdx(1),  LayerIdx(15), DeviceId("h")),
        Stage(LayerIdx(16), LayerIdx(17), DeviceId("a")),
        Stage(LayerIdx(18), LayerIdx(19), DeviceId("b")),
        Stage(LayerIdx(20), LayerIdx(23), DeviceId("c")),
        Stage(LayerIdx(24), LayerIdx(24), DeviceId("d")),
    ]
    # unit sizes: hidden_dim = n_heads*head_dim = 1; mirror/stage = 1; 4 stages → mirror=4
    # kv/stage = layers*2; Σ = (2+2+4+1)*2 = 18
    s = shipping_overhead(placement, n_heads=1, head_dim=1, itemsize=1)
    assert s["input_mirror_bytes_per_step"] == 4
    assert s["kv_column_bytes_per_step"] == 18
    sbs = s["shipping_bytes_per_step"]
    # parity == replicate (mirror + same KV columns)
    assert sbs["parity"] == sbs["replicate"] == 22
    # mirror-only families equal and NOT zero
    assert sbs["surgical"] == sbs["full_replay"] == sbs["reactive"] == 4
    # KV column is the parity−surgical delta
    assert sbs["parity"] - sbs["surgical"] == s["kv_column_bytes_per_step"]
    # KV column term matches replication_overhead's Σ (replicate_bytes)
    o = replication_overhead(placement, n_heads=1, head_dim=1, itemsize=1)
    assert s["kv_column_bytes_per_step"] == o["replicate_bytes"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_shipping_overhead.py -v`
Expected: FAIL — `ImportError: cannot import name 'shipping_overhead'`

- [ ] **Step 3: Write the implementation**

Add to `experiments/_harness.py` immediately after `replication_overhead`:

```python
def shipping_overhead(placement: Placement, n_heads: int, head_dim: int, itemsize: int) -> dict:
    """Steady-state worker->coord shipping bytes per decode step, per family.

    Two shipments, verified against radp/worker/server.py:
      - input mirror (activation, submit_mirror): ALWAYS-ON for every non-head
        stage in ANY mode (server.py:438-451, gated only on _mirror not None +
        start_layer>1 + not replay_only). hidden_dim*itemsize per stage.
      - KV column (MirrorKV, _maybe_push_parity_kv): RADP_PARITY-gated
        (server.py:473-484) -> parity/replicate only. Same per-stage KV column
        replication_overhead computes.

    So the mirror is the shared baseline; the KV column is the delta parity/
    replicate pay on top. surgical/full_replay/reactive ship the mirror only.
    """
    hidden_dim = n_heads * head_dim
    mirror = 0
    kv = 0
    per_stage_kv = []
    per_stage_mirror = []
    for stage in placement:
        if int(stage.start_layer) == 1:  # head is coord-sourced, ships nothing
            continue
        n_layers = int(stage.end_layer) - int(stage.start_layer) + 1
        stage_kv = n_layers * 2 * n_heads * head_dim * itemsize
        stage_mirror = hidden_dim * itemsize
        kv += stage_kv
        mirror += stage_mirror
        per_stage_kv.append(((int(stage.start_layer), int(stage.end_layer)), stage_kv))
        per_stage_mirror.append(((int(stage.start_layer), int(stage.end_layer)), stage_mirror))
    return {
        "input_mirror_bytes_per_step": mirror,
        "kv_column_bytes_per_step": kv,
        "shipping_bytes_per_step": {
            "full_replay": mirror,
            "reactive": mirror,
            "surgical": mirror,
            "parity": mirror + kv,
            "replicate": mirror + kv,
        },
        "per_stage_kv": per_stage_kv,
        "per_stage_mirror": per_stage_mirror,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_shipping_overhead.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add experiments/_harness.py tests/test_shipping_overhead.py
git commit  # message: "feat(harness): shipping_overhead — per-family steady-state network bytes"
```

---

### Task 2: `gen_overhead.py` — write shipping/bandwidth into b1_ft_overhead.json

**Files:**
- Create: `experiments/gen_overhead.py`
- Modify (regenerate, gitignored): `experiments/results/b1_ft_overhead.json`

**Interfaces:**
- Consumes: `experiments._harness.replication_overhead`, `experiments._harness.shipping_overhead` (Task 1), `radp.common.types.Stage/LayerIdx/DeviceId`.
- Reads the placement from the existing `b1_ft_overhead.json` `"placement"` string (format `ao-2[1-15]/on-1[16-17]/on-6[18-19]/ao-1[20-23]/on-2[24]`), and `median_tbt` from `b1_ft_fleet_parity.json` (median of `median_tbt_seconds` over trials with `sequence_match`).
- Produces: rewritten `b1_ft_overhead.json` with existing storage fields PLUS `shipping_bytes_per_step`, `input_mirror_bytes_per_step`, `kv_column_bytes_per_step`, `bandwidth_bytes_per_s` (dict per family), `median_tbt_seconds`.

- [ ] **Step 1: Write the script**

```python
# experiments/gen_overhead.py
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
        m = re.fullmatch(r"(.+?)\[(\d+)-(\d+)\]", part.strip())
        if not m:
            raise ValueError(f"bad placement segment: {part!r}")
        dev, a, b = m.group(1), int(m.group(2)), int(m.group(3))
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
```

- [ ] **Step 2: Run the generator**

Run: `.venv/bin/python -m experiments.gen_overhead`
Expected output (deployed placement, ~163 ms TBT): parity/replicate ship 45056 B/step ≈ 44 KB/s; surgical/full_replay/reactive ship 8192 B/step ≈ 8 KB/s. (44/8 KB/s here is per-request; exact numbers land from the run — do not assert specific KB/s, only that both lines print and parity > surgical.)

- [ ] **Step 3: Verify the JSON has the new fields**

Run:
```bash
.venv/bin/python -c "import json; d=json.load(open('experiments/results/b1_ft_overhead.json')); \
assert d['shipping_bytes_per_step']['parity']==d['shipping_bytes_per_step']['replicate']; \
assert d['shipping_bytes_per_step']['surgical']==d['shipping_bytes_per_step']['full_replay']==d['shipping_bytes_per_step']['reactive']; \
assert d['shipping_bytes_per_step']['parity']>d['shipping_bytes_per_step']['surgical']; \
assert d['kv_column_bytes_per_step']==d['replicate_bytes']; \
print('overhead JSON invariants OK')"
```
Expected: `overhead JSON invariants OK`

- [ ] **Step 4: Commit**

```bash
git add experiments/gen_overhead.py
# NOTE: b1_ft_overhead.json is gitignored — do NOT add it.
git commit  # message: "feat(overhead): gen_overhead — storage + network shipping + bandwidth"
```

---

### Task 3: `fidelity_compare.py` — pure KV bit-diff

**Files:**
- Create: `experiments/fidelity_compare.py`
- Test: `tests/test_fidelity_compare.py`

**Interfaces:**
- Produces: `kv_sha256(kv_bytes: bytes) -> str`; `compare_kv(a: bytes, b: bytes, np_dtype) -> dict` with keys `exact` (bool), `fraction_mismatched` (float), `max_abs_diff` (float). `np_dtype` is a numpy dtype (e.g. `np.float16`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fidelity_compare.py
import numpy as np


def test_identical_is_exact():
    from experiments.fidelity_compare import compare_kv, kv_sha256
    a = np.arange(12, dtype=np.float16).tobytes()
    assert kv_sha256(a) == kv_sha256(a)
    r = compare_kv(a, a, np.float16)
    assert r["exact"] is True
    assert r["fraction_mismatched"] == 0.0
    assert r["max_abs_diff"] == 0.0


def test_perturbed_reports_magnitude():
    from experiments.fidelity_compare import compare_kv
    a = np.zeros(10, dtype=np.float16)
    b = a.copy()
    b[3] = np.float16(2.0)  # one element differs by 2.0
    r = compare_kv(a.tobytes(), b.tobytes(), np.float16)
    assert r["exact"] is False
    assert r["fraction_mismatched"] == 0.1  # 1/10
    assert r["max_abs_diff"] == 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_fidelity_compare.py -v`
Expected: FAIL — `ModuleNotFoundError: experiments.fidelity_compare`

- [ ] **Step 3: Write the implementation**

```python
# experiments/fidelity_compare.py
"""Pure bit-fidelity comparison for recovered-vs-original KV dumps. No torch,
no fleet — just bytes in, verdict out. Used by probe_recompute_fidelity.py."""
from __future__ import annotations
import hashlib
import numpy as np


def kv_sha256(kv_bytes: bytes) -> str:
    return hashlib.sha256(kv_bytes).hexdigest()


def compare_kv(a: bytes, b: bytes, np_dtype) -> dict:
    """Bit-compare two KV byte dumps of the same shape/dtype. Exact iff bytes
    are identical; otherwise report the fraction of mismatched elements and the
    max absolute difference (in float64 to avoid fp16 overflow)."""
    if a == b:
        return {"exact": True, "fraction_mismatched": 0.0, "max_abs_diff": 0.0}
    xa = np.frombuffer(a, dtype=np_dtype).astype(np.float64)
    xb = np.frombuffer(b, dtype=np_dtype).astype(np.float64)
    if xa.size != xb.size:
        raise ValueError(f"KV size mismatch: {xa.size} vs {xb.size} — not a fidelity diff, a shape bug")
    mism = int(np.count_nonzero(xa != xb))
    return {
        "exact": False,
        "fraction_mismatched": mism / xa.size,
        "max_abs_diff": float(np.max(np.abs(xa - xb))),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_fidelity_compare.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add experiments/fidelity_compare.py tests/test_fidelity_compare.py
git commit  # message: "feat(fidelity): compare_kv/kv_sha256 — pure KV bit-diff"
```

---

### Task 4: `probe_recompute_fidelity.py` — cross-tier recompute probe (LIVE)

**Files:**
- Create: `experiments/probe_recompute_fidelity.py`
- Writes (gitignored): `experiments/results/b1_ft_fidelity.json`

**Interfaces:**
- Consumes: `radp.worker.stage_runner.StageRunner` (`load_primary(model_id, start, end)`, `run(request_id, activation_blob, *, start, end, is_prefill)`, `export_kv(request_id, *, start, end)`), `radp.common.tensor_io.encode`, `experiments.fidelity_compare.kv_sha256/compare_kv`, `radp.common.types.RequestId/LayerIdx/DeviceId`.
- Two modes selected by argparse: `--board` (run on one board, dump KV + print hash) and `--controller` (default: generate input once, fan out via ansible, collect, compare, write JSON).

**Constants (top of file):** `MODEL_ID="facebook/opt-350m"`, `STAGE=(16,17)` (a fixed 2-layer non-head stage), `SEQ=8`, `HIDDEN_DIM=1024`, `SEED=0`. Tier boards: `TIERS = {"cuda": "on-1", "cpu": "on-3", "agx": "ao-1"}`. Board runtime is read from env the board already sets (`RADP_TORCH_DEVICE`, `RADP_DTYPE`) so the probe uses the board's real device/dtype.

- [ ] **Step 1: Board mode — load stage, run fixed input, export KV, print hash**

```python
# experiments/probe_recompute_fidelity.py  (board-mode core)
import argparse, hashlib, json, os, subprocess, sys
from pathlib import Path

MODEL_ID = "facebook/opt-350m"
STAGE = (16, 17)
SEQ, HIDDEN_DIM, SEED = 8, 1024, 0
INPUT_FILE = "/tmp/radp_probe_input.pt"   # shipped identical to every board
DUMP_FILE = "/tmp/radp_probe_kv.bin"

def board_main() -> None:
    import torch
    from radp.worker.stage_runner import StageRunner
    from radp.common.tensor_io import encode
    from radp.common.types import RequestId, LayerIdx, DeviceId
    from experiments.fidelity_compare import kv_sha256

    device = os.environ.get("RADP_TORCH_DEVICE", "cpu")
    dtype = os.environ.get("RADP_DTYPE", "float16")
    dev_id = os.environ.get("RADP_DEVICE_ID", "probe")

    payload = torch.load(INPUT_FILE)   # {"hidden_states","attention_mask"} — identical bytes on every board
    runner = StageRunner(DeviceId(dev_id), torch_device=device, dtype=dtype)
    runner.load_primary(MODEL_ID, LayerIdx(STAGE[0]), LayerIdx(STAGE[1]))
    blob = encode(payload)
    runner.run(RequestId(1), blob, start=LayerIdx(STAGE[0]), end=LayerIdx(STAGE[1]), is_prefill=True)
    kv = runner.export_kv(RequestId(1), start=LayerIdx(STAGE[0]), end=LayerIdx(STAGE[1]))
    Path(DUMP_FILE).write_bytes(kv)
    print(json.dumps({"device": device, "dtype": dtype, "sha256": kv_sha256(kv), "n_bytes": len(kv)}))
```

**Risk note for the implementer:** `StageRunner.load_primary` + `run` must work standalone (off the worker gRPC server). If it needs worker-server context that isn't available, fall back to loading the two decoder layers directly via `AutoModelForCausalLM.from_pretrained(MODEL_ID).model.decoder.layers[15:17]` on the board device and running them on the same input — the goal is only "same layers, same input bytes, board's real device/dtype → KV bytes". Verify the standalone path first.

- [ ] **Step 2: Smoke board mode on one board**

Generate the input once (controller, CPU, fixed seed) and copy it to one board, then run board mode there. Run from repo root:
```bash
.venv/bin/python - <<'PY'
import torch
torch.manual_seed(0)
payload = {"hidden_states": torch.randn(1, 8, 1024, dtype=torch.float16),
           "attention_mask": torch.ones(1, 8, dtype=torch.long)}
torch.save(payload, "/tmp/radp_probe_input.pt")
print("input saved")
PY
cd deploy && ansible on-1 -m copy -a "src=/tmp/radp_probe_input.pt dest=/tmp/radp_probe_input.pt"
ansible on-1 -m shell -a "cd /home/isp/radp && .venv/bin/python -m experiments.probe_recompute_fidelity --board"
```
Expected: a JSON line with a stable `sha256`. Re-running on the SAME board must give the SAME hash (determinism check).

- [ ] **Step 3: Controller mode — fan out to ≥2 tiers, compare, write JSON**

```python
# experiments/probe_recompute_fidelity.py  (controller-mode core)
def controller_main(tier_hosts: dict[str, str]) -> None:
    import torch
    from radp.common.tensor_io import decode
    from experiments._harness import RESULTS_DIR
    from experiments.fidelity_compare import compare_kv
    import numpy as np

    # 1. generate the fixed input ONCE on CPU, save, ship identical bytes to each board
    torch.manual_seed(SEED)
    payload = {"hidden_states": torch.randn(1, SEQ, HIDDEN_DIM, dtype=torch.float16),
               "attention_mask": torch.ones(1, SEQ, dtype=torch.long)}
    torch.save(payload, INPUT_FILE)

    results = {}   # tier -> {sha256, device, dtype, dump_path}
    for tier, host in tier_hosts.items():
        _ansible(host, "-m", "copy", "-a", f"src={INPUT_FILE} dest={INPUT_FILE}")
        out = _ansible(host, "-m", "shell", "-a",
                       "cd /home/isp/radp && .venv/bin/python -m experiments.probe_recompute_fidelity --board")
        meta = json.loads(_last_json_line(out))
        local_dump = f"/tmp/radp_probe_kv_{tier}.bin"
        _ansible(host, "-m", "fetch", "-a", f"src={DUMP_FILE} dest={local_dump} flat=yes")
        meta["dump_path"] = local_dump
        results[tier] = meta

    # 2. compare each tier pair
    pairs = []
    tiers = list(results)
    for i in range(len(tiers)):
        for j in range(i + 1, len(tiers)):
            ta, tb = tiers[i], tiers[j]
            a = Path(results[ta]["dump_path"]).read_bytes()
            b = Path(results[tb]["dump_path"]).read_bytes()
            cmp = compare_kv(a, b, np.float16)
            pairs.append({"tier_a": ta, "tier_b": tb,
                          "hash_equal": results[ta]["sha256"] == results[tb]["sha256"], **cmp})

    diverges = any(not p["hash_equal"] for p in pairs)
    verdict = {
        "parity": "bit-exact (by construction)",
        "replicate": "bit-exact (by construction)",
        "surgical": "tier-dependent recompute" if diverges else "bit-exact (recompute, measured)",
        "full_replay": "tier-dependent recompute" if diverges else "bit-exact (recompute, measured)",
        "reactive": "tier-dependent recompute" if diverges else "bit-exact (recompute, measured)",
    }
    out = {"model": MODEL_ID, "stage": list(STAGE), "seq": SEQ,
           "tiers": {t: {k: results[t][k] for k in ("device", "dtype", "sha256")} for t in results},
           "pairs": pairs, "recompute_diverges": diverges, "family_verdict": verdict}
    (RESULTS_DIR / "b1_ft_fidelity.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({"recompute_diverges": diverges, "pairs": pairs}, indent=2))
```

Add these helpers + an `argparse` `main()` dispatching `--board`/`--controller` with `TIERS`:

```python
import subprocess
from pathlib import Path

_INVENTORY = str(Path(__file__).resolve().parent.parent / "deploy" / "inventory.ini")

def _ansible(host: str, *args: str) -> str:
    """Run `ansible <host> -i inventory.ini <args>` and return stdout (raises on
    non-zero). Mirrors experiments/b1_ft_fleet.py's _ansible invocation style."""
    cp = subprocess.run(
        ["ansible", host, "-i", _INVENTORY, *args],
        capture_output=True, text=True, timeout=300, check=True,
    )
    return cp.stdout

def _last_json_line(text: str) -> str:
    """The board prints one JSON line; ansible wraps it in banners. Return the
    last line that parses as JSON."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return line
    raise ValueError(f"no JSON line in ansible output:\n{text}")

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--board", action="store_true", help="run the forward on THIS board")
    p.add_argument("--controller", action="store_true", help="fan out to tiers + compare (default)")
    args = p.parse_args()
    if args.board:
        board_main()
    else:
        controller_main({"cuda": "on-1", "cpu": "on-3"})  # add "agx": "ao-1" if the first pair diverges

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the controller probe on 2 tiers**

Run: `.venv/bin/python -m experiments.probe_recompute_fidelity --controller`
Expected: prints `recompute_diverges` + per-pair `hash_equal`/`fraction_mismatched`/`max_abs_diff`; writes `b1_ft_fidelity.json`. CUDA(on-1)↔CPU(on-3) is the pair most likely to diverge.

- [ ] **Step 5: Commit**

```bash
git add experiments/probe_recompute_fidelity.py
# b1_ft_fidelity.json is gitignored — do NOT add it.
git commit  # message: "feat(fidelity): cross-tier recompute probe + per-family verdict"
```

---

### Task 5: Deliverables — REPORT / PHASES / wiki (after Task 2 & 4 numbers land)

**Files:**
- Modify: `experiments/REPORT.md`, `PHASES.md`, `/Users/hjkim24/Obsidian/Brain/topics/radp-fault-tolerance.md`

**Interfaces:**
- Consumes: `b1_ft_overhead.json` (Task 2 numbers), `b1_ft_fidelity.json` (Task 4 numbers). Read the ACTUAL numbers back from these files — do not retype from this plan.

- [ ] **Step 1: REPORT §B1-OVERHEAD**

Add a section after §B1-REACTIVE. Read the shipping/bandwidth numbers from `b1_ft_overhead.json`. Cover: per-family per-step shipping + bandwidth (table); the mirror is the always-on baseline paid by all five, the KV column is the parity/replicate delta; **frame the mirror as the price of the surgical fallback rung** (parity → surgical → full-replay cost ladder; only surgical consumes the mirror, parity/replicate only on fallback, full-replay/reactive never), and the `parity → full-replay` alternative that would drop the mirror at the cost of expensive fallbacks; tie to §B1-FIDELITY (a surgical fallback is a recompute, forfeiting bit-exactness). Add finding #14 to §11.

- [ ] **Step 2: REPORT §B1-FIDELITY**

Add a section. Read `b1_ft_fidelity.json`. State the probe result honestly: if `recompute_diverges` — parity/replicate bit-exact by construction vs recompute drifts cross-tier (magnitude), the new "correctness axis"; if not — all five bit-exact (recompute verified tier-invariant on this stack). Include the caveat: parity/replicate exactness is conditional on the primary branch (not the surgical fallback), gated by `parity_branch_ran`/`replicate_branch_ran`. Add finding #15.

- [ ] **Step 3: PHASES entries**

Append `## Phase B1-OVERHEAD` and `## Phase B1-FIDELITY` following the existing Phase-entry style (goal / 구현 / 검증 결과 / 의도된 한계), with the numbers from the JSONs.

- [ ] **Step 4: brain-wiki update**

Read `/Users/hjkim24/Obsidian/Brain/CLAUDE.md` schema first. Update `topics/radp-fault-tolerance.md`: add a metrics subsection (TTR, storage, **network overhead**, **fidelity**), the mirror-as-fallback-premium framing, and the fidelity result. Append a `log.md` entry. Do NOT manually commit the vault (its Stop hook auto-commits).

- [ ] **Step 5: Commit (repo docs only)**

```bash
git add experiments/REPORT.md PHASES.md
git commit  # message: "docs(b1): REPORT/PHASES — network overhead + recovery fidelity metrics"
```

---

## Notes on execution order

- Tasks 1 and 3 are pure/offline and can be done first (no fleet). Task 2 needs `b1_ft_overhead.json` + `b1_ft_fleet_parity.json` present (they are). Task 4 needs the fleet boards up (on-1 CUDA + on-3 CPU at minimum). Task 5 needs Task 2 and Task 4 outputs.
- The figure form for ① (network as a 3rd Pareto axis vs a standalone bar) is deliberately NOT in this plan — decide it after the Task 2/4 numbers land, as its own small follow-up.
