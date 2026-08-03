# RAID-6 Double-Parity KV Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend cross-stage parity KV recovery from single-failure (RAID-5, one XOR blob) to double-failure (RAID-6, blobs P+Q over GF(2⁸)), runtime-toggleable via `RADP_PARITY_K`, then measure RAID-5 vs replicate vs RAID-6 on the fleet.

**Architecture:** A pure GF(2⁸) module supplies the field arithmetic and the 2-erasure solver. `ParityCache` gains a second blob Q (GF-weighted) maintained in lockstep with P when `k=2`. The gateway computes Q coordinator-side from the already-shipped KV columns (worker untouched) and, on a double failure, solves the 2×2 GF system per KV slot; a single failure still uses the P-only XOR path. Storage accounting and a fleet 2-victim measurement complete the RAID-5/replicate/RAID-6 comparison.

**Tech Stack:** Python 3.9 (`.venv-py39` for slow/model + gateway tests), numpy, PyTorch, gRPC, pytest.

## Global Constraints

- `RADP_PARITY_K` default `1` MUST reproduce today's RAID-5 path byte-for-byte (Q never allocated, `coeff_index` ignored, single-fault decode unchanged).
- Worker code is NOT modified. Q is folded coordinator-side from the same columns the worker already ships under `RADP_PARITY`.
- GF(2⁸): primitive polynomial `0x11d`, generator `g = 0x02`. Stage coefficient = `gⁱ`, i = 0-based rank of the stage among non-head stages sorted by `start_layer` (device-independent, stable across rewiring).
- k = 2 exactly. No general Reed-Solomon (k>2). >2 simultaneous dead stages → fall back to `_recover_surgical`.
- Never emit a wrong token: any doubt (P/Q incomplete, survivor geometry mismatch, >2 deaths, victim with no downstream survivor, missing mirror input) → `_recover_surgical` fallback.
- Recovered KV MUST be bit-exact to the original (GF reconstruction is integer/deterministic).
- `recovery_mode` enum and worker gates unchanged. `RADP_PARITY_K` is meaningful only when `RADP_RECOVERY_MODE=parity`.
- `experiments/results/*.json` are gitignored; figure PNG/PDF are tracked.
- Commit trailer (main-branch commits):
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FfKQPAstkv5E1GtvR5op9j
  ```

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `radp/coordinator/gf256.py` | GF(2⁸) tables, scalar/vector mul, pow, inv, 2-erasure solver | Create |
| `tests/test_gf256.py` | GF identities + 2-erasure solver bit-exact sweep | Create |
| `radp/coordinator/parity_cache.py` | add `k`, Q blob, `coeff_index`, `get_qparity` | Modify |
| `tests/test_parity_cache.py` | k=2 Q-blob correctness; k=1 regression | Modify |
| `radp/coordinator/gateway.py` | `parity_k` plumbing, coeff map, Q encoding in `record_kv`, `_gf_reconstruct_kv`, double-failure dispatch | Modify |
| `radp/coordinator/server.py` | read `RADP_PARITY_K`, pass to gateway | Modify |
| `tests/test_parity_recovery.py` | k=2 `record_kv` feeds P and Q (slow) | Modify |
| `tests/test_raid6_recovery.py` | in-process 2-victim double recovery bit-exact + output match (slow) | Create |
| `experiments/_harness.py` | `replication_overhead` returns `raid6_bytes` | Modify |
| `experiments/gen_overhead.py` | emit raid6 storage | Modify |
| `experiments/storage_scaling_models.py` | raid6 line + crossover note | Modify |
| `tests/test_shipping_overhead.py` | raid6 = 2× parity assertion | Modify |
| `paper/figures/make_storage_scaling_models.py` | raid6 line on the figure | Modify |
| `experiments/b1_ft_fleet.py` | `pick_two_interior_victims`, raid6 mode, 2-victim trial | Modify |
| `experiments/REPORT.md`, `PHASES.md`, brain-wiki | 3-way comparison write-up | Modify |

---

### Task 1: GF(2⁸) field module + 2-erasure solver

**Files:**
- Create: `radp/coordinator/gf256.py`
- Test: `tests/test_gf256.py`

**Interfaces:**
- Produces:
  - `GF_EXP: np.ndarray` (uint8, len 512), `GF_LOG: np.ndarray` (uint8, len 256)
  - `gf_mul(a: int, b: int) -> int`
  - `gf_pow(base: int, exp: int) -> int` (negative `exp` allowed)
  - `gf_inv(c: int) -> int`
  - `gf_mul_scalar(c: int, arr: np.ndarray) -> np.ndarray` (uint8 in, uint8 out)
  - `solve_two_erasures(pxy: np.ndarray, qxy: np.ndarray, x: int, y: int) -> tuple[np.ndarray, np.ndarray]` where `pxy = Dx^Dy`, `qxy = gˣ·Dx ^ gʸ·Dy`, `x < y`; returns `(Dx, Dy)` as uint8 arrays.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gf256.py
import numpy as np
import pytest
from radp.coordinator.gf256 import (
    gf_mul, gf_pow, gf_inv, gf_mul_scalar, solve_two_erasures,
)


def test_inverse_identity():
    for a in range(1, 256):
        assert gf_mul(a, gf_inv(a)) == 1


def test_pow_matches_iterated_mul():
    for e in range(0, 20):
        acc = 1
        for _ in range(e):
            acc = gf_mul(acc, 2)
        assert gf_pow(2, e) == acc


def test_pow_negative_is_inverse():
    for x in range(1, 16):
        assert gf_mul(gf_pow(2, x), gf_pow(2, -x)) == 1


def test_mul_scalar_matches_elementwise():
    arr = np.arange(256, dtype=np.uint8)
    out = gf_mul_scalar(3, arr)
    assert [int(v) for v in out] == [gf_mul(3, int(a)) for a in arr]
    assert out.dtype == np.uint8


def test_mul_scalar_zero_and_one():
    arr = np.array([0, 1, 2, 200, 255], dtype=np.uint8)
    assert list(gf_mul_scalar(0, arr)) == [0, 0, 0, 0, 0]
    assert list(gf_mul_scalar(1, arr)) == list(arr)


def test_solve_two_erasures_bit_exact_all_pairs():
    rng = np.random.default_rng(0)
    m = 8  # ranks 0..7
    dx_all = {i: rng.integers(0, 256, size=64, dtype=np.uint8) for i in range(m)}
    for x in range(m):
        for y in range(x + 1, m):
            Dx, Dy = dx_all[x], dx_all[y]
            pxy = Dx ^ Dy
            qxy = gf_mul_scalar(gf_pow(2, x), Dx) ^ gf_mul_scalar(gf_pow(2, y), Dy)
            rx, ry = solve_two_erasures(pxy, qxy, x, y)
            assert np.array_equal(rx, Dx), f"Dx mismatch at ({x},{y})"
            assert np.array_equal(ry, Dy), f"Dy mismatch at ({x},{y})"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_gf256.py -v`
