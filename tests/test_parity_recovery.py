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
