# Lazy Model Loading for 7B-Class Models — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve `NousResearch/Llama-2-7b-hf` on the Jetson fleet by removing the three call sites that materialize a whole checkpoint to obtain a few hundred megabytes of modules.

**Architecture:** Each model family already knows how to build its own decoder blocks (`architectures.py`). Extend that adapter with the head/embedding modules, then add one `load_head_modules` loader in `model_utils.py` that fills them from the existing lazy `_WeightReader` — the same machinery `load_stage_blocks` uses. The coordinator, the worker's `load_head`, and the profiler then stop calling `load_model`. The coordinator additionally reads its three tensors from a small pre-extracted bundle, because its disk cannot hold a shard.

**Tech Stack:** Python 3.10, PyTorch, HuggingFace `transformers` + `safetensors` + `huggingface_hub`, pytest, Ansible.

## Global Constraints

- Target model is `NousResearch/Llama-2-7b-hf` (safetensors, 2 shards, ungated). Do **not** switch to an OPT 7B-class model: `facebook/opt-6.7b` ships `bin` shards only, and `torch.load` on a ~10 GB shard reproduces the failure this work exists to remove.
- `safetensors` is loaded through `safe_open` (mmap, per-tensor); `bin` is loaded through `torch.load` (whole file). Never introduce a code path that reads a `bin` shard for a 7B-class model.
- `load_model` stays in place and keeps working. This plan adds a narrower path beside it; it does not delete it.
- Existing public signatures used by the scheduler must not change: `profile_layers` still returns `list[LayerProfile]` with `memory_bytes` and `compute_time`.
- Tests that download HF weights are marked `@pytest.mark.slow` (the suite runs `-m 'not slow'` by default), following `tests/test_load_stage_blocks.py`.
- Coordinator memory budget is ~7 GB available and its disk has ~80 MB free. Nothing may write a shard to `ax-1`.
- Do not delete anything under `/home/isp/jinwoo` or `/home/isp/yerin` on `ax-1` — other people's data.
- `ao-1` is offline. Do not add tasks that depend on it.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `radp/common/architectures.py` | per-family module construction and weight-key layout | add `make_head_modules` to the protocol + both families |
| `radp/common/model_utils.py` | checkpoint discovery and lazy tensor reading | add `HeadModules`, `load_head_modules` |
| `radp/coordinator/gateway.py` | embedding + tail on the coordinator | swap `load_model` for `load_head_modules` |
| `radp/worker/stage_runner.py` | worker stage lifecycle | swap `load_model` for `load_head_modules` in `load_head` |
| `radp/profiler/layer_profiler.py` | per-layer timing | block-wise loop instead of whole-model forward |
| `scripts/extract_head_bundle.py` | new — writes the coordinator's ~512 MB bundle | create |
| `tests/test_head_modules.py` | new — correctness gate for the loader | create |
| `tests/test_block_profiler.py` | new — profiler equivalence | create |

---

### Task 1: `make_head_modules` on the architecture adapters

Each family builds the modules its own `embed()` and `head()` already expect. The loader in Task 2 stays family-agnostic.

**Files:**
- Modify: `radp/common/architectures.py`
- Test: `tests/test_head_modules.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `radp.common.architectures.HeadModuleSet` — dataclass with fields
    `decoder: nn.Module`, `lm_head: nn.Module`, `key_prefixes: dict[str, str]`.
    `key_prefixes` maps a dotted attribute path (`"embed_tokens"`, `"lm_head"`)
    to the checkpoint key prefix for that module (`"model.decoder.embed_tokens."`).
  - `ModelArchitecture.make_head_modules(config: Any, dtype: torch.dtype, device: str) -> HeadModuleSet`
    implemented by `OPTArchitecture` and `_RoPEArchitecture`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_head_modules.py`:

