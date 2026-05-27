"""Phase D4 — cluster.yaml.j2 round-trip with CoordinatorConfig.

The Ansible template + the YAML parser are a contract; if they drift the
coordinator silently boots with wrong/missing config. Render the actual
deploy/ template against both schedule modes and assert that
CoordinatorConfig.from_yaml accepts the result and produces the expected
fields.
"""

from __future__ import annotations

from pathlib import Path

import jinja2
import pytest

from radp.common.types import DeviceId
from radp.coordinator.server import CoordinatorConfig

_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "deploy/roles/radp-coordinator/templates/cluster.yaml.j2"
)


def _render(**vars: object) -> str:
    return jinja2.Template(_TEMPLATE_PATH.read_text()).render(**vars)


_COMMON_VARS = {
    "model_id": "facebook/opt-125m",
    "model_dtype": "float16",
    "model_torch_device": "cpu",
    "radp_coord_port": 50050,
    "radp_worker_port": 50051,
    "heartbeat_timeout_seconds": 5.0,
    "heartbeat_tick_seconds": 1.0,
    "groups": {"workers": ["w-1", "w-2"]},
    "hostvars": {
        "w-1": {"device_id": "w-1", "ansible_host": "10.0.0.1"},
        "w-2": {"device_id": "w-2", "ansible_host": "10.0.0.2"},
    },
}


def test_template_renders_auto_mode(tmp_path: Path) -> None:
    rendered = _render(
        **_COMMON_VARS,
        schedule_mode="auto",
        activation_bytes=524288,
        slo_ttft_seconds=0.5,
        slo_tbt_seconds=0.2,
        profiling_layer_warmup=2,
        profiling_layer_repeats=4,
        profiling_layer_seq_length=24,
        profiling_network_payload_bytes=2048,
        profiling_network_rounds=5,
        profiling_wait_timeout_seconds=30.0,
    )
    p = tmp_path / "cluster.yaml"
    p.write_text(rendered)

    cfg = CoordinatorConfig.from_yaml(p)
    assert cfg.schedule_mode == "auto"
    # auto mode: placement + recovery are absent → empty
    assert cfg.placement == []
    assert cfg.recovery == {}
    # SLO + profiling + activation are all carried through
    assert cfg.slo_ttft_seconds == pytest.approx(0.5)
    assert cfg.slo_tbt_seconds == pytest.approx(0.2)
    assert cfg.activation_bytes == 524288
    assert cfg.profiling_layer_warmup == 2
    assert cfg.profiling_layer_repeats == 4
    assert cfg.profiling_layer_seq_length == 24
    assert cfg.profiling_network_payload_bytes == 2048
    assert cfg.profiling_network_rounds == 5
    assert cfg.profiling_wait_timeout_seconds == pytest.approx(30.0)
    # Workers come from groups['workers']
    assert {w.device_id for w in cfg.workers} == {
        DeviceId("w-1"), DeviceId("w-2"),
    }


def test_template_renders_manual_mode(tmp_path: Path) -> None:
    rendered = _render(
        **_COMMON_VARS,
        schedule_mode="manual",
        cluster_placement=[
            {"device": "w-1", "start": 1, "end": 6},
            {"device": "w-2", "start": 7, "end": 12},
        ],
        cluster_recovery={"w-1": "w-2", "w-2": "w-1"},
    )
    p = tmp_path / "cluster.yaml"
    p.write_text(rendered)

    cfg = CoordinatorConfig.from_yaml(p)
    assert cfg.schedule_mode == "manual"
    assert len(cfg.placement) == 2
    assert cfg.recovery == {
        DeviceId("w-1"): DeviceId("w-2"),
        DeviceId("w-2"): DeviceId("w-1"),
    }


def test_template_omits_placement_block_in_auto_mode(tmp_path: Path) -> None:
    """auto-rendered YAML must not contain manual-mode keys at all."""
    rendered = _render(**_COMMON_VARS, schedule_mode="auto")
    assert "placement:" not in rendered
    assert "recovery:" not in rendered


def test_template_omits_profiling_block_in_manual_mode(tmp_path: Path) -> None:
    """manual-rendered YAML must not carry profiling knobs."""
    rendered = _render(
        **_COMMON_VARS,
        schedule_mode="manual",
        cluster_placement=[{"device": "w-1", "start": 1, "end": 12}],
        cluster_recovery={},
    )
    assert "profiling:" not in rendered
    # SLO is shared between modes, but profiling is auto-only
    assert "slo:" in rendered
