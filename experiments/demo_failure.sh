#!/usr/bin/env bash
# Spawn 3 workers + 1 coordinator, run a prompt, kill worker-b, run another
# prompt, and verify the second one succeeds via R(worker-b) = worker-c.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="${ROOT}/experiments/configs/failure_demo.yaml"
LOG_DIR="${ROOT}/.demo_logs"
mkdir -p "${LOG_DIR}"

cleanup() {
  for pid in "${WA_PID:-}" "${WB_PID:-}" "${WC_PID:-}" "${COORD_PID:-}"; do
    [[ -n "${pid}" ]] && kill "${pid}" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT

start_worker() {
  local name=$1 port=$2
  uv run radp-worker \
    --device-id "${name}" \
    --bind "127.0.0.1:${port}" \
    --coord "127.0.0.1:50050" \
    --heartbeat-interval 0.5 \
    >"${LOG_DIR}/${name}.log" 2>&1 &
  echo $!
}

echo "[demo] starting workers..."
WA_PID=$(start_worker worker-a 50051)
WB_PID=$(start_worker worker-b 50052)
WC_PID=$(start_worker worker-c 50053)

echo "[demo] waiting for worker ports..."
for port in 50051 50052 50053; do
  for _ in $(seq 1 30); do
    if nc -z 127.0.0.1 "${port}"; then break; fi
    sleep 0.3
  done
done

echo "[demo] starting coordinator (deploys primaries + backups)..."
uv run radp-coordinator --config "${CFG}" \
  >"${LOG_DIR}/coordinator.log" 2>&1 &
COORD_PID=$!

for _ in $(seq 1 60); do
  if nc -z 127.0.0.1 50050; then break; fi
  sleep 0.5
done

echo "[demo] healthy run..."
uv run python -c "
from radp.common.protocol import CoordinatorClient
with CoordinatorClient('127.0.0.1:50050') as c:
    print('HEALTHY:', repr(''.join(c.generate('The quick brown fox', max_tokens=4))))
"

echo "[demo] killing worker-b (SIGKILL the actual Python child, simulates crash)..."
# uv spawns a wrapper; we need to kill the real Python child by command-line match.
pkill -KILL -f "radp-worker.*--device-id worker-b" 2>/dev/null || true
WB_PID=""

echo "[demo] waiting for heartbeat timeout (~3-5s)..."
sleep 5

echo "[demo] post-failure run (should route through worker-c backup)..."
uv run python -c "
from radp.common.protocol import CoordinatorClient
with CoordinatorClient('127.0.0.1:50050') as c:
    print('AFTER FAILURE:', repr(''.join(c.generate('The quick brown fox', max_tokens=4))))
"

echo "[demo] done — logs in ${LOG_DIR}/"
