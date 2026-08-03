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
from _slide import (BODY, NAME, SLIDE_BAND, SLIDE_FULL, SLIDE_WIDE,  # noqa: E402
                    SUBJECT, note, panel, save_slide)

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
BW, BH = 1.55, 0.72


def _chain(ax, xs, y, dead_idx=None, fs=11.5):
    for i, (x, n) in enumerate(zip(xs, NAMES)):
        dead = (i == dead_idx)
        box(ax, x, y, BW, BH, n,
            face=DEAD if dead else (HEAD if i == 0 else OK),
            text="white" if dead else BODY, fs=fs, bold=dead or i > 0)
        if i < 3:
            arrow(ax, x + BW, y + BH / 2, xs[i + 1], y + BH / 2, lw=1.1)


def parity_mechanism():
    """Three panels: what is stored, how the XOR works, how recovery inverts it.

    The earlier version showed the flow but never said what a "KV column" is or
    what the XOR actually operates on, which is the part an audience seeing this
    for the first time needs most. Panel 2 carries that: byte-wise XOR over
    zero-padded columns, one blob regardless of stage count.
    """
    fig = plt.figure(figsize=SLIDE_BAND)
    XS = [0.25 + i * 1.95 for i in range(4)]
    Y_NODE, Y_BAR = 0.35, 2.05

    # ── ① steady state ────────────────────────────────────────────
    ax = panel(fig, [0.015, 0.10, 0.315, 0.80], (-0.1, 8.0), (-0.55, 3.30),
               title="① Steady state")
    box(ax, XS[1], Y_BAR, XS[3] + BW - XS[1], 0.70, "parity blob  P",
        face=PAR, text="white", fs=12, bold=True)
    _chain(ax, XS, Y_NODE)
    for x in XS[1:]:
        arrow(ax, x + BW / 2, Y_NODE + BH, x + BW / 2, Y_BAR,
              color=PAR, lw=1.4, ls=(0, (4, 2)))
    ax.annotate("each non-head\nstage ships its\nKV column",
                xy=(XS[1] + BW / 2, (Y_NODE + BH + Y_BAR) / 2), xytext=(-12, 0),
                textcoords="offset points", ha="right", va="center",
                fontsize=10.5, color=PAR, linespacing=1.4)
    ax.text(XS[0], Y_NODE - 0.30, "head is coordinator-sourced —\nnot in the parity group",
            fontsize=10, color=BODY, va="top", linespacing=1.4)
    ax.text(0, 3.05, "one blob, not one copy per stage",
            fontsize=11, color=PAR, fontweight="bold")

    # ── ② what the XOR operates on ────────────────────────────────
    ax = panel(fig, [0.355, 0.10, 0.29, 0.80], (0, 10), (-0.55, 3.30),
               title="② Byte-wise XOR")
    CW, CG, CH = 1.02, 0.10, 0.52
    X0 = 2.35
    rows = [("KV_A", ["a0", "a1", "a2", "a3"], OK),
            ("KV_B", ["b0", "b1", "b2", "0"], OK),
            ("KV_C", ["c0", "c1", "c2", "c3"], OK)]
    for r, (name, cells, face) in enumerate(rows):
        y = 2.30 - r * 0.66
        if r:                                   # 행 사이에 연산자를 둔다
            ax.text(X0 - 0.62, y + CH + 0.07, "⊕", ha="center", va="center",
                    fontsize=13, color=PAR, fontweight="bold")
        ax.text(X0 - 0.18, y + CH / 2, name, ha="right", va="center",
                fontsize=11, color=BODY)
        for c, val in enumerate(cells):
            pad = (val == "0")
            box(ax, X0 + c * (CW + CG), y, CW, CH, val,
                face="#EDEFEF" if pad else face,
                text="#9AA3A3" if pad else BODY, fs=10.5)
    ax.text(X0 + 4 * (CW + CG) - CG + 0.12, 2.30 - 0.66 + CH / 2,
            "zero-pad", ha="left", va="center", fontsize=10, color="#9AA3A3")
    ax.plot([X0 - 0.05, X0 + 4 * (CW + CG) - CG + 0.05], [0.72, 0.72],
            color=BODY, linewidth=1.1)
    for c, val in enumerate(["p0", "p1", "p2", "p3"]):
        box(ax, X0 + c * (CW + CG), 0.06, CW, CH, val, face=PAR,
            text="white", fs=10.5, bold=True)
    ax.text(X0 - 0.18, 0.06 + CH / 2, "P", ha="right", va="center",
            fontsize=11, color=PAR, fontweight="bold")
    ax.text(X0, -0.30, "one column per position, per stage",
            fontsize=10, color=BODY, va="top")
    ax.text(0, 3.05, "raw bytes — works for any dtype",
            fontsize=11, color=PAR, fontweight="bold")

    # ── ③ recovery ────────────────────────────────────────────────
    ax = panel(fig, [0.675, 0.10, 0.315, 0.80], (-0.1, 8.0), (-0.55, 3.30),
               title="③ Recovery", right="zero forward passes")
    box(ax, XS[1], Y_BAR, XS[3] + BW - XS[1], 0.70, "parity blob  P",
        face=PAR, text="white", fs=12, bold=True)
    _chain(ax, XS, Y_NODE, dead_idx=2)
    for i in (1, 3):
        arrow(ax, XS[i] + BW / 2, Y_NODE + BH, XS[i] + BW / 2, Y_BAR,
              color=BODY, lw=1.1, ls=(0, (4, 2)))
    arrow(ax, XS[2] + BW / 2, Y_BAR, XS[2] + BW / 2, Y_NODE + BH,
          color=PAR, lw=2.6)
    ax.annotate("solve", xy=(XS[2] + BW / 2, (Y_NODE + BH + Y_BAR) / 2),
                xytext=(9, 0), textcoords="offset points", ha="left",
                va="center", fontsize=11, color=PAR, fontweight="bold")
    ax.annotate("dead", xy=(XS[2] + BW / 2, Y_NODE), xytext=(0, -7),
                textcoords="offset points", ha="center", va="top",
                fontsize=10.5, color=DEAD, fontweight="bold")
    ax.text(0, 3.05, "survivors give back what they still hold",
            fontsize=11, color=BODY)

    # ── the two equations carry the whole idea ────────────────────
    ax = panel(fig, [0.015, 0.0, 0.975, 0.095], (0, 10), (0, 1))
    ax.text(2.45, 0.5, "P  =  KV_A  ⊕  KV_B  ⊕  KV_C", ha="center",
            va="center", fontsize=14, color=BODY, fontweight="bold")
    ax.text(7.35, 0.5, "KV_B  =  KV_A  ⊕  KV_C  ⊕  P", ha="center",
            va="center", fontsize=14, color=PAR, fontweight="bold")

    save_slide(fig, "fig_parity_mechanism")
    plt.close(fig)