```python
"""Head/embedding module construction and lazy loading."""

from __future__ import annotations

import pytest
import torch
from torch import nn
from transformers import LlamaConfig, OPTConfig

from radp.common.architectures import get_architecture


def test_opt_head_modules_have_config_shapes() -> None:
    config = OPTConfig(
        vocab_size=1000, hidden_size=32, word_embed_proj_dim=16,
        num_hidden_layers=2, num_attention_heads=2, ffn_dim=64,
        max_position_embeddings=64, do_layer_norm_before=True,
    )
    arch = get_architecture("opt")
    hms = arch.make_head_modules(config, torch.float32, "cpu")

    assert hms.decoder.embed_tokens.num_embeddings == 1000
    assert hms.decoder.embed_tokens.embedding_dim == 16
    # word_embed_proj_dim != hidden_size, so OPT needs both projections.
    assert hms.decoder.project_in is not None
    assert hms.decoder.project_out is not None
    assert hms.decoder.final_layer_norm is not None
    assert hms.lm_head.out_features == 1000
    assert hms.key_prefixes["embed_tokens"] == "model.decoder.embed_tokens."
    assert hms.key_prefixes["lm_head"] == "lm_head."


def test_opt_without_projection_omits_project_modules() -> None:
    config = OPTConfig(
        vocab_size=1000, hidden_size=32, word_embed_proj_dim=32,
        num_hidden_layers=2, num_attention_heads=2, ffn_dim=64,
        max_position_embeddings=64, do_layer_norm_before=True,
    )
    hms = get_architecture("opt").make_head_modules(config, torch.float32, "cpu")
    assert getattr(hms.decoder, "project_in", None) is None
    assert getattr(hms.decoder, "project_out", None) is None


def test_llama_head_modules_have_config_shapes() -> None:
    config = LlamaConfig(
        vocab_size=1000, hidden_size=32, intermediate_size=64,
        num_hidden_layers=2, num_attention_heads=2,
    )
    hms = get_architecture("llama").make_head_modules(config, torch.float32, "cpu")

    assert hms.decoder.embed_tokens.num_embeddings == 1000
    assert isinstance(hms.decoder.norm, nn.Module)
    assert hms.lm_head.out_features == 1000
    assert hms.key_prefixes["embed_tokens"] == "model.embed_tokens."
    assert hms.key_prefixes["norm"] == "model.norm."
    assert hms.key_prefixes["lm_head"] == "lm_head."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_head_modules.py -v`
Expected: FAIL with `AttributeError: 'OPTArchitecture' object has no attribute 'make_head_modules'`

- [ ] **Step 3: Add `HeadModuleSet` and the protocol method**

In `radp/common/architectures.py`, add after the imports:

```python
from dataclasses import dataclass, field


@dataclass
class HeadModuleSet:
    """The non-block modules a family needs for embed() and head().

    ``decoder`` is a stand-in for the HF decoder object: it carries the same
    attribute names ``embed()``/``head()`` already read, so those methods work
    unchanged whether they are handed a real model's decoder or this stub.
    ``key_prefixes`` maps each attribute to its checkpoint key prefix so a
    generic loader can fill them without knowing the family.
    """

    decoder: nn.Module
    lm_head: nn.Module
    key_prefixes: dict[str, str] = field(default_factory=dict)


class _DecoderStub(nn.Module):
    """Attribute bag with nn.Module semantics (.to(), .eval(), parameters())."""
```

Add to the `ModelArchitecture` Protocol, beside `make_aux`:

```python
    def make_head_modules(
        self, config: Any, dtype: torch.dtype, device: str
    ) -> HeadModuleSet: ...
```

- [ ] **Step 4: Implement for OPT**

Add to `OPTArchitecture`:

```python
    def make_head_modules(
        self, config: Any, dtype: torch.dtype, device: str
    ) -> HeadModuleSet:
        from transformers.models.opt.modeling_opt import OPTLearnedPositionalEmbedding

        stub = _DecoderStub()
        stub.embed_tokens = nn.Embedding(
            config.vocab_size, config.word_embed_proj_dim, config.pad_token_id
        )
        stub.embed_positions = OPTLearnedPositionalEmbedding(
            config.max_position_embeddings, config.hidden_size
        )
        prefixes = {
            "embed_tokens": "model.decoder.embed_tokens.",
            "embed_positions": "model.decoder.embed_positions.",
        }
        # OPT-350M is the lone variant with word_embed_proj_dim != hidden_size;
        # its project_in/out bridge the two spaces. Absent otherwise.
        if config.word_embed_proj_dim != config.hidden_size:
            stub.project_in = nn.Linear(
                config.word_embed_proj_dim, config.hidden_size, bias=False
            )
            stub.project_out = nn.Linear(
                config.hidden_size, config.word_embed_proj_dim, bias=False
            )
            prefixes["project_in"] = "model.decoder.project_in."
            prefixes["project_out"] = "model.decoder.project_out."
        if config.do_layer_norm_before:
            stub.final_layer_norm = nn.LayerNorm(config.hidden_size)
            prefixes["final_layer_norm"] = "model.decoder.final_layer_norm."

        lm_head = nn.Linear(config.word_embed_proj_dim, config.vocab_size, bias=False)
        prefixes["lm_head"] = "lm_head."

        stub.to(device=device, dtype=dtype)
        stub.eval()
        lm_head.to(device=device, dtype=dtype)
        lm_head.eval()
        return HeadModuleSet(decoder=stub, lm_head=lm_head, key_prefixes=prefixes)
```

- [ ] **Step 5: Implement for the RoPE families**

Add to `_RoPEArchitecture` (inherited by `LlamaArchitecture` and `MistralArchitecture`):

