"""Recovery-Aware DP scheduler (plan.md §3, §5.2–5.3).

Solves
    A(1->y, D_n) = min_{n-1 ≤ l < y} max{ A(1->l, D_{n-1}),  T_stage + T_comm }
where the n-th device handles layers [l+1, y], subject to:
  - memory: self + backup-reserve ≤ Mem(n)
  - SLO:    per-stage cost (T_stage + T_comm) ≤ TBT_SLO
  - coverage: every layer placed exactly once (enforced by 1..L summation)

Device ordering D is taken as given (plan.md §7.1: "외부에서 정렬되어 들어옴").
All M devices participate ("모든 노드 참여 가정").

Two entry points:
  * ``solve(R)`` — single-shot DP. Uses a round-robin reference placement
    for the backup-burden term in memory_check (Phase 1 simplification).
  * ``solve_alternating()`` — R-Ψ alternating optimization (plan.md §3.4
    "구현 단순화" → §7.2 future work). Iterates until (R, Ψ) is mutually
    self-consistent or ``max_iterations`` is hit.
"""

from __future__ import annotations

import math
from itertools import permutations

from radp.common.logging_utils import get_logger
from radp.common.types import (
    AlternatingIterationLog,
    AlternatingResult,
    ClusterSpec,
    DeviceId,
    DeviceProfile,
    DPResult,
    LayerIdx,
    NoFeasibleSolutionError,
    NoRecoveryError,
    Placement,
    RecoveryTable,
    Stage,
)
from radp.coordinator.memory_check import memory_check
from radp.coordinator.recovery_table import determine_recovery_table

log = get_logger(__name__)


