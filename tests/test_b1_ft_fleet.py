"""Unit test for the fleet driver's parity-branch verification predicate.

No SSH, no ansible, no fleet — pure string-matching logic, so it's
collectable without `-m slow`. See experiments/b1_ft_fleet.py's
`_parity_branch_ran` docstring for why this check exists: the gateway's
`_recover_parity` safely falls back to `_recover_surgical` whenever parity
can't be trusted, so a "parity" trial can silently run the surgical path
and get mislabeled — this predicate is how the driver catches that.
"""

from __future__ import annotations

import pytest

from experiments.b1_ft_fleet import (
    _client_recovery_interval,
    _parity_branch_ran,
)

# The real zero-forward XOR path's marker, exactly as formatted by
# gateway.py's `_recover_parity` (the ``log.warning("request=%d PARITY
# reconstruct: backup %s stage[%d..%d] KV slots=%d (zero-forward XOR), then
# run pos %d live", ...)`` call).
_REAL_PARITY_LOG = (
    "2026-07-19 10:22:31 WARNING radp.coordinator.gateway: "
    "request=42 PARITY reconstruct: backup on-6 stage[16..17] KV "
    "slots=8 (zero-forward XOR), then run pos 8 live"
)

# A sample fallback line — one of several "can't trust parity" gates in
# `_recover_parity`, none of which contain the real-path marker.
_FALLBACK_LOG = (
    "2026-07-19 10:22:30 WARNING radp.coordinator.gateway: "
    "request=42 parity: no non-head survivors; fallback to surgical"
)


def test_parity_branch_ran_true_on_real_marker():
    assert _parity_branch_ran(_REAL_PARITY_LOG) is True


def test_parity_branch_ran_false_on_fallback_only():
    assert _parity_branch_ran(_FALLBACK_LOG) is False


def test_parity_branch_ran_false_on_empty_log():
    assert _parity_branch_ran("") is False


def test_parity_branch_ran_true_amid_other_lines():
    """The predicate greps the whole multi-line journal dump, not just the
    last line — the real marker can be surrounded by unrelated coordinator
    chatter (heartbeats, promote_backup, rewire logs)."""
    log_text = "\n".join([
        "some unrelated INFO line",
        _FALLBACK_LOG,  # e.g. an earlier already-dead attribution warning
        _REAL_PARITY_LOG,
        "trailing INFO line",
    ])
    assert _parity_branch_ran(log_text) is True


def test_client_recovery_interval_ends_at_first_new_token():
    interval, first_new = _client_recovery_interval(
        [" A", " B"], [1.0, 2.0],
        [" A", " B", " C", " D"], [10.0, 11.0, 12.5, 13.0],
    )
    assert interval == 10.5
    assert first_new == 2


def test_client_recovery_interval_rejects_mismatched_replay_prefix():
    with pytest.raises(ValueError, match="replayed prefix"):
        _client_recovery_interval(
            [" A", " B"], [1.0, 2.0],
            [" A", " X", " C"], [10.0, 11.0, 12.0],
        )
