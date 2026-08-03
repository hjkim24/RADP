"""Worker KV helpers: DynamicCache <-> raw bytes round-trip (parity recovery,
Task 2). Slow/model tests only -- see docs/superpowers/specs/2026-07-20-parity-
recovery-design.md for the full mechanism these helpers feed into.
"""
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
    """Drive prefill + one decode so the stage KV has >=2 positions.

    NOTE: stage_runner.run() expects the additive 4D causal mask that
    RequestGateway._prefill/_decode_step build via
    _prepare_4d_causal_attention_mask before calling into a stage (see
    radp/coordinator/gateway.py). A plain 2D mask of ones is only the
    tokenizer-level mask; passing it straight through makes OPTAttention's
    `attention_mask[:, :, :, :key_states.shape[-2]]` slice a 2D tensor with
    4 indices (IndexError), unrelated to this task's new helpers. Build the
    4D mask here the same way the gateway does, to drive a real forward
    pass end-to-end.
    """
    import torch
    from transformers.modeling_attn_mask_utils import _prepare_4d_causal_attention_mask
    from radp.common.tensor_io import encode

    hidden = torch.randn(1, 3, 768)          # opt-125m hidden=768
    mask2d = torch.ones(1, 3)
    mask4d = _prepare_4d_causal_attention_mask(mask2d, (1, 3), hidden, past_key_values_length=0)
    blob = encode({"hidden_states": hidden, "attention_mask": mask4d})
    runner.run(RequestId(1), blob, start=LayerIdx(start), end=LayerIdx(end), is_prefill=True)

    hidden2 = torch.randn(1, 1, 768)
    mask2d_2 = torch.ones(1, 4)
    mask4d_2 = _prepare_4d_causal_attention_mask(mask2d_2, (1, 1), hidden2, past_key_values_length=3)
    blob2 = encode({"hidden_states": hidden2, "attention_mask": mask4d_2})
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


# --- Task 4: worker server wiring (MirrorKV push + FetchKV/LoadKV) ---------


def test_worker_fetchkv_loadkv_roundtrip():
    """FetchKV bytes installed via LoadKV reproduce KV bit-exact through gRPC-less servicer."""
    from radp.worker.server import _WorkerServicer
    from radp.common.proto import radp_pb2
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


class _FakeCoordDispatcher:
    """Records submit_kv calls. submit_mirror is a no-op stub — the existing
    input-activation mirror push isn't under test here."""

    def __init__(self) -> None:
        self.kv_calls: list[tuple] = []

    def submit_mirror(self, **kwargs):
        return None

    def submit_kv(self, *, request_id, start_layer, end_layer, position,
                  kv_bytes, is_prefill, num_positions):
        self.kv_calls.append(
            (request_id, start_layer, end_layer, position, kv_bytes, is_prefill, num_positions)
        )
        return None


class _FakeParityStageRunner:
    """Drop-in StageRunner double for the local-run (non-head) path. Tracks a
    fake per-(request, stage) seq_len so kv_seq_len reflects run() calls
    without any real model: prefill activation is the literal token count
    (e.g. b"3" -> 3 new positions), decode always adds exactly one."""

    has_head = False
    device_id = "fake"

    def __init__(self) -> None:
        self._seq_len: dict[tuple, int] = {}
        self.extract_calls: list[tuple] = []

    def run(self, *, request_id, activation_blob, start, end, is_prefill):
        key = (int(request_id), int(start), int(end))
        if is_prefill:
            self._seq_len[key] = int(activation_blob.decode())
        else:
            self._seq_len[key] = self._seq_len.get(key, 0) + 1
        return b"OUT:" + activation_blob

    def kv_seq_len(self, request_id, *, start, end):
        return self._seq_len.get((int(request_id), int(start), int(end)), 0)

    def extract_kv_column(self, request_id, *, start, end, position):
        self.extract_calls.append((int(request_id), int(start), int(end), position))
        return f"col{position}".encode()


