"""Figure C: recovery wall-clock CDF.

Star topology = 5 trials (a2_kill_ao1_n5.json) — RADP 의 정상 작동 영역.
Chain topology = sync 1-trial + async 1-trial (PHASES.md EXP-D3 Phase 3.2) —
trailer-attribution 의 차이 시각화.

Baseline (greedy/uniform/Jupiter-DP) 은 SIGKILL 경계에서 stream abort →
recovery time = ∞ 로 표시 (오른쪽 끝 marker).
"""
from __future__ import annotations
import json
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from _common import save, PALETTE  # noqa: E402

RESULTS = Path(__file__).parent.parent.parent / "experiments" / "results"

# --- Star topology (5 trials, a2_kill_ao1_n5.json) ---
star_d = json.load(open(RESULTS / "a2_kill_ao1_n5.json"))
star_times = np.array(star_d["aggregate"]["recovery_step_seconds"]["values"]) * 1000  # → ms
star_sorted = np.sort(star_times)
star_cdf = np.arange(1, len(star_sorted) + 1) / len(star_sorted)

# --- Chain topology (PHASES.md EXP-D3 Phase 3.2 reported numbers) ---
# Sync chain: trailer 즉시 → recovery step ~3608ms (token 4 의 recovery step time,
# 첫 토큰 재생성 포함). Async chain: trailer 못 씀 → heartbeat fallback 5-8s.
# (single-trial 측정이므로 점으로만 표시)
chain_sync_ms = 3608.0
chain_async_ms = 3985.0   # fix bf238b2 후 측정값 (Phase 3.2 §C)

fig, ax = plt.subplots(figsize=(5.0, 3.0))

# Star CDF (step function)
ax.step(
    star_sorted, star_cdf,
    where="post", color=PALETTE["primary"], linewidth=1.5,
    label=f"Star topology, RADP (n={len(star_sorted)})",
)
ax.scatter(
    star_sorted, star_cdf,
    color=PALETTE["primary"], s=18, zorder=3,
)

# Chain sync / async 단일 trial: vertical line + 점
ax.axvline(
    chain_sync_ms, color=PALETTE["tertiary"], linewidth=1.0, linestyle="--",
    alpha=0.8, label=f"Chain (4-stage) sync, n=1",
)
ax.scatter(
    [chain_sync_ms], [1.0],
    color=PALETTE["tertiary"], s=30, marker="v", zorder=3,
)

ax.axvline(
    chain_async_ms, color=PALETTE["secondary"], linewidth=1.0, linestyle="--",
    alpha=0.8, label=f"Chain (4-stage) async, n=1",
)
ax.scatter(
    [chain_async_ms], [1.0],
    color=PALETTE["secondary"], s=30, marker="v", zorder=3,
)

# Baseline annotation: aborted at SIGKILL boundary
ax.axhline(0, color="black", linewidth=0.3)
ax.text(
    0.98, 0.03,
    "Greedy / Uniform / Jupiter-DP baselines:\nstream aborts at SIGKILL boundary\n(no recovery — 17–20 tokens lost)",
    transform=ax.transAxes, ha="right", va="bottom",
    fontsize=6.5, color="#777", style="italic",
    bbox=dict(boxstyle="round,pad=0.3", facecolor="#f5f5f5", edgecolor="#ccc", linewidth=0.5),
)

ax.set_xscale("log")
ax.set_xlim(300, 8000)
ax.set_ylim(-0.02, 1.05)
ax.set_xlabel("Recovery wall-clock (ms, log scale)", fontsize=8)
ax.set_ylabel("CDF", fontsize=8)

ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

ax.legend(loc="center right", fontsize=6.5, framealpha=0.95)

fig.tight_layout()
save(fig, "fig_recovery")

# 통계 출력 (caption 작성용)
print(f"Star mean={star_times.mean():.0f}ms p50={np.median(star_times):.0f}ms "
      f"p95={np.percentile(star_times, 95):.0f}ms (n={len(star_times)})")
print(f"Chain sync={chain_sync_ms}ms  async={chain_async_ms}ms")
print("Figure C done.")