class Scheduler:
    """Recovery-Aware DP scheduler.

    Single-shot mode (Phase 1, plan.md §3.4):
      - Backup memory burden is estimated from a uniform round-robin
        "initial placement"; the DP only sees this round-robin reference.
        R is held fixed across the DP run.

    Alternating mode (this file, plan.md §3.4 "구현 단순화" → §7.2):
      - Iterate (R, Ψ) until both stabilize and Ψ is consistent with its
        OWN backup burden. The DP at iteration i uses Ψ_{i-1} as its
        reference; after solving, we re-check the new Ψ_i against its
        own backup burden to detect inconsistencies introduced by the
        change in stage sizes.
    """

    def __init__(self, spec: ClusterSpec) -> None:
        self.spec = spec
        self._L = len(spec.layers)
        self._M = len(spec.devices)

    # ------------------------------------------------------------------
    # Public API — single shot
    # ------------------------------------------------------------------
    def solve(
        self,
        recovery: RecoveryTable,
        *,
        ref_placement: Placement | None = None,
    ) -> DPResult:
        """Run DP forward + backtracking. Returns the optimal placement.

        ``ref_placement`` is the backup-burden reference used by
        ``memory_check`` during DP. If omitted, defaults to a uniform
        round-robin placement (Phase 1 behavior).
        """
        if self._L == 0 or self._M == 0:
            raise NoFeasibleSolutionError("Empty layers or devices")
        if self._L < self._M:
            raise NoFeasibleSolutionError(
                f"Fewer layers ({self._L}) than devices ({self._M}); "
                "DP requires each device to host at least one layer."
            )

        if ref_placement is None:
            ref_placement = uniform_placement(self.spec.devices, self._L)
        A, choice = self._forward(recovery, ref_placement=ref_placement)
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
    # Public API — alternating
    # ------------------------------------------------------------------
    def solve_alternating(
        self,
        *,
        initial_placement: Placement | None = None,
        max_iterations: int = 10,
    ) -> AlternatingResult:
        """Run the R-Ψ alternating optimization.

        At each iteration: derive R from the current Ψ via
        ``determine_recovery_table``, then DP with that R using the current Ψ
        as the backup-burden reference. Check whether the resulting Ψ' is
        consistent with ITS OWN backup burden; track the best self-consistent
        Ψ seen across iterations as a safe fallback.

        Convergence: (R, Ψ) unchanged from previous iteration AND Ψ is
        self-consistent. Otherwise we run up to ``max_iterations`` and
        return the best self-consistent Ψ.
        """
        if self._L < self._M:
            raise NoFeasibleSolutionError(
                f"Fewer layers ({self._L}) than devices ({self._M}); "
                "DP requires each device to host at least one layer."
            )

        prev_psi: Placement = (
            initial_placement
            if initial_placement is not None
            else uniform_placement(self.spec.devices, self._L)
        )
        prev_r: RecoveryTable | None = None
        history: list[AlternatingIterationLog] = []
        best_consistent: AlternatingResult | None = None

        for i in range(1, max_iterations + 1):
            try:
                r = determine_recovery_table(self.spec, prev_psi)
            except NoRecoveryError as e:
                if best_consistent is not None:
                    log.warning(
                        "alternating iter=%d: recovery infeasible (%s); "
                        "falling back to best self-consistent (max_stage=%.4f)",
                        i, e, best_consistent.max_stage_time,
                    )
                    return _replace_history(best_consistent, history)
                raise

            try:
                A, choice = self._forward(r, ref_placement=prev_psi)
            except NoFeasibleSolutionError:
                if best_consistent is not None:
                    return _replace_history(best_consistent, history)
                raise

            if math.isinf(A[self._L][self._M]):
                if best_consistent is not None:
                    log.warning(
                        "alternating iter=%d: DP infeasible; falling back", i,
                    )
                    return _replace_history(best_consistent, history)
                raise NoFeasibleSolutionError(
                    f"Alternating iter={i}: DP found no feasible placement"
                )

            psi = self._backtrack(choice)
            max_stage = A[self._L][self._M]
            self_consistent = self._memory_self_check(psi, r)

            log_entry = AlternatingIterationLog(
                iteration=i,
                max_stage_time=max_stage,
                self_consistent=self_consistent,
                psi_changed=(psi != prev_psi),
                r_changed=(r != prev_r),
            )
            history.append(log_entry)
            log.debug(
                "alternating iter=%d max_stage=%.4f self_consistent=%s "
                "psi_changed=%s r_changed=%s",
                i, max_stage, self_consistent, log_entry.psi_changed, log_entry.r_changed,
            )

            if self_consistent and (
                best_consistent is None or max_stage < best_consistent.max_stage_time
            ):
                best_consistent = AlternatingResult(
                    placement=psi,
                    recovery=r,
                    max_stage_time=max_stage,
                    iterations=i,
                    converged=False,
                    history=list(history),
                )

            # Converged when R and Ψ are stable AND Ψ is self-consistent.
            if r == prev_r and psi == prev_psi and self_consistent:
                return AlternatingResult(
                    placement=psi,
                    recovery=r,
                    max_stage_time=max_stage,
                    iterations=i,
                    converged=True,
                    history=history,
                )

            prev_r = r
            prev_psi = psi

        # Hit max iterations without convergence.
        if best_consistent is not None:
            return _replace_history(best_consistent, history)
        raise NoFeasibleSolutionError(
            f"No self-consistent (R, Ψ) found in {max_iterations} iterations"
        )

    # ------------------------------------------------------------------
    # Public API — alternating with device-order search
    # ------------------------------------------------------------------
    def solve_alternating_best_order(
        self,
        *,
        max_search_devices: int = 8,
        **alt_kwargs: object,
    ) -> AlternatingResult:
        """Try every permutation of device order; return the best one.

        Heartbeat-arrival ordering of ``spec.devices`` is arbitrary, but the
        DP treats that order as the fixed pipeline sequence — so a bad order
        can leave a 30%+ gap on the table (2026-06-06 brute-force on the
        live 7-worker fleet: best 85.7 ms vs worst 95.8 ms with calibrated
        activation_bytes; range widens further with overestimated
        activation_bytes since stage count starts to dominate).

        For M ≤ max_search_devices, run solve_alternating() over all M!
        permutations and pick the one with the smallest max_stage_time. For
        M > max_search_devices, fall back to the spec's existing order.

        ``alt_kwargs`` is forwarded to solve_alternating() unchanged.
        """
        M = self._M
        if M > max_search_devices:
            log.info(
                "solve_alternating_best_order: M=%d > %d, "
                "skipping permutation search and using spec order",
                M, max_search_devices,
            )
            return self.solve_alternating(**alt_kwargs)  # type: ignore[arg-type]

        original_devices = list(self.spec.devices)
        total = math.factorial(M)
        log.info(
            "solve_alternating_best_order: searching %d device-order "
            "permutations (M=%d)",
            total, M,
        )

        # When one device (typically the slowest tier) sets the max_stage_time
        # floor, multiple placements tie on the primary objective. Tiebreaker:
        # prefer placements that load more work onto faster devices — measured
        # as Σ throughput(d) × layer_count(d). Heavier weight on the fastest
        # devices gives the cluster more compute headroom for prefill / spikes.
        throughput_by_id = {d.id: d.compute_throughput for d in original_devices}

        def tiebreak_score(result: AlternatingResult) -> float:
            return sum(
                throughput_by_id.get(s.device, 0.0)
                * (int(s.end_layer) - int(s.start_layer) + 1)
                for s in result.placement
            )

        best: AlternatingResult | None = None
        best_order: tuple[DeviceProfile, ...] | None = None
        best_score: float = -1.0
        feasible_count = 0
        for perm in permutations(original_devices):
            self.spec = ClusterSpec(
                devices=list(perm),
                layers=self.spec.layers,
                network=self.spec.network,
                slo=self.spec.slo,
                activation_bytes=self.spec.activation_bytes,
            )
            try:
                result = self.solve_alternating(**alt_kwargs)  # type: ignore[arg-type]
            except NoFeasibleSolutionError:
                continue
            if math.isinf(result.max_stage_time):
                continue
            feasible_count += 1
            score = tiebreak_score(result)
            better = (
                best is None
                or result.max_stage_time < best.max_stage_time - 1e-9
                or (
                    abs(result.max_stage_time - best.max_stage_time) < 1e-9
                    and score > best_score
                )
            )
            if better:
                best = result
                best_order = perm
                best_score = score

        # Restore original device order in spec
        self.spec = ClusterSpec(
            devices=original_devices,
            layers=self.spec.layers,
            network=self.spec.network,
            slo=self.spec.slo,
            activation_bytes=self.spec.activation_bytes,
        )

        if best is None or best_order is None:
            raise NoFeasibleSolutionError(
                f"No feasible placement found across {total} device orderings"
            )
        log.info(
            "solve_alternating_best_order: %d/%d permutations feasible, "
            "best max_stage_time=%.4fs with order=%s",
            feasible_count, total, best.max_stage_time,
            [d.id for d in best_order],
        )
        return best

    # ------------------------------------------------------------------
    # Consistency check
    # ------------------------------------------------------------------
    def _memory_self_check(
        self, placement: Placement, recovery: RecoveryTable
    ) -> bool:
        """Does every stage in `placement` fit its own self+backup burden?

        ``memory_check`` is called with ``placement`` as both the candidate
        and the reference, so the answer reflects what the DP would have
        seen had it run with this Ψ as the reference from the start.
        """
        devices_by_id = {d.id: d for d in self.spec.devices}
        for stage in placement:
            device = devices_by_id[stage.device]
            if not memory_check(
                device, stage.start_layer, stage.end_layer,
                recovery, placement, self.spec.layers,
                eager_backup=self.spec.eager_backup,
            ):
                return False
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _forward(
        self,
        recovery: RecoveryTable,
        *,
        ref_placement: Placement,
    ) -> tuple[list[list[float]], list[list[int]]]:
        spec = self.spec
        L, M = self._L, self._M
        devices = spec.devices
        layers = spec.layers
        tbt = spec.slo.tbt_seconds

        # A[y][n] = best max-stage-time placing layers [1..y] across first n devices.
        # choice[y][n] = the split point l (last layer of the (n-1)-th device).
        A: list[list[float]] = [[math.inf] * (M + 1) for _ in range(L + 1)]
        choice: list[list[int]] = [[-1] * (M + 1) for _ in range(L + 1)]
        A[0][0] = 0.0

        # Base case: n = 1, device d_1 alone handles layers [1..y].
        d1 = devices[0]
        for y in range(1, L + 1):
            if not memory_check(
                d1, LayerIdx(1), LayerIdx(y), recovery, ref_placement, layers,
                eager_backup=spec.eager_backup,
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
                        eager_backup=spec.eager_backup,
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
# Module-internal helpers
# ---------------------------------------------------------------------------
def _replace_history(
    result: AlternatingResult, full_history: list[AlternatingIterationLog]
) -> AlternatingResult:
    """Return a copy of `result` whose history is the full run's history.

    The best_consistent snapshot was taken mid-run; we want the user to see
    every iteration in the returned log even if we ended on a fallback.
    """
    return AlternatingResult(
        placement=result.placement,
        recovery=result.recovery,
        max_stage_time=result.max_stage_time,
        iterations=result.iterations,
        converged=False,
        history=full_history,
    )


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
