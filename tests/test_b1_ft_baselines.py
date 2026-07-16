"""Driver scaffold tests for B1 fault-tolerance baseline comparison.

Marked `slow`: `generate_reference` loads opt-125m in-process.
"""

from __future__ import annotations

import logging

import pytest

from experiments.b1_ft_baselines import (
    BaselineResult,
    chain_config,
    generate_reference,
    generate_wired_reference,
    run_radp_full_replay,
    run_radp_surgical,
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


def test_radp_surgical_line(caplog):
    """RADP-surgical under a mid-stage crash: recovers the exact wired
    reference sequence via the SURGICAL rebuild branch (not the fallback)."""
    prompt, max_tokens, kill_after = "The quick brown fox", 12, 4
    reference = generate_wired_reference(prompt=prompt, max_tokens=max_tokens)
    with caplog.at_level(logging.WARNING, logger="radp.coordinator.gateway"):
        r = run_radp_surgical(
            prompt=prompt, max_tokens=max_tokens,
            kill_after_tokens=kill_after, reference=reference,
        )
    assert r.name == "RADP-surgical"
    assert not r.aborted
    assert r.tokens_completed == max_tokens
    assert r.sequence_matches_reference is True, (
        f"recovered token ids did not match the wired reference exactly"
    )
    assert r.ttr_seconds is not None and r.ttr_seconds > 0
    assert "SURGICAL rebuild" in caplog.text, (
        "surgical line did not run the surgical rebuild branch:\n" + caplog.text
    )
    assert "falling back to full-chain replay" not in caplog.text, (
        "surgical line fell back to full-chain replay instead of the "
        "surgical branch:\n" + caplog.text
    )


def test_radp_full_replay_line():
    """RADP-full-replay under the SAME mid-stage crash: recovers the exact
    wired reference sequence via the O(positions x stages) replay path."""
    prompt, max_tokens, kill_after = "The quick brown fox", 12, 4
    reference = generate_wired_reference(prompt=prompt, max_tokens=max_tokens)
    r = run_radp_full_replay(
        prompt=prompt, max_tokens=max_tokens,
        kill_after_tokens=kill_after, reference=reference,
    )
    assert r.name == "RADP-full-replay"
    assert not r.aborted
    assert r.tokens_completed == max_tokens
    assert r.sequence_matches_reference is True, (
        f"recovered token ids did not match the wired reference exactly"
    )
    assert r.ttr_seconds is not None and r.ttr_seconds > 0
