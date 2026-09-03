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
STAGES = [("head", True, False, ["stage $n$"]), ("stage 2", False, False, ["stage 3"]),
          ("stage 3", False, False, ["head"]), ("", False, True, []), ("stage $n$", False, False, ["stage 2"])]

fig, ax = plt.subplots(figsize=(3.45, 2.25))
ax.set_xlim(0, 100); ax.set_ylim(9, 75); ax.axis("off")

def box(x0, y0, w, h, *, ls="-", ec=INK, fc="white", lw=0.7, r=1.2):
    ax.add_patch(FancyBboxPatch((x0, y0), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                linestyle=ls, edgecolor=ec, facecolor=fc, linewidth=lw, zorder=2))

def arrow(p, q, *, color=INK, ls="-", lw=0.7, z=3):
    ax.annotate("", xy=q, xytext=p, zorder=z,
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw, linestyle=ls,
                                shrinkA=0, shrinkB=0, mutation_scale=6))

# --- client
box(51.5, 66.5, 16, 7); ax.text(59.5, 70, "client", ha="center", va="center", size=7)
arrow((59.5, 66.5), (59.5, 60.5)); ax.text(61, 63.5, "request", size=5.5, color=GRAY, va="center")

# --- coordinator
box(28, 40, 63, 20.5, lw=0.9)
ax.text(59.5, 57.6, "Coordinator", ha="center", va="center", size=7.5, weight="bold")
for x, y, t in [(44.5, 51.2, "recovery-aware\nplacement ($\\psi$, $R$)"), (74.5, 51.2, "cross-stage\nparity ($P$, $Q$)"),
                (44.5, 44.0, "input mirror"), (74.5, 44.0, "failure detection")]:
    h = 6.6 if "\n" in t else 4.4
    box(x - 14, y - h / 2, 28, h, ec=LIGHT, lw=0.5, r=0.6)
    ax.text(x, y, t, ha="center", va="center", size=6, linespacing=1.05)

# --- legend (top right)
lx = 2
box(lx, 40, 25, 20.5, ec=LIGHT, lw=0.5)
ax.plot([lx + 1.5, lx + 6.5], [56.5, 56.5], color=GRAY, lw=0.7); ax.text(lx + 8, 56.5, "activation", size=5.5, va="center")
ax.plot([lx + 1.5, lx + 6.5], [50.6, 50.6], color=EMPH, lw=0.7); ax.text(lx + 8, 50.6, "KV column,\ninput", size=5.5, va="center", linespacing=1.05)
box(lx + 1.5, 42.4, 5, 3.2, ls=(0, (2, 1.5)), ec=INK, lw=0.5, r=0.5); ax.text(lx + 8, 44.0, "backup ($R$)", size=5.5, va="center")

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
        arrow((c, 30), (c, 36), color=EMPH, lw=0.6)
# activation chain
for i in range(4):
    a = centers[i] + (W / 2 if not STAGES[i][2] else 3.2)
    b = centers[i + 1] - (W / 2 if not STAGES[i + 1][2] else 3.2)
    arrow((a, 24.5), (b, 24.5), color=GRAY, lw=0.6)
# bus into the coordinator
ax.plot([centers[1], centers[-1]], [36, 36], color=EMPH, lw=0.6, zorder=3)
arrow((59.5, 36), (59.5, 40), color=EMPH, lw=0.6)

save(fig, "fig_architecture")