Expected: FAIL — `ModuleNotFoundError: radp.coordinator.gf256`

- [ ] **Step 3: Write the implementation**

```python
# radp/coordinator/gf256.py
"""GF(2^8) arithmetic for RAID-6 double-parity KV recovery.

Primitive polynomial 0x11d (x^8+x^4+x^3+x^2+1), generator g=0x02 — the standard
RAID-6 field (H. P. Anvin, "The mathematics of RAID-6"). Pure numpy: log/exp
tables give byte-vector scalar multiply for the P (XOR) + Q (GF-weighted) folds
and the two-data-loss solver.
"""
from __future__ import annotations

import numpy as np

_POLY = 0x11D
_GEN = 0x02


def _build_tables() -> tuple[np.ndarray, np.ndarray]:
    exp = np.zeros(512, dtype=np.uint8)
    log = np.zeros(256, dtype=np.uint8)
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= _POLY
    for i in range(255, 512):  # duplicate so exp[a+b] never indexes out of range
        exp[i] = exp[i - 255]
    return exp, log


GF_EXP, GF_LOG = _build_tables()


def gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return int(GF_EXP[int(GF_LOG[a]) + int(GF_LOG[b])])


def gf_pow(base: int, exp: int) -> int:
    if base == 0:
        return 0
    return int(GF_EXP[(int(GF_LOG[base]) * exp) % 255])  # Python % is non-negative


def gf_inv(c: int) -> int:
    if c == 0:
        raise ZeroDivisionError("GF(2^8): 0 has no inverse")
    return int(GF_EXP[(255 - int(GF_LOG[c])) % 255])


def gf_mul_scalar(c: int, arr: np.ndarray) -> np.ndarray:
    """Multiply every byte of `arr` (uint8) by scalar `c` in GF(2^8)."""
    if c == 0:
        return np.zeros_like(arr)
    if c == 1:
        return arr.copy()
    out = np.zeros_like(arr)
    nz = arr != 0
    lc = int(GF_LOG[c])
    out[nz] = GF_EXP[lc + GF_LOG[arr[nz]].astype(np.uint16)]
    return out


def solve_two_erasures(
    pxy: np.ndarray, qxy: np.ndarray, x: int, y: int
) -> tuple[np.ndarray, np.ndarray]:
    """Recover (Dx, Dy) from pxy = Dx^Dy and qxy = g^x·Dx ^ g^y·Dy, x < y.

    Anvin §4:  A = g^(y-x)·(g^(y-x)^1)^-1,  B = g^(-x)·(g^(y-x)^1)^-1
               Dx = A·pxy ^ B·qxy,  Dy = pxy ^ Dx
    """
    if not x < y:
        raise ValueError(f"require x < y, got x={x}, y={y}")
    g_d = gf_pow(_GEN, y - x)
    denom_inv = gf_inv(g_d ^ 1)
    A = gf_mul(g_d, denom_inv)
    B = gf_mul(gf_pow(_GEN, -x), denom_inv)
    dx = gf_mul_scalar(A, pxy) ^ gf_mul_scalar(B, qxy)
    dy = pxy ^ dx
    return dx, dy
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_gf256.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add radp/coordinator/gf256.py tests/test_gf256.py
git commit -m "feat(raid6): GF(2^8) field + two-erasure solver"
```

---

### Task 2: ParityCache double-parity (Q blob)

**Files:**
- Modify: `radp/coordinator/parity_cache.py`
- Test: `tests/test_parity_cache.py`

**Interfaces:**
- Consumes: `gf_mul_scalar`, `gf_pow` from `radp.coordinator.gf256` (Task 1).
- Produces:
  - `ParityCache(num_stages, max_bytes=..., k: int = 1)`
  - `xor_in(request_id, stage_key, position, column_bytes, coeff_index: int = 0)`
  - `get_qparity(request_id, position) -> bytes | None`

- [ ] **Step 1: Write the failing test** (append to `tests/test_parity_cache.py`)

```python
def test_k2_maintains_q_blob():
    """k=2: P = XOR, Q = g^0·A ^ g^1·B (coeff_index = stage rank)."""
    import numpy as np
    from radp.coordinator.gf256 import gf_mul_scalar, gf_pow
    pc = ParityCache(num_stages=2, k=2)
    A, B = bytes([1, 2, 3, 4]), bytes([9, 8, 7, 6])
    pc.xor_in(_rid(1), (1, 2), 0, A, coeff_index=0)
    pc.xor_in(_rid(1), (3, 4), 0, B, coeff_index=1)
    assert pc.is_complete(_rid(1), 0)
    assert pc.get_parity(_rid(1), 0) == bytes(a ^ b for a, b in zip(A, B))
    an = np.frombuffer(A, np.uint8); bn = np.frombuffer(B, np.uint8)
    expect_q = gf_mul_scalar(gf_pow(2, 0), an) ^ gf_mul_scalar(gf_pow(2, 1), bn)
    assert pc.get_qparity(_rid(1), 0) == expect_q.tobytes()


def test_k1_has_no_q_blob():
    """Default k=1 keeps the RAID-5 path: no Q allocated."""
    pc = ParityCache(num_stages=2)  # k defaults to 1
    pc.xor_in(_rid(1), (1, 2), 0, bytes([1, 2]), coeff_index=0)
    assert pc.get_qparity(_rid(1), 0) is None


def test_k2_q_grows_zero_padded():
    """Unequal column lengths: Q grows/zero-pads in lockstep with P."""
    import numpy as np
    from radp.coordinator.gf256 import gf_mul_scalar, gf_pow
    pc = ParityCache(num_stages=2, k=2)
    big, small = bytes([1, 2, 3, 4, 5, 6]), bytes([10, 20])
    pc.xor_in(_rid(1), (1, 6), 0, big, coeff_index=0)
    pc.xor_in(_rid(1), (7, 8), 0, small, coeff_index=1)
    q = np.frombuffer(pc.get_qparity(_rid(1), 0), np.uint8)
    expect = (gf_mul_scalar(gf_pow(2, 0), np.frombuffer(big, np.uint8))
              ^ gf_mul_scalar(gf_pow(2, 1), np.frombuffer(small.ljust(6, b"\0"), np.uint8)))
    assert np.array_equal(q, expect)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_parity_cache.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'k'`

- [ ] **Step 3: Implement — edit `radp/coordinator/parity_cache.py`**

Add the import at the top (after `import numpy as np`):
```python
from radp.coordinator.gf256 import gf_mul_scalar, gf_pow
```