class _FakeParityHeadStageRunner(_FakeParityStageRunner):
    """Same seq_len tracking, but drives the tail-sample (has_head) path."""

    has_head = True

    def run_tail_and_sample(self, *, request_id, activation_blob, start, end, is_prefill):
        self.run(request_id=request_id, activation_blob=activation_blob,
                  start=start, end=end, is_prefill=is_prefill)
        return 999


def _run_stage_request(**overrides):
    from radp.common.proto import radp_pb2
    fields = dict(
        activation=b"3", request_id=1, is_prefill=True,
        start_layer=5, end_layer=8, position=0,
    )
    fields.update(overrides)
    return radp_pb2.RunStageRequest(**fields)


def test_worker_pushes_kv_column_per_new_slot_local_run(monkeypatch):
    """Local-run path: RADP_PARITY on, non-head stage -> one submit_kv per
    newly-added absolute KV slot (all of 0..N-1 on prefill, just the new
    slot on decode)."""
    from radp.worker.server import _WorkerServicer

    monkeypatch.setenv("RADP_PARITY", "1")
    runner = _FakeParityStageRunner()
    mirror = _FakeCoordDispatcher()
    servicer = _WorkerServicer(runner, mirror)

    servicer.RunStage(_run_stage_request(activation=b"3", is_prefill=True, position=0), None)
    assert [c[3] for c in mirror.kv_calls] == [0, 1, 2]
    assert all(c[1] == 5 and c[2] == 8 and c[5] is True and c[6] == 1 for c in mirror.kv_calls)
    assert [c[4] for c in mirror.kv_calls] == [b"col0", b"col1", b"col2"]
    mirror.kv_calls.clear()

    servicer.RunStage(_run_stage_request(activation=b"", is_prefill=False, position=1), None)
    assert [c[3] for c in mirror.kv_calls] == [3]
    assert mirror.kv_calls[0][5] is False and mirror.kv_calls[0][6] == 1


def test_worker_pushes_kv_column_per_new_slot_tail_sample(monkeypatch):
    """Tail-sample (has_head) path gets the same per-slot push wiring."""
    from radp.worker.server import _WorkerServicer

    monkeypatch.setenv("RADP_PARITY", "1")
    runner = _FakeParityHeadStageRunner()
    mirror = _FakeCoordDispatcher()
    servicer = _WorkerServicer(runner, mirror)

    servicer.RunStage(_run_stage_request(activation=b"2", is_prefill=True, position=0), None)
    assert [c[3] for c in mirror.kv_calls] == [0, 1]
    mirror.kv_calls.clear()

    servicer.RunStage(_run_stage_request(activation=b"", is_prefill=False, position=1), None)
    assert [c[3] for c in mirror.kv_calls] == [2]


def test_worker_no_kv_push_when_parity_unset(monkeypatch):
    """Default path (RADP_PARITY unset) never calls submit_kv."""
    from radp.worker.server import _WorkerServicer

    monkeypatch.delenv("RADP_PARITY", raising=False)
    runner = _FakeParityStageRunner()
    mirror = _FakeCoordDispatcher()
    servicer = _WorkerServicer(runner, mirror)

    servicer.RunStage(_run_stage_request(activation=b"3", is_prefill=True, position=0), None)
    servicer.RunStage(_run_stage_request(activation=b"", is_prefill=False, position=1), None)
    assert mirror.kv_calls == []


def test_worker_no_kv_push_on_head_stage(monkeypatch):
    """start_layer == 1 (head, coord-sourced) never ships KV even with
    RADP_PARITY on."""
    from radp.worker.server import _WorkerServicer

    monkeypatch.setenv("RADP_PARITY", "1")
    runner = _FakeParityStageRunner()
    mirror = _FakeCoordDispatcher()
    servicer = _WorkerServicer(runner, mirror)

    servicer.RunStage(
        _run_stage_request(activation=b"3", is_prefill=True, start_layer=1, end_layer=4, position=0),
        None,
    )
    assert mirror.kv_calls == []


def test_worker_no_kv_push_when_replay_only(monkeypatch):
    """replay_only calls (KV cache rebuild, not real generation) never push."""
    from radp.worker.server import _WorkerServicer

    monkeypatch.setenv("RADP_PARITY", "1")
    runner = _FakeParityStageRunner()
    mirror = _FakeCoordDispatcher()
    servicer = _WorkerServicer(runner, mirror)

    servicer.RunStage(
        _run_stage_request(activation=b"3", is_prefill=True, position=0, replay_only=True),
        None,
    )
    assert mirror.kv_calls == []


