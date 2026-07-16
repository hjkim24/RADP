"""Driver scaffold tests for B1 fault-tolerance baseline comparison.

Marked `slow`: `generate_reference` loads opt-125m in-process.
"""

from __future__ import annotations

import pytest

from experiments.b1_ft_baselines import BaselineResult, chain_config, generate_reference

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