Replace `_Entry` with a k-aware version:
```python
class _Entry:
    __slots__ = ("parity", "q_parity", "contributors")

    def __init__(self, size: int, k: int) -> None:
        self.parity = np.zeros(size, dtype=np.uint8)
        self.q_parity = np.zeros(size, dtype=np.uint8) if k == 2 else None
        self.contributors: set[StageKey] = set()
```

Add `k` to `__init__`:
```python
    def __init__(
        self, num_stages: int, max_bytes: int = 256 * 1024 * 1024, k: int = 1
    ) -> None:
        self.num_stages = num_stages
        self.max_bytes = max_bytes
        self.k = k
        self._lock = threading.Lock()
        self._by_request: OrderedDict[RequestId, dict[int, _Entry]] = OrderedDict()
        self._bytes_used = 0
```

Replace `xor_in`:
```python
    def xor_in(
        self, request_id: RequestId, stage_key: StageKey,
        position: int, column_bytes: bytes, coeff_index: int = 0,
    ) -> None:
        col = np.frombuffer(column_bytes, dtype=np.uint8)
        with self._lock:
            positions = self._by_request.setdefault(request_id, {})
            self._by_request.move_to_end(request_id)
            entry = positions.get(position)
            if entry is None:
                entry = _Entry(col.size, self.k)
                positions[position] = entry
                self._bytes_used += col.size * self.k  # P (+ Q when k==2)
            if stage_key in entry.contributors:
                return  # dedup — never double-fold
            if col.size > entry.parity.size:  # grow both blobs, zero-padded
                grown = np.zeros(col.size, dtype=np.uint8)
                grown[: entry.parity.size] = entry.parity
                self._bytes_used += col.size - entry.parity.size
                entry.parity = grown
                if entry.q_parity is not None:
                    gq = np.zeros(col.size, dtype=np.uint8)
                    gq[: entry.q_parity.size] = entry.q_parity
                    self._bytes_used += col.size - entry.q_parity.size
                    entry.q_parity = gq
            entry.parity[: col.size] ^= col
            if entry.q_parity is not None:
                entry.q_parity[: col.size] ^= gf_mul_scalar(gf_pow(2, coeff_index), col)
            entry.contributors.add(stage_key)
            self._evict_if_needed_locked()
```

Add `get_qparity` after `get_parity`:
```python
    def get_qparity(self, request_id: RequestId, position: int) -> bytes | None:
        with self._lock:
            positions = self._by_request.get(request_id)
            if not positions or position not in positions:
                return None
            entry = positions[position]
            return entry.q_parity.tobytes() if entry.q_parity is not None else None
```

Update byte accounting in `evict_request` and `_evict_if_needed_locked` to count Q. Replace each `sum(e.parity.size for e in positions.values())` with:
```python
                sum(e.parity.size + (e.q_parity.size if e.q_parity is not None else 0)
                    for e in positions.values())
```
(both occurrences: `evict_request` and `_evict_if_needed_locked`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_parity_cache.py -v`
Expected: PASS — new k=2 tests plus all existing k=1 tests (regression gate).

- [ ] **Step 5: Commit**

```bash
git add radp/coordinator/parity_cache.py tests/test_parity_cache.py
git commit -m "feat(raid6): ParityCache double-parity Q blob (k=2)"
```

---

### Task 3: Gateway/server `parity_k` plumbing + Q encoding

**Files:**
- Modify: `radp/coordinator/gateway.py` (constructor `95-160`, `record_kv` `260-279`)
- Modify: `radp/coordinator/server.py` (`_ensure_gateway`, `520-531`)
- Test: `tests/test_parity_recovery.py` (`test_gateway_record_kv_feeds_parity`, `276-299`)

**Interfaces:**
- Consumes: `ParityCache(..., k=)` and `xor_in(..., coeff_index=)` (Task 2).
- Produces: `RequestGateway(..., parity_k: int = 1)`; `self._parity_coeff: dict[tuple[int,int], int]`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_parity_recovery.py`)

```python
def test_gateway_record_kv_feeds_p_and_q_when_k2():
    from radp.coordinator.gateway import RequestGateway
    from radp.common.types import Stage, LayerIdx, DeviceId
    from radp.coordinator.gf256 import gf_mul_scalar, gf_pow
    import numpy as np

    gw = RequestGateway(
        placement=[Stage(LayerIdx(1), LayerIdx(4), DeviceId("head")),
                   Stage(LayerIdx(5), LayerIdx(8), DeviceId("b")),
                   Stage(LayerIdx(9), LayerIdx(12), DeviceId("c"))],
        recovery={},
        worker_addresses={DeviceId("head"): "localhost:0",
                          DeviceId("b"): "localhost:0",
                          DeviceId("c"): "localhost:0"},
        model_id=MODEL,
        recovery_mode="parity",
        parity_k=2,
    )
    # non-head ranks by start_layer: (5,8)->0, (9,12)->1
    assert gw._parity_coeff == {(5, 8): 0, (9, 12): 1}
    A, B = bytes([1, 2]), bytes([3, 4])
    gw.record_kv(RequestId(1), 5, 8, 0, A)
    gw.record_kv(RequestId(1), 9, 12, 0, B)
    assert gw.parity_cache.get_parity(RequestId(1), 0) == bytes([1 ^ 3, 2 ^ 4])
    expect_q = (gf_mul_scalar(gf_pow(2, 0), np.frombuffer(A, np.uint8))
                ^ gf_mul_scalar(gf_pow(2, 1), np.frombuffer(B, np.uint8)))
    assert gw.parity_cache.get_qparity(RequestId(1), 0) == expect_q.tobytes()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest "tests/test_parity_recovery.py::test_gateway_record_kv_feeds_p_and_q_when_k2" -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'parity_k'`

- [ ] **Step 3: Implement**

In `radp/coordinator/gateway.py` `__init__` signature (after `recovery_mode: str = "full_replay",`):
```python
        parity_k: int = 1,
```
After the `recovery_mode` validation block, validate k:
```python
        if parity_k not in {1, 2}:
            raise ValueError(f"parity_k must be 1 or 2, got {parity_k!r}")
        self.parity_k = parity_k
```
Change the `ParityCache` construction (currently line 147) to pass k:
```python
        self.parity_cache = ParityCache(
            num_stages=max(len(placement) - 1, 0), k=parity_k
        )
```
After `self.parity_cache`/`self.replica_cache` are built, add the stable coeff map:
```python
        # gⁱ coefficient per non-head stage, i = 0-based rank by start_layer.
        # Device-independent, so it survives placement rewiring during recovery.
        non_head = sorted(
            (s for s in placement if int(s.start_layer) > 1),
            key=lambda s: int(s.start_layer),
        )
        self._parity_coeff = {
            (int(s.start_layer), int(s.end_layer)): i
            for i, s in enumerate(non_head)
        }
```

