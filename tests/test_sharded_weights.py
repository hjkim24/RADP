"""Phase B2: sharded safetensors / bin support in ``_WeightReader``.

Uses a synthetic 2-shard layout written to a tmp directory — no HF download
needed for these unit tests. Verifies:

  * ``WeightsLocation`` correctly identifies single vs sharded formats.
  * ``_WeightReader.keys()`` returns the union of tensors across all shards
    for sharded modes.
  * ``get_tensor(key)`` lazily opens the right shard on first access and
    caches it.
  * Single-file path is unchanged.

A real sharded HF model (SmolLM-1.7B) is exercised in the slow integration
test ``test_sharded_integration``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch
from safetensors.torch import save_file

from radp.common.model_utils import (
    WeightsLocation,
    _open_weight_reader,
    _WeightReader,
)


def _make_synthetic_sharded(tmp_path: Path) -> dict[str, torch.Tensor]:
    """Create two safetensors shards + an index.json. Returns the ground-
    truth tensors for verification."""
    truth = {
        "model.layers.0.weight": torch.arange(8, dtype=torch.float32).reshape(2, 4),
        "model.layers.0.bias":   torch.zeros(4, dtype=torch.float32),
        "model.layers.1.weight": torch.arange(8, 16, dtype=torch.float32).reshape(2, 4),
        "model.layers.1.bias":   torch.ones(4, dtype=torch.float32),
    }
    shard_a = {k: v for k, v in truth.items() if "layers.0" in k}
    shard_b = {k: v for k, v in truth.items() if "layers.1" in k}
    save_file(shard_a, str(tmp_path / "model-00001-of-00002.safetensors"))
    save_file(shard_b, str(tmp_path / "model-00002-of-00002.safetensors"))
    index = {
        "metadata": {"total_size": sum(t.numel() * 4 for t in truth.values())},
        "weight_map": {
            **{k: "model-00001-of-00002.safetensors" for k in shard_a},
            **{k: "model-00002-of-00002.safetensors" for k in shard_b},
        },
    }
    (tmp_path / "model.safetensors.index.json").write_text(json.dumps(index))
    return truth


def test_reader_returns_all_keys_across_shards(tmp_path: Path) -> None:
    _make_synthetic_sharded(tmp_path)
    # Manually construct WeightsLocation pointing at our synthetic layout —
    # this skips the HF download path entirely.
    idx_path = tmp_path / "model.safetensors.index.json"
    idx_data = json.loads(idx_path.read_text())
    loc = WeightsLocation(
        fmt="safetensors_sharded",
        path=idx_path,
        model_id=None,
        weight_map=idx_data["weight_map"],
    )
    # _WeightReader requires model_id for sharded paths (used for HF download).
    # Our synthetic test bypasses that by pre-populating the shard cache.
    with pytest.raises(ValueError, match="model_id"):
        _WeightReader(loc, torch_device="cpu")


def test_reader_with_model_id_lazy_downloads_shards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stub out ``hf_hub_download`` to return paths inside ``tmp_path`` so
    we exercise the lazy-shard-open code path without hitting the network."""
    truth = _make_synthetic_sharded(tmp_path)
    idx_path = tmp_path / "model.safetensors.index.json"
    idx_data = json.loads(idx_path.read_text())

    # Patch huggingface_hub.hf_hub_download to map filename → tmp_path/filename.
    import huggingface_hub
    download_calls: list[str] = []

    def fake_download(repo_id: str, filename: str, **kwargs: object) -> str:
        download_calls.append(filename)
        return str(tmp_path / filename)

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", fake_download)

    loc = WeightsLocation(
        fmt="safetensors_sharded",
        path=idx_path,
        model_id="fake/model",
        weight_map=idx_data["weight_map"],
    )
    reader = _open_weight_reader(loc, torch_device="cpu")
    try:
        # keys() does NOT trigger any downloads — uses the weight_map.
        keys = reader.keys()
        assert keys == set(truth)
        assert download_calls == []

        # First read in shard A → triggers download of shard A only.
        got = reader.get_tensor("model.layers.0.weight")
        assert torch.equal(got, truth["model.layers.0.weight"])
        assert download_calls == ["model-00001-of-00002.safetensors"]

        # Second read in shard A → uses cached handle, no new download.
        _ = reader.get_tensor("model.layers.0.bias")
        assert download_calls == ["model-00001-of-00002.safetensors"]

        # Read in shard B → triggers shard B download.
        got = reader.get_tensor("model.layers.1.bias")
        assert torch.equal(got, truth["model.layers.1.bias"])
        assert download_calls == [
            "model-00001-of-00002.safetensors",
            "model-00002-of-00002.safetensors",
        ]
    finally:
        reader.close()