# --- Task 5: coordinator wiring (gateway.record_kv -> ParityCache) ---------
#
# RequestGateway.__init__ calls load_model(), so this can't live in the
# pure-logic tests/test_parity_cache.py (no torch there) -- it belongs here,
# slow-marked, run under .venv-py39.
#
# CONTROLLER REFINEMENT: the head stage (placement[0], start_layer==1) is
# coord-sourced and never ships KV (see test_worker_no_kv_push_on_head_stage
# above). Only non-head stages contribute to parity, so
# ParityCache.num_stages must be len(placement) - 1, NOT len(placement).
# With a 3-stage placement (1 head + 2 non-head), num_stages == 2.
def test_gateway_record_kv_feeds_parity():
    from radp.coordinator.gateway import RequestGateway
    from radp.common.types import Stage, LayerIdx, DeviceId

    gw = RequestGateway(
        placement=[Stage(LayerIdx(1), LayerIdx(4), DeviceId("head")),
                   Stage(LayerIdx(5), LayerIdx(8), DeviceId("b")),
                   Stage(LayerIdx(9), LayerIdx(12), DeviceId("c"))],
        recovery={},
        # RequestGateway.__init__ requires an address for every placement
        # device (raises ValueError otherwise); channels are opened lazily
        # so these never actually get dialed in this test.
        worker_addresses={
            DeviceId("head"): "localhost:0",
            DeviceId("b"): "localhost:0",
            DeviceId("c"): "localhost:0",
        },
        model_id=MODEL,
    )
    assert gw.parity_cache.num_stages == 2          # non-head count = len(placement)-1
    gw.record_kv(RequestId(1), 5, 8, 0, bytes([1, 2]))   # non-head stage b
    gw.record_kv(RequestId(1), 9, 12, 0, bytes([3, 4]))  # non-head stage c
    assert gw.parity_cache.is_complete(RequestId(1), 0)
    assert gw.parity_cache.get_parity(RequestId(1), 0) == bytes([1 ^ 3, 2 ^ 4])


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
    # non-head stages by start_layer: (5,8)->0, (9,12)->1
    assert gw._parity_coeff == {(5, 8): 0, (9, 12): 1}
    A, B = bytes([1, 2]), bytes([3, 4])
    gw.record_kv(RequestId(1), 5, 8, 0, A)
    gw.record_kv(RequestId(1), 9, 12, 0, B)
    assert gw.parity_cache.get_parity(RequestId(1), 0) == bytes([1 ^ 3, 2 ^ 4])
    expect_q = (gf_mul_scalar(gf_pow(2, 0), np.frombuffer(A, np.uint8))
                ^ gf_mul_scalar(gf_pow(2, 1), np.frombuffer(B, np.uint8)))
    assert gw.parity_cache.get_qparity(RequestId(1), 0) == expect_q.tobytes()


# --- Task 6: end-to-end zero-forward parity KV reconstruction --------------
import logging
import time

import numpy as np
import torch

from experiments._harness import (
    deploy,
    in_process_cluster_with_mirror,
    wire_chain,
)
from radp.common.types import Stage as _Stage
from radp.coordinator.gateway import RequestGateway


def _cfg():
    """3 stages (head + 2 non-head); the only interior victim is the FIRST
    non-head stage, whose non-head survivor is DOWNSTREAM (same slot count)."""
    ids = ["worker-a", "worker-b", "worker-c"]
    placement = [
        _Stage(LayerIdx(1), LayerIdx(4), DeviceId("worker-a")),
        _Stage(LayerIdx(5), LayerIdx(8), DeviceId("worker-b")),
        _Stage(LayerIdx(9), LayerIdx(12), DeviceId("worker-c")),
    ]
    recovery = {
        DeviceId("worker-a"): DeviceId("worker-b"),
        DeviceId("worker-b"): DeviceId("worker-c"),
        DeviceId("worker-c"): DeviceId("worker-a"),
    }
    return ids, placement, recovery


