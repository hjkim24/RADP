#!/usr/bin/env bash
# Spawn 2 workers + 1 coordinator on localhost, run a prompt, then shut down.
#
# Usage: bash experiments/demo_local.sh
#
# Requires: `uv sync --extra dev` already done, and `bash scripts/gen_proto.sh`.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="${ROOT}/experiments/configs/local_demo.yaml"
LOG_DIR="${ROOT}/.demo_logs"
mkdir -p "${LOG_DIR}"

cleanup() {
  if [[ -n "${COORD_PID:-}" ]]; then kill "${COORD_PID}" 2>/dev/null || true; fi
  if [[ -n "${WA_PID:-}"    ]]; then kill "${WA_PID}"    2>/dev/null || true; fi
  if [[ -n "${WB_PID:-}"    ]]; then kill "${WB_PID}"    2>/dev/null || true; fi
  wait 2>/dev/null || true
}
trap cleanup EXIT

echo "[demo] starting workers..."
uv run radp-worker --device-id worker-a --bind 127.0.0.1:50051 \
  >"${LOG_DIR}/worker-a.log" 2>&1 &
WA_PID=$!
uv run radp-worker --device-id worker-b --bind 127.0.0.1:50052 \
  >"${LOG_DIR}/worker-b.log" 2>&1 &
WB_PID=$!

echo "[demo] waiting for workers to be ready..."
for _ in $(seq 1 30); do
  if nc -z 127.0.0.1 50051 && nc -z 127.0.0.1 50052; then break; fi
  sleep 0.3
done

echo "[demo] starting coordinator (deploys stages, ~5-10s)..."
uv run radp-coordinator --config "${CFG}" \
  >"${LOG_DIR}/coordinator.log" 2>&1 &
COORD_PID=$!

echo "[demo] waiting for coordinator to be ready..."
for _ in $(seq 1 60); do
  if nc -z 127.0.0.1 50050; then break; fi
  sleep 0.5
done

echo "[demo] sending Generate request..."
uv run python -c "
from radp.common.protocol import CoordinatorClient
with CoordinatorClient('127.0.0.1:50050') as c:
    chunks = c.generate('The quick brown fox', max_tokens=5)
    print('GENERATED:', repr(''.join(chunks)))
"

echo "[demo] done — logs in ${LOG_DIR}/"
