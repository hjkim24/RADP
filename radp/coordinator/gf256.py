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