# ----------------------------------------------------------------- 2. families
def recovery_families(only_existing: bool = False):
    """only_existing=True 면 parity 행을 뺀다.

    새 기술을 소개하는 발표에서는 기존 방식의 한계를 먼저 세워야 원리 설명이
    읽힌다. 같은 그림을 두 번 쓰되 앞에서는 parity 를 감춰, 청중이 "둘 다
    재계산이라 늦게 죽을수록 비싸다" 를 먼저 받아들이게 한다.
    """
    fig = plt.figure(figsize=SLIDE_FULL)
    ax = panel(fig, [0.02, 0.11, 0.96, 0.80], (0, 10),
               (0.55, 3.15) if only_existing else (0, 3.6),
               title="filled = recomputed", right="cost per position")

    rows = [
        (NAME["full_replay"], SUBJECT["full_replay"], [0, 1, 2, 3, 4], "164 ms"),
        (NAME["surgical"],    SUBJECT["surgical"],    [2],             "16 ms"),
        (NAME["parity"],      SUBJECT["parity"],      [],              "0.87 ms"),
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
        if title == NAME["parity"]:          # 재계산 대신 P에서 역산 (KV-RAID)
            ax.annotate("⊕ P", xy=(cx(DEAD_IDX) + CW / 2, y), xytext=(0, -7),
                        textcoords="offset points", ha="center", va="top",
                        fontsize=13, color=color, fontweight="bold")
        ax.text(9.95, y + RH / 2, cost, ha="right", va="center",
                fontsize=14, color=color, fontweight="bold")

    # 죽은 노드 표식은 첫 행 윗변에 붙인다 (행 수가 바뀌어도 따라오게)
    top_row = 2.42 - (0.51 if only_existing else 0) + RH
    ax.annotate("dead stage", xy=(cx(DEAD_IDX) + CW / 2, top_row), xytext=(0, 16),
                textcoords="offset points", ha="center", va="bottom",
                fontsize=11.5, color=DEAD, fontweight="bold",
                arrowprops=dict(arrowstyle="-|>", color=DEAD, lw=1.5,
                                shrinkA=2, shrinkB=0))

    ax = panel(fig, [0.02, 0.0, 0.96, 0.10], (0, 10), (0, 1))
    ax.text(0.05, 0.5,
            "both re-run the dead stage — cost scales with how far in it died"
            if only_existing
            else f"{NAME['parity']} solves for the dead stage instead of re-running it",
            fontsize=13, color=BODY, va="center")

    save_slide(fig, "fig_recovery_families_before" if only_existing
               else "fig_recovery_families")
    plt.close(fig)


# ----------------------------------------------------------- 3. generalization
def generalization():
    fig = plt.figure(figsize=SLIDE_WIDE)

    # ── (a) slot alignment ────────────────────────────────────────
    ax = panel(fig, [0.015, 0.22, 0.45, 0.62], (0, 10), (0.45, 4.3),
               title="① Upstream survivors run one slot ahead")
    SX, SW, SGAP, SH = 3.55, 0.52, 0.10, 0.62
    rows = [("upstream survivor", 9, SUR), ("victim", 8, DEAD),
            ("downstream survivor", 8, OK)]
    for i, (name, n, color) in enumerate(rows):
        y = 3.05 - i * 1.05
        ax.text(0.05, y + SH / 2, name, fontsize=11.5, color=BODY, va="center")
        for k in range(n):
            box(ax, SX + k * (SW + SGAP), y, SW, SH, "", face=color)
        ax.text(9.95, y + SH / 2, f"{n} slots", ha="right", va="center",
                fontsize=12, color=BODY, fontweight="bold")

    cut = SX + 8 * (SW + SGAP) - SGAP / 2      # 8칸째 뒤 = 자르는 지점
    ax.plot([cut, cut], [0.55, 3.95], color=BODY, linestyle=":", linewidth=1.6)
    ax.annotate("trim to min = 8", xy=(cut, 3.95), xytext=(0, 6),
                textcoords="offset points", ha="center", va="bottom",
                fontsize=11.5, color=BODY, fontweight="bold")

    ax = panel(fig, [0.015, 0.02, 0.45, 0.16], (0, 10), (0, 1))
    note(ax, 0.05, 0.5, "Any interior victim recovers, not just the first one",
         width=64, size=12)

    # ── (b) trailer overwrite ─────────────────────────────────────
    ax = panel(fig, [0.535, 0.22, 0.45, 0.62], (0, 10), (0.45, 4.3),
               title="② The failure marker was being overwritten")
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
            "each hop overwrote the marker with its own next hop",
            ha="center", va="center", fontsize=11.5, color=DEAD)
    ax.text(CX + 1.5 * STEP + CW2 / 2, y_back - 1.02,
            "→ a live hop got blamed and killed",
            ha="center", va="center", fontsize=12.5, color=DEAD,
            fontweight="bold")

    ax = panel(fig, [0.535, 0.02, 0.45, 0.16], (0, 10), (0, 1))
    note(ax, 0.05, 0.5, "Invisible on a 3-node chain — only one hop exists "
         "to be blamed", width=64, size=12)

    save_slide(fig, "fig_generalization")
    plt.close(fig)


