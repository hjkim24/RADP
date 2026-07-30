"""Flip hunt (advisor #3 deep-dive): does the cross-tier recompute drift ever
flip a real greedy decision?

Efficient sampling via teacher-forcing. One tier (cuda) greedy-generates several
diverse sequences; then BOTH tiers run ONE forward over each of those SAME
sequences and emit the per-position top-2 (id, logit). Comparing the per-position
argmax across tiers samples every decision in one forward — no autoregressive
cascade — so a few thousand decisions are covered cheaply. A position where
cuda-argmax != cpu-argmax is a real flip (the greedy next-token would differ).

Phases (see the session/Bash controller):
  1. `--generate-batch` on cuda  -> list of token-id sequences (one per prompt)
  2. `--teacher-force-batch --ids-file F` on cuda AND cpu -> per-seq per-position top-2
  3. controller compares argmax per position.
"""
from __future__ import annotations

import argparse
import json
import os

PROMPTS = [
    "The history of modern science begins in the seventeenth century, when",
    "Once upon a time, in a small village by the sea, there lived",
    "To configure the server, first open the settings file and then",
    "The recipe calls for the following ingredients: flour, sugar,",
    '"I never expected to see you here," she said, and he replied,',
    "In conclusion, the main advantages of distributed systems are",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generate-batch", action="store_true")
    ap.add_argument("--teacher-force-batch", action="store_true")
    ap.add_argument("--n", type=int, default=512, help="tokens to generate per prompt")
    ap.add_argument("--ids-file", default="/tmp/radp_hunt_ids.json")
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
        .to(device).eval()
    )

    if args.generate_batch:
        seqs = []
        for p in PROMPTS:
            ids = tok(p, return_tensors="pt").input_ids.to(device)
            with torch.no_grad():
                out = model.generate(ids, max_new_tokens=args.n, do_sample=False)
            seqs.append(out[0].tolist())
        print(json.dumps({"device": device, "seqs": seqs}))
        return

    if args.teacher_force_batch:
        seqs = json.load(open(args.ids_file))["seqs"]
        per_seq = []
        for s in seqs:
            ids = torch.tensor([s], device=device)
            with torch.no_grad():
                logits = model(ids).logits[0].float()  # [seq, vocab]
            t2 = torch.topk(logits, 2, dim=-1)
            per_seq.append([
                [int(t2.indices[i, 0]), float(t2.values[i, 0]),
                 int(t2.indices[i, 1]), float(t2.values[i, 1])]
                for i in range(logits.shape[0])
            ])
        print(json.dumps({
            "device": device,
            "dtype": str(dtype).split(".")[-1],
            "per_seq": per_seq,
        }))
        return


if __name__ == "__main__":
    main()
