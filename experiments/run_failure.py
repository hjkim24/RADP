"""Single-node failure recovery benchmark (plan.md §6.5 scenarios 2-3).

Kills a victim worker mid-inference; measures recovery start/complete time
and dropped-request count.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("Phase 4: orchestrate kill -> detect -> recover flow.")


if __name__ == "__main__":
    main()