def _cfg4():
    """4 stages (head + 3 non-head) so a MIDDLE non-head victim exists: killing
    worker-c[7..9] leaves an UPSTREAM non-head survivor (worker-b, already
    advanced past the failed position -> one extra KV slot) and a DOWNSTREAM
    one (worker-d, still at the victim's slot count)."""
    ids = ["worker-a", "worker-b", "worker-c", "worker-d"]
    placement = [
        _Stage(LayerIdx(1), LayerIdx(3), DeviceId("worker-a")),
        _Stage(LayerIdx(4), LayerIdx(6), DeviceId("worker-b")),
        _Stage(LayerIdx(7), LayerIdx(9), DeviceId("worker-c")),
        _Stage(LayerIdx(10), LayerIdx(12), DeviceId("worker-d")),
    ]
    recovery = {
        DeviceId("worker-a"): DeviceId("worker-b"),
        DeviceId("worker-b"): DeviceId("worker-c"),
        DeviceId("worker-c"): DeviceId("worker-d"),
        DeviceId("worker-d"): DeviceId("worker-a"),
    }
    return ids, placement, recovery


def _healthy_reference(prompt, n, cfg=_cfg):
    ids, placement, recovery = cfg()
    with in_process_cluster_with_mirror(ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL,
        )
        attach(gw)
        ref = list(gw.generate(prompt, max_tokens=n))
        gw.close()
    return ref


def _kv_layers(buf, n_layers, n_heads, head_dim, np_dtype):
    """Split layer-major export_kv bytes into per-layer (K, V) numpy arrays."""
    arr = np.frombuffer(buf, dtype=np_dtype)
    N = arr.size // (n_layers * 2 * n_heads * head_dim)
    arr = arr.reshape(n_layers, 2, n_heads, N, head_dim)
    return [(arr[li, 0], arr[li, 1]) for li in range(n_layers)]


