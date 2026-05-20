"""Tensor (de)serialization for inter-stage activation transport.

Phase 2 uses ``torch.save`` over an in-memory buffer. It handles arbitrary
dict-of-tensors payloads (hidden states + attention mask + any auxiliaries)
without needing per-field schema. Future phases may swap this for a leaner
zero-copy format (safetensors / shared memory) if profiling shows it matters.
"""

from __future__ import annotations

import io

import torch


def encode(payload: dict[str, torch.Tensor]) -> bytes:
    """Serialize a dict of tensors to a contiguous byte blob."""
    buf = io.BytesIO()
    torch.save(payload, buf)
    return buf.getvalue()


def decode(blob: bytes) -> dict[str, torch.Tensor]:
    """Inverse of `encode`. ``map_location='cpu'`` lets the receiver later
    move tensors to its own device explicitly."""
    buf = io.BytesIO(blob)
    obj = torch.load(buf, map_location="cpu", weights_only=True)
    if not isinstance(obj, dict):
        raise TypeError(f"Expected dict payload, got {type(obj).__name__}")
    return obj
