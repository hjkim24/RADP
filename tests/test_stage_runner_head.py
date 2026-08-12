"""StageRunner.load_head coverage (Task 3 review fix).

No test previously called StageRunner.load_head at any level — the only
production callers are the coordinator's deploy() (real fleet) and the
gRPC worker server, neither exercised by the suite. This mirrors
test_head_modules.py::test_head_modules_produce_identical_logits, but for
the worker's chain-tail head instead of the coordinator's, so a wiring bug
(wrong attribute, dtype, device) would show up as a numeric mismatch
instead of passing silently on an "is not None" check.
"""

from __future__ import annotations

import pytest
import torch

from radp.common.architectures import get_architecture
from radp.common.model_utils import load_model
from radp.common.types import DeviceId
from radp.worker.stage_runner import StageRunner


@pytest.mark.slow
def test_load_head_installs_modules_matching_full_model() -> None:
    """Numerical equality on the path the chain-tail worker actually runs."""
    model_id = "facebook/opt-125m"

    runner = StageRunner(DeviceId("worker-a"), torch_device="cpu", dtype="float32")
    runner.load_head(model_id)
    assert runner.has_head

    full = load_model(model_id, dtype="float32", torch_device="cpu")
    arch = get_architecture(full.model.config.model_type)
    ref_decoder = arch.get_decoder(full.model)

    hidden = torch.randn(1, 4, full.model.config.hidden_size)
    with torch.no_grad():
        ref_logits = arch.head(ref_decoder, full.model.lm_head, hidden)
        runner_logits = arch.head(runner._head_decoder, runner._head_lm_head, hidden)

    assert torch.equal(runner_logits, ref_logits)
