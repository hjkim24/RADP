# Cross-stage Parity KV-Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third recovery family to RADP — cross-stage XOR parity — that reconstructs a dead pipeline stage's KV cache with zero model forward pass, measured as a third line on the live fleet vs surgical/full-replay.

**Architecture:** Each worker ships its per-position KV column (raw fp16 bytes) to the coordinator, which folds it into a single running parity blob `P` (RAID-5 across stages, zero-padded to the max stage size). On a single-stage failure the coordinator fetches the survivors' KV, byte-XORs them with `P` to recover the dead stage's exact KV bytes, and installs them into the promoted backup — no forward. Falls back to surgical→full-replay for correctness.

**Tech Stack:** Python 3.9/3.10, PyTorch (DynamicCache), gRPC (grpcio + protoc), numpy (byte XOR), pytest.

## Global Constraints

- transformers pin: `>=4.40,<4.51` (fleet + `.venv-py39` run 4.50.3). Do not upgrade.
- In-process model tests MUST be marked `pytestmark = pytest.mark.slow` (module level) and run with `-m slow`; pure-logic tests are unmarked (default `-m 'not slow'`).
- Default recovery is byte-for-byte unchanged: `recovery_mode="full_replay"` is the default; `"parity"` is opt-in via `RADP_RECOVERY_MODE`.
- KV shipping is opt-in via worker env `RADP_PARITY=1` — inert (zero cost) otherwise.
- Commit trailer on every commit:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01FfKQPAstkv5E1GtvR5op9j`
- PUBLIC repo: no secrets in commits; `experiments/results/` and `deploy/inventory.ini` stay gitignored.
- **Column format = RAW fp16 tensor bytes**, NOT `torch.save`. A stage's KV column at a position = for each layer in the stage, K then V, each `.cpu().contiguous()` fp16 tensor's raw bytes, concatenated. Fixed, deterministic size = `n_layers × 2 × n_heads × head_dim × seq × 2 bytes`. This is what makes byte-XOR + truncate exact. (Refines spec §4's "tensor_io" phrasing; `tensor_io` is still used for non-XOR'd transfers only where noted.)
- Fleet victim (deterministic DP placement): `on-1[16..17]`, backup `on-6`. Coordinator measured in `chain_mode: sync`.

---

## File Structure

- **Create** `radp/coordinator/parity_cache.py` — `ParityCache`: maintain P, dedup, completeness. Pure logic, no torch.
- **Create** `tests/test_parity_cache.py` — fast unit tests for ParityCache.
- **Create** `tests/test_parity_recovery.py` — slow in-process end-to-end parity recovery.
- **Modify** `radp/common/proto/radp.proto` — add `MirrorKV`, `FetchKV`, `LoadKV` RPCs + messages; regenerate stubs.
- **Modify** `radp/worker/stage_runner.py` — add `extract_kv_column`, `export_kv`, `install_kv` (DynamicCache ↔ raw bytes).
- **Modify** `radp/worker/server.py` — MirrorKV push (RADP_PARITY-gated) in RunStage; `FetchKV`/`LoadKV` handlers; `_CoordDispatcher.submit_kv`.
- **Modify** `radp/common/protocol.py` — `WorkerClient.fetch_kv`, `WorkerClient.load_kv`.
- **Modify** `radp/coordinator/server.py` — build `ParityCache`; `MirrorKV` handler → `xor_in`.
- **Modify** `radp/coordinator/gateway.py` — `recovery_mode="parity"` branch + `_recover_parity`.
- **Modify** `experiments/b1_ft_fleet.py` — `parity` mode (RADP_PARITY drop-in on workers).
- **Modify** `paper/figures/make_recovery_ttr.py` — 3rd line when present.

---

## Task 1: ParityCache (pure logic, no model)

**Files:**
- Create: `radp/coordinator/parity_cache.py`
- Test: `tests/test_parity_cache.py`

**Interfaces:**
- Produces:
  - `ParityCache(num_stages: int, max_bytes: int = 256*1024*1024)`
  - `.xor_in(request_id: RequestId, stage_key: tuple[int,int], position: int, column_bytes: bytes) -> None`
  - `.is_complete(request_id, position) -> bool` (True iff exactly `num_stages` distinct stages contributed)
  - `.get_parity(request_id, position) -> bytes | None` (padded parity blob)
  - `.evict_request(request_id) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_parity_cache.py
from radp.coordinator.parity_cache import ParityCache
from radp.common.types import RequestId


def _rid(n): return RequestId(n)


def test_xor_recovers_missing_stage():
    """P = A^B^C; A^C^P == B, exactly (RAID-5 invariant)."""
    pc = ParityCache(num_stages=3)
    A, B, C = bytes([1, 2, 3, 4]), bytes([9, 8, 7, 6]), bytes([5, 5, 5, 5])
    for sk, col in [((1, 2), A), ((3, 4), B), ((5, 6), C)]:
        pc.xor_in(_rid(1), sk, position=0, column_bytes=col)
    assert pc.is_complete(_rid(1), 0)
    P = pc.get_parity(_rid(1), 0)
    recovered = bytes(a ^ c ^ p for a, c, p in zip(A, C, P))
    assert recovered == B


