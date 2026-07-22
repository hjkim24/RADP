# Full-KV-Replication Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `recovery_mode="replicate"` baseline (store each stage's KV verbatim, reload on failure — zero recompute, like parity but without the XOR fold) and measure it against parity on a 2-D Pareto (TTR × steady-state storage), plus a cold-restart anchor.

**Architecture:** `ReplicaCache` is `ParityCache` with the XOR removed and keyed by stage instead of folded into one blob. Recovery reads the dead stage's own stored columns directly — no survivor fetch, no XOR, no slot-spread guard (we hold the dead stage's columns, not survivors'). The SLOT→LAYER transpose that turns stored columns into `install_kv` bytes is shared with parity. The worker ships columns identically (same `RADP_PARITY` env gate); only the coordinator's storage differs by `recovery_mode`.

**Tech Stack:** Python 3, numpy, gRPC (existing MirrorKV/FetchKV/LoadKV — no new proto), pytest, matplotlib (slide figures).

## Global Constraints

- Generated `*_pb2.py` / `*_pb2_grpc.py` are gitignored — never commit them.
- Recovery correctness must never depend on replicate: fallback ladder `replicate → surgical → full-replay` preserved; a wrong token is never emitted.
- Measurement integrity: a mode's TTR is published only when its own branch log (`"REPLICATE reconstruct:"`) confirms it ran — no surgical-fallback mislabeled as replicate.
- The bit-identical KV assertion applies to replicate (loads stored bytes) exactly as to parity, and NOT to surgical/full-replay (recompute).
- Figures follow `ppt/DESIGN_SYSTEM.md` §7: slide scale, deck palette (`_slide.py`), English in-figure text, anchor text to shapes.
- Reuse `RADP_PARITY` as the worker KV-ship gate for replicate too (the worker does not know the coordinator's storage mode). Do not add a new worker env.

---

### Task 1: ReplicaCache

**Files:**
- Create: `radp/coordinator/replica_cache.py`
- Test: `tests/test_replicate_recovery.py`

**Interfaces:**
- Consumes: `radp.common.types.RequestId`.
- Produces: `ReplicaCache(num_stages: int, max_bytes: int = 256*1024*1024)` with
  `store(request_id, stage_key: tuple[int,int], position: int, column_bytes: bytes) -> None`,
  `get_stage_kv(request_id, stage_key) -> bytes | None`,
  `is_complete(request_id, stage_key, up_to_position: int) -> bool`,
  `evict_request(request_id) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_replicate_recovery.py`:

```python
import numpy as np
from radp.coordinator.replica_cache import ReplicaCache
from radp.common.types import RequestId

R = RequestId(1)
SK = (16, 17)  # a stage's (start_layer, end_layer)


def test_store_get_concatenates_in_position_order():
    c = ReplicaCache(num_stages=3)
    c.store(R, SK, 0, b"\x01\x02")
    c.store(R, SK, 1, b"\x03\x04")
    assert c.get_stage_kv(R, SK) == b"\x01\x02\x03\x04"


def test_store_is_deduped():
    c = ReplicaCache(num_stages=3)
    c.store(R, SK, 0, b"\x01\x02")
    c.store(R, SK, 0, b"\xff\xff")  # re-arriving (stage, pos) ignored
    assert c.get_stage_kv(R, SK) == b"\x01\x02"


def test_get_missing_stage_returns_none():
    c = ReplicaCache(num_stages=3)
    assert c.get_stage_kv(R, SK) is None


def test_is_complete_detects_hole():
    c = ReplicaCache(num_stages=3)
    c.store(R, SK, 0, b"\x01\x02")
    c.store(R, SK, 2, b"\x05\x06")  # position 1 missing
    assert c.is_complete(R, SK, up_to_position=2) is False
    assert c.is_complete(R, SK, up_to_position=0) is True


def test_evict_keeps_sole_request():
    c = ReplicaCache(num_stages=1, max_bytes=1)  # tiny cap
    c.store(R, SK, 0, b"\x01\x02\x03\x04")  # over cap, but sole request
    assert c.get_stage_kv(R, SK) == b"\x01\x02\x03\x04"  # not evicted


def test_evict_drops_oldest_when_second_arrives():
    c = ReplicaCache(num_stages=1, max_bytes=4)
    c.store(R, SK, 0, b"\x01\x02\x03\x04")
    c.store(RequestId(2), SK, 0, b"\x05\x06\x07\x08")  # pushes over cap
    assert c.get_stage_kv(R, SK) is None            # oldest evicted
    assert c.get_stage_kv(RequestId(2), SK) is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_replicate_recovery.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'radp.coordinator.replica_cache'`

- [ ] **Step 3: Write the implementation**

Create `radp/coordinator/replica_cache.py`:

```python
"""Full-KV replication cache (design spec 2026-07-22-replication-baseline).

The zero-recompute baseline against which parity is compared. Where
``ParityCache`` folds every stage's KV column into ONE XOR blob per position,
``ReplicaCache`` keeps each stage's columns verbatim, keyed by stage. Recovery
reads the dead stage's own stored columns directly — no survivor fetch, no XOR.

Storage is Σ(stage KV) vs parity's max(stage KV): that gap is the whole point
of the comparison. TTR is similar (both reload, no recompute).
"""
from __future__ import annotations

import threading
from collections import OrderedDict

from radp.common.types import RequestId

StageKey = tuple[int, int]


class ReplicaCache:
    def __init__(self, num_stages: int, max_bytes: int = 256 * 1024 * 1024) -> None:
        self.num_stages = num_stages
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        # request -> stage_key -> {position: column_bytes}
        self._by_request: OrderedDict[
            RequestId, dict[StageKey, dict[int, bytes]]
        ] = OrderedDict()
        self._bytes_used = 0

    def store(
        self, request_id: RequestId, stage_key: StageKey,
        position: int, column_bytes: bytes,
    ) -> None:
        with self._lock:
            stages = self._by_request.setdefault(request_id, {})
            self._by_request.move_to_end(request_id)
            positions = stages.setdefault(stage_key, {})
            if position in positions:
                return  # dedup — re-arriving (stage, position) ignored
            positions[position] = column_bytes
            self._bytes_used += len(column_bytes)
            self._evict_if_needed_locked()

    def get_stage_kv(
        self, request_id: RequestId, stage_key: StageKey
    ) -> bytes | None:
        with self._lock:
            stages = self._by_request.get(request_id)
            if not stages or stage_key not in stages:
                return None
            positions = stages[stage_key]
            return b"".join(positions[p] for p in sorted(positions))

    def is_complete(
        self, request_id: RequestId, stage_key: StageKey, up_to_position: int
    ) -> bool:
        with self._lock:
            stages = self._by_request.get(request_id)
            if not stages or stage_key not in stages:
                return False
            positions = stages[stage_key]
            return all(p in positions for p in range(up_to_position + 1))

    def evict_request(self, request_id: RequestId) -> None:
        with self._lock:
            stages = self._by_request.pop(request_id, None)
            if stages:
                self._bytes_used -= sum(
                    len(b) for positions in stages.values() for b in positions.values()
                )

    def _evict_if_needed_locked(self) -> None:
        # Never evict the sole in-flight request: store() calls move_to_end(),
        # making it both oldest and newest if alone. Evicting it would destroy
        # the KV just added (actively maintained for recovery) with no savings.
        while self._bytes_used > self.max_bytes and len(self._by_request) > 1:
            _, stages = self._by_request.popitem(last=False)  # oldest request
            self._bytes_used -= sum(
                len(b) for positions in stages.values() for b in positions.values()
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_replicate_recovery.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add radp/coordinator/replica_cache.py tests/test_replicate_recovery.py
git commit -m "feat(replicate): ReplicaCache — per-stage KV store, no XOR"
```

---

### Task 2: Extract shared SLOT→LAYER transpose helper

**Files:**
- Modify: `radp/coordinator/gateway.py` (`_xor_reconstruct_kv`, add `_slot_major_to_layer_major`)

**Interfaces:**
- Produces: staticmethod `RequestGateway._slot_major_to_layer_major(dead_slots: np.ndarray, n_dead_layers: int, n_heads: int, head_dim: int, np_dtype) -> bytes`, where `dead_slots` is a uint8 array of shape `(n_slots, dead_slot_bytes)`. Returns LAYER-major bytes for `install_kv`.
- Consumes (used by later Task 3): the same helper.

This is a refactor that must NOT change parity behavior — the existing `tests/test_parity_recovery.py` bit-exact test is the regression net.

- [ ] **Step 1: Add the helper method**

In `radp/coordinator/gateway.py`, add this staticmethod to `RequestGateway` (place it directly above `_xor_reconstruct_kv`):

```python
    @staticmethod
    def _slot_major_to_layer_major(
        dead_slots,  # np.ndarray[uint8], shape (n_slots, dead_slot_bytes)
        n_dead_layers: int,
        n_heads: int,
        head_dim: int,
        np_dtype,
    ) -> bytes:
        """Turn per-slot dead-stage columns into LAYER-major install_kv bytes.

        Inverse of extract_kv_column's layout: reshape each slot to
        (n_dead_layers, 2, n_heads, head_dim), stack over slots, then move the
        slot axis back between heads and head_dim (transpose (1,2,3,0,4)).
        Axis order pinned by the parity bit-exact end-to-end test.
        """
        import numpy as np
        n_slots = dead_slots.shape[0]
        dead_slot_major = dead_slots.view(np_dtype).reshape(
            n_slots, n_dead_layers, 2, n_heads, head_dim
        )
        dead_layer_major = np.ascontiguousarray(
            np.transpose(dead_slot_major, (1, 2, 3, 0, 4))
        )
        return dead_layer_major.tobytes()
```

- [ ] **Step 2: Replace the tail of `_xor_reconstruct_kv` to call it**

In `_xor_reconstruct_kv`, replace the final block (from `dead_slot_major = dead_slots.view(...)` through `return dead_layer_major.tobytes()`) with:

```python
        return self._slot_major_to_layer_major(
            dead_slots, n_dead_layers, n_heads, head_dim, np_dtype
        )
```

- [ ] **Step 3: Run the parity regression test**

Run: `.venv/bin/python -m pytest tests/test_parity_recovery.py -v`
Expected: PASS (all existing parity tests, including bit-exact end-to-end, unchanged)

- [ ] **Step 4: Commit**

```bash
git add radp/coordinator/gateway.py
git commit -m "refactor(recovery): extract _slot_major_to_layer_major, shared by parity/replicate"
```

---

### Task 3: `_recover_replicate` + record_kv dispatch + mode validation

**Files:**
- Modify: `radp/coordinator/gateway.py`
- Test: `tests/test_replicate_recovery.py` (add end-to-end cases)

**Interfaces:**
- Consumes: `ReplicaCache` (Task 1), `_slot_major_to_layer_major` (Task 2), existing `self._kv_dims()`, `self._attribute_chain_failure`, `self._recover_surgical`, `self._rewire_chain`, `WorkerClient.load_kv`, `self._invoke`, `self.cache.get_history`.
- Produces: recovery when `recovery_mode == "replicate"`.

Reference — the existing parity recovery this mirrors (`_recover_parity`) ends by promoting the backup, calling `_slot_major_to_layer_major`, `client.load_kv(...)`, then `self._invoke(backup_stage, ..., history[current_position], replay_only=False)`. Replicate keeps that tail verbatim and replaces the survivor-fetch + XOR body with a single `get_stage_kv` read. There is **no slot-spread guard** in replicate — it holds the dead stage's own columns, not survivors', so no alignment skew exists.

- [ ] **Step 1: Write the failing end-to-end tests**

Append to `tests/test_replicate_recovery.py`. Mirror the parity end-to-end harness — open `tests/test_parity_recovery.py` and copy its imports, `MODEL`, `_healthy_reference`, `in_process_cluster_with_mirror`, `deploy`, `wire_chain`, and the 3-stage `cfg()` used by `_assert_parity_recovery`. Then:

```python
def _assert_replicate_recovery(monkeypatch, caplog, *, cfg, victim_dev, backup_dev):
    """Drive one replicate recovery; assert (a) the REPLICATE branch ran and did
    NOT fall back to surgical; (b) reconstructed backup KV is bit-identical to
    the victim's per layer K & V; (c) recovered sequence equals the reference."""
    from radp.coordinator.gateway import RequestGateway
    monkeypatch.setenv("RADP_PARITY", "1")  # worker ships columns (shared gate)
    prompt, n, kill_at = "The quick brown fox", 12, 4
    reference = _healthy_reference(prompt, n, cfg)
    ids, placement, recovery = cfg()
    victim_stage = next(s for s in placement if s.device == DeviceId(victim_dev))
    dead_key = (int(victim_stage.start_layer), int(victim_stage.end_layer))
    with in_process_cluster_with_mirror(ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(
            worker_addresses=addrs, model_id=MODEL,
            recovery_mode="replicate",
            initial_placement=placement, recovery_table=recovery,
        )
        # ... drive request with a compute-time crash at position kill_at on
        # victim_dev, exactly as _assert_parity_recovery does (copy that body,
        # swapping "PARITY reconstruct" for "REPLICATE reconstruct").
        surgical_calls = {"n": 0}
        orig = gw._recover_surgical
        def spy(*a, **k):
            surgical_calls["n"] += 1
            return orig(*a, **k)
        gw._recover_surgical = spy
        # drive, assert reference match, assert surgical_calls["n"] == 0,
        # assert "REPLICATE reconstruct:" in caplog.text,
        # assert reconstructed backup KV bit-identical to victim original.


def test_replicate_recovery_matches_reference(monkeypatch, caplog):
    # Reuse the parity test's `_cfg` factory (3-worker chain, victim "worker-b",
    # backup "worker-c") and its MODEL = "facebook/opt-125m". Do NOT use fleet
    # device names (on-1/on-6) — those are for the live driver, not this test.
    _assert_replicate_recovery(
        monkeypatch, caplog, cfg=_cfg,
        victim_dev="worker-b", backup_dev="worker-c",
    )


def test_replicate_falls_back_when_incomplete(monkeypatch, caplog):
    """If the dead stage's stored columns have a hole, fall back to surgical;
    output still matches the reference (correctness never depends on replicate)."""
    # Force ReplicaCache.is_complete -> False (monkeypatch on the gw's cache),
    # drive the same crash, assert surgical ran AND sequence matches reference.
```

Note: reuse the exact crash-injection and reference-comparison mechanics from `_assert_parity_recovery` in `tests/test_parity_recovery.py`. Do not invent a new harness. The bit-identical check copies parity's `_kv_layers`-based per-layer comparison.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_replicate_recovery.py -k reference -v`
Expected: FAIL — `recovery_mode must be 'full_replay', 'surgical' or 'parity'` (validation rejects "replicate")

- [ ] **Step 3: Add mode validation + cache + dispatch + recovery**

3a. In `RequestGateway.__init__`, widen the validation set and add the cache. Find:

```python
        if recovery_mode not in {"full_replay", "surgical", "parity"}:
```
replace the set with `{"full_replay", "surgical", "parity", "replicate"}` and update the error string to include `'replicate'`. Directly after `self.parity_cache = ParityCache(num_stages=max(len(placement) - 1, 0))` add:

```python
        from radp.coordinator.replica_cache import ReplicaCache
        self.replica_cache = ReplicaCache(num_stages=max(len(placement) - 1, 0))
```

3b. In `record_kv`, dispatch by mode. Replace the single `self.parity_cache.xor_in(...)` call with:

```python
        key = (int(start_layer), int(end_layer))
        if self.recovery_mode == "replicate":
            self.replica_cache.store(
                RequestId(request_id), key, int(position), kv_bytes
            )
        else:
            self.parity_cache.xor_in(
                RequestId(request_id), key, int(position), kv_bytes
            )
```

3c. In the recovery dispatch (where `if self.recovery_mode == "parity": return self._recover_parity(...)` lives, near line 692), add directly above it:

```python
        if self.recovery_mode == "replicate":
            return self._recover_replicate(
                request_id, head_stage, error, current_position
            )
```

3d. Add `_recover_replicate` next to `_recover_parity`:

```python
    def _recover_replicate(
        self,
        request_id: RequestId,
        head_stage: Stage,
        error: grpc.RpcError,
        current_position: int,
    ) -> tuple[Stage, Any]:
        """Full-KV-replication recovery — install the dead stage's own stored
        KV columns onto the promoted backup, then run the failed position live.
        No survivor fetch, no XOR (cf. _recover_parity). Falls back to surgical
        whenever the stored columns are missing or incomplete — a wrong token is
        never emitted.
        """
        import numpy as np
        dead_stage = self._attribute_chain_failure(head_stage, error)
        if int(dead_stage.start_layer) == 1:  # head: coord-sourced, never stored
            return self._recover_surgical(
                request_id, head_stage, error, current_position
            )
        dead_key = (int(dead_stage.start_layer), int(dead_stage.end_layer))
        # The victim died computing position `current_position`, having
        # completed 0..current_position-1 (that is what it stored).
        n_slots = current_position
        if n_slots < 1 or not self.replica_cache.is_complete(
            request_id, dead_key, up_to_position=n_slots - 1
        ):
            log.info(
                "request=%d replicate: stored KV incomplete for %s; "
                "deferring to surgical", request_id, dead_key,
            )
            return self._recover_surgical(
                request_id, head_stage, error, current_position
            )
        stored = self.replica_cache.get_stage_kv(request_id, dead_key)
        if stored is None:
            return self._recover_surgical(
                request_id, head_stage, error, current_position
            )
        history = self.cache.get_history(request_id, dead_key)
        if len(history) <= current_position:
            log.info(
                "request=%d replicate: mirror history len=%d <= failed pos %d; "
                "fallback to surgical", request_id, len(history), current_position,
            )
            return self._recover_surgical(
                request_id, head_stage, error, current_position
            )
        if dead_stage.device not in self._dead:
            self.mark_dead(dead_stage.device)
        n_heads, head_dim, np_dtype, itemsize = self._kv_dims()
        n_dead_layers = dead_key[1] - dead_key[0] + 1
        dead_slot_bytes = n_dead_layers * 2 * n_heads * head_dim * itemsize
        dead_slots = np.frombuffer(stored, dtype=np.uint8).reshape(
            n_slots, dead_slot_bytes
        )
        dead_kv_bytes = self._slot_major_to_layer_major(
            dead_slots, n_dead_layers, n_heads, head_dim, np_dtype
        )
        backup_dev = self.recovery.get(dead_stage.device)
        if backup_dev is None:
            raise NoRecoveryError(f"no backup for {dead_stage.device}")
        backup_addr = self.worker_addresses.get(backup_dev)
        if backup_addr is None:
            raise RuntimeError(f"recovery device {backup_dev} has no address")
        with WorkerClient(backup_addr) as client:
            client.promote_backup(for_device_id=dead_stage.device)
        self._rewire_chain()
        backup_stage = next(
            (s for s in self.current_plan()
             if (int(s.start_layer), int(s.end_layer)) == dead_key),
            None,
        )
        if backup_stage is None:
            raise RuntimeError(
                f"layer range {dead_key} not present in post-recovery plan"
            )
        log.warning(
            "request=%d REPLICATE reconstruct: backup %s stage[%d..%d] "
            "slots=%d (stored KV, zero-forward), then run pos %d live",
            request_id, backup_stage.device, *dead_key, n_slots, current_position,
        )
        with WorkerClient(self.worker_addresses[backup_stage.device]) as client:
            client.load_kv(
                request_id=request_id,
                start_layer=dead_key[0], end_layer=dead_key[1],
                kv_bytes=dead_kv_bytes, num_positions=n_slots,
            )
        history = self.cache.get_history(request_id, dead_key)
        last_resp = self._invoke(
            backup_stage, request_id, history[current_position],
            is_prefill=(current_position == 0),
            position=current_position, replay_only=False,
        )
        return backup_stage, last_resp
```

Note on `self._backup_for(...)` and `self.mark_dead(...)`: use whatever helper `_recover_parity` uses to find the backup device and mark dead — copy those exact calls from `_recover_parity` (this plan shows the shape; match the neighbor's method names verbatim when you open the file).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_replicate_recovery.py -v`
Expected: PASS (unit + end-to-end: reference match, no surgical fallback, REPLICATE log present, bit-identical KV, and the incomplete→fallback case)

- [ ] **Step 5: Commit**

```bash
git add radp/coordinator/gateway.py tests/test_replicate_recovery.py
git commit -m "feat(replicate): _recover_replicate + record_kv dispatch + mode validation"
```

---

### Task 4: replication_overhead() computation

**Files:**
- Modify: `experiments/_harness.py`
- Test: `tests/test_replicate_recovery.py` (append)

**Interfaces:**
- Produces: `replication_overhead(placement, n_heads: int, head_dim: int, itemsize: int) -> dict` with keys `replicate_bytes` (Σ non-head stage KV), `parity_bytes` (max non-head stage KV), `ratio` (Σ/max), `per_stage` (list of `(stage_key, bytes)`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_replicate_recovery.py`:

```python
def test_replication_overhead_sum_vs_max():
    from experiments._harness import replication_overhead
    from radp.common.types import Stage, DeviceId, LayerIdx
    # head [1..15] excluded; non-head layer counts 2,2,4,1
    placement = [
        Stage(DeviceId("h"),  LayerIdx(1),  LayerIdx(15)),
        Stage(DeviceId("a"),  LayerIdx(16), LayerIdx(17)),  # 2
        Stage(DeviceId("b"),  LayerIdx(18), LayerIdx(19)),  # 2
        Stage(DeviceId("c"),  LayerIdx(20), LayerIdx(23)),  # 4
        Stage(DeviceId("d"),  LayerIdx(24), LayerIdx(24)),  # 1
    ]
    # per-layer bytes = 2 (K,V) * n_heads * head_dim * itemsize; use unit sizes
    o = replication_overhead(placement, n_heads=1, head_dim=1, itemsize=1)
    # bytes per stage = layers * 2; sum = (2+2+4+1)*2 = 18, max = 4*2 = 8
    assert o["replicate_bytes"] == 18
    assert o["parity_bytes"] == 8
    assert abs(o["ratio"] - 18 / 8) < 1e-9
    assert len(o["per_stage"]) == 4  # non-head only
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_replicate_recovery.py::test_replication_overhead_sum_vs_max -v`
Expected: FAIL with `ImportError: cannot import name 'replication_overhead'`

- [ ] **Step 3: Implement**

Add to `experiments/_harness.py`:

```python
def replication_overhead(placement, n_heads: int, head_dim: int, itemsize: int) -> dict:
    """Steady-state coordinator storage: replicate = Σ non-head stage KV,
    parity = max non-head stage KV. Deterministic — no measurement. Feeds the
    2-D Pareto y-axis and the O(N) storage-scaling curve.
    """
    per_stage = []
    for stage in placement:
        if int(stage.start_layer) == 1:  # head is coord-sourced, not stored
            continue
        n_layers = int(stage.end_layer) - int(stage.start_layer) + 1
        stage_bytes = n_layers * 2 * n_heads * head_dim * itemsize
        per_stage.append(((int(stage.start_layer), int(stage.end_layer)), stage_bytes))
    sizes = [b for _, b in per_stage]
    total = sum(sizes)
    biggest = max(sizes) if sizes else 0
    return {
        "replicate_bytes": total,
        "parity_bytes": biggest,
        "ratio": (total / biggest) if biggest else 0.0,
        "per_stage": per_stage,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_replicate_recovery.py::test_replication_overhead_sum_vs_max -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add experiments/_harness.py tests/test_replicate_recovery.py
git commit -m "feat(replicate): replication_overhead — Σ vs max storage bytes"
```

---

### Task 5: In-process baseline line — run_radp_replicate

**Files:**
- Modify: `experiments/b1_ft_baselines.py`

**Interfaces:**
- Consumes: existing `_drive_inplace_crash(name, recovery_mode, prompt, max_tokens, kill_after_tokens, reference)` and `run_all`.
- Produces: `run_radp_replicate(...)` returning a `BaselineResult`, wired into `run_all`.

- [ ] **Step 1: Add the line function**

In `experiments/b1_ft_baselines.py`, directly after `run_radp_full_replay` add:

```python
def run_radp_replicate(*, prompt, max_tokens, kill_after_tokens, reference):
    return _drive_inplace_crash(
        name="RADP-replicate", recovery_mode="replicate",
        prompt=prompt, max_tokens=max_tokens,
        kill_after_tokens=kill_after_tokens, reference=reference,
    )
```

Note: `_drive_inplace_crash` must run with the worker KV-ship gate on. Confirm it sets `RADP_PARITY=1` for the recovery_mode in {"parity","replicate"} path; if it only enables it for "parity", widen that check to include "replicate" (one-line edit in `_drive_inplace_crash`).

- [ ] **Step 2: Wire it into run_all**

In `run_all`, add `run_radp_replicate(...)` to the `lines = [...]` list, directly after the `run_radp_full_replay(...)` entry, passing the same `prompt`, `max_tokens`, `kill_after_tokens`, `reference` kwargs.

- [ ] **Step 3: Run the in-process baseline driver**

Run: `.venv/bin/python experiments/b1_ft_baselines.py --max-tokens 12 --kill-after-tokens 4 --out /tmp/b1_repl_check`
Expected: prints `wrote ...`; open the JSON and confirm a `RADP-replicate` line exists with `sequence_matches_reference: true` and `aborted: false`.

- [ ] **Step 4: Commit**

```bash
git add experiments/b1_ft_baselines.py
git commit -m "feat(replicate): run_radp_replicate in-process baseline line"
```

---

### Task 6: Fleet sweep line + cold-restart anchor

**Files:**
- Modify: `experiments/b1_ft_fleet.py`

**Interfaces:**
- Consumes: existing `set_recovery_mode`, `set_worker_parity`, `run_trial`, `_linfit`, `_parity_branch_ran`.
- Produces: `"replicate"` in the swept `modes`; a `cold_restart` single-point measurement at P=32; `set_worker_replication(on)`; `_replicate_branch_ran(log_text)`.

This driver runs against live hardware; there is no unit test. The deliverable is the extended driver plus a documented dry-run check.

- [ ] **Step 1: Add the replicate log gate**

After `_parity_branch_ran` in `experiments/b1_ft_fleet.py` add:

```python
def _replicate_branch_ran(log_text: str) -> bool:
    """True iff the coordinator log shows the replicate branch ran (not a
    surgical fallback). Mirrors _parity_branch_ran."""
    return "REPLICATE reconstruct:" in log_text
```

- [ ] **Step 2: Add set_worker_replication**

Add next to `set_worker_parity`:

```python
def set_worker_replication(on: bool) -> None:
    """Replicate reuses the same worker KV-ship gate as parity — the worker does
    not know the coordinator's storage mode. Alias for clarity at call sites."""
    set_worker_parity(on)
```

- [ ] **Step 3: Add "replicate" to the swept modes and gate its trials**

Wherever the driver builds its `modes` list (the CLI `--modes` default or the sweep loop), allow `"replicate"`. In the per-trial validity check, extend the parity-specific gate so a `replicate` trial is valid only when `_replicate_branch_ran(log_text)` is true — the exact mirror of how `parity` uses `_parity_branch_ran`. Ensure `set_worker_replication(True)` (equivalently `set_worker_parity(True)`) is on for the replicate sweep, and `set_recovery_mode(coord_host, "replicate")` is set per trial.

- [ ] **Step 4: Add the cold-restart single anchor at P=32**

Add a function that measures cold-restart at one position only:

```python
def run_cold_restart_anchor(coord_host, coord_ssh, ssh_key, victim_host,
                            victim_stage, *, position=32, prompt, max_tokens):
    """Cold-restart at a single worst-case P. Its TTR is dominated by ansible /
    systemd restart + model reload — a deployment-tooling property, not the
    recovery algorithm — so it is one anchor point, not a swept line."""
    set_recovery_mode(coord_host, "cold_restart")
    # arm the victim to die at `position`, drive one request, and measure the
    # wall from crash to recovered-token exactly as run_trial does; return a
    # single {"mode": "cold_restart", "position": position, "ttr_seconds": ...}.
```

If `recovery_mode == "cold_restart"` is not a coordinator branch, measure cold-restart the way `b1_ft_baselines.run_b1_cold_restart` does (kill worker → ansible restart → replay from position 0 against the healthy reference wall) but on the fleet; reuse `restart_coordinator_and_wait` / ansible worker restart. Emit the single point into the same results JSON under a `cold_restart_anchor` key.

- [ ] **Step 5: Dry-run check (document, do not block on hardware)**

Run: `.venv/bin/python experiments/b1_ft_fleet.py --help`
Expected: `--modes` accepts `replicate`. If the VPN/fleet is up, a smoke sweep `--modes replicate --positions 8` should produce a JSON where the replicate trial has `replicate_branch_ran: true`. If the fleet is down, note that in the commit message and defer the live sweep.

- [ ] **Step 6: Commit**

```bash
git add experiments/b1_ft_fleet.py
git commit -m "feat(replicate): fleet replicate sweep + cold-restart P=32 anchor"
```

---

### Task 7: Figures — 2-D Pareto, storage scaling, replicate line

**Files:**
- Create: `paper/figures/make_recovery_2d.py`, `paper/figures/make_storage_scaling.py`
- Modify: `paper/figures/make_recovery_ttr_slide.py`

**Interfaces:**
- Consumes: `_slide.py` (`SUBJECT`, `SLIDE_FULL`, `save_slide`, `BODY`, `ACCENT`, `NAVY`, `ALERT`), results JSON `b1_ft_fleet_replicate.json` + `b1_ft_fleet_parity.json`, computed `b1_ft_overhead.json`.
- Produces: `fig_recovery_2d.{png,pdf}`, `fig_storage_scaling.{png,pdf}`, updated `fig_recovery_ttr_slide`.

`SUBJECT` currently has `full_replay`, `surgical`, `parity`, `baseline`. Add a `replicate` color. Pick `"#808080"` (the existing `baseline` grey) so replicate reads as "the rival baseline" and does not steal parity's emphasis blue.

- [ ] **Step 1: Add replicate to the subject palette**

In `paper/figures/_slide.py`, in the `SUBJECT` dict add:

```python
    "replicate":   "#808080",   # rival baseline — neutral grey, not parity's blue
```

- [ ] **Step 2: Write make_storage_scaling.py (computed, no measurement)**

Create `paper/figures/make_storage_scaling.py`:

```python
"""Storage vs stage count: replicate O(N) vs parity O(1). Computed from
placement, not measured — the caption must say so (DESIGN_SYSTEM §11)."""
import sys
from pathlib import Path
import matplotlib.pyplot as plt
sys.path.insert(0, str(Path(__file__).parent))
from _slide import BODY, SLIDE_FULL, SUBJECT, save_slide, strip_chrome  # noqa: E402

# Equal-sized stages (unit KV each) to show the asymptotics cleanly.
stages = list(range(2, 13))
replicate = [n for n in stages]     # Σ = N units
parity = [1 for _ in stages]        # max = 1 unit

fig, ax = plt.subplots(figsize=SLIDE_FULL)
ax.plot(stages, replicate, "o-", color=SUBJECT["replicate"], label="replicate  O(N)")
ax.plot(stages, parity, "^-", color=SUBJECT["parity"], label="parity  O(1)")
ax.set_xlabel("pipeline stages  N")
ax.set_ylabel("coordinator storage  (KV units)")
ax.set_ylim(0, None)
strip_chrome(ax)
ax.legend(loc="upper left", frameon=False)
fig.tight_layout()
save_slide(fig, "fig_storage_scaling")
```

- [ ] **Step 3: Write make_recovery_2d.py (Pareto)**

Create `paper/figures/make_recovery_2d.py`:

```python
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
          and t.get("recovery_visible") and t["sequence_match"]]
    return sum(t["ttr_seconds"] for t in xs) / len(xs)

pts = [
    ("full-replay", ttr_at(par, "full_replay"), 0,                      SUBJECT["full_replay"], "o"),
    ("surgical",    ttr_at(par, "surgical"),    0,                      SUBJECT["surgical"],    "s"),
    ("replicate",   ttr_at(rep, "replicate"),   ovh["replicate_bytes"], SUBJECT["replicate"],   "D"),
    ("parity",      ttr_at(par, "parity"),      ovh["parity_bytes"],    SUBJECT["parity"],      "^"),
]

fig, ax = plt.subplots(figsize=SLIDE_FULL)
for name, x, y, color, marker in pts:
    ax.scatter(x, y, s=140, color=color, marker=marker, zorder=3)
    ax.annotate(name, xy=(x, y), xytext=(8, 6), textcoords="offset points",
                color=color, fontsize=13, fontweight="bold")
ax.set_xlabel("recovery time at P=32  (s)")
ax.set_ylabel("steady-state storage  (bytes)")
ax.set_xlim(0, None); ax.set_ylim(0, None)
strip_chrome(ax)
fig.tight_layout()
save_slide(fig, "fig_recovery_2d")
```

- [ ] **Step 4: Add a replicate line to make_recovery_ttr_slide.py**

In `paper/figures/make_recovery_ttr_slide.py`, add a `"replicate"` entry to the `STYLE` dict (`(SUBJECT["replicate"], "D", "replicate")`) and load `b1_ft_fleet_replicate.json` alongside the parity JSON so the replicate points/fit are drawn on the same axes. Keep the log axis and the normal-decode-step reference line. Do not hide that replicate overlaps or beats parity.

- [ ] **Step 5: Generate figures and eyeball**

Run (from repo root, only if the two results JSONs exist; otherwise defer with the live sweep in Task 6):
```bash
.venv/bin/python paper/figures/make_storage_scaling.py
.venv/bin/python paper/figures/make_recovery_2d.py
.venv/bin/python paper/figures/make_recovery_ttr_slide.py
```
Expected: three `wrote ...` lines. Open each PNG; confirm parity is alone in the low-low corner of `fig_recovery_2d`, and storage scaling shows the O(N) vs O(1) split.

- [ ] **Step 6: Commit**

```bash
git add paper/figures/_slide.py paper/figures/make_recovery_2d.py \
        paper/figures/make_storage_scaling.py paper/figures/make_recovery_ttr_slide.py \
        paper/figures/fig_recovery_2d.* paper/figures/fig_storage_scaling.* \
        paper/figures/fig_recovery_ttr_slide.*
git commit -m "feat(figures): 2-D Pareto + storage scaling + replicate TTR line"
```

---

## Notes for the implementer

- **`_recover_replicate` is deliberately shorter than `_recover_parity`** — no survivor fetch, no XOR, no slot-spread guard. If you find yourself copying the survivor-fetch loop or the `max(slot_counts) - min(slot_counts) > 1` guard, stop: replicate reads the dead stage's own columns, so there is no cross-survivor alignment to reconcile.
- **Match neighbor method names verbatim.** Task 3's `_recover_replicate` shows the shape; when you open `gateway.py`, copy the exact helper calls `_recover_parity` uses for backup lookup (`self._backup_for` or equivalent), `mark_dead`, and history access. Do not introduce new names.
- **The worker never changes.** Column shipping is already `RADP_PARITY`-gated and mode-agnostic. Replicate reuses it.
