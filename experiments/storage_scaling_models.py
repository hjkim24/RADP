"""Storage-overhead scaling across model sizes (advisor feedback 2026-07-30, #1).

Pure arithmetic from model geometry — no model is run (big models don't fit on
the Nano fleet anyway; KV storage is geometry, not a live measurement). Answers
"does a bigger model make the replicate-vs-parity absolute gap larger?"

Model:
  KV per layer per token (fp16) = 2(K,V) x n_kv_heads x head_dim x 2 bytes
  For a balanced N-stage pipeline (1 head stage + (N-1) non-head stages), each
  stage holds ~L/N layers. The coordinator backs up only NON-HEAD stages (the
  head is re-embedded from tokens), so:
    replicate = (N-1) non-head stages  = (N-1)/N of the full KV  (Sigma)
    parity    = 1 largest stage        =     1/N of the full KV  (max)
    ratio     = N-1     (grows with pipeline DEPTH, model-independent)
    abs gap   = replicate - parity = (N-2)/N of the full KV  (grows with model x context)
The full KV cache per token = L x per-layer, so both scale with model size and
context length; parity keeps only 1/N of what replicate stores.
"""
from __future__ import annotations

# name -> (n_layers, n_kv_heads, head_dim)  [MHA: n_kv_heads == n_heads]
MODELS = {
    "OPT-350M":  (24, 16, 64),
    "OPT-1.3B":  (24, 32, 64),
    "OPT-2.7B":  (32, 32, 80),
    "OPT-6.7B":  (32, 32, 128),
    "Llama2-7B": (32, 32, 128),
    "OPT-13B":   (40, 40, 128),
}
ITEMSIZE = 2  # fp16


def per_layer_token_bytes(n_kv_heads: int, head_dim: int) -> int:
    return 2 * n_kv_heads * head_dim * ITEMSIZE  # K and V


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}"
        n /= 1024


def main() -> None:
    N = 5           # pipeline stages (matches our fleet: 1 head + 4 non-head)
    seqs = [1, 512, 2048, 4096]
    print(f"# balanced N={N}-stage pipeline; ratio replicate/parity = N-1 = {N-1}x\n")
    hdr = f"{'model':10} {'full KV/tok':>11} | " + " | ".join(
        f"gap@{s}tok" if s > 1 else "gap/tok" for s in seqs)
    print(hdr)
    print("-" * len(hdr))
    for name, (L, kvh, hd) in MODELS.items():
        per_layer = per_layer_token_bytes(kvh, hd)
        full_tok = L * per_layer
        # replicate = (N-1)/N of full non-head; parity = 1/N; gap = (N-2)/N of full
        gap_tok = full_tok * (N - 2) / N
        cells = " | ".join(f"{human(gap_tok * s):>8}" for s in seqs)
        print(f"{name:10} {human(full_tok):>11} | {cells}")
    print()
    # concrete replicate vs parity at one realistic point
    s = 2048
    print(f"# replicate vs parity backup size @ {s}-token context (balanced N={N}):")
    for name, (L, kvh, hd) in MODELS.items():
        per_layer = per_layer_token_bytes(kvh, hd)
        full = L * per_layer * s
        rep = full * (N - 1) / N
        par = full * 1 / N
        print(f"  {name:10} replicate {human(rep):>8}  parity {human(par):>8}  gap {human(rep-par):>8}")

    # Reconcile with the ACTUAL measured fleet placement (b1_ft_overhead.json).
    # Our fleet's head stage held 15/24 layers (ao-2 is a large AGX), so only 9
    # layers are non-head -> replicate=36864, parity=16384 per token (ratio 2.25,
    # not the balanced 4). That head-heavy split makes our gap the CONSERVATIVE
    # end; a typical even split gives the larger balanced numbers above.
    rep_tok, par_tok = 36864, 16384  # measured OPT-350M per token
    print(f"\n# ANCHOR — measured OPT-350M on the real fleet (head-heavy, ratio 2.25):")
    for s2 in (1, 512, 2048, 4096):
        print(f"  @{s2:>4}tok: replicate {human(rep_tok*s2):>8}  parity {human(par_tok*s2):>8}"
              f"  gap {human((rep_tok-par_tok)*s2):>8}")


if __name__ == "__main__":
    main()
