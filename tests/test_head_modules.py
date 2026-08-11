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
