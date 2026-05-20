"""Single-token sampling primitives (Phase 2.9).

The coordinator computes logits via the LM head and then chooses one
token id per step. This module isolates the choice policy:

  * ``temperature == 0``       → greedy argmax (deterministic, the default)
  * ``temperature > 0``        → softmax sampling, optionally constrained by:
      - ``top_k > 0``          → keep only the k highest-logit tokens
      - ``0 < top_p < 1``      → nucleus filter (smallest set with cum_prob ≥ top_p)
  * ``generator``              → torch.Generator for reproducibility

Operates on a 1-D logits tensor of shape ``[vocab_size]``.
"""

from __future__ import annotations

import torch


def sample_next_token(
    logits: torch.Tensor,
    *,
    temperature: float = 0.0,
    top_k: int = 0,
    top_p: float = 1.0,
    generator: torch.Generator | None = None,
) -> int:
    """Return a single token id sampled from ``logits``.

    ``logits`` shape: ``[vocab_size]``. Computation runs on whatever device
    the tensor lives on; the optional ``generator`` MUST live on that same
    device (``torch.multinomial`` requires matching device).
    """
    if logits.dim() != 1:
        raise ValueError(f"Expected 1-D logits, got shape {tuple(logits.shape)}")
    if temperature <= 0.0:
        return int(torch.argmax(logits).item())

    scaled = logits / max(temperature, 1e-6)

    # Top-k filter: mask out everything below the kth-largest logit.
    if 0 < top_k < scaled.size(-1):
        kth = torch.topk(scaled, top_k).values[-1]
        scaled = torch.where(
            scaled < kth, torch.full_like(scaled, float("-inf")), scaled
        )

    # Top-p (nucleus): keep smallest set whose cumulative probability ≥ top_p.
    # Always keep at least the most-likely token.
    if 0.0 < top_p < 1.0:
        sorted_logits, sorted_idx = torch.sort(scaled, descending=True)
        probs = torch.softmax(sorted_logits, dim=-1)
        cum = torch.cumsum(probs, dim=-1)
        # Tokens whose cumulative-prob already exceeds top_p (i.e. tail of distribution).
        drop = cum > top_p
        drop[0] = False
        sorted_logits = sorted_logits.masked_fill(drop, float("-inf"))
        scaled = torch.empty_like(scaled).scatter_(0, sorted_idx, sorted_logits)

    probs = torch.softmax(scaled, dim=-1)
    return int(torch.multinomial(probs, num_samples=1, generator=generator).item())