```python
    def _norm_cls(self) -> type[nn.Module]:
        raise NotImplementedError

    def make_head_modules(
        self, config: Any, dtype: torch.dtype, device: str
    ) -> HeadModuleSet:
        stub = _DecoderStub()
        stub.embed_tokens = nn.Embedding(
            config.vocab_size, config.hidden_size, config.pad_token_id
        )
        stub.norm = self._norm_cls()(config.hidden_size, eps=config.rms_norm_eps)
        lm_head = nn.Linear(config.hidden_size, config.vocab_size, bias=False)

        stub.to(device=device, dtype=dtype)
        stub.eval()
        lm_head.to(device=device, dtype=dtype)
        lm_head.eval()
        return HeadModuleSet(
            decoder=stub,
            lm_head=lm_head,
            key_prefixes={
                "embed_tokens": "model.embed_tokens.",
                "norm": "model.norm.",
                "lm_head": "lm_head.",
            },
        )
```

Add `_norm_cls` to both subclasses:

```python
# in LlamaArchitecture
    def _norm_cls(self) -> type[nn.Module]:
        from transformers.models.llama.modeling_llama import LlamaRMSNorm
        return LlamaRMSNorm

# in MistralArchitecture
    def _norm_cls(self) -> type[nn.Module]:
        from transformers.models.mistral.modeling_mistral import MistralRMSNorm
        return MistralRMSNorm
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_head_modules.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Run the full suite for regressions**

Run: `.venv/bin/python -m pytest tests/ 2>&1 | tail -3`
Expected: all pass (146 + 3 new)

- [ ] **Step 8: Commit**

```bash
git add radp/common/architectures.py tests/test_head_modules.py
git commit -m "feat(architectures): build head/embedding modules from config"
```

---

### Task 2: `load_head_modules` — fill those modules from the lazy reader

**Files:**
- Modify: `radp/common/model_utils.py`
- Test: `tests/test_head_modules.py` (append)

**Interfaces:**
- Consumes: `HeadModuleSet`, `ModelArchitecture.make_head_modules` from Task 1.
- Produces:
  ```python
  def load_head_modules(
      model_id: str,
      *,
      dtype: str = "float32",
      torch_device: str = "cpu",
      weights_path: Path | None = None,
  ) -> HeadModuleSet
  ```
  `weights_path` points at a single safetensors file to read instead of the
  model's own shards (used by Task 4). Task 3 and Task 5 call this.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_head_modules.py`:

```python
@pytest.mark.slow
def test_loaded_head_modules_match_full_model() -> None:
    """The whole design rests on this: the same tensors, without the 13 GB."""
    from radp.common.model_utils import get_transformer_layers, load_head_modules, load_model

    model_id = "facebook/opt-125m"
    full = load_model(model_id, dtype="float32", torch_device="cpu")
    arch = get_architecture(full.model.config.model_type)
    ref_decoder = arch.get_decoder(full.model)

    hms = load_head_modules(model_id, dtype="float32", torch_device="cpu")

    assert torch.equal(
        hms.decoder.embed_tokens.weight, ref_decoder.embed_tokens.weight
    )
    assert torch.equal(
        hms.decoder.embed_positions.weight, ref_decoder.embed_positions.weight
    )
    assert torch.equal(hms.lm_head.weight, full.model.lm_head.weight)


def test_tied_embeddings_share_the_embedding_weight() -> None:
    """When the checkpoint has no lm_head.weight, lm_head reuses embed_tokens.

    Exercises the sharing contract without a download; the loader branch that
    triggers it is the `not local_state and tie_word_embeddings` condition.
    """
    from transformers import LlamaConfig

    config = LlamaConfig(
        vocab_size=64, hidden_size=8, intermediate_size=16,
        num_hidden_layers=1, num_attention_heads=1, tie_word_embeddings=True,
    )
    hms = get_architecture("llama").make_head_modules(config, torch.float32, "cpu")
    hms.lm_head.weight = hms.decoder.embed_tokens.weight
    assert hms.lm_head.weight is hms.decoder.embed_tokens.weight


@pytest.mark.slow
def test_head_modules_produce_identical_logits() -> None:
    """Numerical equality on the path the coordinator actually runs."""
    from radp.common.model_utils import load_head_modules, load_model

    model_id = "facebook/opt-125m"
    full = load_model(model_id, dtype="float32", torch_device="cpu")
    arch = get_architecture(full.model.config.model_type)
    ref_decoder = arch.get_decoder(full.model)
    hms = load_head_modules(model_id, dtype="float32", torch_device="cpu")

    input_ids = torch.tensor([[5, 9, 42, 7]])
    mask = torch.ones_like(input_ids)
    with torch.no_grad():
        ref_embed = arch.embed(ref_decoder, input_ids, mask, 0)
        new_embed = arch.embed(hms.decoder, input_ids, mask, 0)
        assert torch.equal(ref_embed, new_embed)

        hidden = torch.randn(1, 4, full.model.config.hidden_size)
        ref_logits = arch.head(ref_decoder, full.model.lm_head, hidden)
        new_logits = arch.head(hms.decoder, hms.lm_head, hidden)
        assert torch.equal(ref_logits, new_logits)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_head_modules.py -v -m slow`
Expected: FAIL with `ImportError: cannot import name 'load_head_modules'`

- [ ] **Step 3: Implement `load_head_modules`**