Replace `record_kv`'s parity branch (line 276-279) to pass the coefficient:
```python
        else:
            self.parity_cache.xor_in(
                RequestId(request_id), key, int(position), kv_bytes,
                coeff_index=self._parity_coeff.get(key, 0),
            )
```

In `radp/coordinator/server.py` `_ensure_gateway` (after the `recovery_mode` read at 520):
```python
                parity_k = int(os.environ.get("RADP_PARITY_K", "1"))
```
and pass `parity_k=parity_k,` into the `RequestGateway(...)` call, and extend the log line:
```python
                log.info("gateway recovery_mode=%s parity_k=%d", recovery_mode, parity_k)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_parity_recovery.py -k "record_kv" -v`
Expected: PASS — both the existing k=1 `test_gateway_record_kv_feeds_parity` and the new k=2 test.

- [ ] **Step 5: Commit**

```bash
git add radp/coordinator/gateway.py radp/coordinator/server.py tests/test_parity_recovery.py
git commit -m "feat(raid6): parity_k plumbing + Q encoding in record_kv"
```

---

### Task 4: Double-failure recovery (`_gf_reconstruct_kv` + dispatch)

**Files:**
- Modify: `radp/coordinator/gateway.py` (`_recover_parity` `1045-1289`; add `_gf_reconstruct_kv`)
- Test: `tests/test_raid6_recovery.py` (create)

**Interfaces:**
- Consumes: `solve_two_erasures`, `gf_mul_scalar`, `gf_pow` (Task 1); `parity_cache.get_qparity` (Task 2); `self._parity_coeff`, `self.parity_k` (Task 3); existing `_fetch_stage_kv`, `_slot_major_to_layer_major`, `_kv_dims`, `_rewire_chain`, `_invoke`, `promote_backup`, `load_kv`.
- Produces: double-failure branch inside `_recover_parity`; `_gf_reconstruct_kv(request_id, dead_keys, surv_ranks, surv_kv, n_slots, *, n_heads, head_dim, np_dtype, itemsize) -> dict[tuple[int,int], bytes]`.

**Design note for the implementer:** the single-failure path (`_recover_parity`, gateway.py:1045-1289) is your template. The novel piece is the per-slot GF math in `_gf_reconstruct_kv` below (fully specified). The plumbing — promote backup, `_rewire_chain`, `load_kv`, run the failed position live — is done ONCE per victim in the single path; for two victims, mirror the promote/rewire/install block (gateway.py:1234-1281) for BOTH dead stages, then run the failed position live ONCE from the upstream-most victim's backup (lowest `start_layer`) using its mirror history, exactly as the single path invokes `backup_stage` at 1284-1288.

- [ ] **Step 1: Write the failing test** (create `tests/test_raid6_recovery.py`)

```python
"""RAID-6 (k=2) double-failure KV recovery — two simultaneous non-head victims
reconstructed via P+Q GF solve, bit-exact, output matches the healthy reference.
Slow/model test — run under .venv-py39."""
import logging
import time

import numpy as np
import pytest
import torch

pytestmark = pytest.mark.slow

from experiments._harness import deploy, in_process_cluster_with_mirror, wire_chain
from radp.common.types import Stage as _Stage, LayerIdx, DeviceId, RequestId
from radp.coordinator.gateway import RequestGateway

MODEL = "facebook/opt-125m"


def _cfg5():
    """head + 4 non-head. Kill the two interior non-head stages (c, d): survivor
    b is UPSTREAM (one extra slot), survivor e is DOWNSTREAM (victim slot count).
    Ranks by start_layer: b=0, c=1, d=2, e=3."""
    ids = ["wa", "wb", "wc", "wd", "we"]
    placement = [
        _Stage(LayerIdx(1), LayerIdx(3), DeviceId("wa")),
        _Stage(LayerIdx(4), LayerIdx(6), DeviceId("wb")),
        _Stage(LayerIdx(7), LayerIdx(8), DeviceId("wc")),
        _Stage(LayerIdx(9), LayerIdx(10), DeviceId("wd")),
        _Stage(LayerIdx(11), LayerIdx(12), DeviceId("we")),
    ]
    recovery = {
        DeviceId("wa"): DeviceId("wb"), DeviceId("wb"): DeviceId("wc"),
        DeviceId("wc"): DeviceId("wa"), DeviceId("wd"): DeviceId("we"),
        DeviceId("we"): DeviceId("wa"),
    }
    return ids, placement, recovery


def _healthy_reference(prompt, n):
    ids, placement, recovery = _cfg5()
    with in_process_cluster_with_mirror(ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(placement=placement, recovery=recovery,
                            worker_addresses=addrs, model_id=MODEL)
        attach(gw)
        ref = list(gw.generate(prompt, max_tokens=n))
        gw.close()
    return ref


def _kv_layers(buf, n_layers, n_heads, head_dim, np_dtype):
    arr = np.frombuffer(buf, dtype=np_dtype)
    N = arr.size // (n_layers * 2 * n_heads * head_dim)
    arr = arr.reshape(n_layers, 2, n_heads, N, head_dim)
    return [(arr[li, 0], arr[li, 1]) for li in range(n_layers)]


def test_raid6_double_recovery_matches_reference(monkeypatch, caplog):
    monkeypatch.setenv("RADP_PARITY", "1")
    prompt, n, kill_at = "The quick brown fox", 12, 4
    reference = _healthy_reference(prompt, n)

    ids, placement, recovery = _cfg5()
    v1, v2 = "wc", "wd"                         # the two interior victims
    key1 = (7, 8)
    key2 = (9, 10)
    with in_process_cluster_with_mirror(ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(placement=placement, recovery=recovery,
                            worker_addresses=addrs, model_id=MODEL,
                            recovery_mode="parity", parity_k=2)
        attach(gw)
        gw.generate(prompt, max_tokens=2)       # warmup before the fault

        surgical = {"n": 0}
        orig_surgical = gw._recover_surgical
        def spy(*a, **k):
            surgical["n"] += 1
            return orig_surgical(*a, **k)
        gw._recover_surgical = spy

        # Snapshot both victims' KV, capture installs on both backups.
        installed = {}
        for bdev, dkey in [("wa", key1), ("we", key2)]:
            r = servers[DeviceId(bdev)].runner
            orig = r.install_kv
            def make(orig, dkey):
                def spy_install(request_id, *, start, end, kv_bytes, num_positions):
                    if (int(start), int(end)) == dkey:
                        installed[dkey] = bytes(kv_bytes)
                    return orig(request_id, start=start, end=end,
                                kv_bytes=kv_bytes, num_positions=num_positions)
                return spy_install
            r.install_kv = make(orig, dkey)

        rid = gw.new_request_id()
        c_runner = servers[DeviceId(v1)].runner
        orig_run = c_runner.run
        victim_kv = {}
        state = {"calls": 0, "tripped": False}

        def flaky_run(request_id, activation_blob, *, start, end, is_prefill):
            if int(request_id) == int(rid) and (int(start), int(end)) == key1:
                state["calls"] += 1
                if state["calls"] - 1 == kill_at and not state["tripped"]:
                    state["tripped"] = True
                    for dev, dkey in [(v1, key1), (v2, key2)]:
                        r = servers[DeviceId(dev)].runner
                        victim_kv[dkey] = r.export_kv(
                            rid, start=LayerIdx(dkey[0]), end=LayerIdx(dkey[1]))
                    # wait for both mirrors + full P/Q, then mark both dead & crash
                    deadline = time.time() + 8.0
                    n_slots = c_runner.kv_seq_len(
                        rid, start=LayerIdx(key1[0]), end=LayerIdx(key1[1]))
                    while time.time() < deadline and not (
                        len(gw.cache.get_history(rid, key1)) > kill_at
                        and len(gw.cache.get_history(rid, key2)) > kill_at
                        and all(gw.parity_cache.is_complete(rid, s)
                                for s in range(n_slots))):
                        time.sleep(0.01)
                    gw.mark_dead(DeviceId(v1))
                    gw.mark_dead(DeviceId(v2))
                    raise RuntimeError("simulated double crash wc+wd")
            return orig_run(request_id, activation_blob, start=start, end=end,
                            is_prefill=is_prefill)

        c_runner.run = flaky_run

        with caplog.at_level(logging.WARNING, logger="radp.coordinator.gateway"):
            gw._prefill(rid, prompt)
            for _ in range(1, n):
                gw._decode_step(rid)
        recovered = list(gw._requests[rid].generated_token_ids)
        gw._evict_everywhere(rid)
        n_heads, head_dim, np_dtype, _ = gw._kv_dims()
        gw.close()

    assert state["tripped"], "double fault never injected"
    assert surgical["n"] == 0, "RAID-6 fell back to surgical:\n" + caplog.text
    for dkey in (key1, key2):
        assert dkey in installed, f"no reconstructed install for {dkey}"
        n_layers = dkey[1] - dkey[0] + 1
        rec = _kv_layers(installed[dkey], n_layers, n_heads, head_dim, np_dtype)
        vic = _kv_layers(victim_kv[dkey], n_layers, n_heads, head_dim, np_dtype)
        for li, ((rk, rv), (vk, vv)) in enumerate(zip(rec, vic)):
            assert torch.equal(torch.from_numpy(rk.copy()), torch.from_numpy(vk.copy()))
            assert torch.equal(torch.from_numpy(rv.copy()), torch.from_numpy(vv.copy()))
    assert recovered == reference, f"recovered={recovered}\nreference={reference}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-py39/bin/python -m pytest tests/test_raid6_recovery.py -v -m slow`
