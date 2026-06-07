"""EXP-D3 Phase 3 live recovery measurement.

Drives a Generate request, kills one worker mid-stream by stopping its
radp-worker systemd unit over SSH (via ansible), expects the gateway to:
  - read the gRPC trailer metadata stamped by the upstream chain worker
    when its downstream RunStage raised UNAVAILABLE,
  - identify the correct dead stage,
  - promote the recovery peer,
  - rewire the chain via SetNextHop,
  - replay the cached input history end-to-end through the new chain,
  - return the next token without the client noticing.

Reports per-step TBT, marks the fault-injection point + the
post-recovery step so replay overhead is readable at a glance, and
queries /api/mirror_stats before/after to confirm the mirror path was
hot.

Usage:
  python -m experiments.run_phase3_recovery \\
    --coord 115.145.158.253:50050 \\
    --web   http://115.145.158.253:8080 \\
    --kill-worker on-6 \\
    --inventory deploy/inventory.ini \\
    --kill-after-token 5 \\
    --max-tokens 12
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass

import grpc

from radp.common.proto import radp_pb2, radp_pb2_grpc

_GRPC_OPTIONS = [
    ("grpc.max_send_message_length", 256 * 1024 * 1024),
    ("grpc.max_receive_message_length", 256 * 1024 * 1024),
]


@dataclass
class _StepRecord:
    index: int
    text: str
    step_seconds: float
    is_first: bool


def _stream_generate(
    coord_addr: str,
    prompt: str,
    max_tokens: int,
) -> Iterator[_StepRecord]:
    with grpc.insecure_channel(coord_addr, options=_GRPC_OPTIONS) as ch:
        stub = radp_pb2_grpc.CoordinatorServiceStub(ch)
        i = 0
        last = time.perf_counter()
        for chunk in stub.Generate(
            radp_pb2.GenerateRequest(prompt=prompt, max_tokens=max_tokens)
        ):
            now = time.perf_counter()
            if chunk.done:
                return
            yield _StepRecord(
                index=i, text=chunk.text,
                step_seconds=now - last, is_first=(i == 0),
            )
            last = now
            i += 1


def _fetch_mirror_stats(web_base: str) -> dict[str, int]:
    with urllib.request.urlopen(f"{web_base}/api/mirror_stats", timeout=5) as r:
        return json.loads(r.read().decode())


def _kill_worker_via_ansible(
    inventory: str, device_id: str
) -> dict[str, object]:
    """Stop the radp-worker systemd unit on the named host. That makes
    the worker's gRPC port refuse connections — the upstream chain worker
    catches the resulting RpcError and stamps the trailer.
    """
    t0 = time.perf_counter()
    cp = subprocess.run(
        [
            "ansible", "-i", inventory, device_id,
            "-m", "systemd",
            "-a", "name=radp-worker state=stopped",
            "--become",
        ],
        capture_output=True, text=True, timeout=30,
    )
    return {
        "rc": cp.returncode,
        "elapsed_ms": (time.perf_counter() - t0) * 1000,
        "stderr_tail": cp.stderr.splitlines()[-3:] if cp.stderr else [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="phase3-recovery")
    parser.add_argument("--coord", required=True, help="coord gRPC address")
    parser.add_argument(
        "--web", required=True, help="coord web API base (http://host:port)"
    )
    parser.add_argument(
        "--prompt",
        default="The quick brown fox jumps over the lazy dog. Once upon a time",
    )
    parser.add_argument("--max-tokens", type=int, default=12)
    parser.add_argument(
        "--kill-worker", required=True, help="device_id to inject failure into"
    )
    parser.add_argument(
        "--inventory",
        default="deploy/inventory.ini",
        help="ansible inventory used to stop the worker systemd unit",
    )
    parser.add_argument(
        "--kill-after-token", type=int, default=5,
        help="inject failure after producing this many tokens",
    )
    args = parser.parse_args()

    stats_before = _fetch_mirror_stats(args.web)
    print(f"[pre]  mirror_stats={stats_before}")

    steps: list[_StepRecord] = []
    killed = False
    kill_step_idx: int | None = None
    kill_wall: float | None = None

    for step in _stream_generate(args.coord, args.prompt, args.max_tokens):
        steps.append(step)
        prefix = "TTFT" if step.is_first else "TBT "
        marker = ""
        if (
            not killed
            and step.index + 1 == args.kill_after_token
        ):
            t0 = time.perf_counter()
            result = _kill_worker_via_ansible(args.inventory, args.kill_worker)
            kill_wall = time.perf_counter() - t0
            killed = True
            kill_step_idx = step.index
            marker = f"  <-- KILL {args.kill_worker} via ansible ({result})"
        print(
            f"[step {step.index:2d}] {prefix} {step.step_seconds*1000:7.1f} ms  "
            f"text={step.text!r}{marker}"
        )

    stats_after = _fetch_mirror_stats(args.web)
    print(f"[post] mirror_stats={stats_after}")
    if killed:
        print(
            f"[post] fault injected at step {kill_step_idx}, "
            f"web call took {kill_wall*1000:.1f} ms"
        )

    # Step right after the failed step is the recovery step — show its
    # wall clock prominently so we can read recovery overhead at a glance.
    if killed and kill_step_idx is not None and kill_step_idx + 1 < len(steps):
        recovery = steps[kill_step_idx + 1]
        print(
            f"[post] recovery step {recovery.index}: "
            f"step_seconds={recovery.step_seconds*1000:.1f} ms text={recovery.text!r}"
        )

    print(
        f"[post] generated {len(steps)} tokens total: "
        f"{''.join(s.text for s in steps)!r}"
    )

    if len(steps) < args.max_tokens:
        print(
            f"[FAIL] expected {args.max_tokens} tokens, got {len(steps)} — "
            "stream terminated early; recovery likely failed"
        )
        raise SystemExit(2)


if __name__ == "__main__":
    main()
