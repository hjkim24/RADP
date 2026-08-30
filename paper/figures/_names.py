"""Paper-facing display names, shared by the deck (_slide.py) and paper (paper/_paper.py) figures.

Baselines take their reference system's name where one exists; our method
carries the system name KV-CARE (2026-08-30). The RAID vocabulary is avoided in
every figure- and paper-facing string. The KEYS are the internal recovery_mode
identifiers used in experiments/results/*.json (``t["mode"]``) and in the code —
never rename them; only the values are display text.
"""
NAME = {
    "full_replay": "Recompute",             # controlled baseline: replay all stages from position 0
    "surgical":    "Petals",                # failed-stage input replay (Petals-style)
    "parity":      "KV-CARE",               # our method, single parity (k=1)
    "raid6":       "KV-CARE (k=2)",         # our method, double parity (k=2)
    "replicate":   "DejaVu",                # KV replication baseline (ASCII: deck font lacks à/é)
    "reactive_replacement": "Reconfigure",  # controlled baseline: re-solve + cold reload + replay
}