Expected: FAIL — RAID-6 branch not implemented; either falls back to surgical (`surgical["n"] > 0`) or errors.

- [ ] **Step 3: Implement**

Add `_gf_reconstruct_kv` next to `_xor_reconstruct_kv` in `radp/coordinator/gateway.py`:
```python
    def _gf_reconstruct_kv(
        self,
        request_id: RequestId,
        dead_keys: list[tuple[int, int]],   # exactly 2, ordered by rank x<y
        surv: list[tuple[Stage, bytes, int]],  # (stage, layer-major bytes, rank)
        n_slots: int,
        *,
        n_heads: int,
        head_dim: int,
        np_dtype: Any,
        itemsize: int,
    ) -> dict[tuple[int, int], bytes]:
        """Reconstruct TWO dead non-head stages' LAYER-major KV via GF(2^8) P+Q.

        Per slot: Pxy = P ⊕ (XOR of survivor columns); Qxy = Q ⊕ (Σ g^rank·col);
        solve_two_erasures(Pxy, Qxy, x, y) → the two dead columns concatenated in
        rank order. Both dead stages share the same slot layout, but may differ in
        bytes-per-slot (different layer counts), so slice each victim's own bytes
        out of the solved column by its own geometry.
        """
        from radp.coordinator.gf256 import gf_mul_scalar, gf_pow, solve_two_erasures

        (x_key, y_key) = dead_keys
        x = self._parity_coeff[x_key]
        y = self._parity_coeff[y_key]
        x_bytes = (x_key[1] - x_key[0] + 1) * 2 * n_heads * head_dim * itemsize
        y_bytes = (y_key[1] - y_key[0] + 1) * 2 * n_heads * head_dim * itemsize

        # Survivor LAYER-major -> per-slot uint8 rows (same reshape/transpose as
        # _xor_reconstruct_kv), plus each survivor's rank for the Q accumulation.
        surv_rows: list[tuple[np.ndarray, int]] = []
        for stage, buf, rank in surv:
            n_l = int(stage.end_layer) - int(stage.start_layer) + 1
            arr = np.frombuffer(buf, dtype=np_dtype).reshape(n_l, 2, n_heads, -1, head_dim)
            slot_major = np.ascontiguousarray(
                np.transpose(arr, (3, 0, 1, 2, 4))[:n_slots])
            surv_rows.append((slot_major.reshape(n_slots, -1).view(np.uint8), rank))

        x_slots = np.empty((n_slots, x_bytes), dtype=np.uint8)
        y_slots = np.empty((n_slots, y_bytes), dtype=np.uint8)
        for slot in range(n_slots):
            p = self.parity_cache.get_parity(request_id, slot)
            q = self.parity_cache.get_qparity(request_id, slot)
            if p is None or q is None:
                raise RuntimeError(f"request={request_id} P/Q missing at slot {slot}")
            pxy = np.frombuffer(p, dtype=np.uint8).copy()
            qxy = np.frombuffer(q, dtype=np.uint8).copy()
            for rows, rank in surv_rows:
                col = rows[slot]
                pxy[: col.size] ^= col
                qxy[: col.size] ^= gf_mul_scalar(gf_pow(2, rank), col)
            dx, dy = solve_two_erasures(pxy, qxy, x, y)
            x_slots[slot] = dx[:x_bytes]
            y_slots[slot] = dy[:y_bytes]

        return {
            x_key: self._slot_major_to_layer_major(
                x_slots, x_key[1] - x_key[0] + 1, n_heads, head_dim, np_dtype),
            y_key: self._slot_major_to_layer_major(
                y_slots, y_key[1] - y_key[0] + 1, n_heads, head_dim, np_dtype),
        }
```

