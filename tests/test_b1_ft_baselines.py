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
    generate_wired_reference_wall,
    resolve_excluding,
    run_all,
    run_b0_abort,
    run_b1_cold_restart,
    run_radp_full_replay,
    run_radp_surgical,
)

# Model-loading tests are marked individually (not via a blanket module
# `pytestmark`) so `test_resolve_excluding_covers_all_layers` — pure
# placement-splitting logic, no model involved — stays collectable and
# runs by default (without `-m slow`).


@pytest.mark.slow
def test_chain_config_has_interior_victim():
    device_ids, placement, recovery, victim = chain_config()
    assert victim == "worker-b"
    # victim is interior: not the first and not the last stage's device
    assert placement[0].device != victim
    assert placement[-1].device != victim
    assert recovery[victim] in device_ids


@pytest.mark.slow
def test_generate_reference_returns_tokens_and_walltime():
    toks, wall = generate_reference(prompt="The quick brown fox", max_tokens=6)
    assert len(toks) == 6
    assert wall > 0.0


@pytest.mark.slow
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


@pytest.mark.slow
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


@pytest.mark.slow
def test_b0_abort_line():
    """No backup deployed: the SAME mid-stage crash makes ``mark_dead``
    raise ``NoRecoveryError`` inside the gateway's recovery path, and the
    stream aborts with a partial (but reference-matching prefix) token run.
    """
    prompt, max_tokens, kill_after = "The quick brown fox", 12, 4
    reference = generate_wired_reference(prompt=prompt, max_tokens=max_tokens)
    r = run_b0_abort(
        prompt=prompt, max_tokens=max_tokens,
        kill_after_tokens=kill_after, reference=reference,
    )
    assert r.name == "B0-abort"
    assert r.aborted is True
    assert r.ttr_seconds is None
    assert r.tokens_completed < max_tokens, (
        f"abort should not complete all {max_tokens} tokens; "
        f"got {r.tokens_completed}"
    )
    assert r.sequence_matches_reference is False


def test_resolve_excluding_covers_all_layers():
    """Pure placement-splitting logic — no model, not slow. Re-solving over
    the survivors {worker-a, worker-c} must cover layers 1..12 gaplessly,
    with no overlaps, using exactly those two devices."""
    plan = resolve_excluding("worker-b", ["worker-a", "worker-c"])
    ordered = sorted(plan, key=lambda s: int(s.start_layer))
    assert {s.device for s in plan} == {"worker-a", "worker-c"}
    assert int(ordered[0].start_layer) == 1
    assert int(ordered[-1].end_layer) == 12
    for prev, nxt in zip(ordered, ordered[1:]):
        assert int(prev.end_layer) + 1 == int(nxt.start_layer), (
            f"gap/overlap between {prev} and {nxt}"
        )


@pytest.mark.slow
def test_run_all_returns_all_four_lines():
    """The unified driver generates the wired reference ONCE and runs all
    four lines against it, returning a single JSON-serializable record."""
    rec = run_all(prompt="The quick brown fox", max_tokens=12, kill_after_tokens=4)

    names = {l["name"] for l in rec["lines"]}
    assert names == {
        "RADP-surgical", "RADP-full-replay", "B1-cold-restart", "B0-abort",
    }
    for line in rec["lines"]:
        assert set(line) >= {
            "ttr_seconds", "tokens_completed", "goodput_tok_per_s",
            "sequence_matches_reference", "aborted",
        }
    assert rec["reference_wall_seconds"] > 0


@pytest.mark.slow
def test_b1_cold_restart_line():
    """Cold-restart under the SAME mid-stage crash: first attempt aborts,
    then a fresh placement + gateway over the survivors reproduces the
    exact wired reference sequence from scratch."""
    prompt, max_tokens, kill_after = "The quick brown fox", 12, 4
    reference = generate_wired_reference(prompt=prompt, max_tokens=max_tokens)
    _ref_toks, reference_wall = generate_wired_reference_wall(
        prompt=prompt, max_tokens=max_tokens
    )
    r = run_b1_cold_restart(
        prompt=prompt, max_tokens=max_tokens, kill_after_tokens=kill_after,
        reference=reference, reference_wall=reference_wall,
    )
    assert r.name == "B1-cold-restart"
    assert not r.aborted
    assert r.tokens_completed == max_tokens
    assert r.sequence_matches_reference is True, (
        "cold-restart's re-run over survivors did not match the wired "
        "reference exactly"
    )
    assert r.ttr_seconds is not None and r.ttr_seconds >= 0