Add to `radp/common/model_utils.py`, after `load_stage_blocks`:

```python
def load_head_modules(
    model_id: str,
    *,
    dtype: str = "float32",
    torch_device: str = "cpu",
    weights_path: Path | None = None,
) -> HeadModuleSet:
    """Build only the embedding/tail modules and fill them from the checkpoint.

    The lazy counterpart to ``load_model`` for callers that need to embed
    tokens or produce logits but not run any transformer block: the
    coordinator, the worker acting as chain tail, and nothing else.

    ``weights_path`` reads a single safetensors file instead of the model's
    own shards. The keys are identical — it is a cache of the same tensors —
    so it exists purely for hosts that cannot store a full shard.
    """
    config = AutoConfig.from_pretrained(model_id)
    arch = get_architecture(config.model_type)
    torch_dtype = DTYPE_MAP[dtype]
    hms = arch.make_head_modules(config, torch_dtype, torch_device)

    if weights_path is not None:
        loc = WeightsLocation(fmt="safetensors", path=Path(weights_path))
    else:
        loc = _find_weights_location(model_id)

    rss_before = measure_resident_bytes()
    reader = _open_weight_reader(loc, torch_device)
    try:
        all_keys = reader.keys()
        # Same layout quirk load_stage_blocks handles: some OPT snapshots
        # publish keys without the leading "model." prefix.
        probe = hms.key_prefixes["embed_tokens"]
        strip_model = (
            probe.startswith("model.")
            and not any(k.startswith(probe) for k in all_keys)
            and any(k.startswith(probe[len("model."):]) for k in all_keys)
        )
        if strip_model:
            log.info("checkpoint uses bare key layout; stripping 'model.' for head modules")

        for attr, prefix in hms.key_prefixes.items():
            module = hms.lm_head if attr == "lm_head" else getattr(hms.decoder, attr, None)
            if module is None:
                continue
            if strip_model and prefix.startswith("model."):
                prefix = prefix[len("model."):]
            local_state = {
                k[len(prefix):]: reader.get_tensor(k).to(dtype=torch_dtype)
                for k in all_keys
                if k.startswith(prefix)
            }
            if not local_state and attr == "lm_head" and getattr(
                config, "tie_word_embeddings", False
            ):
                # Tied embeddings: the checkpoint has no separate lm_head.weight.
                hms.lm_head.weight = hms.decoder.embed_tokens.weight
                continue
            if not local_state:
                log.warning("no checkpoint keys under %r for %s", prefix, attr)
                continue
            missing, unexpected = module.load_state_dict(local_state, strict=False)
            if missing:
                log.warning("head module %s missing keys: %s", attr, missing)
            if unexpected:
                log.warning("head module %s unexpected keys: %s", attr, unexpected)
    finally:
        reader.close()

    log.info(
        "load_head_modules %s: rss +%.1f MB (now %.1f MB)",
        model_id,
        (measure_resident_bytes() - rss_before) / (1024 * 1024),
        measure_resident_bytes() / (1024 * 1024),
    )
    return hms
```

Add the import at the top of `model_utils.py`:

```python
from radp.common.architectures import HeadModuleSet, get_architecture
```