At the TOP of `_recover_parity` (right after `dead_stage = self._attribute_chain_failure(...)` and the head check, before the single-victim survivor gathering), branch to the double path when two non-head stages are dead and k==2:
```python
        # RAID-6 (k=2): if two non-head stages are dead, reconstruct both via P+Q.
        dead_nonhead = [
            s for s in self.placement
            if int(s.start_layer) > 1 and s.device in self._dead
        ]
        if self.parity_k == 2 and len(dead_nonhead) == 2:
            return self._recover_parity_double(
                request_id, head_stage, error, current_position, dead_nonhead
            )
        if self.parity_k == 2 and len(dead_nonhead) > 2:
            log.warning("request=%d RAID-6: >2 dead non-head stages; surgical",
                        request_id)
            return self._recover_surgical(request_id, head_stage, error, current_position)
```

Add `_recover_parity_double`. Mirror the single path's survivor-fetch, slot-geometry, completeness gate, and mirror-history checks (gateway.py:1145-1232) but over the TWO dead keys; then reconstruct with `_gf_reconstruct_kv`, promote+rewire+install BOTH backups (mirror 1234-1281 twice), and run the failed position live once from the upstream-most victim's backup (mirror 1282-1289). Concretely:
```python
    def _recover_parity_double(
        self, request_id, head_stage, error, current_position, dead_nonhead,
    ):
        # order the two victims by rank (start_layer); mark both dead defensively
        dead_nonhead = sorted(dead_nonhead, key=lambda s: int(s.start_layer))
        dead_keys = [(int(s.start_layer), int(s.end_layer)) for s in dead_nonhead]
        for s in dead_nonhead:
            if s.device not in self._dead:
                self.mark_dead(s.device)

        survivors = [
            s for s in self.current_plan()
            if int(s.start_layer) > 1
            and (int(s.start_layer), int(s.end_layer)) not in dead_keys
        ]
        if not survivors:
            log.warning("request=%d RAID-6: no non-head survivors; surgical", request_id)
            return self._recover_surgical(request_id, head_stage, error, current_position)

        n_heads, head_dim, np_dtype, itemsize = self._kv_dims()
        try:
            surv_kv = []
            for s in survivors:
                buf, _ = self._fetch_stage_kv(request_id, s, current_position)
                surv_kv.append((s, buf))
        except Exception:  # noqa: BLE001
            log.exception("request=%d RAID-6 survivor FetchKV failed; surgical", request_id)
            return self._recover_surgical(request_id, head_stage, error, current_position)

        # slot geometry — identical rule to the single path (min shared prefix)
        slot_counts = []
        for s, buf in surv_kv:
            n_l = int(s.end_layer) - int(s.start_layer) + 1
            bps = n_l * 2 * n_heads * head_dim * itemsize
            if bps == 0 or len(buf) % bps != 0:
                log.warning("request=%d RAID-6 survivor geometry bad; surgical", request_id)
                return self._recover_surgical(request_id, head_stage, error, current_position)
            slot_counts.append(len(buf) // bps)
        if max(slot_counts) - min(slot_counts) > 1:
            log.warning("request=%d RAID-6 survivor slot spread >1; surgical", request_id)
            return self._recover_surgical(request_id, head_stage, error, current_position)
        n_slots = min(slot_counts)
        if n_slots == 0:
            return self._recover_surgical(request_id, head_stage, error, current_position)
        for slot in range(n_slots):
            if not self.parity_cache.is_complete(request_id, slot):
                log.warning("request=%d RAID-6 parity incomplete slot %d; surgical",
                            request_id, slot)
                return self._recover_surgical(request_id, head_stage, error, current_position)

        # both victims need a mirrored input at the failed position to run live;
        # we enter the chain at the upstream-most victim.
        up_key = dead_keys[0]
        history = self.cache.get_history(request_id, up_key)
        if len(history) <= current_position:
            log.warning("request=%d RAID-6 mirror history short; surgical", request_id)
            return self._recover_surgical(request_id, head_stage, error, current_position)

        # promote + rewire BOTH backups
        for s in dead_nonhead:
            backup_dev = self.recovery.get(s.device)
            if backup_dev is None or self.worker_addresses.get(backup_dev) is None:
                raise RuntimeError(f"no recovery/address for dead device {s.device}")
            with WorkerClient(self.worker_addresses[backup_dev]) as client:
                client.promote_backup(for_device_id=s.device)
        self._rewire_chain()

        surv_ranked = [
            (s, buf, self._parity_coeff[(int(s.start_layer), int(s.end_layer))])
            for s, buf in surv_kv
        ]
        recon = self._gf_reconstruct_kv(
            request_id, dead_keys, surv_ranked, n_slots,
            n_heads=n_heads, head_dim=head_dim, np_dtype=np_dtype, itemsize=itemsize,
        )
        for dkey in dead_keys:
            backup_stage = next(
                (s for s in self.current_plan()
                 if (int(s.start_layer), int(s.end_layer)) == dkey), None)
            if backup_stage is None:
                raise RuntimeError(f"layer range {dkey} absent from post-recovery plan")
            with WorkerClient(self.worker_addresses[backup_stage.device]) as client:
                client.load_kv(request_id=request_id, start_layer=dkey[0],
                               end_layer=dkey[1], kv_bytes=recon[dkey],
                               num_positions=n_slots)

        log.warning("request=%d RAID-6 reconstruct: victims=%s slots=%d, run pos %d live",
                    request_id, dead_keys, n_slots, current_position)
        entry_stage = next(
            s for s in self.current_plan()
            if (int(s.start_layer), int(s.end_layer)) == up_key)
        last_resp = self._invoke(
            entry_stage, request_id, history[current_position],
            is_prefill=(current_position == 0), position=current_position,
            replay_only=False,
        )
        return entry_stage, last_resp
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv-py39/bin/python -m pytest tests/test_raid6_recovery.py -v -m slow`
Expected: PASS — double fault fires, RAID-6 branch runs (no surgical fallback), both KVs bit-exact, output matches reference.
Then regression: `.venv-py39/bin/python -m pytest tests/test_parity_recovery.py -v -m slow`
Expected: PASS — single-failure RAID-5 path unchanged.

- [ ] **Step 5: Commit**

```bash
git add radp/coordinator/gateway.py tests/test_raid6_recovery.py
git commit -m "feat(raid6): double-failure P+Q reconstruction + dispatch"
```

---

### Task 5: Storage accounting (raid6 = 2× parity)

**Files:**
- Modify: `experiments/_harness.py` (`replication_overhead`, `323-343`)
- Modify: `experiments/gen_overhead.py` (`main`, emit raid6)
- Modify: `experiments/storage_scaling_models.py` (`main`, raid6 column)
- Test: `tests/test_shipping_overhead.py`

**Interfaces:**
- Produces: `replication_overhead(...)` return dict gains `"raid6_bytes"` (= 2 × `parity_bytes`).

- [ ] **Step 1: Write the failing test** (append to `tests/test_shipping_overhead.py`)

