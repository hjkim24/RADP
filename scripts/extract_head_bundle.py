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


def _drop_tied_lm_head(
    wanted: dict[str, torch.Tensor],
    lm_head_prefix: str | None,
    tie_word_embeddings: bool,
) -> dict[str, torch.Tensor]:
    """Drop lm_head keys that alias another kept tensor's storage.

    Checkpoints with tied embeddings (e.g. opt-125m) store lm_head.weight as
    a *view* over embed_tokens.weight's storage; safetensors refuses to save
    two keys pointing at one buffer.

    Dropping is only safe when the checkpoint's structural fact (storage
    aliasing) agrees with the config's declared fact (tie_word_embeddings) —
    load_head_modules()'s restore path is gated on the config flag, not on
    storage layout. If they disagree, dropping would ship a bundle that
    silently leaves lm_head at its random nn.Linear init on load (no
    exception, just a warning). Raise here instead, on the machine with
    disk, rather than let that reach the coordinator.
    """
    if not lm_head_prefix:
        return wanted
    other_ptrs = {
        t.data_ptr() for k, t in wanted.items() if not k.startswith(lm_head_prefix)
    }
    aliased = {
        k
        for k, t in wanted.items()
        if k.startswith(lm_head_prefix) and t.data_ptr() in other_ptrs
    }
    if not aliased:
        return wanted
    if not tie_word_embeddings:
        raise SystemExit(
            f"{sorted(aliased)} share storage with another kept tensor (the "
            "checkpoint structurally ties them) but config.tie_word_embeddings "
            "is False. Dropping it would make load_head_modules() silently "
            "leave lm_head randomly initialized; refusing to write a bundle "
            "that disagrees with its own config."
        )
    return {k: t for k, t in wanted.items() if k not in aliased}


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
        # Some checkpoints (opt-350m safetensors, opt-6.7b bin) publish bare
        # keys without the leading "model." -- the same detection
        # load_head_modules() performs, so the bundle matches what it will
        # later read back. Keys are written as found; the loader re-detects.
        prefixes = list(hms.key_prefixes.values())
        probe = hms.key_prefixes["embed_tokens"]
        if (
            probe.startswith("model.")
            and not any(k.startswith(probe) for k in keys)
            and any(k.startswith(probe[len("model."):]) for k in keys)
        ):
            prefixes = [
                p[len("model."):] if p.startswith("model.") else p for p in prefixes
            ]
        wanted = {
            k: reader.get_tensor(k).contiguous()
            for k in keys
            if any(k.startswith(p) for p in prefixes)
        }
    finally:
        reader.close()

    wanted = _drop_tied_lm_head(
        wanted,
        hms.key_prefixes.get("lm_head"),
        bool(getattr(config, "tie_word_embeddings", False)),
    )

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
