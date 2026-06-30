"""Persistent placement cache for auto-mode scheduling.

The auto-mode DP solve (``Scheduler.solve_alternating_best_order``) enumerates
Σ_{k} P(M, k) (subset, permutation) candidates — ~13.7 k for a 7-device fleet,
~9 min on the Xavier coordinator's CPU. The chosen placement is deterministic in
the fleet's *structural* inputs (which devices, their hardware class, the model,
and the cost-model knobs), so we cache it keyed on a fingerprint of those inputs.
A systemd restart (or reboot) with an unchanged fleet then reuses the placement
instead of re-solving; the cache self-invalidates the moment the fleet
composition or any cost-model parameter changes (the fingerprint differs).

We deliberately key on device *identity + class*, NOT the measured layer/network
profiles: those drift a few percent run-to-run and would defeat every cache hit,
while the resulting placement is stable within a hardware tier. The trade-off:
a large *within-class* speed change (e.g. an AGX dropping out of MAXN power mode)
is not noticed by the cache. Delete the cache file or set the env var
``RADP_PLACEMENT_CACHE=""`` to force a fresh solve.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from radp.common.logging_utils import get_logger
from radp.common.types import (
    AlternatingResult,
    DeviceId,
    LayerIdx,
    RecoveryTable,
    Stage,
)

log = get_logger(__name__)

_DEFAULT_CACHE_PATH = Path.home() / ".cache" / "radp" / "placement_cache.json"


def default_cache_path() -> Path | None:
    """Resolve the cache path, honouring RADP_PLACEMENT_CACHE.

    Returns None when caching is explicitly disabled (env var set to empty).
    """
    env = os.environ.get("RADP_PLACEMENT_CACHE")
    if env is None:
        return _DEFAULT_CACHE_PATH
    if env.strip() == "":
        return None
    return Path(env)


def compute_fingerprint(
    *,
    device_ids: list[str],
    device_classes: dict[str, str | None],
    model_id: str,
    num_layers: int,
    params: dict[str, Any],
) -> str:
    """SHA-256 of the structural inputs that determine the placement.

    ``device_classes`` maps device id -> hardware class (from the heartbeat);
    ``params`` carries the cost-model + search knobs (optimization_mode,
    eager_backup, hop_overhead_seconds, enable_subset_search, …). Order is
    canonicalised so heartbeat-arrival order can't change the key.
    """
    payload = {
        # Sorted so arrival order is irrelevant; pair each id with its class.
        "devices": sorted(
            (str(d), device_classes.get(str(d))) for d in device_ids
        ),
        "model_id": model_id,
        "num_layers": num_layers,
        "params": {k: params[k] for k in sorted(params)},
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load(path: Path | None, fingerprint: str) -> AlternatingResult | None:
    """Return the cached result iff the file exists and the fingerprint matches.

    Any read/parse error is treated as a miss (logged, swallowed) — a corrupt
    cache must never block scheduling.
    """
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        log.warning("placement cache unreadable at %s; ignoring", path)
        return None
    if data.get("fingerprint") != fingerprint:
        return None
    try:
        placement: list[Stage] = [
            Stage(
                start_layer=LayerIdx(int(s["start"])),
                end_layer=LayerIdx(int(s["end"])),
                device=DeviceId(s["device"]),
            )
            for s in data["placement"]
        ]
        recovery: RecoveryTable = {
            DeviceId(j): DeviceId(k) for j, k in data["recovery"].items()
        }
    except Exception:  # noqa: BLE001
        log.warning("placement cache malformed at %s; ignoring", path)
        return None
    # history is the per-iteration solve log — not reconstructable from cache
    # and only used for diagnostics, so an empty list is correct here.
    return AlternatingResult(
        placement=placement,
        recovery=recovery,
        max_stage_time=float(data.get("max_stage_time", 0.0)),
        iterations=int(data.get("iterations", 0)),
        converged=bool(data.get("converged", False)),
        history=[],
        sum_stage_time=float(data.get("sum_stage_time", 0.0)),
    )


def save(path: Path | None, fingerprint: str, result: AlternatingResult) -> None:
    """Persist the result keyed on the fingerprint. Best-effort.

    Writes atomically (temp file + rename) so a concurrent reader never sees a
    half-written cache. Failure is logged and swallowed — the coordinator must
    not die because the cache couldn't be written.
    """
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "fingerprint": fingerprint,
            "placement": [
                {
                    "device": str(s.device),
                    "start": int(s.start_layer),
                    "end": int(s.end_layer),
                }
                for s in result.placement
            ],
            "recovery": {str(j): str(k) for j, k in result.recovery.items()},
            "max_stage_time": result.max_stage_time,
            "sum_stage_time": result.sum_stage_time,
            "iterations": result.iterations,
            "converged": result.converged,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(path)
        log.info("placement cache written to %s (fingerprint=%s)", path, fingerprint[:12])
    except Exception:  # noqa: BLE001
        log.exception("failed to write placement cache to %s", path)
