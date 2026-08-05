"""GF(2^3) RAID-6 (KV-RAID-6) recovery, worked example — slide diagram.

Three panels: encode (P + GF-weighted Q) -> two blocks die -> recover on the
field. Concrete numbers D0=5, D1=3, D2=6 so the audience can follow every GF
step by hand; the real code is GF(2^8) but the mechanism is identical. Figure
text is English + mathtext (font-glyph safe), per DESIGN_SYSTEM §7.3.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

sys.path.insert(0, str(Path(__file__).parent))
from _slide import ACCENT, BODY, SLIDE_BAND, panel, save_slide  # noqa: E402

DATA = "#DCE6EE"        # data block fill (light blue)
PAR = ACCENT            # parity blob (deck accent blue)
DEAD_F = "#F3DDDB"      # lost block fill
DEAD = "#CB3E3A"        # lost / edge red
RECOV = "#2E8B57"       # recovered green
GREY = "#8A9199"


def box(ax, x, y, w, h, label, face=DATA, edge=None, text=BODY, fs=13, bold=True):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012",
                                linewidth=1.8, facecolor=face,
                                edgecolor=edge or face, zorder=2))
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", zorder=3,
            fontsize=fs, color=text, fontweight="bold" if bold else "normal")


def arrow(ax, x1, y1, x2, y2, color=GREY, lw=1.3):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                                 mutation_scale=11, lw=lw, color=color, zorder=1,
                                 shrinkA=1, shrinkB=1))


# data-block geometry shared by panels 1-2
BX = [0.4, 3.75, 7.1]
BW, BH, BY = 2.5, 1.7, 6.4
VALS = [5, 3, 6]


def data_boxes(ax, dead=()):
    for i, x in enumerate(BX):
        d = i in dead
        box(ax, x, BY, BW, BH,
            (f"$D_{i}=?$" if d else f"$D_{i}={VALS[i]}$"),
            face=DEAD_F if d else DATA, edge=DEAD if d else None,
            text=DEAD if d else BODY)
        ax.text(x + BW / 2, BY + BH + 0.35, f"$g^{i}$", ha="center", va="bottom",
                fontsize=10.5, color=GREY)


fig = plt.figure(figsize=(12.5, 4.35))

# ── ① Encode ────────────────────────────────────────────────────────────
ax = panel(fig, [0.008, 0.10, 0.315, 0.82], title="① Encode")
data_boxes(ax)
for x in BX:
    arrow(ax, x + BW / 2, BY - 0.05, 3.1 + (0 if x < 4 else 3.6), 3.85)
box(ax, 0.6, 2.35, 3.2, 1.35, "$P=0$", face=PAR, text="white")
box(ax, 5.0, 2.35, 3.2, 1.35, "$Q=6$", face=PAR, text="white")
ax.text(0.2, 1.15, r"$P = D_0 \oplus D_1 \oplus D_2$", fontsize=11.5, color=BODY, va="center")
ax.text(0.2, 0.45, r"$Q = g^0 D_0 \oplus g^1 D_1 \oplus g^2 D_2$", fontsize=11.5, color=BODY, va="center")

# ── ② Two blocks die ────────────────────────────────────────────────────
ax = panel(fig, [0.345, 0.10, 0.315, 0.82], title="② Two blocks die  ($D_0, D_2$)")
data_boxes(ax, dead=(0, 2))
box(ax, 0.6, 3.6, 3.2, 1.2, "$P=0$", face=PAR, text="white", fs=12)
box(ax, 5.0, 3.6, 3.2, 1.2, "$Q=6$", face=PAR, text="white", fs=12)
ax.text(0.2, 2.35, r"$P_{xy}=P \oplus D_1 = 3$", fontsize=11.5, color=BODY, va="center")
ax.text(5.0, 2.35, r"$(=D_0 \oplus D_2)$", fontsize=10, color=GREY, va="center")
ax.text(0.2, 1.5, r"$Q_{xy}=Q \oplus g^1 D_1 = 0$", fontsize=11.5, color=BODY, va="center")
ax.text(5.0, 1.5, r"$(=g^0 D_0 \oplus g^2 D_2)$", fontsize=10, color=GREY, va="center")
ax.text(0.2, 0.55, "2 unknowns, 2 equations", fontsize=11, color=DEAD, va="center", style="italic")

# ── ③ Recover on GF(2^3) ────────────────────────────────────────────────
ax = panel(fig, [0.682, 0.10, 0.315, 0.82], title="③ Recover on GF($2^3$)")
ax.text(0.2, 8.9, r"$D_0 = \dfrac{g^2 P_{xy} \oplus Q_{xy}}{\,g^0 \oplus g^2\,}$",
        fontsize=13, color=BODY, va="center")
ax.text(0.2, 6.55, r"$= \dfrac{7 \oplus 0}{\,1 \oplus 4\,} = \dfrac{7}{5} = 7 \cdot 2 = 5$",
        fontsize=12.5, color=BODY, va="center")
ax.text(0.2, 4.5, r"$D_2 = P_{xy} \oplus D_0 = 3 \oplus 5 = 6$",
        fontsize=12.5, color=BODY, va="center")
box(ax, 0.5, 1.9, 3.0, 1.4, "$D_0=5$", face=RECOV, text="white")
box(ax, 4.3, 1.9, 3.0, 1.4, "$D_2=6$", face=RECOV, text="white")
ax.text(0.2, 0.75, "✓  bit-exact vs original  (5, 6)", fontsize=11.5,
        color=RECOV, va="center", fontweight="bold")

save_slide(fig, "fig_gf_recovery")
