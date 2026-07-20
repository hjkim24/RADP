"""Explanatory diagrams for the recovery work (ppt/DESIGN_SYSTEM.md §7).

Three figures that carry points which words alone do not land:

  fig_parity_mechanism    — how parity keeps ONE blob and inverts it on failure
  fig_recovery_families   — what each of the three families recomputes
  fig_generalization      — the slot-alignment fix and the trailer-overwrite bug

Built at slide scale with the deck palette so they drop straight into the
progress-report template. Data-free diagrams: nothing here is measured, so the
numbers that appear are quoted from experiments/results/b1_ft_fleet_parity.json
and REPORT.md, not computed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

sys.path.insert(0, str(Path(__file__).parent))
from _slide import BODY, SLIDE_FULL, SLIDE_WIDE, SUBJECT, save_slide  # noqa: E402

DEAD = SUBJECT["full_replay"]      # 죽은 노드 표시
OK = "#B8C0C0"                     # 평상시 노드
PAR = SUBJECT["parity"]
SUR = SUBJECT["surgical"]


def box(ax, x, y, w, h, label, face=OK, edge=None, text=BODY, fs=12, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012",
                                linewidth=1.4, facecolor=face,
                                edgecolor=edge or face))
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
            fontsize=fs, color=text, fontweight="bold" if bold else "normal")


def arrow(ax, x1, y1, x2, y2, color=BODY, style="-|>", lw=1.4, ls="-"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
                                 mutation_scale=13, linewidth=lw,
                                 color=color, linestyle=ls,
                                 shrinkA=2, shrinkB=2))


def blank(ax, xlim=(0, 10), ylim=(0, 6)):
    ax.set_xlim(*xlim); ax.set_ylim(*ylim); ax.axis("off")


# ---------------------------------------------------------------- 1. mechanism
def parity_mechanism():
    """정상 운영(위)과 장애 복원(아래)을 위아래로 나눠, '역산'이 보이게 한다."""
    fig, ax = plt.subplots(figsize=SLIDE_FULL)
    blank(ax, (0, 10), (0, 6.4))

    names = ["head", "A", "B", "C"]
    xs = [1.9 + i * 1.85 for i in range(4)]
    BW, BH = 1.5, 0.72

    def chain(y, dead_idx=None):
        for i, (x, n) in enumerate(zip(xs, names)):
            is_dead = (i == dead_idx)
            face = DEAD if is_dead else ("#DDE3E3" if i == 0 else OK)
            box(ax, x, y, BW, BH, n, face=face,
                text="white" if is_dead else BODY, fs=11.5, bold=is_dead or i > 0)
            if i < 3:
                arrow(ax, x + BW, y + BH / 2, xs[i + 1], y + BH / 2, lw=1.1)

    # ── 위: 정상 운영 ─────────────────────────────────────────────
    ax.text(0.05, 6.15, "정상 운영", fontsize=13, color=BODY,
            fontweight="bold", va="top")
    box(ax, 3.75, 5.05, 5.95, 0.72, "parity 1장  (P)", face=PAR,
        text="white", fs=12.5, bold=True)
    chain(3.55)
    for x in xs[1:]:                       # non-head만 올림
        arrow(ax, x + BW / 2, 4.30, x + BW / 2, 5.02, color=PAR, lw=1.2, ls="--")
    ax.text(0.05, 4.75, "각 노드가\nKV 컬럼을\n올린다", fontsize=10.5,
            color=PAR, va="center")
    ax.text(9.95, 5.90, "전체 복제 아님", fontsize=10.5, color=BODY,
            ha="right", va="center")
    ax.text(1.9, 3.30, "head 는 coordinator 가 소스라 parity 그룹에서 빠진다",
            fontsize=10, color=BODY, va="top")

    # ── 아래: 장애 복원 ───────────────────────────────────────────
    ax.text(0.05, 2.75, "장애 복원", fontsize=13, color=BODY,
            fontweight="bold", va="top")
    box(ax, 3.75, 1.95, 5.95, 0.72, "parity 1장  (P)", face=PAR,
        text="white", fs=12.5, bold=True)
    chain(0.85, dead_idx=2)
    for i in (1, 3):                       # 생존자는 KV 를 내어주고
        arrow(ax, xs[i] + BW / 2, 1.57, xs[i] + BW / 2, 1.92,
              color=BODY, lw=1.1, ls="--")
    # P 에서 죽은 노드로 역산
    arrow(ax, xs[2] + BW / 2, 1.92, xs[2] + BW / 2, 1.59, color=PAR, lw=2.4)
    ax.text(xs[2] + BW / 2 + 0.18, 1.75, "역산", fontsize=11,
            color=PAR, va="center", fontweight="bold")
    ax.text(xs[2] + BW / 2, 0.60, "죽음", ha="center", fontsize=10.5,
            color=DEAD, fontweight="bold")

    ax.text(5.0, 0.18, "생존자 KV  ⊕  P   =   B 의 KV        모델 forward 0회",
            ha="center", va="bottom", fontsize=13, color=BODY, fontweight="bold")

    fig.tight_layout()
    save_slide(fig, "fig_parity_mechanism")


# ----------------------------------------------------------------- 2. families
def recovery_families():
    fig, ax = plt.subplots(figsize=SLIDE_FULL)
    blank(ax, (0, 10), (0, 6))

    rows = [
        ("full-replay", SUBJECT["full_replay"], [0, 1, 2, 3, 4], "164 ms"),
        ("surgical",    SUBJECT["surgical"],    [2],             " 16 ms"),
        ("parity",      SUBJECT["parity"],      [],              "0.9 ms"),
    ]
    names = ["head", "A", "B", "C", "tail"]

    DEAD_IDX = 2                            # 세 행 모두 같은 장애(B)를 비교한다
    for r, (title, color, recompute, cost) in enumerate(rows):
        y = 4.45 - r * 1.60
        ax.text(0.05, y + 0.42, title, fontsize=13, color=color,
                fontweight="bold", va="center")
        for i, n in enumerate(names):
            x = 2.05 + i * 1.35
            hit = i in recompute
            box(ax, x, y, 1.15, 0.82, n,
                face=color if hit else OK,
                edge=DEAD if i == DEAD_IDX else None,   # 죽은 노드는 빨간 테두리
                text="white" if hit else BODY, fs=11, bold=hit)
        if title == "parity":               # 재계산 대신 P 에서 역산 (박스 아래에)
            ax.text(2.05 + DEAD_IDX * 1.35 + 0.58, y - 0.18, "⊕ P", ha="center",
                    va="center", fontsize=12.5, color=color, fontweight="bold")
        ax.text(9.95, y + 0.41, cost, ha="right", va="center",
                fontsize=13, color=color, fontweight="bold")

    ax.text(2.05, 5.72, "색칠 = 다시 계산하는 구간", fontsize=11.5, color=BODY)
    ax.text(9.95, 5.72, "position 1개당 비용", fontsize=11.5, color=BODY, ha="right")
    ax.text(2.05 + DEAD_IDX * 1.35 + 0.58, 5.42, "↓ 죽은 노드", ha="center",
            fontsize=10.5, color=DEAD, fontweight="bold")
    ax.text(0.05, 0.30,
            "parity 는 죽은 노드를 다시 돌리지 않고 parity 에서 역산한다",
            fontsize=12.5, color=BODY)

    fig.tight_layout()
    save_slide(fig, "fig_recovery_families")


# ----------------------------------------------------------- 3. generalization
def generalization():
    fig, axes = plt.subplots(1, 2, figsize=SLIDE_WIDE)

    # (a) slot alignment
    ax = axes[0]; blank(ax, (0, 10), (0, 6))
    ax.text(0.1, 5.6, "① 앞선 노드가 한 칸 더 가 있다", fontsize=13,
            color=BODY, fontweight="bold", va="top")
    labels = [("upstream 생존자", 9, SUR), ("victim", 8, DEAD), ("downstream 생존자", 8, OK)]
    for i, (name, n, color) in enumerate(labels):
        y = 4.1 - i * 1.25
        ax.text(0.1, y + 0.3, name, fontsize=11, color=BODY, va="center")
        for k in range(n):
            box(ax, 3.9 + k * 0.62, y, 0.5, 0.6, "", face=color)
        ax.text(3.9 + n * 0.62 + 0.15, y + 0.3, f"{n}", fontsize=12,
                color=color, va="center", fontweight="bold")
    ax.plot([3.9 + 8 * 0.62 - 0.06] * 2, [0.6, 4.9], color=BODY,
            linestyle=":", linewidth=1.4)
    ax.text(0.1, 0.35, "min(생존자) = 8 로 잘라 맞추면 아무 위치나 복원된다",
            fontsize=11.5, color=BODY)

    # (b) trailer overwrite
    ax = axes[1]; blank(ax, (0, 10), (0, 6))
    ax.text(0.1, 5.6, "② 누가 죽었는지가 덮어써지고 있었다", fontsize=13,
            color=BODY, fontweight="bold", va="top")
    chain = ["entry", "hop", "dead"]
    for i, n in enumerate(chain):
        x = 0.6 + i * 3.1
        dead = (n == "dead")
        box(ax, x, 3.3, 2.3, 0.9, n, face=DEAD if dead else OK,
            text="white" if dead else BODY, fs=12, bold=dead)
        if i < 2:
            arrow(ax, x + 2.3, 3.75, 0.6 + (i + 1) * 3.1, 3.75)
    ax.annotate("", xy=(1.75, 3.2), xytext=(4.85, 3.2),
                arrowprops=dict(arrowstyle="-|>", color=DEAD, lw=1.6))
    ax.text(3.3, 2.75, "표식이 자기 다음 홉으로 덮어써짐", ha="center",
            fontsize=11, color=DEAD)
    ax.text(1.75, 2.15, "→ 멀쩡한 hop 이 범인으로 몰려 죽었다", ha="left",
            fontsize=12, color=DEAD, fontweight="bold")
    ax.text(0.1, 1.2, "노드 3개일 땐 홉이 하나뿐이라\n구조적으로 드러날 수 없던 버그",
            fontsize=11.5, color=BODY, va="top")

    fig.tight_layout()
    save_slide(fig, "fig_generalization")


if __name__ == "__main__":
    parity_mechanism()
    recovery_families()
    generalization()
