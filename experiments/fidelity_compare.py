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