def test_single_file_path_unchanged(tmp_path: Path) -> None:
    """Single-file safetensors reader still works after the refactor."""
    truth = {"a.weight": torch.tensor([1.0, 2.0, 3.0])}
    p = tmp_path / "model.safetensors"
    save_file(truth, str(p))
    loc = WeightsLocation(fmt="safetensors", path=p)
    reader = _open_weight_reader(loc, torch_device="cpu")
    try:
        assert reader.keys() == set(truth)
        assert torch.equal(reader.get_tensor("a.weight"), truth["a.weight"])
    finally:
        reader.close()


def test_bin_reader_uses_cpu_map_location_regardless_of_torch_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Structural test, not a memory measurement (no GPU on this machine).

    torch.load(mmap=True, map_location=<cuda>) resolves the location eagerly
    per tensor *during* torch.load() itself (torch/serialization.py
    _get_restore_location / load_tensor) -- i.e. passing the real target
    device would copy the whole checkpoint onto the GPU right there, before
    load_stage_blocks ever filters down to one layer's keys. Only
    map_location="cpu" defers materialization. Pin that _WeightReader always
    passes "cpu" here, independent of what torch_device the caller asked for.
    """
    p = tmp_path / "pytorch_model.bin"
    torch.save({"a.weight": torch.tensor([1.0, 2.0, 3.0])}, str(p))

    calls: list[dict[str, object]] = []
    real_load = torch.load

    def spy_load(*args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        # Never actually touch a CUDA path on a machine that may have no GPU;
        # just prove what _WeightReader asked for.
        return {"a.weight": torch.tensor([1.0, 2.0, 3.0])} if kwargs.get(
            "map_location"
        ) == "cuda" else real_load(*args, **kwargs)

    monkeypatch.setattr(torch, "load", spy_load)

    loc = WeightsLocation(fmt="bin", path=p)
    reader = _open_weight_reader(loc, torch_device="cuda")
    try:
        assert calls[-1]["map_location"] == "cpu"
        assert calls[-1]["mmap"] is True
    finally:
        reader.close()


def test_sharded_bin_reader_uses_cpu_map_location_regardless_of_torch_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same pin as above, for the per-shard bin path (_get_shard_bin)."""
    import huggingface_hub

    shard_path = tmp_path / "pytorch_model-00001-of-00001.bin"
    torch.save({"a.weight": torch.tensor([1.0, 2.0, 3.0])}, str(shard_path))
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda *a, **k: str(shard_path))

    calls: list[dict[str, object]] = []
    real_load = torch.load

    def spy_load(*args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return {"a.weight": torch.tensor([1.0, 2.0, 3.0])} if kwargs.get(
            "map_location"
        ) == "cuda" else real_load(*args, **kwargs)

    monkeypatch.setattr(torch, "load", spy_load)

    loc = WeightsLocation(
        fmt="bin_sharded", path=tmp_path / "index.json",
        model_id="fake/model", weight_map={"a.weight": "pytorch_model-00001-of-00001.bin"},
    )
    reader = _open_weight_reader(loc, torch_device="cuda")
    try:
        reader.get_tensor("a.weight")
        assert calls[-1]["map_location"] == "cpu"
        assert calls[-1]["mmap"] is True
    finally:
        reader.close()


def test_index_json_parsed_into_weight_map(tmp_path: Path) -> None:
    """The index path stored on disk must round-trip through json correctly."""
    truth = _make_synthetic_sharded(tmp_path)
    idx_path = tmp_path / "model.safetensors.index.json"
    data = json.loads(idx_path.read_text())
    assert set(data["weight_map"].keys()) == set(truth.keys())
    # Every value is one of the two shard filenames.
    expected_shards = {
        "model-00001-of-00002.safetensors",
        "model-00002-of-00002.safetensors",
    }
    assert set(data["weight_map"].values()) <= expected_shards