def test_unequal_lengths_zero_padded():
    """Shorter columns are zero-padded to the max; recovery truncates back."""
    pc = ParityCache(num_stages=2)
    big = bytes([1, 2, 3, 4, 5, 6])      # 6-layer-ish stage
    small = bytes([10, 20])              # 2-layer stage
    pc.xor_in(_rid(1), (1, 6), 0, big)
    pc.xor_in(_rid(1), (7, 8), 0, small)
    P = pc.get_parity(_rid(1), 0)
    assert len(P) == 6                    # padded to max
    # recover `small` (truncate to its known length 2)
    rec_padded = bytes(b ^ p for b, p in zip(big.ljust(6, b"\0"), P))
    assert rec_padded[:2] == small
    assert rec_padded[2:] == bytes(4)     # padding is zeros


def test_duplicate_stage_ignored():
    """A retried column for the same (stage,position) must not double-XOR."""
    pc = ParityCache(num_stages=2)
    pc.xor_in(_rid(1), (1, 2), 0, bytes([7, 7]))
    pc.xor_in(_rid(1), (1, 2), 0, bytes([7, 7]))   # duplicate
    assert not pc.is_complete(_rid(1), 0)          # still only 1 contributor
    pc.xor_in(_rid(1), (3, 4), 0, bytes([1, 1]))
    assert pc.is_complete(_rid(1), 0)
    assert pc.get_parity(_rid(1), 0) == bytes([7 ^ 1, 7 ^ 1])


def test_incomplete_before_all_stages():
    pc = ParityCache(num_stages=3)
    pc.xor_in(_rid(1), (1, 2), 0, bytes([1]))
    pc.xor_in(_rid(1), (3, 4), 0, bytes([2]))
    assert not pc.is_complete(_rid(1), 0)


def test_evict_request_frees_bytes():
    pc = ParityCache(num_stages=1, max_bytes=1000)
    pc.xor_in(_rid(1), (1, 2), 0, bytes(100))
    pc.evict_request(_rid(1))
    assert pc.get_parity(_rid(1), 0) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_parity_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: radp.coordinator.parity_cache`

- [ ] **Step 3: Implement ParityCache**

```python
# radp/coordinator/parity_cache.py
"""Cross-stage XOR parity cache (design spec 2026-07-20-parity-recovery).

Maintains ONE parity blob P per (request, position) = XOR of every stage's
zero-padded raw KV-column bytes (RAID-5 across pipeline stages). Stores only P
plus a per-(request, position) set of contributing stages, so a position is
usable for reconstruction only once all `num_stages` stages have contributed
exactly once (duplicate (stage, position) pushes are ignored).
"""
from __future__ import annotations

import threading
from collections import OrderedDict

import numpy as np

from radp.common.types import RequestId

StageKey = tuple[int, int]


class _Entry:
    __slots__ = ("parity", "contributors")

    def __init__(self, size: int) -> None:
        self.parity = np.zeros(size, dtype=np.uint8)
        self.contributors: set[StageKey] = set()


class ParityCache:
    def __init__(self, num_stages: int, max_bytes: int = 256 * 1024 * 1024) -> None:
        self.num_stages = num_stages
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._by_request: OrderedDict[RequestId, dict[int, _Entry]] = OrderedDict()
        self._bytes_used = 0

    def xor_in(
        self, request_id: RequestId, stage_key: StageKey,
        position: int, column_bytes: bytes,
    ) -> None:
        col = np.frombuffer(column_bytes, dtype=np.uint8)
        with self._lock:
            positions = self._by_request.setdefault(request_id, {})
            self._by_request.move_to_end(request_id)
            entry = positions.get(position)
            if entry is None:
                entry = _Entry(col.size)
                positions[position] = entry
                self._bytes_used += col.size
            if stage_key in entry.contributors:
                return  # dedup — never double-XOR
            if col.size > entry.parity.size:  # grow to new max, zero-padded
                grown = np.zeros(col.size, dtype=np.uint8)
                grown[: entry.parity.size] = entry.parity
                self._bytes_used += col.size - entry.parity.size
                entry.parity = grown
            entry.parity[: col.size] ^= col
            entry.contributors.add(stage_key)
            self._evict_if_needed_locked()

    def is_complete(self, request_id: RequestId, position: int) -> bool:
        with self._lock:
            positions = self._by_request.get(request_id)
            if not positions or position not in positions:
                return False
            return len(positions[position].contributors) == self.num_stages

    def get_parity(self, request_id: RequestId, position: int) -> bytes | None:
        with self._lock:
            positions = self._by_request.get(request_id)
            if not positions or position not in positions:
                return None
            return positions[position].parity.tobytes()

    def evict_request(self, request_id: RequestId) -> None:
        with self._lock:
            positions = self._by_request.pop(request_id, None)
            if positions:
                self._bytes_used -= sum(e.parity.size for e in positions.values())

    def _evict_if_needed_locked(self) -> None:
        while self._bytes_used > self.max_bytes and len(self._by_request) > 1:
            _, positions = self._by_request.popitem(last=False)  # oldest request
            self._bytes_used -= sum(e.parity.size for e in positions.values())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_parity_cache.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add radp/coordinator/parity_cache.py tests/test_parity_cache.py
