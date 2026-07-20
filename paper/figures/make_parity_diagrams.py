"""Explanatory diagrams for the recovery work (ppt/DESIGN_SYSTEM.md §7).

Three figures that carry points which words alone do not land:

  fig_parity_mechanism    — how parity keeps ONE blob and inverts it on failure
  fig_recovery_families   — what each of the three families recomputes
  fig_generalization      — the slot-alignment fix and the trailer-overwrite bug

Built at slide scale with the deck palette so they drop straight into the
progress-report template. Data-free diagrams: nothing here is measured, so the
numbers that appear are quoted from experiments/results/b1_ft_fleet_parity.json
and REPORT.md, not computed.

**Layout rule.** Every panel gets its own axes via `_slide.panel()` and every
caption sits in a strip reserved for it. Text is never dropped into the drawing
area at hand-picked data coordinates — that is what made the first version drift
and overlap. Labels that belong to a shape use `annotate(xy=shape)` so they
follow the shape instead of remembering where it used to be.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

sys.path.insert(0, str(Path(__file__).parent))
from _slide import (BODY, SLIDE_FULL, SLIDE_WIDE, SUBJECT,  # noqa: E402
                    note, panel, save_slide)

DEAD = SUBJECT["full_replay"]      # 죽은 노드
OK = "#B8C0C0"                     # 평상시 노드
HEAD = "#DDE3E3"                   # head는 parity 그룹 밖이라 더 옅게
PAR = SUBJECT["parity"]
SUR = SUBJECT["surgical"]


def box(ax, x, y, w, h, label, face=OK, edge=None, text=BODY, fs=12, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012",
                                linewidth=1.6, facecolor=face,
                                edgecolor=edge or face, zorder=2))
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", zorder=3,
            fontsize=fs, color=text, fontweight="bold" if bold else "normal")


def arrow(ax, x1, y1, x2, y2, color=BODY, lw=1.4, ls="-"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                                 mutation_scale=13, linewidth=lw, color=color,
                                 linestyle=ls, shrinkA=2, shrinkB=2, zorder=4))


# ---------------------------------------------------------------- 1. mechanism
NAMES = ["head", "A", "B", "C"]
XS = [0.30 + i * 2.45 for i in range(4)]     # head 0.30 / A 2.75 / B 5.20 / C 7.65
BW, BH = 2.10, 0.90
BAR_X, BAR_W = XS[1], XS[3] + BW - XS[1]     # parity 막대는 non-head만 덮는다
Y_NODE, Y_BAR = 0.55, 2.35


def _chain(ax, dead_idx=None):
    for i, (x, n) in enumerate(zip(XS, NAMES)):
        dead = (i == dead_idx)
        box(ax, x, Y_NODE, BW, BH, n,
            face=DEAD if dead else (HEAD if i == 0 else OK),
            text="white" if dead else BODY, fs=13, bold=dead or i > 0)
        if i < 3:
            arrow(ax, x + BW, Y_NODE + BH / 2, XS[i + 1], Y_NODE + BH / 2, lw=1.2)


def _bar(ax):
    box(ax, BAR_X, Y_BAR, BAR_W, 0.85, "parity  1장  (P)", face=PAR,
        text="white", fs=14, bold=True)


def parity_mechanism():
    """정상 운영(위) / 장애 복원(아래). 두 패널이 각자 축을 갖는다."""
    fig = plt.figure(figsize=SLIDE_FULL)
    LIM = (-0.2, 10.2), (-0.45, 3.45)

    # ── 위: 정상 운영 ─────────────────────────────────────────────
    ax = panel(fig, [0.02, 0.545, 0.96, 0.375], *LIM,
               title="정상 운영", right="저장량은 stage 수와 무관하게 KV 1개분")
    _bar(ax); _chain(ax)
    for x in XS[1:]:
        arrow(ax, x + BW / 2, Y_NODE + BH, x + BW / 2, Y_BAR,
              color=PAR, lw=1.5, ls=(0, (4, 2)))
    ax.annotate("KV 컬럼\n올림", xy=(XS[1] + BW / 2, (Y_NODE + BH + Y_BAR) / 2),
                xytext=(-24, 0), textcoords="offset points", ha="right",
                va="center", fontsize=11.5, color=PAR, linespacing=1.4)
    note(ax, XS[0], Y_NODE - 0.28, "head는 coordinator가 소스 → parity 그룹 제외",
         width=48, size=11, va="top")

    # ── 아래: 장애 복원 ───────────────────────────────────────────
    ax = panel(fig, [0.02, 0.115, 0.96, 0.375], *LIM,
               title="장애 복원", right="모델 forward 0회")
    _bar(ax); _chain(ax, dead_idx=2)
    for i in (1, 3):                                   # 생존자는 KV를 내어주고
        arrow(ax, XS[i] + BW / 2, Y_NODE + BH, XS[i] + BW / 2, Y_BAR,
              color=BODY, lw=1.2, ls=(0, (4, 2)))
    arrow(ax, XS[2] + BW / 2, Y_BAR, XS[2] + BW / 2, Y_NODE + BH,
          color=PAR, lw=2.8)                           # P에서 죽은 노드로 역산
    ax.annotate("역산", xy=(XS[2] + BW / 2, (Y_NODE + BH + Y_BAR) / 2),
                xytext=(12, 0), textcoords="offset points", ha="left",
                va="center", fontsize=12, color=PAR, fontweight="bold")
    ax.annotate("죽음", xy=(XS[2] + BW / 2, Y_NODE), xytext=(0, -8),
                textcoords="offset points", ha="center", va="top",
                fontsize=11.5, color=DEAD, fontweight="bold")

    # ── 결론: 자기 영역을 갖는다 ──────────────────────────────────
    ax = panel(fig, [0.02, 0.0, 0.96, 0.105], (0, 10), (0, 1))
    ax.text(5, 0.5, "생존자 KV   ⊕   P   =   B의 KV", ha="center", va="center",
            fontsize=15, color=BODY, fontweight="bold")

    save_slide(fig, "fig_parity_mechanism")
    plt.close(fig)


# ----------------------------------------------------------------- 2. families
def recovery_families(only_existing: bool = False):
    """only_existing=True 면 parity 행을 뺀다.

    새 기술을 소개하는 발표에서는 기존 방식의 한계를 먼저 세워야 원리 설명이
    읽힌다. 같은 그림을 두 번 쓰되 앞에서는 parity 를 감춰, 청중이 "둘 다
    재계산이라 깊이를 탄다" 를 먼저 받아들이게 한다.
    """
    fig = plt.figure(figsize=SLIDE_FULL)
    ax = panel(fig, [0.02, 0.11, 0.96, 0.80], (0, 10),
               (0.55, 3.15) if only_existing else (0, 3.6),
               title="색칠 = 다시 계산하는 구간", right="position 1개당 비용")

    rows = [
        ("full-replay", SUBJECT["full_replay"], [0, 1, 2, 3, 4], "164 ms"),
        ("surgical",    SUBJECT["surgical"],    [2],             "16 ms"),
        ("parity",      SUBJECT["parity"],      [],              "0.87 ms"),
    ]
    if only_existing:
        rows = rows[:2]
    names = ["head", "A", "B", "C", "tail"]
    DEAD_IDX = 2                            # 세 행 모두 같은 장애(B)를 비교한다
    X0, CW, GAP, RH = 2.25, 1.18, 0.16, 0.78

    def cx(i):
        return X0 + i * (CW + GAP)

    for r, (title, color, recompute, cost) in enumerate(rows):
        y = 2.42 - r * 1.02 - (0.51 if only_existing else 0)   # 2행이면 세로 중앙
        ax.text(0.05, y + RH / 2, title, fontsize=13.5, color=color,
                fontweight="bold", va="center")
        for i, n in enumerate(names):
            hit = i in recompute
            box(ax, cx(i), y, CW, RH, n,
                face=color if hit else OK,
                text="white" if hit else BODY, fs=11.5, bold=hit)
        if title == "parity":               # 재계산 대신 P에서 역산
            ax.annotate("⊕ P", xy=(cx(DEAD_IDX) + CW / 2, y), xytext=(0, -7),
                        textcoords="offset points", ha="center", va="top",
                        fontsize=13, color=color, fontweight="bold")
        ax.text(9.95, y + RH / 2, cost, ha="right", va="center",
                fontsize=14, color=color, fontweight="bold")

    # 죽은 노드 표식은 첫 행 윗변에 붙인다 (행 수가 바뀌어도 따라오게)
    top_row = 2.42 - (0.51 if only_existing else 0) + RH
    ax.annotate("죽은 노드", xy=(cx(DEAD_IDX) + CW / 2, top_row), xytext=(0, 16),
                textcoords="offset points", ha="center", va="bottom",
                fontsize=11.5, color=DEAD, fontweight="bold",
                arrowprops=dict(arrowstyle="-|>", color=DEAD, lw=1.5,
                                shrinkA=2, shrinkB=0))

    ax = panel(fig, [0.02, 0.0, 0.96, 0.10], (0, 10), (0, 1))
    ax.text(0.05, 0.5,
            "둘 다 죽은 노드를 다시 돌림 → 깊이에 비례" if only_existing
            else "parity는 죽은 노드를 다시 돌리지 않고 parity에서 역산함",
            fontsize=13, color=BODY, va="center")

    save_slide(fig, "fig_recovery_families_before" if only_existing
               else "fig_recovery_families")
    plt.close(fig)


# ----------------------------------------------------------- 3. generalization
def generalization():
    fig = plt.figure(figsize=SLIDE_WIDE)

    # ── (a) slot alignment ────────────────────────────────────────
    ax = panel(fig, [0.015, 0.22, 0.45, 0.62], (0, 10), (0.45, 4.3),
               title="① 앞선 노드가 한 칸 더 감")
    SX, SW, SGAP, SH = 3.55, 0.52, 0.10, 0.62
    rows = [("upstream 생존자", 9, SUR), ("victim", 8, DEAD),
            ("downstream 생존자", 8, OK)]
    for i, (name, n, color) in enumerate(rows):
        y = 3.05 - i * 1.05
        ax.text(0.05, y + SH / 2, name, fontsize=11.5, color=BODY, va="center")
        for k in range(n):
            box(ax, SX + k * (SW + SGAP), y, SW, SH, "", face=color)
        ax.text(9.95, y + SH / 2, f"{n} slot", ha="right", va="center",
                fontsize=12, color=BODY, fontweight="bold")

    cut = SX + 8 * (SW + SGAP) - SGAP / 2      # 8칸째 뒤 = 자르는 지점
    ax.plot([cut, cut], [0.55, 3.95], color=BODY, linestyle=":", linewidth=1.6)
    ax.annotate("min = 8에서 자름", xy=(cut, 3.95), xytext=(0, 6),
                textcoords="offset points", ha="center", va="bottom",
                fontsize=11.5, color=BODY, fontweight="bold")

    ax = panel(fig, [0.015, 0.02, 0.45, 0.16], (0, 10), (0, 1))
    note(ax, 0.05, 0.5, "잘라 맞추면 첫 워커 외 임의 위치 복원됨",
         width=60, size=12)

    # ── (b) trailer overwrite ─────────────────────────────────────
    ax = panel(fig, [0.535, 0.22, 0.45, 0.62], (0, 10), (0.45, 4.3),
               title="② 누가 죽었는지가 덮어써짐")
    chain = ["entry", "hop", "dead"]
    CX, CW2, CH = 0.30, 2.60, 0.95
    STEP = 3.35
    y = 2.55
    for i, n in enumerate(chain):
        x = CX + i * STEP
        dead = (n == "dead")
        box(ax, x, y, CW2, CH, n, face=DEAD if dead else OK,
            text="white" if dead else BODY, fs=12.5, bold=dead)
        if i < 2:
            arrow(ax, x + CW2, y + CH / 2, CX + (i + 1) * STEP, y + CH / 2)

    # 표식이 dead에서 hop으로 되돌아 덮어쓰는 흐름
    y_back = y - 0.42
    ax.annotate("", xy=(CX + STEP + CW2 / 2, y_back),
                xytext=(CX + 2 * STEP + CW2 / 2, y_back),
                arrowprops=dict(arrowstyle="-|>", color=DEAD, lw=2.0,
                                shrinkA=0, shrinkB=0))
    ax.text(CX + 1.5 * STEP + CW2 / 2, y_back - 0.42,
            "장애 표식이 자기 다음 홉으로 덮어써짐",
            ha="center", va="center", fontsize=11.5, color=DEAD)
    ax.text(CX + 1.5 * STEP + CW2 / 2, y_back - 1.02,
            "→ 멀쩡한 hop이 범인으로 몰려 죽음",
            ha="center", va="center", fontsize=12.5, color=DEAD,
            fontweight="bold")

    ax = panel(fig, [0.535, 0.02, 0.45, 0.16], (0, 10), (0, 1))
    note(ax, 0.05, 0.5, "노드 3개일 땐 홉이 하나뿐이라 구조적으로 드러날 수 없던 버그",
         width=60, size=12)

    save_slide(fig, "fig_generalization")
    plt.close(fig)


if __name__ == "__main__":
    parity_mechanism()
    recovery_families(only_existing=True)
    recovery_families()
    generalization()
