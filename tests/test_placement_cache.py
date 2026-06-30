"""Persistent placement cache (radp/coordinator/placement_cache.py).

Tests:
  * Fingerprint is invariant to device-arrival order and param-dict order.
  * Fingerprint changes when the fleet composition or a param changes.
  * save → load round-trips placement + recovery + solve metrics.
  * A fingerprint mismatch, missing file, corrupt file, or None path → miss.
  * default_cache_path() honours the RADP_PLACEMENT_CACHE env var.
"""

from __future__ import annotations

from pathlib import Path

from radp.common.types import (
    AlternatingResult,
    DeviceId,
    LayerIdx,
    Stage,
)
from radp.coordinator import placement_cache as pc


def _result() -> AlternatingResult:
    return AlternatingResult(
        placement=[
            Stage(LayerIdx(1), LayerIdx(14), DeviceId("ao-2")),
            Stage(LayerIdx(15), LayerIdx(24), DeviceId("ao-1")),
        ],
        recovery={DeviceId("ao-2"): DeviceId("ao-1")},
        max_stage_time=0.0128,
        iterations=2,
        converged=True,
        history=[],
        sum_stage_time=0.05,
    )


def test_fingerprint_invariant_to_order() -> None:
    a = pc.compute_fingerprint(
        device_ids=["ao-2", "ao-1"],
        device_classes={"ao-1": "agx", "ao-2": "agx"},
        model_id="m",
        num_layers=24,
        params={"a": 1, "b": 2},
    )
    b = pc.compute_fingerprint(
        device_ids=["ao-1", "ao-2"],
        device_classes={"ao-2": "agx", "ao-1": "agx"},
        model_id="m",
        num_layers=24,
        params={"b": 2, "a": 1},
    )
    assert a == b


def test_fingerprint_sensitive_to_composition_and_params() -> None:
    base = dict(
        device_ids=["ao-1", "ao-2"],
        device_classes={"ao-1": "agx", "ao-2": "agx"},
        model_id="m",
        num_layers=24,
        params={"a": 1},
    )
    fp = pc.compute_fingerprint(**base)
    # drop a device
    assert fp != pc.compute_fingerprint(**{**base, "device_ids": ["ao-1"]})
    # change a class
    assert fp != pc.compute_fingerprint(
        **{**base, "device_classes": {"ao-1": "agx", "ao-2": "nano"}}
    )
    # change a cost-model knob
    assert fp != pc.compute_fingerprint(**{**base, "params": {"a": 2}})
    # change the model / layer count
    assert fp != pc.compute_fingerprint(**{**base, "model_id": "other"})
    assert fp != pc.compute_fingerprint(**{**base, "num_layers": 16})


def test_save_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    res = _result()
    pc.save(path, "fp-1", res)
    got = pc.load(path, "fp-1")
    assert got is not None
    assert [(s.device, int(s.start_layer), int(s.end_layer)) for s in got.placement] == [
        ("ao-2", 1, 14),
        ("ao-1", 15, 24),
    ]
    assert got.recovery == {DeviceId("ao-2"): DeviceId("ao-1")}
    assert got.converged is True
    assert got.iterations == 2
    assert got.max_stage_time == 0.0128
    assert got.sum_stage_time == 0.05


def test_load_misses(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    pc.save(path, "fp-1", _result())
    assert pc.load(path, "fp-other") is None          # fingerprint mismatch
    assert pc.load(tmp_path / "absent.json", "fp-1") is None  # missing file
    assert pc.load(None, "fp-1") is None              # caching disabled


def test_load_corrupt_file_is_miss(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    path.write_text("{ not valid json")
    assert pc.load(path, "fp-1") is None


def test_save_none_path_is_noop() -> None:
    # Must not raise when caching is disabled.
    pc.save(None, "fp-1", _result())


def test_default_cache_path_env(monkeypatch) -> None:
    monkeypatch.delenv("RADP_PLACEMENT_CACHE", raising=False)
    assert pc.default_cache_path() == pc._DEFAULT_CACHE_PATH
    monkeypatch.setenv("RADP_PLACEMENT_CACHE", "")
    assert pc.default_cache_path() is None
    monkeypatch.setenv("RADP_PLACEMENT_CACHE", "/tmp/custom_cache.json")
    assert pc.default_cache_path() == Path("/tmp/custom_cache.json")