git commit -m "feat(parity): ParityCache — cross-stage XOR parity with dedup + completeness"
# + trailer
```

---

## Task 2: Worker KV helpers (DynamicCache ↔ raw bytes)

**Files:**
- Modify: `radp/worker/stage_runner.py`
- Test: `tests/test_parity_recovery.py` (start it here — helper round-trip only; the full recovery test lands in Task 6)

**Interfaces:**
- Consumes: `StageRunner._kv_cache: dict[(RequestId, StageKey), DynamicCache]`, `StageRunner._stages`, existing `get_seq_length(layer_idx=...)` convention (cache slots indexed by GLOBAL layer index; a stage's layers are `start-1 .. end-1`, 0-based).
- Produces (methods on `StageRunner`):
  - `extract_kv_column(request_id, *, start, end, position) -> bytes` — raw fp16 bytes of this stage's K,V at `position` (all its layers, K then V per layer, concatenated, contiguous CPU fp16).
  - `export_kv(request_id, *, start, end) -> bytes` — raw fp16 bytes of this stage's full K,V for positions `0..seq-1` (same layout, all positions).
  - `install_kv(request_id, *, start, end, kv_bytes, num_positions) -> None` — rebuild a DynamicCache for `(request, (start,end))` from raw bytes, no forward. Overwrites any existing.
  - Layout is fixed: for layer index `L` in `start-1..end-1`, append `K[L]` bytes then `V[L]` bytes; each tensor shaped `[1, n_heads, num_positions, head_dim]`, fp16, C-contiguous, CPU. Shapes come from the loaded stage's config (`self._arch` / model config: `n_heads`, `head_dim`).

- [ ] **Step 1: Write the failing test (round-trip)**

```python
# tests/test_parity_recovery.py
import pytest

pytestmark = pytest.mark.slow

from radp.worker.stage_runner import StageRunner
from radp.common.types import DeviceId, LayerIdx, RequestId

MODEL = "facebook/opt-125m"  # small, 12 layers, fast


def _load_stage(dev, start, end):
    r = StageRunner(DeviceId(dev), torch_device="cpu", dtype="float32")
    r.load_primary(MODEL, LayerIdx(start), LayerIdx(end))
    return r


def _prefill_two_tokens(runner, start, end):
    """Drive prefill + one decode so the stage KV has >=2 positions."""
    import torch
    from radp.common.tensor_io import encode
    hidden = torch.randn(1, 3, 768)          # opt-125m hidden=768
    mask = torch.ones(1, 3)
    blob = encode({"hidden_states": hidden, "attention_mask": mask})
    runner.run(RequestId(1), blob, start=LayerIdx(start), end=LayerIdx(end), is_prefill=True)
    hidden2 = torch.randn(1, 1, 768)
    mask2 = torch.ones(1, 4)
    blob2 = encode({"hidden_states": hidden2, "attention_mask": mask2})
    runner.run(RequestId(1), blob2, start=LayerIdx(start), end=LayerIdx(end), is_prefill=False)


def test_extract_install_roundtrip():
    """install_kv(extract...) reproduces the exact KV tensors."""
    import torch
    src = _load_stage("w", 5, 8)
    _prefill_two_tokens(src, 5, 8)
    full = src.export_kv(RequestId(1), start=LayerIdx(5), end=LayerIdx(8))

    dst = _load_stage("w2", 5, 8)
    dst.install_kv(RequestId(1), start=LayerIdx(5), end=LayerIdx(8),
                   kv_bytes=full, num_positions=4)

    src_cache = src._kv_cache[(RequestId(1), (5, 8))]
    dst_cache = dst._kv_cache[(RequestId(1), (5, 8))]
    for L in range(4, 8):  # 0-based layers 4..7
        assert torch.equal(src_cache.key_cache[L], dst_cache.key_cache[L])
        assert torch.equal(src_cache.value_cache[L], dst_cache.value_cache[L])


def test_xor_reconstructs_stage_column():
    """Byte-XOR of two stages' columns + parity recovers the third, bit-exact."""
    a = _load_stage("a", 1, 4); _prefill_two_tokens(a, 1, 4)
    b = _load_stage("b", 5, 8); _prefill_two_tokens(b, 5, 8)
    c = _load_stage("c", 9, 12); _prefill_two_tokens(c, 9, 12)
    import numpy as np
    cols = [s.extract_kv_column(RequestId(1), start=LayerIdx(st), end=LayerIdx(en), position=1)
            for s, st, en in [(a, 1, 4), (b, 5, 8), (c, 9, 12)]]
    m = max(len(x) for x in cols)
    padded = [np.frombuffer(x.ljust(m, b"\0"), np.uint8) for x in cols]
    P = padded[0] ^ padded[1] ^ padded[2]
    rec_b = (padded[0] ^ padded[2] ^ P).tobytes()[: len(cols[1])]
    assert rec_b == cols[1]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv-py39/bin/python -m pytest tests/test_parity_recovery.py -m slow -v`
Expected: FAIL — `AttributeError: 'StageRunner' object has no attribute 'export_kv'`

- [ ] **Step 3: Implement the three helpers**

Add to `radp/worker/stage_runner.py`. Algorithm (implementer verifies exact DynamicCache attribute names against the installed transformers — `key_cache`/`value_cache` are lists indexed by global layer idx):

```python
import numpy as np  # add to imports

    def _stage_layer_indices(self, start, end):
        return list(range(int(start) - 1, int(end)))  # 0-based global indices

    def extract_kv_column(self, request_id, *, start, end, position) -> bytes:
        cache = self._kv_cache[(request_id, (int(start), int(end)))]
        parts = []
        for L in self._stage_layer_indices(start, end):
            k = cache.key_cache[L][:, :, position:position + 1, :]
            v = cache.value_cache[L][:, :, position:position + 1, :]
            parts.append(k.cpu().contiguous().view(torch.float16).numpy().tobytes()
                         if k.dtype == torch.float16
                         else k.cpu().contiguous().numpy().tobytes())
            parts.append(v.cpu().contiguous().numpy().tobytes())
        return b"".join(parts)

    def export_kv(self, request_id, *, start, end) -> bytes:
        cache = self._kv_cache[(request_id, (int(start), int(end)))]
        parts = []
        for L in self._stage_layer_indices(start, end):
            parts.append(cache.key_cache[L].cpu().contiguous().numpy().tobytes())
            parts.append(cache.value_cache[L].cpu().contiguous().numpy().tobytes())
        return b"".join(parts)

    def install_kv(self, request_id, *, start, end, kv_bytes, num_positions) -> None:
        from transformers import DynamicCache
        layers = self._stage_layer_indices(start, end)
        cfg = self._arch_config()  # n_heads, head_dim, np_dtype (see note)
        per = 1 * cfg.n_heads * num_positions * cfg.head_dim
        itemsize = np.dtype(cfg.np_dtype).itemsize
        buf = np.frombuffer(kv_bytes, dtype=cfg.np_dtype)
        cache = DynamicCache()
        off = 0
        # DynamicCache expects layers appended in order 0..max; fill non-stage
        # layers with the existing cache if present, else the stage builds only
        # its own slots (mirrors how run() populates only this stage's layers).
        for L in layers:
            def take():
                nonlocal off
                arr = buf[off:off + per].reshape(1, cfg.n_heads, num_positions, cfg.head_dim)
                off += per
                return torch.from_numpy(arr.copy()).to(self.torch_device)
            k, v = take(), take()
            cache.update(k, v, L)  # verify update() signature; else set key_cache[L]
        self._kv_cache[(request_id, (int(start), int(end)))] = cache