def _assert_parity_recovery(monkeypatch, caplog, *, cfg, victim_dev, backup_dev):
    """Drive one zero-forward parity recovery and assert all three gates:
    (a) the PARITY branch runs and never falls back to surgical;
    (b) the reconstructed backup KV is bit-identical to the victim's, per
    layer for K and V; (c) the recovered sequence equals the wired reference.

    ``victim_dev``/``backup_dev`` are device ids; the victim's layer range is read off
    the placement, and ``backup_dev`` is where ``recovery`` promotes it.
    """
    from radp.coordinator.gateway import RequestGateway

    monkeypatch.setenv("RADP_PARITY", "1")
    prompt, n, kill_at = "The quick brown fox", 12, 4
    reference = _healthy_reference(prompt, n, cfg)

    ids, placement, recovery = cfg()
    victim_stage = next(s for s in placement if s.device == DeviceId(victim_dev))
    dead_key = (int(victim_stage.start_layer), int(victim_stage.end_layer))
    with in_process_cluster_with_mirror(ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL,
            recovery_mode="parity",
        )
        attach(gw)
        gw.generate(prompt, max_tokens=2)  # warmup BEFORE installing the fault

        # Spy: parity must NOT fall back to surgical.
        surgical_calls = {"n": 0}
        orig_surgical = gw._recover_surgical

        def spy_surgical(*a, **k):
            surgical_calls["n"] += 1
            return orig_surgical(*a, **k)

        gw._recover_surgical = spy_surgical

        # Capture the KV bytes the gateway installs onto the promoted backup.
        c_runner = servers[DeviceId(backup_dev)].runner
        orig_install = c_runner.install_kv
        installed: dict = {}

        def spy_install(request_id, *, start, end, kv_bytes, num_positions):
            if (int(start), int(end)) == dead_key:
                installed["bytes"] = bytes(kv_bytes)
                installed["N"] = int(num_positions)
            return orig_install(
                request_id, start=start, end=end,
                kv_bytes=kv_bytes, num_positions=num_positions,
            )

        c_runner.install_kv = spy_install

        rid = gw.new_request_id()
        b_runner = servers[DeviceId(victim_dev)].runner
        orig_run = b_runner.run
        state = {"calls": 0, "tripped": False}
        victim: dict = {}

        def flaky_run(request_id, activation_blob, *, start, end, is_prefill):
            if int(request_id) == int(rid) and (int(start), int(end)) == dead_key:
                state["calls"] += 1  # call k -> position k-1 (prefill = pos 0)
                if state["calls"] - 1 == kill_at and not state["tripped"]:
                    state["tripped"] = True
                    # Snapshot the victim's KV (slots 0..N-1) BEFORE crashing.
                    victim["N"] = b_runner.kv_seq_len(
                        rid, start=LayerIdx(dead_key[0]), end=LayerIdx(dead_key[1])
                    )
                    victim["bytes"] = b_runner.export_kv(
                        rid, start=LayerIdx(dead_key[0]), end=LayerIdx(dead_key[1])
                    )
                    # Wait until BOTH the input mirror for pos kill_at AND the
                    # parity for every slot 0..N-1 have landed, so recovery
                    # takes the PARITY branch (not the fallback), then crash.
                    deadline = time.time() + 8.0
                    while time.time() < deadline and not (
                        len(gw.cache.get_history(rid, dead_key)) > kill_at
                        and all(
                            gw.parity_cache.is_complete(rid, s)
                            for s in range(victim["N"])
                        )
                    ):
                        time.sleep(0.01)
                    raise RuntimeError(
                        f"simulated {victim_dev} mid-stage crash after mirror+kv"
                    )
            return orig_run(
                request_id, activation_blob, start=start, end=end,
                is_prefill=is_prefill,
            )

        b_runner.run = flaky_run

        with caplog.at_level(logging.WARNING, logger="radp.coordinator.gateway"):
            gw._prefill(rid, prompt)
            for _ in range(1, n):
                gw._decode_step(rid)
        recovered = list(gw._requests[rid].generated_token_ids)
        gw._evict_everywhere(rid)
        n_heads, head_dim, np_dtype, _ = gw._kv_dims()
        gw.close()

    # (a) fault fired, PARITY branch ran, surgical fallback did NOT.
    assert state["tripped"], "fault never injected — recovery path not exercised"
    assert "PARITY reconstruct" in caplog.text, (
        "parity branch did not run — recovery took another path:\n" + caplog.text
    )
    assert surgical_calls["n"] == 0, (
        "parity fell back to surgical instead of reconstructing:\n" + caplog.text
    )
    assert "bytes" in installed, "gateway never installed reconstructed KV"

    # (b) reconstructed KV bit-identical to victim's original (per layer, K & V).
    assert installed["N"] == victim["N"], (
        f"slot count mismatch: installed={installed['N']} victim={victim['N']}"
    )
    n_layers = dead_key[1] - dead_key[0] + 1
    recon_layers = _kv_layers(installed["bytes"], n_layers, n_heads, head_dim, np_dtype)
    vic_layers = _kv_layers(victim["bytes"], n_layers, n_heads, head_dim, np_dtype)
    for li, ((rk, rv), (vk, vv)) in enumerate(zip(recon_layers, vic_layers)):
        assert torch.equal(
            torch.from_numpy(rk.copy()), torch.from_numpy(vk.copy())
        ), f"reconstructed K != victim K at layer {li}"
        assert torch.equal(
            torch.from_numpy(rv.copy()), torch.from_numpy(vv.copy())
        ), f"reconstructed V != victim V at layer {li}"

    # (c) recovered sequence == healthy wired reference.
    assert len(recovered) == n
    assert recovered == reference, f"recovered={recovered}\nreference={reference}"


def test_parity_recovery_matches_reference(monkeypatch, caplog):
    """FIRST non-head victim: every non-head survivor is downstream, so all
    survivors already agree on the slot count (no slicing needed)."""
    _assert_parity_recovery(
        monkeypatch, caplog, cfg=_cfg, victim_dev="worker-b", backup_dev="worker-c"
    )


