"""Model-family adapters (Phase 2.10).

Each adapter teaches RADP how to instantiate decoder blocks, map weight
keys for that family, embed/head on the coordinator, and run individual
blocks on the worker. Look up an adapter by ``config.model_type``.

Currently supported:
  * ``opt``    — OPT family (decoder.layers, learned position embeddings,
                 OPT block forward signature)
  * ``llama``  — LLaMA family (model.layers, RoPE, LlamaDecoderLayer)
  * ``mistral``— Mistral family (same forward shape as LLaMA, different
                 block class; LLaMA's adapter handles it with a different
                 block_class hook)
"""

from __future__ import annotations

from typing import Any, Protocol

import torch
from torch import nn


class ModelArchitecture(Protocol):
    """Adapter contract for one transformer family."""

    name: str

    def make_block(self, config: Any, layer_idx: int) -> nn.Module: ...
    def weight_prefix(self, layer_idx: int) -> str: ...
    def get_decoder(self, model: Any) -> Any: ...
    def embed(
        self,
        decoder: Any,
        input_ids: torch.Tensor,
        attention_mask_2d: torch.Tensor,
        past_kv_length: int,
    ) -> torch.Tensor: ...
    def head(self, decoder: Any, lm_head: nn.Module, hidden: torch.Tensor) -> torch.Tensor: ...
    def make_aux(
        self, config: Any, dtype: torch.dtype, device: str
    ) -> dict[str, nn.Module]: ...
    def run_block(
        self,
        block: nn.Module,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        cache: Any,
        past_length: int,
        aux: dict[str, nn.Module],
    ) -> torch.Tensor: ...


# ---------------------------------------------------------------------------
# OPT
# ---------------------------------------------------------------------------
class OPTArchitecture:
    name = "opt"

    def make_block(self, config: Any, layer_idx: int) -> nn.Module:
        from transformers.models.opt.modeling_opt import OPTDecoderLayer
        return OPTDecoderLayer(config, layer_idx=layer_idx)

    def weight_prefix(self, layer_idx: int) -> str:
        return f"model.decoder.layers.{layer_idx}."

    def get_decoder(self, model: Any) -> Any:
        return model.model.decoder

    def embed(
        self,
        decoder: Any,
        input_ids: torch.Tensor,
        attention_mask_2d: torch.Tensor,
        past_kv_length: int,
    ) -> torch.Tensor:
        inputs_embeds = decoder.embed_tokens(input_ids)
        # OPT-350M is the lone OPT variant with word_embed_proj_dim ≠ hidden_size
        # (512 ≠ 1024). Its `project_in` lifts the embedding into the decoder's
        # hidden space, and HF transformers applies it BEFORE adding pos_embeds.
        # Applying it after the sum produced a 512-vs-1024 mismatch.
        if getattr(decoder, "project_in", None) is not None:
            inputs_embeds = decoder.project_in(inputs_embeds)
        pos_embeds = decoder.embed_positions(
            attention_mask_2d, past_key_values_length=past_kv_length
        )
        hidden: torch.Tensor = inputs_embeds + pos_embeds
        return hidden

    def head(self, decoder: Any, lm_head: nn.Module, hidden: torch.Tensor) -> torch.Tensor:
        if getattr(decoder, "final_layer_norm", None) is not None:
            hidden = decoder.final_layer_norm(hidden)
        if getattr(decoder, "project_out", None) is not None:
            hidden = decoder.project_out(hidden)
        return lm_head(hidden)  # type: ignore[no-any-return]

    def make_aux(
        self, config: Any, dtype: torch.dtype, device: str
    ) -> dict[str, nn.Module]:
        return {}

    def run_block(
        self,
        block: nn.Module,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        cache: Any,
        past_length: int,
        aux: dict[str, nn.Module],
    ) -> torch.Tensor:
        # transformers 4.x OPTDecoderLayer expects `past_key_value` (singular);
        # 5.x renamed it to `past_key_values` (plural). Detect at call site so
        # the same radp build works against either transformers major.
        import inspect
        sig = inspect.signature(block.forward)
        kwargs: dict[str, Any] = {
            "attention_mask": attention_mask,
            "use_cache": True,
        }
        if "past_key_values" in sig.parameters:
            kwargs["past_key_values"] = cache
        elif "past_key_value" in sig.parameters:
            kwargs["past_key_value"] = cache
        out: Any = block(hidden, **kwargs)
        return out[0] if isinstance(out, tuple) else out  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# LLaMA / Mistral (share the same forward shape)
