"""Recovery-Aware DP scheduler (plan.md §3, §5.2–5.3).

Solves
    A(1->y, D_n) = min_{n-1 ≤ l < y} max{ A(1->l, D_{n-1}),  T_stage + T_comm }
where the n-th device handles layers [l+1, y], subject to:
  - memory: self + backup-reserve ≤ Mem(n)
  - SLO:    per-stage cost (T_stage + T_comm) ≤ TBT_SLO
  - coverage: every layer placed exactly once (enforced by 1..L summation)

Device ordering D is taken as given (plan.md §7.1: "외부에서 정렬되어 들어옴").
All M devices participate ("모든 노드 참여 가정").
"""

from __future__ import annotations

import math

from radp.common.types import (
    ClusterSpec,
    DeviceId,
    DeviceProfile,
    DPResult,
    LayerIdx,
    NoFeasibleSolutionError,
    Placement,
    RecoveryTable,
    Stage,
)
from radp.coordinator.memory_check import memory_check


class Scheduler:
    """Recovery-Aware DP scheduler.

    Phase 1 simplification (plan.md §3.4):
      - Backup memory burden is estimated from a uniform round-robin
        "initial placement"; this is the only `current_placement` the DP
        sees during memory_check. R is held fixed across the DP run.
    """

    def __init__(self, spec: ClusterSpec) -> None:
        self.spec = spec
        self._L = len(spec.layers)
        self._M = len(spec.devices)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def solve(self, recovery: RecoveryTable) -> DPResult:
        """Run DP forward + backtracking. Returns the optimal placement."""
        if self._L == 0 or self._M == 0:
            raise NoFeasibleSolutionError("Empty layers or devices")
        if self._L < self._M:
            raise NoFeasibleSolutionError(
                f"Fewer layers ({self._L}) than devices ({self._M}); "
                "DP requires each device to host at least one layer."
            )

        A, choice = self._forward(recovery)
        if math.isinf(A[self._L][self._M]):
            raise NoFeasibleSolutionError(
                "Every (y, n) cell is infeasible under the given memory + SLO constraints."
            )
        placement = self._backtrack(choice)
        return DPResult(
            placement=placement,
            recovery=recovery,
            max_stage_time=A[self._L][self._M],
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _forward(
        self,
        recovery: RecoveryTable,
    ) -> tuple[list[list[float]], list[list[int]]]:
        spec = self.spec
        L, M = self._L, self._M
        devices = spec.devices
        layers = spec.layers
        tbt = spec.slo.tbt_seconds

        # Backup-burden reference: uniform initial placement (round-robin).
        ref_placement = uniform_placement(devices, L)

        # A[y][n] = best max-stage-time placing layers [1..y] across first n devices.
        # choice[y][n] = the split point l (last layer of the (n-1)-th device).
        A: list[list[float]] = [[math.inf] * (M + 1) for _ in range(L + 1)]
        choice: list[list[int]] = [[-1] * (M + 1) for _ in range(L + 1)]
        A[0][0] = 0.0

        # Base case: n = 1, device d_1 alone handles layers [1..y].
        d1 = devices[0]
        for y in range(1, L + 1):
            if not memory_check(
                d1, LayerIdx(1), LayerIdx(y), recovery, ref_placement, layers
            ):
                continue
            t_stage = self._stage_time(d1.id, 1, y)
            if t_stage > tbt:
                continue
            A[y][1] = t_stage

        # Main loop: add device d_n to handle layers [l+1..y].
        for n in range(2, M + 1):
            d_n = devices[n - 1]
            d_prev = devices[n - 2]
            t_comm = self._comm_time(d_prev.id, d_n.id)

            # y must leave at least one layer per earlier device (>= n-1),
            # and the new device gets at least one layer too (so y >= n).
            for y in range(n, L + 1):
                # split ∈ [n-1, y-1]: earlier n-1 devices hold layers [1..split],
                # so split ≥ n-1; d_n holds [split+1..y], so split ≤ y-1.
                # (Plan.md calls this `l`; we use `split` to avoid lint E741.)
                for split in range(n - 1, y):
                    prev_cost = A[split][n - 1]
                    if math.isinf(prev_cost):
                        continue
                    if not memory_check(
                        d_n,
                        LayerIdx(split + 1),
                        LayerIdx(y),
                        recovery,
                        ref_placement,
                        layers,
                    ):
                        continue
                    t_stage = self._stage_time(d_n.id, split + 1, y)
                    stage_cost = t_stage + t_comm
                    if stage_cost > tbt:
                        continue
                    cell = max(prev_cost, stage_cost)
                    if cell < A[y][n]:
                        A[y][n] = cell
                        choice[y][n] = split

        return A, choice

    def _backtrack(self, choice: list[list[int]]) -> Placement:
        L, M = self._L, self._M
        devices = self.spec.devices
        stages: list[Stage] = []
        y = L
        for n in range(M, 1, -1):
            split = choice[y][n]
            if split < 0:
                raise NoFeasibleSolutionError(
                    f"Backtrack failed at (y={y}, n={n}); no choice recorded."
                )
            stages.append(
                Stage(
                    start_layer=LayerIdx(split + 1),
                    end_layer=LayerIdx(y),
                    device=devices[n - 1].id,
                )
            )
            y = split
        # First device covers [1..y].
        stages.append(
            Stage(start_layer=LayerIdx(1), end_layer=LayerIdx(y), device=devices[0].id)
        )
        stages.reverse()
        return stages

    # ------------------------------------------------------------------
    # Cost helpers
    # ------------------------------------------------------------------
    def _stage_time(self, device_id: DeviceId, start: int, end: int) -> float:
        """Σ T_comp(i, device) for i ∈ [start, end]."""
        total = 0.0
        for i in range(start, end + 1):
            t = self.spec.layers[i - 1].compute_time.get(device_id)
            if t is None:
                return math.inf
            total += t
        return total

    def _comm_time(self, src: DeviceId, dst: DeviceId) -> float:
        """Inter-stage activation transfer: activation_bytes / bw + latency."""
        key = (src, dst)
        bw = self.spec.network.bandwidth.get(key)
        lat = self.spec.network.latency.get(key, 0.0)
        if bw is None or bw <= 0:
            return math.inf
        return self.spec.activation_bytes / bw + lat


# ---------------------------------------------------------------------------
# Helpers exposed for tests + the recovery-table caller.
# ---------------------------------------------------------------------------
def uniform_placement(devices: list[DeviceProfile], num_layers: int) -> Placement:
    """Round-robin baseline placement: floor(L/M) each, remainder to early devices.

    Used as the `current_placement` reference for the backup-memory term in
    the Phase 1 memory_check. The DP overrides this with its own self-stage.
    """
    M = len(devices)
    if M == 0 or num_layers == 0:
        return []
    base, extra = divmod(num_layers, M)
    stages: list[Stage] = []
    cursor = 1
    for i, d in enumerate(devices):
        count = base + (1 if i < extra else 0)
        if count == 0:
            continue
        stages.append(
            Stage(
                start_layer=LayerIdx(cursor),
                end_layer=LayerIdx(cursor + count - 1),
                device=d.id,
            )
        )
        cursor += count
    return stages
