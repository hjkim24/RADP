"""Driver scaffold tests for B1 fault-tolerance baseline comparison.

Marked `slow`: `generate_reference` loads opt-125m in-process.
"""

from __future__ import annotations

import pytest

from experiments.b1_ft_baselines import (
    BaselineResult,
    chain_config,
    generate_reference,
    run_radp,
)

pytestmark = pytest.mark.slow


def test_chain_config_has_interior_victim():
    device_ids, placement, recovery, victim = chain_config()
    assert victim == "worker-b"
    # victim is interior: not the first and not the last stage's device
    assert placement[0].device != victim
    assert placement[-1].device != victim
    assert recovery[victim] in device_ids


def test_generate_reference_returns_tokens_and_walltime():
    toks, wall = generate_reference(prompt="The quick brown fox", max_tokens=6)
    assert len(toks) == 6
    assert wall > 0.0


def test_radp_recovers_full_sequence():
    prompt, max_tokens = "The quick brown fox", 12
    ref, _ = generate_reference(prompt=prompt, max_tokens=max_tokens)
    r = run_radp(prompt=prompt, max_tokens=max_tokens, kill_after_tokens=4, reference=ref)
    assert r.name == "RADP"
    assert not r.aborted
    assert r.tokens_completed == max_tokens
    assert r.sequence_matches_reference is True
    assert r.ttr_seconds is not None and r.ttr_seconds > 0
