"""Roundtrip tests for tensor_io."""

from __future__ import annotations

import pytest
import torch

from radp.common.tensor_io import decode, encode


def test_roundtrip_single_tensor() -> None:
    payload = {"hidden_states": torch.randn(1, 8, 16)}
    blob = encode(payload)
    out = decode(blob)
    assert torch.equal(payload["hidden_states"], out["hidden_states"])


def test_roundtrip_multiple_tensors() -> None:
    payload = {
        "hidden_states": torch.randn(2, 4, 8),
        "attention_mask": torch.zeros(2, 1, 4, 4),
    }
    out = decode(encode(payload))
    assert torch.equal(payload["hidden_states"], out["hidden_states"])
    assert torch.equal(payload["attention_mask"], out["attention_mask"])


def test_decode_rejects_non_dict() -> None:
    import io

    buf = io.BytesIO()
    torch.save(torch.randn(2, 2), buf)
    with pytest.raises(TypeError, match="Expected dict"):
        decode(buf.getvalue())