```

Note on `_arch_config()`: add a small helper returning `n_heads`, `head_dim`, and the numpy dtype matching `self.dtype` (`float16→np.float16`, `float32→np.float32`), read from `AutoConfig.from_pretrained(self._model_id)` (cache it). The exact DynamicCache construction API (`.update(k,v,layer_idx)` vs assigning `.key_cache`/`.value_cache`) must be verified against transformers 4.50.3 — pin it with the round-trip test.

- [ ] **Step 4: Run to verify pass**

Run: `.venv-py39/bin/python -m pytest tests/test_parity_recovery.py::test_extract_install_roundtrip tests/test_parity_recovery.py::test_xor_reconstructs_stage_column -m slow -v`
Expected: PASS (2 tests). If the DynamicCache API differs, fix `install_kv` until the round-trip passes — the test is the contract.

- [ ] **Step 5: Commit**

```bash
git add radp/worker/stage_runner.py tests/test_parity_recovery.py
git commit -m "feat(parity): worker KV helpers — extract_kv_column / export_kv / install_kv (raw bytes)"
# + trailer
```

---

## Task 3: proto — MirrorKV / FetchKV / LoadKV

**Files:**
- Modify: `radp/common/proto/radp.proto`
- (regenerate) `radp/common/proto/radp_pb2.py`, `radp_pb2_grpc.py`

**Interfaces:**
- Produces messages/RPCs:
  - `CoordinatorService.MirrorKV(MirrorKVRequest) → MirrorKVResponse`
  - `WorkerService.FetchKV(FetchKVRequest) → FetchKVResponse`
  - `WorkerService.LoadKV(LoadKVRequest) → LoadKVResponse`

- [ ] **Step 1: Add messages + RPCs to `radp.proto`**

Under `service WorkerService { ... }` add:
```proto
  rpc FetchKV (FetchKVRequest) returns (FetchKVResponse);
  rpc LoadKV  (LoadKVRequest)  returns (LoadKVResponse);
```
Under `service CoordinatorService { ... }` add:
```proto
  rpc MirrorKV (MirrorKVRequest) returns (MirrorKVResponse);
```
Add messages (place near MirrorActivationRequest):
```proto
message MirrorKVRequest {
  int32 request_id  = 1;
  int32 start_layer = 2;
  int32 end_layer   = 3;
  int32 position    = 4;
  bytes kv_bytes    = 5;   // raw fp16 column bytes (K then V per layer)
  bool  is_prefill  = 6;
  int32 num_positions = 7; // positions covered by kv_bytes (1 for decode; prompt_len for prefill)
}
message MirrorKVResponse {}

message FetchKVRequest {
  int32 request_id     = 1;
  int32 start_layer    = 2;
  int32 end_layer      = 3;
  int32 up_to_position = 4;  // inclusive
}
message FetchKVResponse {
  bytes kv_bytes     = 1;    // raw fp16, positions 0..up_to_position
  int32 num_positions = 2;
}

message LoadKVRequest {
  int32 request_id   = 1;
  int32 start_layer  = 2;
  int32 end_layer    = 3;
  bytes kv_bytes     = 4;
  int32 num_positions = 5;
}
message LoadKVResponse {}
```

- [ ] **Step 2: Regenerate stubs**

Run:
```bash
.venv/bin/python -m grpc_tools.protoc -I radp/common/proto \
  --python_out=radp/common/proto --grpc_python_out=radp/common/proto \
  radp/common/proto/radp.proto
