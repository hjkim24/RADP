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
