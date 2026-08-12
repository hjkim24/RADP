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

    # Tied-embedding checkpoints (e.g. opt-125m) store lm_head.weight as a
    # view over the same storage as embed_tokens.weight; safetensors refuses
    # to serialize two keys that alias one buffer. Drop the lm_head copy —
    # load_head_modules()'s tie fallback (config.tie_word_embeddings)
    # reconstructs it from embed_tokens on load.
    lm_head_prefix = hms.key_prefixes.get("lm_head")
    if lm_head_prefix:
        other_ptrs = {
            t.data_ptr() for k, t in wanted.items() if not k.startswith(lm_head_prefix)
        }
        wanted = {
            k: t
            for k, t in wanted.items()
            if not (k.startswith(lm_head_prefix) and t.data_ptr() in other_ptrs)
        }

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
