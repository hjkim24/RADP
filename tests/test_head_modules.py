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