```
Then apply the package-relative import patch the repo uses (see `deploy/roles/common/tasks/main.yml` "Patch generated stub"): in `radp_pb2_grpc.py` the `import radp_pb2` line must become `from . import radp_pb2` (match the existing patched form).

- [ ] **Step 3: Verify import**

Run: `.venv/bin/python -c "from radp.common.proto import radp_pb2, radp_pb2_grpc; radp_pb2.MirrorKVRequest(); radp_pb2.FetchKVRequest(); radp_pb2.LoadKVRequest(); print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add radp/common/proto/radp.proto radp/common/proto/radp_pb2.py radp/common/proto/radp_pb2_grpc.py
git commit -m "feat(parity): proto — MirrorKV / FetchKV / LoadKV RPCs"
# + trailer
```

---

## Task 4: Worker server wiring (MirrorKV push + FetchKV/LoadKV handlers)

**Files:**
- Modify: `radp/worker/server.py`

**Interfaces:**
- Consumes: Task 2 helpers, Task 3 messages, existing `_CoordDispatcher` (has `_stub`, `submit_mirror`), `_WorkerServicer`.
- Produces:
  - `_CoordDispatcher.submit_kv(*, request_id, start_layer, end_layer, position, kv_bytes, is_prefill, num_positions) -> None` (fire-and-forget, mirrors `submit_mirror`).
  - `_WorkerServicer.FetchKV(request, context)`, `_WorkerServicer.LoadKV(request, context)`.
  - In `RunStage`, after the local stage runs and appends KV, if `os.environ.get("RADP_PARITY")` and `start_layer > 1` and not `replay_only`: extract this position's column and `submit_kv`.

- [ ] **Step 1: Write failing test (in-process worker)**

```python
# append to tests/test_parity_recovery.py
def test_worker_fetchkv_loadkv_roundtrip():
    """FetchKV bytes installed via LoadKV reproduce KV bit-exact through gRPC-less servicer."""
    from radp.worker.server import _WorkerServicer
    from radp.common.proto import radp_pb2
    from radp.common.types import RequestId, LayerIdx
    import torch

    src = _load_stage("s", 5, 8); _prefill_two_tokens(src, 5, 8)
    src_srv = _WorkerServicer(src, None)
    resp = src_srv.FetchKV(
        radp_pb2.FetchKVRequest(request_id=1, start_layer=5, end_layer=8, up_to_position=3),
        None,
    )
    dst = _load_stage("d", 5, 8)
    dst_srv = _WorkerServicer(dst, None)
    dst_srv.LoadKV(
        radp_pb2.LoadKVRequest(request_id=1, start_layer=5, end_layer=8,
                               kv_bytes=resp.kv_bytes, num_positions=resp.num_positions),
        None,
    )
    for L in range(4, 8):
        assert torch.equal(src._kv_cache[(RequestId(1), (5, 8))].key_cache[L],
                           dst._kv_cache[(RequestId(1), (5, 8))].key_cache[L])
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv-py39/bin/python -m pytest tests/test_parity_recovery.py::test_worker_fetchkv_loadkv_roundtrip -m slow -v`
Expected: FAIL — `AttributeError: '_WorkerServicer' object has no attribute 'FetchKV'`

- [ ] **Step 3: Implement**

In `_CoordDispatcher` (after `submit_mirror`):
```python
    def submit_kv(self, *, request_id, start_layer, end_layer, position,
                  kv_bytes, is_prefill, num_positions):
        with contextlib.suppress(RuntimeError):
            return self._mirror_exec.submit(
                self._send_kv, request_id, start_layer, end_layer,
                position, kv_bytes, is_prefill, num_positions,
            )
        return None

    def _send_kv(self, request_id, start_layer, end_layer, position,
                 kv_bytes, is_prefill, num_positions):
        try:
            self._stub.MirrorKV(radp_pb2.MirrorKVRequest(
                request_id=request_id, start_layer=start_layer, end_layer=end_layer,
                position=position, kv_bytes=kv_bytes, is_prefill=is_prefill,
                num_positions=num_positions), timeout=5.0)
        except Exception as e:  # noqa: BLE001
            log.debug("MirrorKV push req=%d pos=%d failed (%s); ignored",
                      request_id, position, e)
```

In `_WorkerServicer`, add handlers:
```python
    def FetchKV(self, request, context):
        num = int(request.up_to_position) + 1
        kv = self._runner.export_kv(
            RequestId(request.request_id),
            start=LayerIdx(request.start_layer), end=LayerIdx(request.end_layer))
        return radp_pb2.FetchKVResponse(kv_bytes=kv, num_positions=num)

    def LoadKV(self, request, context):
        self._runner.install_kv(
            RequestId(request.request_id),
            start=LayerIdx(request.start_layer), end=LayerIdx(request.end_layer),
            kv_bytes=bytes(request.kv_bytes), num_positions=int(request.num_positions))
        return radp_pb2.LoadKVResponse()
```

In `RunStage`, after the existing mirror-push block and the local run (find where `result = self._runner.run(...)` completes for the local-stage path), add — gated:
```python
        if (os.environ.get("RADP_PARITY")
                and int(request.start_layer) > 1 and not replay_only):
            with contextlib.suppress(Exception):
                col = self._runner.extract_kv_column(
                    RequestId(request.request_id),
                    start=LayerIdx(request.start_layer), end=LayerIdx(request.end_layer),
                    position=int(request.position))
                if self._mirror is not None:
                    self._mirror.submit_kv(
                        request_id=int(request.request_id),
                        start_layer=int(request.start_layer),
                        end_layer=int(request.end_layer),
                        position=int(request.position), kv_bytes=col,
                        is_prefill=bool(request.is_prefill),
                        num_positions=1 if not request.is_prefill else -1)
