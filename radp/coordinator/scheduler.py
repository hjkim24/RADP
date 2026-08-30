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
from itertools import combinations, permutations

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


# DP cell state = (sum_stage_time, max_stage_time). The forward stores
# tuples so the same DP body can be re-ranked under any mode without a
# rewrite — see CostMode.
_INF_STATE: tuple[float, float] = (math.inf, math.inf)


def _rank(state: tuple[float, float], mode: str, alpha: float = 0.0) -> float:
    """Mode-specific ranking of a (sum, max) DP cell.

    throughput → max                  (Jupiter Eq. 1 / EdgeShard throughput)
    latency    → sum                  (EdgeShard Eq. 6, batch=1 single-stream)
    blended    → sum + α·max          (Jupiter Eq. 4 at single sub-sequence;
                                       α = |D|-1 reproduces their formula)
    """
    sum_t, max_t = state
    if mode == "throughput":
        return max_t
    if mode == "latency":
        return sum_t
    if mode == "blended":
        return sum_t + alpha * max_t
    raise ValueError(f"Unknown optimization_mode: {mode!r}")


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
        final_state = A[self._L][self._M]
        if math.isinf(final_state[0]) or math.isinf(final_state[1]):
            raise NoFeasibleSolutionError(
                "Every (y, n) cell is infeasible under the given memory + SLO constraints."
            )
        placement = self._backtrack(choice)
        return DPResult(
            placement=placement,
            recovery=recovery,
            max_stage_time=final_state[1],
            sum_stage_time=final_state[0],
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

        # Under tight memory the round-robin seed can itself have no feasible
        # recovery table. Iteration 1 would then raise with nothing recorded,
        # and the solver reports failure even though feasible (Ψ, R) pairs
        # exist — measured on the live snapshot at a 200 MB free-memory cap,
        # where seeding with a cost-only placement converges immediately.
        # Repair the seed once from the cost-only DP, which ignores backup
        # burden and so still answers when the recovery-aware seed cannot.
        if self.spec.backup_placement:
            try:
                determine_recovery_table(self.spec, prev_psi)
            except NoRecoveryError:
                try:
                    A0, choice0 = self._forward({}, ref_placement=prev_psi)
                    if not math.isinf(A0[self._L][self._M][0]):
                        prev_psi = self._backtrack(choice0)
                        log.debug("alternating: repaired infeasible seed via cost-only DP")
                except NoFeasibleSolutionError:
                    pass

        for i in range(1, max_iterations + 1):
            try:
                r = (
                    determine_recovery_table(self.spec, prev_psi)
                    if self.spec.backup_placement
                    else {}
                )
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

            final_state = A[self._L][self._M]
            if math.isinf(final_state[0]) or math.isinf(final_state[1]):
                if best_consistent is not None:
                    log.warning(
                        "alternating iter=%d: DP infeasible; falling back", i,
                    )
                    return _replace_history(best_consistent, history)
                raise NoFeasibleSolutionError(
                    f"Alternating iter={i}: DP found no feasible placement"
                )

            psi = self._backtrack(choice)
            sum_stage, max_stage = final_state
            objective_rank = _rank(
                final_state, self.spec.optimization_mode, self.spec.blend_alpha,
            )
            self_consistent = self._memory_self_check(psi, r)

            log_entry = AlternatingIterationLog(
                iteration=i,
                max_stage_time=max_stage,
                self_consistent=self_consistent,
                psi_changed=(psi != prev_psi),
                r_changed=(r != prev_r),
                sum_stage_time=sum_stage,
            )
            history.append(log_entry)
            log.debug(
                "alternating iter=%d sum=%.4f max=%.4f self_consistent=%s "
                "psi_changed=%s r_changed=%s",
                i, sum_stage, max_stage, self_consistent,
                log_entry.psi_changed, log_entry.r_changed,
            )

            if self_consistent and (
                best_consistent is None
                or objective_rank < _rank(
                    (best_consistent.sum_stage_time, best_consistent.max_stage_time),
                    self.spec.optimization_mode, self.spec.blend_alpha,
                )
            ):
                best_consistent = AlternatingResult(
                    placement=psi,
                    recovery=r,
                    max_stage_time=max_stage,
                    iterations=i,
                    converged=False,
                    history=list(history),
                    sum_stage_time=sum_stage,
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
                    sum_stage_time=sum_stage,
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
        enable_subset_search: bool = True,
        **alt_kwargs: object,
    ) -> AlternatingResult:
        """Try every (subset, permutation) of devices; return the best one.

        Two orthogonal search dimensions:

        1. **Permutation**. Heartbeat-arrival ordering of ``spec.devices`` is
           arbitrary, but the DP treats it as the fixed pipeline sequence —
           bad order leaves 30%+ on the table (2026-06-06 brute-force on the
           live 7-worker fleet: best 85.7 ms vs worst 95.8 ms with calibrated
           activation_bytes).

        2. **Subset** (enable_subset_search=True). Every device participates
           in the DP by default, which on heterogeneous edge fleets pulls
           slow devices into the pipeline at the layer floor (1-2 layers)
           where their compute is dwarfed by hop overhead. EXP-D2.3 measured
           a 7-worker (CPU + CUDA) fleet's max_stage at 87 ms; the same fleet
           reduced to a 4-CUDA subset drops to 8.35 ms (-90%). Enumerating
           subsets lets the DP discover that smaller fleets can win
           — particularly in throughput mode (alpha=1) at high concurrency.

        Complexity:
          - permutation-only:  M!
          - subset+perm:       Σ_{k=2}^M C(M,k) · k!  ≈  2.7 × M! for M ≤ 8

        For M > max_search_devices, fall back to the spec's existing order
        with no search.

        ``alt_kwargs`` is forwarded to solve_alternating() unchanged.
        """
        M = self._M
        if max_search_devices < M:
            log.info(
                "solve_alternating_best_order: M=%d > %d, "
                "skipping search and using spec order",
                M, max_search_devices,
            )
            return self.solve_alternating(**alt_kwargs)  # type: ignore[arg-type]

        original_devices = list(self.spec.devices)
        # Subset sizes: 2..M when enabled, else only the full set.
        subset_sizes = range(2, M + 1) if enable_subset_search else (M,)
        total = sum(
            math.factorial(M) // math.factorial(M - k) for k in subset_sizes
        )
        log.info(
            "solve_alternating_best_order: searching %d (subset, permutation) "
            "candidates (M=%d, subset_search=%s)",
            total, M, enable_subset_search,
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

        mode = self.spec.optimization_mode
        alpha = self.spec.blend_alpha

        def with_devices(devs: list[DeviceProfile]) -> ClusterSpec:
            # Re-emit spec preserving every field — earlier versions dropped
            # eager_backup / optimization_mode here and quietly fell back to
            # defaults, which masked our A5 prototype until commit f378ddd.
            # D2.7 / D2.8 added hop_overhead_seconds + target_concurrency +
            # thread_pool_size + stage_count_penalty_seconds; forward those
            # too or every subset silently runs with cost-model v1.
            return ClusterSpec(
                devices=devs,
                layers=self.spec.layers,
                network=self.spec.network,
                slo=self.spec.slo,
                activation_bytes=self.spec.activation_bytes,
                eager_backup=self.spec.eager_backup,
                backup_placement=self.spec.backup_placement,
                # Subset enumeration narrows the pipeline; without this the
                # backup scope narrows with it and nodes dropped for being
                # slow stop being usable as backup hosts.
                backup_hosts=self.spec.backup_hosts,
                optimization_mode=self.spec.optimization_mode,
                blend_alpha=self.spec.blend_alpha,
                hop_overhead_seconds=self.spec.hop_overhead_seconds,
                target_concurrency=self.spec.target_concurrency,
                thread_pool_size=self.spec.thread_pool_size,
                stage_count_penalty_seconds=self.spec.stage_count_penalty_seconds,
            )

        def _install(spec: ClusterSpec) -> None:
            # Subset enumeration shrinks |D| mid-search, so the cached _M /
            # _L on Scheduler must move with each swap or solve_alternating's
            # inner DP indexes off the end of the (now-smaller) device list.
            self.spec = spec
            self._L = len(spec.layers)
            self._M = len(spec.devices)

        best: AlternatingResult | None = None
        best_rank: float = math.inf
        best_order: tuple[DeviceProfile, ...] | None = None
        best_score: float = -1.0
        feasible_count = 0
        for k in subset_sizes:
            for subset in combinations(original_devices, k):
                for perm in permutations(subset):
                    _install(with_devices(list(perm)))
                    try:
                        result = self.solve_alternating(**alt_kwargs)  # type: ignore[arg-type]
                    except (NoFeasibleSolutionError, NoRecoveryError):
                        # A subset whose stages leave no peer with room for
                        # a backup is infeasible under Eq. (mem) just like a
                        # DP with no placement -- skip it, don't abort the
                        # search. First hit on the OPT-6.7B boot (2026-08-30):
                        # the 2-Nano subsets have 6.5 GB stages nobody can
                        # back up, while 3+-device subsets are fine.
                        continue
                    result_state = (result.sum_stage_time, result.max_stage_time)
                    if math.isinf(result_state[0]) or math.isinf(result_state[1]):
                        continue
                    feasible_count += 1
                    # EXP-D2.8: γ_stages · |ψ| penalises larger subsets at
                    # the outer-search ranking step, where each subset has
                    # a different stage count |ψ|=len(perm). Inside the
                    # inner DP the term is constant so it doesn't affect
                    # the chosen split between layers.
                    stage_penalty = (
                        self.spec.stage_count_penalty_seconds * len(perm)
                    )
                    rank = _rank(result_state, mode, alpha) + stage_penalty
                    score = tiebreak_score(result)
                    better = (
                        best is None
                        or rank < best_rank - 1e-9
                        or (abs(rank - best_rank) < 1e-9 and score > best_score)
                    )
                    if better:
                        best = result
                        best_rank = rank
                        best_order = perm
                        best_score = score

        # Restore original device order in spec
        _install(with_devices(original_devices))

        if best is None or best_order is None:
            raise NoFeasibleSolutionError(
                f"No feasible placement found across {total} (subset, permutation) candidates"
            )
        log.info(
            "solve_alternating_best_order: %d/%d candidates feasible, "
            "mode=%s best sum=%.4fs max=%.4fs (rank=%.4f) "
            "subset_size=%d order=%s",
            feasible_count, total, mode,
            best.sum_stage_time, best.max_stage_time, best_rank,
            len(best_order), [d.id for d in best_order],
        )
        # Post-hoc SLO feasibility check. Throughput mode already enforced the
        # per-stage cap inline; latency / blended modes only flag here.
        tbt_slo = self.spec.slo.tbt_seconds
        objective_time = best.sum_stage_time if mode != "throughput" else best.max_stage_time
        if objective_time > tbt_slo:
            log.warning(
                "post-hoc SLO check: best %s objective=%.4fs exceeds TBT_SLO=%.4fs — "
                "no placement on this fleet meets the latency target",
                "sum" if mode != "throughput" else "max",
                objective_time, tbt_slo,
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
    ) -> tuple[list[list[tuple[float, float]]], list[list[int]]]:
        spec = self.spec
        L, M = self._L, self._M
        devices = spec.devices
        layers = spec.layers
        mode = spec.optimization_mode
        alpha = spec.blend_alpha
        tbt = spec.slo.tbt_seconds
        # Throughput-mode keeps the per-stage SLO as a hard constraint so that
        # individual stages stay within QoS under concurrent load. Latency- and
        # blended-mode treat SLO as a post-hoc feasibility check on the total —
        # capping a single stage there would just spread layers thin and
        # inflate Σ stage_time.
        per_stage_slo_cap = tbt if mode == "throughput" else math.inf

        # A[y][n] = (sum_stage_time, max_stage_time) so far across the optimal
        # placement of layers [1..y] across the first n devices.
        # choice[y][n] = split l where the (n-1)-th device's stage ends.
        A: list[list[tuple[float, float]]] = [
            [_INF_STATE] * (M + 1) for _ in range(L + 1)
        ]
        choice: list[list[int]] = [[-1] * (M + 1) for _ in range(L + 1)]
        A[0][0] = (0.0, 0.0)

        # Base case: n = 1, device d_1 alone handles layers [1..y]. No comm
        # cost on the first stage (input is local on the source/gateway).
        d1 = devices[0]
        for y in range(1, L + 1):
            if not memory_check(
                d1, LayerIdx(1), LayerIdx(y), recovery, ref_placement, layers,
                eager_backup=spec.eager_backup,
            ):
                continue
            # |ψ| = self._M is the subset's total stage count, which the
            # outer search varies across all subsets ≥ 2. Passing self._M
            # makes the pool-saturation multiplier consistent across the
            # inner DP's intermediate states.
            t_stage = self._stage_time_with_interference(d1.id, 1, y, self._M)
            if t_stage > per_stage_slo_cap:
                continue
            A[y][1] = (t_stage, t_stage)

        # Main loop: add device d_n to handle layers [l+1..y].
        for n in range(2, M + 1):
            d_n = devices[n - 1]
            d_prev = devices[n - 2]
            t_comm = self._comm_time(d_prev.id, d_n.id)

            for y in range(n, L + 1):
                for split in range(n - 1, y):
                    prev_state = A[split][n - 1]
                    if math.isinf(prev_state[0]) or math.isinf(prev_state[1]):
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
                    t_stage = self._stage_time_with_interference(
                        d_n.id, split + 1, y, self._M
                    )
                    stage_cost = t_stage + t_comm
                    if stage_cost > per_stage_slo_cap:
                        continue
                    new_state = (
                        prev_state[0] + stage_cost,
                        max(prev_state[1], stage_cost),
                    )
                    if _rank(new_state, mode, alpha) < _rank(A[y][n], mode, alpha):
                        A[y][n] = new_state
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
        """Σ T_comp(i, device) for i ∈ [start, end] — wire-only baseline."""
        total = 0.0
        for i in range(start, end + 1):
            t = self.spec.layers[i - 1].compute_time.get(device_id)
            if t is None:
                return math.inf
            total += t
        return total

    def _stage_time_with_interference(
        self, device_id: DeviceId, start: int, end: int, num_stages: int
    ) -> float:
        """T_stage(s) inflated by the pool-saturation multiplier.

        Multiplier = max(1, target_concurrency · num_stages / thread_pool_size).
        Models that, when num_stages × target_concurrency exceeds the
        worker-side gRPC handler pool, each stream queues for its slot,
        so per-stage wall-clock inflates roughly linearly. EXP-D2.8.

        Pure-function in (target_concurrency, thread_pool_size,
        num_stages) — with target_concurrency=1 (the default) the
        multiplier collapses to 1.0 and this matches _stage_time
        exactly, so single-stream callers stay backward-compatible.
        """
        base = self._stage_time(device_id, start, end)
        if math.isinf(base):
            return base
        C = self.spec.target_concurrency
        pool = self.spec.thread_pool_size
        if C <= 1 or pool <= 0 or num_stages <= 0:
            return base
        multiplier = max(1.0, (C * num_stages) / pool)
        return base * multiplier

    def _comm_time(self, src: DeviceId, dst: DeviceId) -> float:
        """Inter-stage activation transfer: activation_bytes / bw + latency
        + a fixed per-hop overhead for everything the wire-only model
        misses (gRPC framing, Python/GIL contention, scheduler delay).

        The hop_overhead_seconds knob (default 0) was added in EXP-D2.7 —
        without it the cost function only sees wire-level transfer
        (microseconds for OPT-350M's 2 KB activation) and treats
        many-small-stage placements as essentially free. Live measurement
        puts the real per-hop cost at 8–10 ms regardless of payload, so
        a 4-stage chain quietly carries ~30 ms of hidden overhead the
        DP never charged. Setting this to ~0.008 surfaces the cost so
        throughput-mode placements stop racing toward 4-stage and start
        considering bulk-on-fast-device solutions.
        """
        key = (src, dst)
        bw = self.spec.network.bandwidth.get(key)
        lat = self.spec.network.latency.get(key, 0.0)
        if bw is None or bw <= 0:
            return math.inf
        wire = self.spec.activation_bytes / bw + lat
        return wire + self.spec.hop_overhead_seconds


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
