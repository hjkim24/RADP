"""System architecture: coordinator roles, a generic n-stage pipeline, and the
backup mapping R.  Minimal text; the caption carries the legend."""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

sys.path.insert(0, str(Path(__file__).parent))
from _paper import EMPH, GRAY, INK, LIGHT, save  # noqa: E402

# generic pipeline: (label, is_head, is_ellipsis, backups hosted by this device)
STAGES = [("head", True, False, ["stage $n$"]), ("stage 2", False, False, []),
          ("stage 3", False, False, ["head", "stage 2"]), ("", False, True, []), ("stage $n$", False, False, ["stage 3"])]

fig, ax = plt.subplots(figsize=(3.45, 2.4))
ax.set_xlim(0, 100); ax.set_ylim(9, 80); ax.axis("off")

def box(x0, y0, w, h, *, ls="-", ec=INK, fc="white", lw=0.7, r=1.2):
    ax.add_patch(FancyBboxPatch((x0, y0), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                linestyle=ls, edgecolor=ec, facecolor=fc, linewidth=lw, zorder=2))

def arrow(p, q, *, color=INK, ls="-", lw=0.7, z=3):
    ax.annotate("", xy=q, xytext=p, zorder=z,
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw, linestyle=ls,
                                shrinkA=0, shrinkB=0, mutation_scale=6))

def dotted_arrow(p, q, *, color=GRAY, lw=0.6):
    """Dotted shaft with a solid arrowhead (matplotlib would dot the head too)."""
    (x0, y0), (x1, y1) = p, q
    L = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5; ux, uy = (x1 - x0) / L, (y1 - y0) / L
    ax.plot([x0, x1 - 1.6 * ux], [y0, y1 - 1.6 * uy], color=color, lw=lw, linestyle=(0, (1, 1.5)), zorder=3)
    arrow((x1 - 1.8 * ux, y1 - 1.8 * uy), q, color=color, lw=lw)

# --- client
box(51.5, 71, 16, 7); ax.text(59.5, 74.5, "client", ha="center", va="center", size=7)
arrow((59.5, 71), (59.5, 65)); ax.text(61, 68, "request", size=5.5, color=GRAY, va="center")

# --- coordinator
box(28, 44.5, 63, 20.5, lw=0.9)
ax.text(59.5, 62.1, "Coordinator", ha="center", va="center", size=7.5, weight="bold")
for x, y, t in [(44.5, 55.7, "recovery-aware\nplacement ($\\psi$, $R$)"), (74.5, 55.7, "cross-stage\nparity ($P$, $Q$)"),
                (44.5, 48.5, "input mirror"), (74.5, 48.5, "failure detection")]:
    h = 6.6 if "\n" in t else 4.4
    box(x - 14, y - h / 2, 28, h, ec=LIGHT, lw=0.5, r=0.6)
    ax.text(x, y, t, ha="center", va="center", size=6, linespacing=1.05)

# --- legend (left)
lx = 2
box(lx, 44.5, 25, 20.5, ec=LIGHT, lw=0.5)
for y, col, ls, t in [(62.3, INK, "-", "request path"), (58.5, GRAY, "-", "activation"),
                      (54.7, EMPH, "-", "KV + input"), (50.9, GRAY, (0, (1, 1.5)), "control ($\\psi$, $R$)")]:
    ax.plot([lx + 1.5, lx + 6.5], [y, y], color=col, lw=0.7, linestyle=ls); ax.text(lx + 8, y, t, size=5.5, va="center")
box(lx + 1.5, 45.5, 5, 3.2, ls=(0, (2, 1.5)), ec=INK, lw=0.5, r=0.5); ax.text(lx + 8, 47.1, "backup ($R$)", size=5.5, va="center")

# --- workers
W, GAP = 15.5, 3.6
x0 = (100 - 5 * W - 4 * GAP) / 2
centers = []
for i, (lab, head, dots, hosted) in enumerate(STAGES):
    x = x0 + i * (W + GAP); c = x + W / 2; centers.append(c)
    if dots:
        ax.text(c, 24.5, "$\\cdots$", ha="center", va="center", size=9, color=GRAY)
        continue
    box(x, 19, W, 11, fc="#F2F2F2" if head else "white")
    ax.text(c, 24.5, lab, ha="center", va="center", size=6.5)
    if hosted:
        h = 3.4 * len(hosted) + 1.2
        box(x + 0.8, 17.2 - h, W - 1.6, h, ls=(0, (2, 1.5)), lw=0.5, r=0.6)
        for k, l in enumerate(hosted):
            ax.text(c, 17.2 - h + 1.9 + 3.4 * (len(hosted) - 1 - k), l, ha="center", va="center", size=5.6, color=GRAY)
    if not head:  # KV column + input to the coordinator
        arrow((c + 2.2, 30), (c + 2.2, 38), color=EMPH, lw=0.6)
    # control stub from the dotted bus
    dotted_arrow((c - 2.2, 34.5), (c - 2.2, 30))
# activation chain
for i in range(4):
    a = centers[i] + (W / 2 if not STAGES[i][2] else 3.2)
    b = centers[i + 1] - (W / 2 if not STAGES[i + 1][2] else 3.2)
    arrow((a, 24.5), (b, 24.5), color=GRAY, lw=0.6)
# KV bus into the coordinator
ax.plot([centers[1] + 2.2, centers[-1] + 2.2], [38, 38], color=EMPH, lw=0.6, zorder=3)
arrow((62, 38), (62, 44.5), color=EMPH, lw=0.6)
# control bus (dotted) from the coordinator down over every worker
ax.plot([centers[0] - 2.2, centers[-1] - 2.2], [34.5, 34.5], color=GRAY, lw=0.6, linestyle=(0, (1, 1.5)), zorder=3)
ax.plot([50, 50], [44.5, 34.5], color=GRAY, lw=0.6, linestyle=(0, (1, 1.5)), zorder=3)
# request path: coordinator -> head (outer left), stage n -> coordinator (outer right)
ax.plot([32, 32, centers[0] + 3], [44.5, 41.5, 41.5], color=INK, lw=0.6, zorder=3)
arrow((centers[0] + 3, 41.5), (centers[0] + 3, 30), color=INK, lw=0.6)
ax.plot([centers[-1] + 5.8, centers[-1] + 5.8, 88], [30, 41.5, 41.5], color=INK, lw=0.6, zorder=3)
arrow((88, 41.5), (88, 44.5), color=INK, lw=0.6)

save(fig, "fig_architecture")
