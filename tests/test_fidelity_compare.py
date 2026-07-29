import numpy as np


def test_identical_is_exact():
    from experiments.fidelity_compare import compare_kv, kv_sha256
    a = np.arange(12, dtype=np.float16).tobytes()
    assert kv_sha256(a) == kv_sha256(a)
    r = compare_kv(a, a, np.float16)
    assert r["exact"] is True
    assert r["fraction_mismatched"] == 0.0
    assert r["max_abs_diff"] == 0.0


def test_perturbed_reports_magnitude():
    from experiments.fidelity_compare import compare_kv
    a = np.zeros(10, dtype=np.float16)
    b = a.copy()
    b[3] = np.float16(2.0)  # one element differs by 2.0
    r = compare_kv(a.tobytes(), b.tobytes(), np.float16)
    assert r["exact"] is False
    assert r["fraction_mismatched"] == 0.1  # 1/10
    assert r["max_abs_diff"] == 2.0
