"""Fig. retained recovery state per token vs simultaneous non-head failures tolerated (k).

KV-CARE stores k parity columns, each the size of the largest protected stage
(k x max); DejaVu stores every protected stage (sum) and tolerates any number.
So k-parity is smaller only while k < sum/max: 3.71 on the main OPT-6.7B
placement and 2.25 on the OPT-350M microscopy placement.  The implementation
supports k=1 and k=2; higher-k markers show geometry only, not implemented
recovery paths.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _paper import COL, EMPH, GRAY, INK, LIGHT, NAME, STYLE, clean, label, save  # noqa: E402

MODEL = os.environ.get("RADP_FIG_MODEL", "7b")     # 7b (default, main paper) | 350m (microscopy)
if MODEL == "7b":
    # OPT-6.7B six-stage placement: non-head stages of 4/4/4/7/7 layers, 16384 B per layer-token
    MAX_STAGE = 7 * 16384              # 112 kB
    SUM_STAGE = 26 * 16384             # 416 kB
    YMAX, NOTE_Y, SUFFIX = 600, 575, ""
else:
    MAX_STAGE = 16384                  # largest non-head stage, B / KV token
    SUM_STAGE = 36864                  # sum of non-head stages
    YMAX, NOTE_Y, SUFFIX = 70, 26, "_350m"
CROSS = SUM_STAGE / MAX_STAGE      # 3.71 (7B) / 2.25 (350M)
KB = 1024

fig, ax = plt.subplots(figsize=COL)

# DejaVu: flat
ax.axhline(SUM_STAGE / KB, color=GRAY, linestyle=STYLE["replicate"]["ls"], linewidth=1.0, zorder=2)
label(ax, f"{NAME['replicate']} (any $k$)", xy=(2.55 if MODEL == "7b" else 4.35, SUM_STAGE / KB), dy=3,
      ha="right", va="bottom", color=GRAY)

# k-parity: k x max. Implemented points (k=1,2) in red; k>=3 hollow (not implemented).
ks = np.array([1, 2, 3, 4])
ax.plot(ks, ks * MAX_STAGE / KB, color=INK, linewidth=0.8, zorder=3)
ax.plot(ks[2:], ks[2:] * MAX_STAGE / KB, linestyle="", marker="^", color=INK,
        mfc="white", markersize=5, zorder=4)
ax.plot(ks[:2], ks[:2] * MAX_STAGE / KB, linestyle="", marker="^", color=EMPH,
        mfc=EMPH, markersize=6, zorder=5)
label(ax, f"{NAME['parity']} ($k$=1): {MAX_STAGE//KB} kB", xy=(1, MAX_STAGE / KB), dx=6, dy=-1,
      color=EMPH, bold=True)
label(ax, f"{NAME['parity']} ($k$=2): {2*MAX_STAGE//KB} kB", xy=(2, 2 * MAX_STAGE / KB), dx=6, dy=-3,
      color=EMPH, bold=True)
label(ax, "$k \\geq 3$: not implemented\n(geometry only)",
      xy=(4.35, NOTE_Y), dx=0, dy=0, ha="right", va="top", color=INK, size=6.5)

# crossover
ax.axvline(CROSS, color=INK, linestyle=":", linewidth=0.6, zorder=1)
label(ax, f"$k = \\Sigma/\\max = {CROSS:.2f}$", xy=(CROSS, YMAX * 0.03), dx=3, dy=0, color=INK, size=6.5)

ax.set_xlabel("simultaneous non-head stage failures tolerated, $k$")
ax.set_ylabel("retained recovery state\n(kB per KV token)")
ax.set_xticks([1, 2, 3, 4])
ax.set_xlim(0.7, 4.4)
ax.set_ylim(0, YMAX)
clean(ax)
fig.subplots_adjust(left=0.17, right=0.98, top=0.97, bottom=0.19)
save(fig, "fig_storage_tolerance" + SUFFIX)
