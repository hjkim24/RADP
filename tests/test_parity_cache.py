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