# ---------------------------------------------------------------------------
class _RoPEArchitecture:
    """Shared logic for RoPE-based decoders (LLaMA / Mistral / etc.).

    Subclasses override ``_block_cls()`` and ``_rotary_cls()``.
    """

    name: str = "override-me"

    def _block_cls(self) -> type[nn.Module]:
        raise NotImplementedError

    def _rotary_cls(self) -> type[nn.Module]:
        raise NotImplementedError

    def make_block(self, config: Any, layer_idx: int) -> nn.Module:
        return self._block_cls()(config, layer_idx=layer_idx)

    def weight_prefix(self, layer_idx: int) -> str:
        # LLaMA / Mistral both use `model.layers.{i}.` in their HF safetensors.
        return f"model.layers.{layer_idx}."

    def get_decoder(self, model: Any) -> Any:
        # No `decoder` namespace; the inner `model` holds embed_tokens + layers + norm.
        return model.model

    def embed(
        self,
        decoder: Any,
        input_ids: torch.Tensor,
        attention_mask_2d: torch.Tensor,
        past_kv_length: int,
    ) -> torch.Tensor:
        # RoPE families don't add a learned position embedding here — the
        # rotation happens inside each block's attention via position_embeddings.
        return decoder.embed_tokens(input_ids)  # type: ignore[no-any-return]

    def head(self, decoder: Any, lm_head: nn.Module, hidden: torch.Tensor) -> torch.Tensor:
        hidden = decoder.norm(hidden)
        return lm_head(hidden)  # type: ignore[no-any-return]

    def make_aux(
        self, config: Any, dtype: torch.dtype, device: str
    ) -> dict[str, nn.Module]:
        rope: nn.Module = self._rotary_cls()(config=config)
        rope.to(device=device, dtype=dtype)
        rope.eval()
        return {"rotary_emb": rope}

    def run_block(
        self,
        block: nn.Module,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        cache: Any,
        past_length: int,
        aux: dict[str, nn.Module],
    ) -> torch.Tensor:
        seq_len = int(hidden.shape[1])
        positions = torch.arange(
            past_length, past_length + seq_len, device=hidden.device
        )
        position_ids = positions.unsqueeze(0)  # [1, seq_len]
        position_embeddings = aux["rotary_emb"](hidden, position_ids)
        # Same plural/singular dance as OPT — accept whichever the installed
        # transformers actually wants.
        import inspect
        sig = inspect.signature(block.forward)
        kwargs: dict[str, Any] = {
            "attention_mask": attention_mask,
            "position_ids": position_ids,
            "use_cache": True,
            "cache_position": positions,
            "position_embeddings": position_embeddings,
        }
        if "past_key_values" in sig.parameters:
            kwargs["past_key_values"] = cache
        elif "past_key_value" in sig.parameters:
            kwargs["past_key_value"] = cache
        out: Any = block(hidden, **kwargs)
        return out[0] if isinstance(out, tuple) else out  # type: ignore[no-any-return]


class LlamaArchitecture(_RoPEArchitecture):
    name = "llama"

    def _block_cls(self) -> type[nn.Module]:
        from transformers.models.llama.modeling_llama import LlamaDecoderLayer
        return LlamaDecoderLayer

    def _rotary_cls(self) -> type[nn.Module]:
        from transformers.models.llama.modeling_llama import LlamaRotaryEmbedding
        return LlamaRotaryEmbedding


class MistralArchitecture(_RoPEArchitecture):
    name = "mistral"

    def _block_cls(self) -> type[nn.Module]:
        from transformers.models.mistral.modeling_mistral import MistralDecoderLayer
        return MistralDecoderLayer

    def _rotary_cls(self) -> type[nn.Module]:
        from transformers.models.mistral.modeling_mistral import MistralRotaryEmbedding
        return MistralRotaryEmbedding


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
_REGISTRY: dict[str, ModelArchitecture] = {
    "opt": OPTArchitecture(),
    "llama": LlamaArchitecture(),
    "mistral": MistralArchitecture(),
}


def get_architecture(model_type: str) -> ModelArchitecture:
    arch = _REGISTRY.get(model_type)
    if arch is None:
        raise NotImplementedError(
            f"No architecture adapter for model_type='{model_type}'. "
            f"Supported: {sorted(_REGISTRY)}"
        )
    return arch


def supported_model_types() -> list[str]:
    return sorted(_REGISTRY)