```python
def test_replication_overhead_reports_raid6():
    from experiments._harness import replication_overhead
    from radp.common.types import Stage, LayerIdx, DeviceId
    placement = [
        Stage(LayerIdx(1), LayerIdx(4), DeviceId("head")),   # head, not stored
        Stage(LayerIdx(5), LayerIdx(8), DeviceId("b")),      # 4 layers
        Stage(LayerIdx(9), LayerIdx(10), DeviceId("c")),     # 2 layers
    ]
    r = replication_overhead(placement, n_heads=16, head_dim=64, itemsize=2)
    # parity = max stage = 4 layers; raid6 = two blobs of that width
    assert r["raid6_bytes"] == 2 * r["parity_bytes"]
    # raid6 still < replicate when non-head stages >= 3; here 2 stages -> raid6 >= replicate
    assert r["replicate_bytes"] == r["per_stage"][0][1] + r["per_stage"][1][1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_shipping_overhead.py::test_replication_overhead_reports_raid6 -v`
Expected: FAIL — `KeyError: 'raid6_bytes'`

- [ ] **Step 3: Implement — edit `experiments/_harness.py` `replication_overhead` return dict**

Add one key to the returned dict (after `"parity_bytes": biggest,`):
```python
        "raid6_bytes": 2 * biggest,   # P blob + Q blob, each sized to max stage
```

Edit `experiments/gen_overhead.py` `main`, add to the `out` dict (after `"parity_bytes": storage["parity_bytes"],`):
```python
        "raid6_bytes": storage["raid6_bytes"],
```
and after the existing print lines add:
```python
    print(f"  storage: parity {storage['parity_bytes']} B  raid6 {storage['raid6_bytes']} B  "
          f"replicate {storage['replicate_bytes']} B/token")
```

Edit `experiments/storage_scaling_models.py` `main`: in the per-model "replicate vs parity" loop (the `s = 2048` block), add a raid6 column:
```python
        raid6 = full * 2 / N
        print(f"  {name:10} replicate {human(rep):>8}  raid6 {human(raid6):>8}  "
              f"parity {human(par):>8}  gap(rep-raid6) {human(rep-raid6):>8}")
```
and after that loop add the crossover note:
```python
    print(f"\n# raid6 (2 blobs) < replicate ({N-1} blobs) requires non-head stages > 2; "
          f"at non-head <= 2 raid6 >= replicate (no storage win).")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_shipping_overhead.py -v`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add experiments/_harness.py experiments/gen_overhead.py experiments/storage_scaling_models.py tests/test_shipping_overhead.py
git commit -m "feat(raid6): storage accounting (2x parity) across harness + gen"
```

---

### Task 6: Storage-scaling figure — raid6 line

**Files:**
- Modify: `paper/figures/make_storage_scaling_models.py`

**Interfaces:**
- Consumes: `GAP_FRAC` geometry already in the figure script.

- [ ] **Step 1: Add the raid6 reference line**

In `paper/figures/make_storage_scaling_models.py`, after the per-model replicate-minus-parity plotting loop, add a raid6-vs-replicate gap band for the balanced N=5 case. Insert before `save_slide(...)`:
```python
# raid6 keeps 2/N vs replicate (N-1)/N -> gap (N-3)/N (dashed, model-agnostic ref
# using the largest plotted model so it sits in range).
RAID6_GAP_FRAC = (N - 3) / N   # replicate - raid6, balanced N=5 -> 2/5
Lb, kvhb, hdb = MODELS[PLOT[-1]]
full_tok_b = Lb * per_layer_token_bytes(kvhb, hdb)
ax.plot(CTX, full_tok_b * RAID6_GAP_FRAC * CTX, linestyle="--", color="#888888",
        linewidth=1.8, label=f"{PLOT[-1]} raid6 gap", zorder=2)
```
and re-call the legend so the new label shows (the existing `ax.legend(...)` line already runs after; if it runs before, move the raid6 plot above it).

- [ ] **Step 2: Regenerate the figure**

Run: `.venv/bin/python paper/figures/make_storage_scaling_models.py`
Expected: writes `fig_storage_scaling_models.{png,pdf}` with the dashed raid6 line below the replicate-minus-parity lines.

- [ ] **Step 3: Commit**

```bash
git add paper/figures/make_storage_scaling_models.py paper/figures/fig_storage_scaling_models.png paper/figures/fig_storage_scaling_models.pdf
git commit -m "feat(raid6): storage-scaling figure raid6 gap line"
```

---

### Task 7: Fleet driver — raid6 mode + two-victim injection

**Files:**
- Modify: `experiments/b1_ft_fleet.py` (add `pick_two_interior_victims`; raid6 mode in `run`/`main`; a `run_raid6_trial`)
- Test: `tests/test_b1_ft_fleet_selection.py` (create — pure selector unit test)

**Interfaces:**
- Consumes: `fetch_placement`, `mark_device_dead`, `clear_all_failures`, `reconfigure_over_survivors`, `set_recovery_mode`, `set_worker_parity` (all exist in `b1_ft_fleet.py`).
- Produces: `pick_two_interior_victims(placement: list[dict]) -> list[tuple[str, int, int]]` (two interior non-head stages, excluding head and last, ordered by start layer).

- [ ] **Step 1: Write the failing test** (create `tests/test_b1_ft_fleet_selection.py`)

```python
"""Pure selector logic for the RAID-6 two-victim fleet trial — no fleet needed."""
from experiments.b1_ft_fleet import pick_two_interior_victims


def _pl(*ranges):
    # each range = (device, start, end); mimic fetch_placement's dict shape
    return [{"device": d, "start_layer": s, "end_layer": e} for d, s, e in ranges]


def test_picks_two_interior_non_head_stages():
    pl = _pl(("h", 1, 5), ("b", 6, 10), ("c", 11, 15), ("d", 16, 20), ("e", 21, 24))
    picks = pick_two_interior_victims(pl)
    devs = [p[0] for p in picks]
    assert devs == ["b", "c"]          # first two interior (exclude head h and last e)
    assert all(p[1] > 1 for p in picks) # never the head
    assert "e" not in devs             # never the last stage


def test_raises_when_too_few_stages():
    import pytest
    pl = _pl(("h", 1, 5), ("b", 6, 10), ("last", 11, 24))  # only 1 interior
    with pytest.raises(ValueError):
        pick_two_interior_victims(pl)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_b1_ft_fleet_selection.py -v`
Expected: FAIL — `ImportError: cannot import name 'pick_two_interior_victims'`

- [ ] **Step 3: Implement — add to `experiments/b1_ft_fleet.py`**

Next to `pick_interior_victim` (line 239):
```python
def pick_two_interior_victims(placement: list[dict]) -> list[tuple[str, int, int]]:
    """Two interior non-head victims for a RAID-6 double-failure trial: exclude
    the head (start_layer == 1) and the LAST stage (no downstream non-head
    survivor → parity gate would fall back). Returns the first two, ordered by
    start layer. Raises ValueError if fewer than two interior stages exist."""
    ordered = sorted(placement, key=lambda s: int(s["start_layer"]))
    interior = [s for s in ordered[:-1] if int(s["start_layer"]) > 1]
    if len(interior) < 2:
        raise ValueError(
            f"need >=2 interior non-head stages for RAID-6, got {len(interior)}"
        )
    return [(s["device"], int(s["start_layer"]), int(s["end_layer"]))
            for s in interior[:2]]
