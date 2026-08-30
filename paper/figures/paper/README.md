# Paper figures (IEEE IoT-J, black & white)

Built by `make_*.py` here with the shared `_paper.py` (Times, 8 pt, 3.5 in
column width, grayscale + one red emphasis, automatic text-overlap check).
Rebuild: `for f in paper/figures/paper/make_*.py; do .venv/bin/python "$f"; done`

| Figure | Kind | Source | Use in Evaluation |
|---|---|---|---|
| `fig_recovery_latency` | live | `b1_ft_fleet_parity.json`, `b1_ft_fleet_replicate.json`, `b1_ft_fleet_reactive_client_interval_20260830.json` | §B recovery latency vs P (5 families; Reconfigure = points + median, no slope) |
| `fig_recovery_pareto` | live (x) + geometry (y) | same three + `b1_ft_overhead.json` | §B/§C latency at P=32 vs retained state per token |
| `fig_storage_tolerance` | geometry | placement 1/3/4/1 non-head layers, 4096 B/layer-token | §C k-parity vs replication, crossover k = Σ/max = 2.25 |
| `fig_storage_scaling` | derived projection + 1 measured point | `experiments/storage_scaling_models.py` | §C gap vs context per model size |
| `fig_protection_cost` | live, N=3 | `b1_steady_modes_n3_20260830.json` | §E failure-free cost of protection |

Not drawn on purpose: double-parity TTR (its 30.3 s intercept is a
concentrated-backup artifact — reported as text: 5/5 bit-correct, slope
2.78 ms/pos); KV-State Fidelity (one tier pair, one stage → table);
Recovery Feasibility memory-cap sweep (D2.9 has no saved JSON yet).

Deck (colour, slide-scale) versions of the same data live one level up
(`make_*_slide.py`, `_slide.py`); both use the display names in `_names.py`.
