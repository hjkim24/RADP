"""Unit tests for sample_next_token (Phase 2.9)."""

from __future__ import annotations

import torch

from radp.coordinator.sampling import sample_next_token


def _logits(values: list[float]) -> torch.Tensor:
    return torch.tensor(values, dtype=torch.float32)


def test_greedy_picks_argmax() -> None:
    logits = _logits([0.1, 5.0, 1.0, 4.9])
    assert sample_next_token(logits, temperature=0.0) == 1


def test_seed_makes_sampling_deterministic() -> None:
    logits = _logits([1.0, 1.0, 1.0, 1.0])  # uniform-ish

    def draw(seed: int) -> list[int]:
        g = torch.Generator()
        g.manual_seed(seed)
        return [
            sample_next_token(logits, temperature=1.0, generator=g)
            for _ in range(20)
        ]

    assert draw(42) == draw(42)
    assert draw(42) != draw(43)  # vanishing probability under seed=42 specifically


def test_top_k_one_collapses_to_argmax() -> None:
    logits = _logits([0.1, 0.2, 5.0, 0.3, 4.0])
    g = torch.Generator()
    g.manual_seed(0)
    for _ in range(10):
        assert sample_next_token(logits, temperature=1.0, top_k=1, generator=g) == 2


def test_top_k_only_returns_within_top_k() -> None:
    logits = _logits([0.1, 0.2, 5.0, 0.3, 4.0, 4.5])
    g = torch.Generator()
    g.manual_seed(0)
    allowed = {2, 4, 5}  # top-3 indices
    for _ in range(50):
        tok = sample_next_token(logits, temperature=1.0, top_k=3, generator=g)
        assert tok in allowed


def test_top_p_keeps_only_nucleus() -> None:
    # Two tokens have ~equal large logits and one tiny — nucleus(0.95) should
    # include the two big tokens and exclude the tiny one.
    logits = _logits([5.0, 5.0, -10.0])
    g = torch.Generator()
    g.manual_seed(0)
    seen = set()
    for _ in range(100):
        tok = sample_next_token(logits, temperature=1.0, top_p=0.95, generator=g)
        seen.add(tok)
    assert 2 not in seen
    assert seen.issubset({0, 1})


def test_top_p_always_keeps_top_one_even_under_tight_cutoff() -> None:
    logits = _logits([10.0, 0.1, 0.1])
    g = torch.Generator()
    g.manual_seed(0)
    # Effectively forces argmax (top-1 dominates) but we exercise the
    # "always keep top" guard with a very tight top_p.
    for _ in range(20):
        assert sample_next_token(logits, temperature=1.0, top_p=0.01, generator=g) == 0