```
(`num_positions=-1` for prefill → the servicer/coord treats prefill as its own multi-position block; for the fleet prototype the reconstruction fetches full KV via FetchKV so prefill column length is self-describing via its byte length. Keep decode `num_positions=1`.)

Register the new servicer methods in the gRPC server (they're picked up automatically by `add_WorkerServiceServicer_to_server` once defined on the class).

- [ ] **Step 4: Run to verify pass**

Run: `.venv-py39/bin/python -m pytest tests/test_parity_recovery.py -m slow -v`
Expected: PASS (all round-trip tests so far).

- [ ] **Step 5: Commit**

```bash
git add radp/worker/server.py tests/test_parity_recovery.py
git commit -m "feat(parity): worker MirrorKV push (RADP_PARITY-gated) + FetchKV/LoadKV handlers"
# + trailer
```

---

## Task 5: Coordinator server — build ParityCache + MirrorKV handler + WorkerClient.fetch_kv/load_kv

**Files:**
- Modify: `radp/coordinator/server.py`
- Modify: `radp/common/protocol.py`

**Interfaces:**
- Consumes: Task 1 `ParityCache`, Task 3 messages.
- Produces:
  - Coordinator servicer method `MirrorKV(request, context)` → `gateway.record_kv(...)` → `parity_cache.xor_in`.
  - `RequestGateway.record_kv(request_id, start_layer, end_layer, position, kv_bytes)` (thin, → parity_cache).
  - `RequestGateway.parity_cache: ParityCache` built with `num_stages = len(placement)`.
  - `WorkerClient.fetch_kv(*, request_id, start_layer, end_layer, up_to_position) -> tuple[bytes, int]`
  - `WorkerClient.load_kv(*, request_id, start_layer, end_layer, kv_bytes, num_positions) -> None`

- [ ] **Step 1: Write failing test**

```python
# tests/test_parity_cache.py  (add — pure logic, no model)
def test_gateway_record_kv_feeds_parity(monkeypatch):
    from radp.coordinator.gateway import RequestGateway
    from radp.common.types import Stage, LayerIdx, DeviceId
    gw = RequestGateway(
        placement=[Stage(LayerIdx(1), LayerIdx(4), DeviceId("a")),
                   Stage(LayerIdx(5), LayerIdx(8), DeviceId("b"))],
        recovery={}, worker_addresses={}, model_id="facebook/opt-125m",
    )
    assert gw.parity_cache.num_stages == 2
    gw.record_kv(RequestId(1), 1, 4, 0, bytes([1, 2]))
    gw.record_kv(RequestId(1), 5, 8, 0, bytes([3, 4]))
    assert gw.parity_cache.is_complete(RequestId(1), 0)
    assert gw.parity_cache.get_parity(RequestId(1), 0) == bytes([1 ^ 3, 2 ^ 4])
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_parity_cache.py::test_gateway_record_kv_feeds_parity -v`
Expected: FAIL — `AttributeError: 'RequestGateway' object has no attribute 'parity_cache'`

- [ ] **Step 3: Implement**

`gateway.py` `__init__` (near `self.cache = ActivationCache(...)`):
```python
from radp.coordinator.parity_cache import ParityCache  # top import
        self.parity_cache = ParityCache(num_stages=len(placement))
```
`gateway.py` new method:
```python
    def record_kv(self, request_id, start_layer, end_layer, position, kv_bytes):
        self.parity_cache.xor_in(
            request_id, (int(start_layer), int(end_layer)), int(position), kv_bytes)
```
`server.py` coordinator servicer — add `MirrorKV`:
```python
    def MirrorKV(self, request, context):
        gw = self._server._ensure_gateway()  # match how MirrorActivation reaches the gateway
        gw.record_kv(RequestId(request.request_id), request.start_layer,
                     request.end_layer, request.position, bytes(request.kv_bytes))
        return radp_pb2.MirrorKVResponse()
```
(Follow the exact pattern the existing `MirrorActivation` servicer uses to reach the gateway — replicate that wiring.)
`protocol.py` `WorkerClient`:
```python
    def fetch_kv(self, *, request_id, start_layer, end_layer, up_to_position):
        resp = self._require_stub().FetchKV(radp_pb2.FetchKVRequest(
            request_id=int(request_id), start_layer=int(start_layer),
            end_layer=int(end_layer), up_to_position=int(up_to_position)))
        return bytes(resp.kv_bytes), int(resp.num_positions)

    def load_kv(self, *, request_id, start_layer, end_layer, kv_bytes, num_positions):
        self._require_stub().LoadKV(radp_pb2.LoadKVRequest(
            request_id=int(request_id), start_layer=int(start_layer),
            end_layer=int(end_layer), kv_bytes=kv_bytes,
            num_positions=int(num_positions)))
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_parity_cache.py -v`
Expected: PASS (all, incl. new).

- [ ] **Step 5: Commit**

```bash
git add radp/coordinator/server.py radp/coordinator/gateway.py radp/common/protocol.py tests/test_parity_cache.py
git commit -m "feat(parity): coordinator MirrorKV handler + gateway.record_kv + WorkerClient fetch/load_kv"
# + trailer
```

---

## Task 6: gateway `_recover_parity` + `recovery_mode="parity"`

**Files:**
- Modify: `radp/coordinator/gateway.py`
- Test: `tests/test_parity_recovery.py`

**Interfaces:**
- Consumes: `parity_cache` (Task 5), `WorkerClient.fetch_kv/load_kv` (Task 5), existing `_attribute_chain_failure`, `mark_dead`, `_rewire_chain`, `_recover_surgical` (fallback), `current_plan`.
- Produces: `_recover_parity(request_id, head_stage, error, current_position) -> tuple[Stage, Any]`; and in `__init__` accept `"parity"` in the `recovery_mode` validation set; in `_recover_from_chain_failure`, branch `if self.recovery_mode == "parity": return self._recover_parity(...)`.

- [ ] **Step 1: Write failing end-to-end test**

```python
# append to tests/test_parity_recovery.py — mirrors test_surgical_recovery structure
def test_parity_recovery_matches_reference():
    """Full in-process chain: parity-reconstruct a killed interior stage's KV,
    assert the generated sequence equals the no-failure reference."""
    # Reuse the mirror harness from tests/test_surgical_recovery.py; build the
    # gateway with recovery_mode="parity", drive N tokens, inject a mid-stage
    # crash on the interior victim at position P, and assert:
    #   (a) recovery took the parity branch (no _replay_stage_history calls),
    #   (b) decoded token ids == reference ids.
    # See tests/test_surgical_recovery.py for the harness scaffolding to copy.
    pytest.skip("implement against the surgical-recovery harness (Task 6 body)")