def test_parity_recovery_middle_victim(monkeypatch, caplog):
    """MIDDLE non-head victim: worker-b (upstream) already appended the failed
    position's KV and so carries one slot MORE than the victim, while worker-d
    (downstream) carries exactly the victim's count. Reconstruction must slice
    the upstream survivor back to the shared slot count instead of bailing out
    to surgical."""
    _assert_parity_recovery(
        monkeypatch, caplog, cfg=_cfg4, victim_dev="worker-c", backup_dev="worker-d"
    )


def test_parity_recovery_last_stage_victim_falls_back(monkeypatch, caplog):
    """LAST non-head victim (worker-d in _cfg4): every non-head survivor
    (worker-b, worker-c) is UPSTREAM and already appended the failed
    position's KV, so both carry one slot MORE than the victim ever will —
    there is no downstream non-head survivor to supply the shared-prefix
    slot. The completeness gate for that extra shared slot finds the
    victim's own contribution missing and safely falls back to surgical,
    exactly as documented in ``_recover_parity``'s docstring and PHASES.md
    Phase B1-PARITY.2. This locks that documented claim with an assertion
    instead of just prose: recovery must still reach the reference output,
    proving the fallback never emits a wrong token."""
    from radp.coordinator.gateway import RequestGateway

    monkeypatch.setenv("RADP_PARITY", "1")
    prompt, n, kill_at = "The quick brown fox", 12, 4
    victim_dev = "worker-d"  # recovery maps it to worker-a (unused directly —
    # the fallback path promotes/rewires internally; we only assert its outcome)
    reference = _healthy_reference(prompt, n, _cfg4)

    ids, placement, recovery = _cfg4()
    victim_stage = next(s for s in placement if s.device == DeviceId(victim_dev))
    dead_key = (int(victim_stage.start_layer), int(victim_stage.end_layer))
    with in_process_cluster_with_mirror(ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL,
            recovery_mode="parity",
        )
        attach(gw)
        gw.generate(prompt, max_tokens=2)  # warmup BEFORE installing the fault

        # Spy: must fall back to surgical (never reconstruct via parity).
        surgical_calls = {"n": 0}
        orig_surgical = gw._recover_surgical

        def spy_surgical(*a, **k):
            surgical_calls["n"] += 1
            return orig_surgical(*a, **k)

        gw._recover_surgical = spy_surgical

        rid = gw.new_request_id()
        d_runner = servers[DeviceId(victim_dev)].runner
        orig_run = d_runner.run
        state = {"calls": 0, "tripped": False}

        def flaky_run(request_id, activation_blob, *, start, end, is_prefill):
            if int(request_id) == int(rid) and (int(start), int(end)) == dead_key:
                state["calls"] += 1  # call k -> position k-1 (prefill = pos 0)
                if state["calls"] - 1 == kill_at and not state["tripped"]:
                    state["tripped"] = True
                    # Wait for the mirrored input for pos kill_at to land so
                    # recovery has what it needs regardless of which path it
                    # takes, then crash.
                    deadline = time.time() + 8.0
                    while time.time() < deadline and not (
                        len(gw.cache.get_history(rid, dead_key)) > kill_at
                    ):
                        time.sleep(0.01)
                    raise RuntimeError(
                        f"simulated {victim_dev} mid-stage crash after mirror+kv"
                    )
            return orig_run(
                request_id, activation_blob, start=start, end=end,
                is_prefill=is_prefill,
            )

        d_runner.run = flaky_run

        with caplog.at_level(logging.WARNING, logger="radp.coordinator.gateway"):
            gw._prefill(rid, prompt)
            for _ in range(1, n):
                gw._decode_step(rid)
        recovered = list(gw._requests[rid].generated_token_ids)
        gw._evict_everywhere(rid)
        gw.close()

    assert state["tripped"], "fault never injected — recovery path not exercised"
    assert surgical_calls["n"] >= 1, (
        "last-stage victim has no downstream non-head survivor and must "
        "fall back to surgical:\n" + caplog.text
    )
    assert "PARITY reconstruct" not in caplog.text, (
        "parity reconstruct ran for a last-stage victim — should have "
        "fallen back to surgical instead:\n" + caplog.text
    )
    assert len(recovered) == n
    assert recovered == reference, f"recovered={recovered}\nreference={reference}"
