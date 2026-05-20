"""Recovery-Aware DP scheduler (plan.md §3, §5.2–5.3).

Solves
    A(1->y, D_n) = min_{l<y} max{ A(1->l, D_{n-1}),  T_stage + T_comm }
subject to memory + SLO + coverage + recoverability constraints.
"""

from __future__ import annotations

from radp.common.types import (
    ClusterSpec,
    DPResult,
    NoFeasibleSolutionError,  # noqa: F401  (raised by solve)
    Placement,
    RecoveryTable,
)


class Scheduler:
    """Recovery-Aware DP scheduler.

    Usage:
        sched  = Scheduler(spec)
        result = sched.solve(recovery_table)
    """

    def __init__(self, spec: ClusterSpec) -> None:
        self.spec = spec

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def solve(self, recovery: RecoveryTable) -> DPResult:
        """Run DP forward + backtracking. Returns the optimal placement.

        Raises NoFeasibleSolutionError if no (Psi, R) pair satisfies the
        memory + SLO constraints.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Internals (exposed for unit tests)
    # ------------------------------------------------------------------
    def _forward(self, recovery: RecoveryTable) -> tuple[list[list[float]], list[list[int]]]:
        """Fill the DP table A and the backpointer table `choice`."""
        raise NotImplementedError

    def _backtrack(
        self,
        choice: list[list[int]],
    ) -> Placement:
        """Reconstruct Placement from the choice table (plan.md §5.3)."""
        raise NotImplementedError
