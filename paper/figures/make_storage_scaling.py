"""Storage vs stage count: replicate O(N) vs parity O(1). Computed from
placement, not measured — the caption must say so (DESIGN_SYSTEM §11)."""
import sys
from pathlib import Path
import matplotlib.pyplot as plt
sys.path.insert(0, str(Path(__file__).parent))
from _slide import BODY, SLIDE_FULL, SUBJECT, save_slide, strip_chrome  # noqa: E402

# Equal-sized stages (unit KV each) to show the asymptotics cleanly.
stages = list(range(2, 13))
replicate = [n for n in stages]     # Σ = N units
parity = [1 for _ in stages]        # max = 1 unit

fig, ax = plt.subplots(figsize=SLIDE_FULL)
ax.plot(stages, replicate, "o-", color=SUBJECT["replicate"], label="replicate  O(N)")
ax.plot(stages, parity, "^-", color=SUBJECT["parity"], label="parity  O(1)")
ax.set_xlabel("pipeline stages  N")
ax.set_ylabel("coordinator storage  (KV units)")
ax.set_ylim(0, None)
strip_chrome(ax)
ax.legend(loc="upper left", frameon=False)
fig.tight_layout()
save_slide(fig, "fig_storage_scaling")