# ------------------------------------------------------- 4. prior art delta
def ghostserve_delta():
    """Where GhostServe put parity vs where we put it.

    Every fact on the left panel is from the paper as cataloged in
    paper/refs/PAPERS.md — coding group = tensor-parallel shards inside one
    node, parity offloaded to host RAM, H200 x8 over NVLink, and the paper's
    own scope note that it is "primarily designed for intra-node serving,
    particularly for tensor parallelism". Nothing here is inferred: the point
    of the figure is that the regime we run in is the one they named as out
    of scope, so the contribution is the transplant, not the mechanism.
    """
    fig = plt.figure(figsize=SLIDE_WIDE)

    # ── GhostServe: inside one server ─────────────────────────────
    ax = panel(fig, [0.015, 0.30, 0.45, 0.58], (0, 10), (0, 4.2),
               title="GhostServe (MLSys '26)")
    ax.add_patch(FancyBboxPatch((0.35, 1.75), 9.3, 1.35,
                                boxstyle="round,pad=0.05", linewidth=1.4,
                                facecolor="#F2F4F4", edgecolor="#C7CFCF"))
    ax.text(0.60, 3.28, "one server", fontsize=11, color=BODY)
    for i in range(4):
        box(ax, 0.75 + i * 2.20, 2.05, 1.85, 0.75, f"GPU {i}", face=OK, fs=11)
        if i < 3:
            ax.plot([0.75 + i * 2.20 + 1.85, 0.75 + (i + 1) * 2.20],
                    [2.42, 2.42], color=BODY, linewidth=1.6)
    ax.text(0.35, 1.62, "NVLink · tensor-parallel shards", ha="left",
            va="top", fontsize=10.5, color=BODY)
    arrow(ax, 7.6, 1.72, 7.6, 1.05, color=PAR, lw=1.8)
    box(ax, 4.9, 0.20, 4.7, 0.80, "host RAM  (parity)", face=PAR,
        text="white", fs=12, bold=True)

    # ── ours: across the network ──────────────────────────────────
    ax = panel(fig, [0.535, 0.30, 0.45, 0.58], (0, 10), (0, 4.2),
               title="Ours — same idea, different regime")
    box(ax, 0.75, 3.05, 3 * 2.20 + 1.85, 0.80, "coordinator  (KV-RAID)",
        face=PAR, text="white", fs=12, bold=True)
    for i in range(4):
        x = 0.75 + i * 2.20
        box(ax, x, 1.35, 1.85, 0.75, f"stage {i}", face=OK, fs=11)
        arrow(ax, x + 0.92, 2.12, x + 0.92, 3.02, color=PAR, lw=1.4,
              ls=(0, (4, 2)))
        if i < 3:
            ax.plot([x + 1.85, 0.75 + (i + 1) * 2.20], [1.72, 1.72],
                    color=BODY, linewidth=1.2, linestyle=":")
    ax.text(5.0, 1.05, "Ethernet · pipeline stages on separate boards",
            ha="center", va="top", fontsize=10.5, color=BODY)
    ax.text(5.0, 0.35, "no spare node, no host RAM to offload to",
            ha="center", va="top", fontsize=10.5, color=DEAD)

    # ── the one sentence that positions the work ──────────────────
    ax = panel(fig, [0.015, 0.0, 0.97, 0.22], (0, 10), (0, 1))
    note(ax, 0.05, 0.5, "KV erasure coding is theirs. The paper scopes itself "
         "to intra-node tensor parallelism and leaves cross-node pipeline as "
         "future work — that gap is the regime we measure in.",
         width=105, size=12)

    save_slide(fig, "fig_ghostserve_delta")
    plt.close(fig)


if __name__ == "__main__":
    parity_mechanism()
    recovery_families(only_existing=True)
    recovery_families()
    generalization()
    ghostserve_delta()