```

Add a `raid6` trial that reuses the injection helpers (model on `run_reactive_replacement_trial`, lines 425-490): it sets `RADP_RECOVERY_MODE=parity` + `RADP_PARITY_K=2` on the coordinator drop-in, arms worker parity, restarts, then per position marks BOTH victims dead and times the recovered step. Add a `set_parity_k(coord_host, k)` helper mirroring `set_recovery_mode` (writes `Environment=RADP_PARITY_K={k}` into the coordinator drop-in), and register `"raid6"` in the `--modes` handling so `run()` dispatches to the double-victim trial. Keep single-failure modes untouched.

- [ ] **Step 4: Run the selector test**

Run: `.venv/bin/python -m pytest tests/test_b1_ft_fleet_selection.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add experiments/b1_ft_fleet.py tests/test_b1_ft_fleet_selection.py
git commit -m "feat(raid6): fleet two-victim injection + raid6 mode driver"
```

- [ ] **Step 6: LIVE FLEET RUN (manual, not a unit test)**

With the 7-worker fleet up, run the RAID-6 double-failure trial and the RAID-5-with-2-victims contrast, writing `experiments/results/b1_ft_raid6.json`:
```bash
.venv/bin/python experiments/b1_ft_fleet.py --modes raid6 --positions 4,8,16,24,32 --out b1_ft_raid6
```
Confirm from the coordinator log that the `RAID-6 reconstruct` branch ran (not surgical) for each position, and that a RAID-5 (k=1) 2-victim run falls back to surgical/full-replay. Record the TTR curve. (This step produces the numbers Task 8 writes up; the JSON is gitignored.)

---

### Task 8: Documentation — 3-way comparison

**Files:**
- Modify: `experiments/REPORT.md` (add §B1-RAID6 + a findings entry)
- Modify: `PHASES.md` (add Phase B1-RAID6)
- Modify: brain-wiki `topics/radp-fault-tolerance.md` (+ `log.md`) under `/Users/hjkim24/Obsidian/Brain`

**Interfaces:** consumes `experiments/results/b1_ft_raid6.json` (Task 7 live run) and the storage numbers from Task 5.

- [ ] **Step 1: Write REPORT §B1-RAID6**

Add a section presenting the 3-way comparison from the ACTUAL measured/geometry numbers (read them back from `b1_ft_raid6.json` and the `gen_overhead` output — never retype from memory):

| family | single-failure TTR | double-failure TTR | steady-state storage | failure tolerance |
|---|---|---|---|---|
| RAID-5 (parity, k=1) | measured | falls back (surgical/full-replay) | 1 blob (max stage) | 1 |
| replicate | measured | measured | Σ non-head (N-1 blobs) | any |
| RAID-6 (parity, k=2) | measured (P path) | measured (P+Q solve) | 2 blobs (max stage ×2) | 2 |

State the storage crossover honestly: raid6 beats replicate only when non-head stages > 2 (our fleet has 4). Add a findings entry (`#16`) summarizing "RAID-6 buys 2-failure tolerance at O(1) storage; single-failure identical to RAID-5."

- [ ] **Step 2: PHASES entry**

Append a `Phase B1-RAID6` section per the repo's PHASES convention (goal, what shipped, files, result), noting the `RADP_PARITY_K` toggle and the live 2-victim measurement.

- [ ] **Step 3: brain-wiki update**

Per the brain-wiki skill: read `/Users/hjkim24/Obsidian/Brain/CLAUDE.md`, then update `topics/radp-fault-tolerance.md` with the RAID-6 metric (P+Q, 2-failure, O(1)) and append to `log.md`. Do NOT manually commit the vault (its Stop hook auto-commits).

- [ ] **Step 4: Commit (repo docs only)**

```bash
git add experiments/REPORT.md PHASES.md
git commit -m "docs(raid6): 3-way RAID-5/replicate/RAID-6 comparison + PHASES"
```

---

## Self-Review

**1. Spec coverage:**
- GF(2⁸) module + solver → Task 1 ✓
- Q blob in ParityCache (k, coeff_index, get_qparity) → Task 2 ✓
- `RADP_PARITY_K` toggle + Q encoding + coeff map → Task 3 ✓
- Double-failure `_gf_reconstruct_kv` + dispatch + fallbacks → Task 4 ✓
- Single-failure reuses P path (RAID-6 contains RAID-5) → Task 4 dispatch (len==1 falls through to existing path) + regression run ✓
- Storage accounting raid6 = 2× parity → Task 5 ✓
- Storage-scaling figure → Task 6 ✓
- Fleet 2-victim measurement → Task 7 ✓
- REPORT/PHASES/brain-wiki 3-way comparison → Task 8 ✓
- Backward-compat (k=1 byte-for-byte) → Global Constraints + Task 2/3 regression gates ✓
- Worker untouched → no worker file in the file map ✓

**2. Placeholder scan:** No TBD/TODO. Every code step carries real code. Task 4's plumbing points at concrete existing line ranges to mirror (not "similar to Task N"); the novel GF math is fully written. Task 7 Step 3's `set_parity_k`/mode-registration and Task 8's prose are the two prose-described steps — both are mechanical extensions of named existing functions with exact env strings given, acceptable for an experiment driver and a write-up.

**3. Type consistency:**
- `gf_mul_scalar(c, arr)`, `gf_pow(base, exp)`, `solve_two_erasures(pxy, qxy, x, y)` — same signatures in Tasks 1, 2, 4 ✓
- `ParityCache(num_stages, max_bytes, k)` + `xor_in(..., coeff_index)` + `get_qparity` — consistent Tasks 2, 3, 4 ✓
- `_parity_coeff: dict[(int,int)->int]`, `parity_k: int` — set in Task 3, read in Task 4 ✓
- `_gf_reconstruct_kv(request_id, dead_keys, surv, n_slots, *, n_heads, head_dim, np_dtype, itemsize) -> dict[(int,int)->bytes]` — defined and called in Task 4 ✓
- `replication_overhead(...)["raid6_bytes"]` — produced Task 5, consumed Task 8 ✓
- `pick_two_interior_victims(placement) -> list[(str,int,int)]` — Task 7 ✓