(`get_architecture` is already imported; extend that line.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_head_modules.py -v -m slow`
Expected: PASS (2 slow tests; downloads OPT-125M)

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ 2>&1 | tail -3`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add radp/common/model_utils.py tests/test_head_modules.py
git commit -m "feat(model_utils): load head modules without materializing the model"
```

---

### Task 3: Point the coordinator and the worker at the new loader

**Files:**
- Modify: `radp/coordinator/gateway.py:129-131`
- Modify: `radp/worker/stage_runner.py:130-150` (`load_head`)
- Test: existing `tests/` suite (the coordinator and worker paths are already covered)

**Interfaces:**
- Consumes: `load_head_modules` from Task 2.
- Produces: no new public API. `Gateway` keeps `self._decoder` and gains
  `self._lm_head`; `StageRunner` keeps `self._head_decoder` / `self._head_lm_head`.

- [ ] **Step 1: Read the two call sites**

Run: `sed -n '125,135p' radp/coordinator/gateway.py && sed -n '130,155p' radp/worker/stage_runner.py`
Note which attributes each keeps off `handle` — the replacement must keep the same names so nothing downstream changes.

- [ ] **Step 2: Replace the coordinator's load**

`self.handle` is used at exactly 8 sites, and it supplies three different
things: the decoder/lm_head modules, the **tokenizer**, and the **config**.
`load_head_modules` replaces only the first, so the tokenizer and config must be
obtained directly — both are metadata-only loads with no weights.

In `radp/coordinator/gateway.py`, replace lines 129-131 with:

```python
        self._config = AutoConfig.from_pretrained(model_id)
        self._tokenizer = AutoTokenizer.from_pretrained(model_id)
        self._arch: ModelArchitecture = get_architecture(self._config.model_type)
        head_bundle = os.environ.get("RADP_HEAD_BUNDLE")
        hms = load_head_modules(
            model_id,
            dtype=dtype,
            torch_device=torch_device,
            weights_path=Path(head_bundle) if head_bundle else None,
        )
        self._decoder = hms.decoder
        self._lm_head = hms.lm_head
```

Then apply exactly these substitutions:

| Line | From | To |
|---|---|---|
| 406 | `self.handle.tokenizer` | `self._tokenizer` |
| 533 | `self.handle.tokenizer` | `self._tokenizer` |
| 1337 | `self.handle.model.config` | `self._config` |
| 1887 | `self.handle.model.lm_head` | `self._lm_head` |
| 1901 | `self.handle.tokenizer` | `self._tokenizer` |

Imports: on line 36 replace `load_model` with `load_head_modules` (keep
`measure_resident_bytes`; drop `ModelHandle` if it becomes unused), add
`AutoConfig, AutoTokenizer` from `transformers`, and add `import os` and
`from pathlib import Path` if absent.

Verify nothing is left: `grep -n "self.handle" radp/coordinator/gateway.py`
must return nothing.

- [ ] **Step 3: Replace the worker's load_head**

In `radp/worker/stage_runner.py`, replace the body of `load_head` after
`self._ensure_model(model_id)` with:

```python
            hms = load_head_modules(
                model_id, dtype=self.dtype, torch_device=self.torch_device
            )
            self._head_decoder = hms.decoder
            self._head_lm_head = hms.lm_head
```

Replace the local `from radp.common.model_utils import load_model` with
`load_head_modules` in the module-level import block (line ~29, beside
`load_stage_blocks`).

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ 2>&1 | tail -3`
Expected: all pass. If a test reaches for `gateway.handle`, update it to the new attribute — that is the intended API change.

- [ ] **Step 5: Run the slow end-to-end tests**

Run: `.venv/bin/python -m pytest tests/ -m slow 2>&1 | tail -5`
Expected: pass. These exercise real generation on OPT-125M and are the gate that embedding and logits still work.

- [ ] **Step 6: Commit**

```bash
git add radp/coordinator/gateway.py radp/worker/stage_runner.py
git commit -m "feat(coordinator,worker): stop loading the whole model for head modules"
```

---

### Task 4: Head bundle for the coordinator

`ax-1` has 80 MB of free disk and needs three tensors totalling ~512 MB. Extract them once, ship the file, point `RADP_HEAD_BUNDLE` at it.

**Files:**
- Create: `scripts/extract_head_bundle.py`
- Test: `tests/test_head_modules.py` (append)

**Interfaces:**
- Consumes: `load_head_modules(..., weights_path=...)` from Task 2.
- Produces: a CLI writing a safetensors file whose keys are exactly the
  checkpoint's head keys.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_head_modules.py`:

```python
@pytest.mark.slow
def test_bundle_round_trips(tmp_path) -> None:
    """A bundle must produce byte-identical modules to reading the shards."""
    import subprocess
    import sys

    from radp.common.model_utils import load_head_modules

    model_id = "facebook/opt-125m"
    bundle = tmp_path / "head.safetensors"
    subprocess.run(
        [sys.executable, "scripts/extract_head_bundle.py", model_id, "-o", str(bundle)],
        check=True,
    )
    assert bundle.exists()

    from_hub = load_head_modules(model_id, dtype="float32", torch_device="cpu")
    from_bundle = load_head_modules(
        model_id, dtype="float32", torch_device="cpu", weights_path=bundle
    )
    assert torch.equal(
        from_hub.decoder.embed_tokens.weight, from_bundle.decoder.embed_tokens.weight
    )
    assert torch.equal(from_hub.lm_head.weight, from_bundle.lm_head.weight)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_head_modules.py::test_bundle_round_trips -v -m slow`
Expected: FAIL — `scripts/extract_head_bundle.py` does not exist.

- [ ] **Step 3: Write the extraction script**

Create `scripts/extract_head_bundle.py`:

```python
#!/usr/bin/env python3
"""Extract just the embedding/tail tensors into one small safetensors file.

The coordinator needs embed_tokens, the final norm and lm_head — about 512 MB
for a 7B model, against a 13.5 GB checkpoint whose two shards it would
otherwise both have to download. ax-1 has 80 MB of free disk, so it reads this
instead. The keys are unchanged, so `load_head_modules(weights_path=...)`
treats it as an ordinary single-file checkpoint.

Run on a machine with disk (not on the coordinator), then copy the output over.

    python scripts/extract_head_bundle.py NousResearch/Llama-2-7b-hf -o head.safetensors
"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from safetensors.torch import save_file
from transformers import AutoConfig

from radp.common.architectures import get_architecture
from radp.common.model_utils import _find_weights_location, _open_weight_reader


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_id")
    ap.add_argument("-o", "--out", required=True, type=Path)
    args = ap.parse_args()

    config = AutoConfig.from_pretrained(args.model_id)
    arch = get_architecture(config.model_type)
    hms = arch.make_head_modules(config, torch.float32, "cpu")

    loc = _find_weights_location(args.model_id)
    reader = _open_weight_reader(loc, "cpu")
    try:
        keys = reader.keys()
        wanted = {
            k: reader.get_tensor(k).contiguous()
            for k in keys
            if any(k.startswith(p) for p in hms.key_prefixes.values())
        }
    finally:
        reader.close()

    if not wanted:
        raise SystemExit(
            f"no head tensors matched for {args.model_id}; "
            f"expected prefixes {sorted(hms.key_prefixes.values())}"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    save_file(wanted, str(args.out))
    total = sum(t.numel() * t.element_size() for t in wanted.values())
    print(f"wrote {len(wanted)} tensors, {total / 2**20:.1f} MB -> {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_head_modules.py::test_bundle_round_trips -v -m slow`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/extract_head_bundle.py tests/test_head_modules.py
git commit -m "feat(scripts): extract a head-only safetensors bundle for the coordinator"
```

---

### Task 5: Block-wise profiler

**Files:**
- Modify: `radp/profiler/layer_profiler.py`
- Test: `tests/test_block_profiler.py`

**Interfaces:**
- Consumes: `load_stage_blocks` (existing), `arch.run_block` / `arch.make_aux` (existing).
- Produces: `profile_layers` with an unchanged signature and return type
  `list[LayerProfile]`. No caller changes.

- [ ] **Step 1: Write the failing test**

Create `tests/test_block_profiler.py`:

```python
"""The profiler must not need the whole model in memory."""

from __future__ import annotations

import pytest

from radp.common.types import DeviceId


@pytest.mark.slow
def test_block_wise_profile_covers_every_layer() -> None:
    from radp.profiler.layer_profiler import profile_layers

    profiles = profile_layers(
        "facebook/opt-125m",
        device_id=DeviceId("test"),
        warmup=1,
        repeat=2,
        dtype="float32",
        torch_device="cpu",
        seq_length=8,
    )
    assert len(profiles) == 12  # opt-125m has 12 layers
    assert [int(p.layer_idx) for p in profiles] == list(range(1, 13))
    for p in profiles:
        assert p.memory_bytes > 0
        assert p.compute_time[DeviceId("test")] > 0


@pytest.mark.slow
def test_block_wise_peak_stays_below_full_model() -> None:
    """The point of the change: peak tracks one block, not the checkpoint."""
    from radp.common.model_utils import measure_resident_bytes
    from radp.profiler.layer_profiler import profile_layers

    before = measure_resident_bytes()
    profile_layers(
        "facebook/opt-125m",
        device_id=DeviceId("test"),
        warmup=1,
        repeat=1,
        dtype="float32",
        torch_device="cpu",
        seq_length=8,
    )
    growth_mb = (measure_resident_bytes() - before) / (1024 * 1024)
    # opt-125m is ~500 MB in float32; one block is ~14 MB. Allow generous slack
    # for the interpreter and HF config caching, but fail if we kept the model.
    assert growth_mb < 200, f"profiler retained {growth_mb:.0f} MB"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_block_profiler.py -v -m slow`
Expected: `test_block_wise_peak_stays_below_full_model` FAILS (the current profiler keeps the whole model resident).

- [ ] **Step 3: Rewrite the profiling loop**

In `radp/profiler/layer_profiler.py`, replace the body of `profile_layers` between the log line and the return with:

```python
    config = AutoConfig.from_pretrained(model_id)
    arch = get_architecture(config.model_type)
    num_layers = config.num_hidden_layers
    hidden_size = config.hidden_size
    torch_dtype = DTYPE_MAP[dtype]
    aux = arch.make_aux(config, torch_dtype, torch_device)
    is_cuda = str(torch_device).startswith("cuda")

    profiles: list[LayerProfile] = []
    for global_idx in range(1, num_layers + 1):
        blocks = load_stage_blocks(
            model_id, LayerIdx(global_idx), LayerIdx(global_idx),
            dtype=dtype, torch_device=torch_device,
        )
        block = blocks[0]
        # A decoder block's real input is a hidden state — this is exactly how
        # stage_runner invokes it. Values do not affect timing; shape does.
        hidden = torch.zeros(
            (1, seq_length, hidden_size), dtype=torch_dtype, device=torch_device
        )
        attention_mask = torch.ones(
            (1, seq_length), dtype=torch.long, device=torch_device
        )

        samples: list[float] = []
        with torch.no_grad():
            for _ in range(warmup):
                arch.run_block(block, hidden, attention_mask, None, 0, aux)
            if is_cuda:
                torch.cuda.synchronize()
            for _ in range(repeat):
                if is_cuda:
                    start_ev = torch.cuda.Event(enable_timing=True)
                    end_ev = torch.cuda.Event(enable_timing=True)
                    start_ev.record()
                    arch.run_block(block, hidden, attention_mask, None, 0, aux)
                    end_ev.record()
                    torch.cuda.synchronize()
                    samples.append(start_ev.elapsed_time(end_ev) / 1000.0)
                else:
                    t0 = time.perf_counter()
                    arch.run_block(block, hidden, attention_mask, None, 0, aux)
                    samples.append(time.perf_counter() - t0)

        param_bytes = layer_param_bytes(block)
        kv_bytes = estimate_kv_cache_bytes(
            hidden_size, kv_cache_max_seq, DTYPE_BYTES[dtype]
        )
        profiles.append(
            LayerProfile(
                layer_idx=LayerIdx(global_idx),
                memory_bytes=param_bytes + kv_bytes,
                compute_time={device_id: median(samples)},
            )
        )
        log.info(
            "layer %d/%d: %.3f ms median (%d samples)",
            global_idx, num_layers, median(samples) * 1000, len(samples),
        )
        del blocks, block
        if is_cuda:
            torch.cuda.empty_cache()

    return profiles
```

Update the imports at the top of the file: drop `load_model` and
`get_transformer_layers`, add `AutoConfig` from `transformers`,
`get_architecture` from `radp.common.architectures`, and
`DTYPE_MAP`, `DTYPE_BYTES`, `load_stage_blocks`, `layer_param_bytes`,
`estimate_kv_cache_bytes` from `radp.common.model_utils`. Add
`from statistics import median` and keep `import time`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_block_profiler.py -v -m slow`
Expected: PASS (2 tests)

- [ ] **Step 5: Check the numbers did not move**

Run: `.venv/bin/python -m pytest tests/test_profilers.py -v -m slow 2>&1 | tail -5`
Expected: PASS. If a test asserts on absolute timings, compare old vs new medians on the same host and record both in the commit message rather than loosening the assertion silently.

- [ ] **Step 6: Commit**

```bash
git add radp/profiler/layer_profiler.py tests/test_block_profiler.py
git commit -m "perf(profiler): profile one block at a time instead of the whole model"
```

---

### Task 6: Prepare the fleet

Ops only — no code. Everything here is reversible except cache deletion, which is authorised.

**Files:** none (fleet state)

**Interfaces:**
- Consumes: `scripts/extract_head_bundle.py` from Task 4.
- Produces: a fleet that can hold Llama-2-7B, and `RADP_HEAD_BUNDLE` set on the coordinator.

- [ ] **Step 1: Free disk on the workers that need a shard**

```bash
ansible workers -i deploy/inventory.ini -m shell -a "rm -rf ~/.cache/huggingface/hub/models--facebook--opt-1.3b ~/.cache/huggingface/hub/models--facebook--opt-125m; du -sh ~/.cache/huggingface; df -h / | tail -1"
```

`on-1` (9.4 GB free, 14 GB cache) and `on-6` (12 GB free, 31 GB cache) must end
with at least 12 GB free. If they do not, remove more model directories under
`~/.cache/huggingface/hub/` — but never touch anything outside that path.

- [ ] **Step 2: Redeploy on-5**

`on-5` rejoined the fleet at a stale checkout (`382739b`).

```bash
ansible-playbook -i deploy/inventory.ini deploy/playbook.yml --tags update --limit on-5
ansible on-5 -i deploy/inventory.ini -m shell -a "cd ~/radp && git log --oneline -1"
```

Expected: the worker's checkout matches this branch's HEAD.

- [ ] **Step 3: Build and ship the head bundle**

Run locally (this machine has disk; `ax-1` does not):

```bash
.venv/bin/python scripts/extract_head_bundle.py NousResearch/Llama-2-7b-hf \
    -o /tmp/llama2-7b-head.safetensors
ls -lh /tmp/llama2-7b-head.safetensors
```

Expected: ~512 MB, 3 tensors.

```bash
ansible ax-1 -i deploy/inventory.ini -m copy \
    -a "src=/tmp/llama2-7b-head.safetensors dest=/home/isp/llama2-7b-head.safetensors"
ansible ax-1 -i deploy/inventory.ini -m shell -a "ls -lh ~/llama2-7b-head.safetensors; df -h / | tail -1"
```

Expected: the file lands and `ax-1` still has free space.

- [ ] **Step 4: Point the coordinator at the bundle**

Add `RADP_HEAD_BUNDLE=/home/isp/llama2-7b-head.safetensors` to the coordinator's
service environment in `deploy/` (the same place `RADP_PARITY_K` is set), then
redeploy the coordinator:

```bash
grep -rn "RADP_PARITY_K" deploy/
ansible-playbook -i deploy/inventory.ini deploy/playbook.yml --tags update --limit coordinator
```

- [ ] **Step 5: Measure the claim on real hardware**

This is the gate the whole design rests on. On a Nano:

```bash
ansible on-5 -i deploy/inventory.ini -m shell -a \
  "~/radp/.venv/bin/python -c \"
from radp.common.model_utils import load_head_modules, measure_resident_bytes
b = measure_resident_bytes()
load_head_modules('NousResearch/Llama-2-7b-hf', dtype='float16', torch_device='cpu')
print('rss delta MB', (measure_resident_bytes()-b)/2**20)
\""
```

Expected: under 1000 MB. If it exceeds that, stop and report — the design's
premise is wrong and the remaining tasks are not worth running.

- [ ] **Step 6: Record fleet state**

Append a short section to `experiments/REPORT.md` noting: caches purged, `on-5`
restored to the CUDA tier, head bundle size, and the measured RSS delta from
Step 5.

```bash
git add experiments/REPORT.md
git commit -m "docs(report): record fleet preparation for 7B"
```

---

### Task 7: Serve Llama-2-7B end to end

**Files:**
- Modify: `experiments/REPORT.md`, `PHASES.md`

**Interfaces:**
- Consumes: everything above.
- Produces: a live 7B deployment and its recorded placement, plus the layer
  profile the ψ–R coupling measurement (separate plan) will need.

- [ ] **Step 1: Time one layer before committing to a full profile**

```bash
ansible on-5 -i deploy/inventory.ini -m shell -a \
  "~/radp/.venv/bin/python -m radp.cli.profile --model NousResearch/Llama-2-7b-hf --layers 1 --repeat 3"
```

If a single layer takes more than ~2 s on a CUDA Nano, a 32-layer profile per
device is impractical; report the number and stop rather than starting a run
that will not finish.

- [ ] **Step 2: Profile the CUDA tier**

Profile on `ao-2`, `on-1`, `on-2`, `on-5`, `on-6` only. `on-3`/`on-4` are
CPU-forced (`compute_throughput` ≈ 0.011) and stay backup hosts, which need
memory and bandwidth, not a layer profile.

- [ ] **Step 3: Solve a placement and deploy**

Start the coordinator against `NousResearch/Llama-2-7b-hf` and let it solve.
Record the resulting ψ and R from `GET /api/cluster`.

- [ ] **Step 4: Generate**

Send one prompt through `POST /api/generate` and confirm the output is coherent
text, not repeated tokens. Repetition is the known signature of a chain wired
head-only (see the `wire_chain` note in the project memory), not of a loading bug.

- [ ] **Step 5: Record the result**

Append to `experiments/REPORT.md`: the placement, the recovery table, per-device
peak RSS during the run, and whether any stage's backup had no viable host —
that last one is the first real observation about ψ–R coupling at 7B, and it is
the input to the next plan.

Add a Phase section to `PHASES.md` per the project's standing rule.

- [ ] **Step 6: Commit**

```bash
git add experiments/REPORT.md PHASES.md
git commit -m "docs(report): Llama-2-7B serving on the Jetson fleet"
```

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| §3.1 lazy head/embedding modules | 1, 2 |
| §3.1 `head_module_spec` on architectures | 1 |
| §3.1 tied-embedding fallback | 2 (implemented in `load_head_modules`) |
| §3.2 block-wise profiler | 5 |
| §3.3 CUDA-only profiling for 7B | 7 step 2 |
| §4 prerequisites (disk, on-5 redeploy) | 6 |
| §4.1 head bundle | 4, 6 step 3-4 |
| §5 unit test vs `load_model` | 2 |
| §5 tied-embedding test | see gap below |
| §5 block-wise profiler test | 5 |
| §5 memory test on hardware | 6 step 5 |
| §5 live serve | 7 |

**Gap found and closed:** §5 asks for a tied-embedding unit test, and Task 2
implements the fallback but OPT-125M does not tie, so the slow tests cannot
reach it. A non-slow test now sits inside Task 2 Step 1 — not here. Anything
that lives only in this self-review section is invisible to a task brief, which
extracts a single task's text; requirements belong in the task.

**Placeholder scan:** no TBD/TODO; every code step carries real code.

**Type consistency:** `HeadModuleSet` is used with the same field names
(`decoder`, `lm_head`, `key_prefixes`) in Tasks 1, 2, 4. `load_head_modules`
keeps one signature across Tasks 2, 3, 4, 6. `profile_layers` keeps its existing
signature in Task 5.

**Risk found and closed during self-review:** Task 3 originally said "update
every `self.handle` hit", which is the kind of instruction that gets half-done.
Enumerating them showed `self.handle` supplies three different things, not one —
the modules, the tokenizer (3 sites), and the config (1 site). Only the first is
what `load_head_modules` returns, so the task now lists all five substitutions
explicitly and ends with a `grep` that must come back empty.

**Remaining uncertainty, stated rather than hidden:** Task 7 Step 1 may find
that a single 7B layer is too slow to profile on a Nano. That is a real possible
outcome, not a defect, and the step says to report the number and stop rather
than start a run that cannot finish. The fallback — profiling only on `ao-2` and
extrapolating per-device times from the existing throughput ratios — is a
decision for whoever sees that number, not something to pre-commit here.
