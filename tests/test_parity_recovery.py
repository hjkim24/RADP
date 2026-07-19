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
