"""Cross-tier OUTPUT divergence screen (advisor feedback 2026-07-30, #3).

Greedy-generate OPT-350M on THIS board's real device/dtype and print the token
IDs. Run on a CUDA board and a CPU board, then compare the two token sequences
to find the first position where the output diverges (if any).

This is an UPPER BOUND on recovery-induced divergence: running the WHOLE model
cross-tier is a bigger perturbation than a single recovered stage's KV. So if
full cross-tier generation does NOT diverge within N tokens, a real recovery
(one stage recomputed cross-tier) diverges no earlier — the fidelity axis then
has no output-level effect, and we keep only the KV-bit metric. If it DOES
diverge at position L, that L bounds where recovery could start to matter.

Board mode only; the controller (see run in the session/Bash) ships this file to
each board, runs it with an explicit RADP_TORCH_DEVICE per host, and compares.
"""
from __future__ import annotations

import argparse
import json
import os


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=256, help="tokens to generate (greedy)")
    ap.add_argument(
        "--prompt",
        default="The quick brown fox jumps over the lazy dog. In a distant future,",
    )
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = os.environ.get("RADP_TORCH_DEVICE", "cpu")
    dtype = (
        torch.float16
        if os.environ.get("RADP_DTYPE", "float16") == "float16"
        else torch.float32
    )
    tok = AutoTokenizer.from_pretrained("facebook/opt-350m")
    model = (
        AutoModelForCausalLM.from_pretrained("facebook/opt-350m", torch_dtype=dtype)
        .to(device)
        .eval()
    )
    ids = tok(args.prompt, return_tensors="pt").input_ids.to(device)
    with torch.no_grad():
        out = model.generate(ids, max_new_tokens=args.n, do_sample=False)  # greedy
    toks = out[0].tolist()
    print(json.dumps({
        "device": device,
        "dtype": str(dtype).split(".")[-1],
        "n_prompt": int(ids.shape[1]),
        "token_ids": toks,
    }))


if __name__ == "__main__":
    main()