```
(Replace the skip with the real body by copying `tests/test_surgical_recovery.py`'s harness and setting `recovery_mode="parity"`, plus arming the KV mirror. The assertion is sequence-equality vs the wired reference — same contract as the surgical test.)

- [ ] **Step 2: Run to verify it fails / skips**

Run: `.venv-py39/bin/python -m pytest tests/test_parity_recovery.py::test_parity_recovery_matches_reference -m slow -v`
Expected: SKIP initially, then FAIL once the body is written (no `_recover_parity`).

- [ ] **Step 3: Implement `_recover_parity`**

```python
    def _recover_parity(self, request_id, head_stage, error, current_position):
        """Zero-forward recovery: reconstruct the dead stage's KV by byte-XOR
        of survivors' KV with the maintained parity blob, install into the
        promoted backup. Falls back to surgical if parity is incomplete for
        any needed position or a FetchKV fails."""
        dead_stage = self._attribute_chain_failure(head_stage, error)
        if dead_stage.device not in self._dead:
            self.mark_dead(dead_stage.device)
        dead_key = (int(dead_stage.start_layer), int(dead_stage.end_layer))

        # Completeness gate → fall back to surgical (which itself ladders to full).
        for pos in range(current_position):
            if not self.parity_cache.is_complete(request_id, pos):
                log.warning("request=%d parity incomplete at pos %d; fallback to surgical",
                            request_id, pos)
                return self._recover_surgical(request_id, head_stage, error, current_position)

        backup_dev = self.recovery.get(dead_stage.device)
        backup_addr = self.worker_addresses.get(backup_dev)
        with WorkerClient(backup_addr) as c:
            c.promote_backup(for_device_id=dead_stage.device)
        self._rewire_chain()

        # Fetch survivors' KV columns (raw bytes, positions 0..P-1), XOR with P.
        survivors = [s for s in self.current_plan()
                     if (int(s.start_layer), int(s.end_layer)) != dead_key]
        try:
            surv_bytes = {}
            for s in survivors:
                addr = self.worker_addresses[s.device]
                with WorkerClient(addr) as c:
                    kv, _ = c.fetch_kv(request_id=request_id, start_layer=s.start_layer,
                                       end_layer=s.end_layer, up_to_position=current_position - 1)
                surv_bytes[(int(s.start_layer), int(s.end_layer))] = kv
        except Exception:
            log.exception("request=%d FetchKV failed; fallback to surgical", request_id)
            return self._recover_surgical(request_id, head_stage, error, current_position)

        dead_kv = self._xor_reconstruct(request_id, dead_key, survivors, surv_bytes,
                                        current_position)  # helper: per-position XOR + truncate

        backup_stage = next(s for s in self.current_plan()
                            if (int(s.start_layer), int(s.end_layer)) == dead_key)
        with WorkerClient(self.worker_addresses[backup_stage.device]) as c:
            c.load_kv(request_id=request_id, start_layer=dead_key[0], end_layer=dead_key[1],
                      kv_bytes=dead_kv, num_positions=current_position)

        # Run the failed position P live through the rewired chain (head already
        # advanced to P) — same tail as _recover_surgical.
        new_plan = self.current_plan(); new_head = new_plan[0]
        last_resp = self._replay_position_live(request_id, dead_key, current_position)
        return new_head, last_resp
