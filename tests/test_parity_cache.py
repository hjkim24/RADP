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


def test_sole_request_not_evicted_even_over_cap():
    """Single in-flight request is never evicted; its parity is actively used."""
    # Small max_bytes to force over-cap with a single column
    pc = ParityCache(num_stages=1, max_bytes=50)

    # Add column to req1 that exceeds max_bytes (100 > 50)
    pc.xor_in(_rid(1), (1, 2), 0, bytes(100))
    # Despite being over cap, sole request must NOT be evicted (parity needed)
    assert pc.get_parity(_rid(1), 0) is not None

    # Now add a second request that also exceeds cap
    pc.xor_in(_rid(2), (3, 4), 0, bytes(100))
    # Request 1 should now be evicted (LRU, and 2+ requests allows eviction)
    assert pc.get_parity(_rid(1), 0) is None
    # Request 2 should remain (newest)
    assert pc.get_parity(_rid(2), 0) is not None


def test_k2_maintains_q_blob():
    """k=2: P = XOR, Q = g^0·A ^ g^1·B (coeff_index = stage rank)."""
    import numpy as np
    from radp.coordinator.gf256 import gf_mul_scalar, gf_pow
    pc = ParityCache(num_stages=2, k=2)
    A, B = bytes([1, 2, 3, 4]), bytes([9, 8, 7, 6])
    pc.xor_in(_rid(1), (1, 2), 0, A, coeff_index=0)
    pc.xor_in(_rid(1), (3, 4), 0, B, coeff_index=1)
    assert pc.is_complete(_rid(1), 0)
    assert pc.get_parity(_rid(1), 0) == bytes(a ^ b for a, b in zip(A, B))
    an = np.frombuffer(A, np.uint8); bn = np.frombuffer(B, np.uint8)
    expect_q = gf_mul_scalar(gf_pow(2, 0), an) ^ gf_mul_scalar(gf_pow(2, 1), bn)
    assert pc.get_qparity(_rid(1), 0) == expect_q.tobytes()


def test_k1_has_no_q_blob():
    """Default k=1 keeps the RAID-5 path: no Q allocated."""
    pc = ParityCache(num_stages=2)  # k defaults to 1
    pc.xor_in(_rid(1), (1, 2), 0, bytes([1, 2]), coeff_index=0)
    assert pc.get_qparity(_rid(1), 0) is None


def test_k2_q_grows_zero_padded():
    """Unequal column lengths: Q grows/zero-pads in lockstep with P."""
    import numpy as np
    from radp.coordinator.gf256 import gf_mul_scalar, gf_pow
    pc = ParityCache(num_stages=2, k=2)
    big, small = bytes([1, 2, 3, 4, 5, 6]), bytes([10, 20])
    pc.xor_in(_rid(1), (1, 6), 0, big, coeff_index=0)
    pc.xor_in(_rid(1), (7, 8), 0, small, coeff_index=1)
    q = np.frombuffer(pc.get_qparity(_rid(1), 0), np.uint8)
    expect = (gf_mul_scalar(gf_pow(2, 0), np.frombuffer(big, np.uint8))
              ^ gf_mul_scalar(gf_pow(2, 1), np.frombuffer(small.ljust(6, b"\0"), np.uint8)))
    assert np.array_equal(q, expect)