```
Implement `_xor_reconstruct` (numpy byte XOR over survivors padded to max, ⊕ parity, slice each position to the dead stage's raw column length computed from `model config × dead layer count`) and reuse/extract the surgical test's "run position P live" tail as `_replay_position_live` (or inline the surgical tail). Add `"parity"` to the `recovery_mode` set in `__init__` and the branch in `_recover_from_chain_failure`.

- [ ] **Step 4: Run to verify pass + no regression**

Run:
```bash
.venv-py39/bin/python -m pytest tests/test_parity_recovery.py -m slow -v
.venv-py39/bin/python -m pytest tests/test_surgical_recovery.py tests/test_b1_ft_baselines.py tests/test_mirror_harness.py -m slow -q
```
Expected: parity test PASS; existing suites still PASS (default path unchanged).

- [ ] **Step 5: Commit**

```bash
git add radp/coordinator/gateway.py tests/test_parity_recovery.py
git commit -m "feat(parity): gateway _recover_parity (zero-forward XOR reconstruct) + parity mode"
# + trailer
```

---

## Task 7: Fleet driver — parity as a third line

**Files:**
- Modify: `experiments/b1_ft_fleet.py`
- Modify: `paper/figures/make_recovery_ttr.py`

**Interfaces:**
- Consumes: existing `b1_ft_fleet.run` structure (mode drop-in, per-P reset/arm/measure). Parity needs the workers armed with `RADP_PARITY=1` for the whole run.
- Produces: `"parity"` accepted in `--modes`; a `set_parity_env(on: bool)` that drops in/removes the worker `RADP_PARITY` drop-in + restarts workers once at run start/end; figure plots a 3rd line when `parity` fits exist.

- [ ] **Step 1: Add parity plumbing to the driver**

In `b1_ft_fleet.py`:
- Add helper `set_worker_parity(on)`: writes/removes `/etc/systemd/system/radp-worker.service.d/parity.conf` (`[Service]\nEnvironment=RADP_PARITY=1`) on all workers via ansible, then restarts workers. Call once before the sweep if `"parity"` in modes; the coordinator restart per trial already re-schedules over them.
- `set_recovery_mode` already writes the coordinator drop-in; it accepts `"parity"` unchanged (env value passed through).
- No other change — the per-P reset/arm/measure loop is mode-agnostic.

- [ ] **Step 2: Extend the figure**

In `make_recovery_ttr.py` add a `parity` entry to `STYLE` (`PALETTE["tertiary"]`, marker `"^"`, label `"parity (XOR-reconstruct, zero recompute)"`) and let the existing loop skip modes with no valid points (guard `if not xs: continue`).

- [ ] **Step 3: Manual validation (one parity trial) before the full sweep**

Run (after Task 8 deploy):
```bash
.venv/bin/python -m experiments.b1_ft_fleet --modes parity --positions 8 --out b1_ft_fleet_parity_smoke
```
Expected: 1/1 trial `fired=True index_ok=True seq_match=True`. If seq_match fails, parity is reconstructing wrong KV — STOP and debug (do not proceed to sweep).

- [ ] **Step 4: Commit**

```bash
git add experiments/b1_ft_fleet.py paper/figures/make_recovery_ttr.py
git commit -m "feat(parity): fleet driver parity line + 3-line TTR figure"
# + trailer
```

---

## Task 8: Deploy, full sweep, docs

**Files:**
- Modify: `experiments/REPORT.md`, `PHASES.md`, memory `project_advisor_pivot_ft`
- (regenerate) `paper/figures/fig_recovery_ttr.{pdf,png}`

- [ ] **Step 1: Commit + push code, then deploy**

```bash
git push origin main
cd deploy && ansible-playbook -i inventory.ini playbook.yml --tags update
```
Verify fleet HEAD + `MirrorKV`/`_recover_parity` present on a node (grep). Restart coordinator; confirm schedule.

- [ ] **Step 2: Full 3-mode sweep**

```bash
.venv/bin/python -m experiments.b1_ft_fleet \
  --modes full_replay,surgical,parity --positions 4,8,16,24,32 --out b1_ft_fleet_parity
```
Expected: 15/15 trials valid; parity slope ≪ surgical's ~15 ms/pos. Regenerate the figure.

- [ ] **Step 3: Write up**

REPORT §B1-FLEET: add the parity row/fits + the compute-vs-network interpretation. PHASES: append a Phase B1-PARITY section. Update memory `project_advisor_pivot_ft`. Commit (results JSON stays gitignored).

- [ ] **Step 4: Restore fleet** (optional, if no more runs)

Remove `RADP_PARITY` / recovery / fault drop-ins, revert `chain_mode: async`, restart. Or leave for continued experiments (note state).

---

## Self-Review

- **Spec coverage:** §2 approach A → Tasks 1–6. §3 data flow (ship→P→XOR→load) → Tasks 4 (ship), 1/5 (P), 6 (XOR+load). §4 proto/ParityCache/worker helpers/gateway → Tasks 3/1/2/6. §4 config wiring → Tasks 4/5/7. §5 fallback ladder → Task 6 completeness gate + FetchKV-fail → surgical. §6 tests → Tasks 1,2,4,6. §7 limits (single-fault, no optimization) → honored (no multi-fault code). §8 success criteria → Tasks 6 (bit/seq), 8 (slope). Covered.
- **Placeholder scan:** Task 6 test body is intentionally deferred to "copy the surgical harness" — the surgical test exists and is the concrete template; the assertion (sequence-equality) is specified. Task 2's DynamicCache API is pinned by the round-trip test rather than guessed (honest — transformers API verified at impl time). All other steps have concrete code.
- **Type consistency:** `extract_kv_column/export_kv/install_kv` signatures consistent across Tasks 2/4/6. `fetch_kv` returns `(bytes, int)` (Task 5) consumed in Task 6. `record_kv`/`xor_in` arg order consistent Tasks 1/5. `num_positions` threaded through MirrorKV/FetchKV/LoadKV consistently.

Two honest deferrals (not placeholders): (1) exact DynamicCache construction API — pinned by Task 2's round-trip test; (2) Task 6 test harness — copy the existing `test_surgical_recovery.py` scaffolding. Both are concrete-by-reference, not vague.
