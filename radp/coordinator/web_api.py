"""Read-only dashboard for the live coordinator (Phase Web0).

Embedded uvicorn thread inside the radp-coordinator process. All cluster
state is reachable as direct Python references — no IPC, no second
systemd unit, no worker-side change.

Endpoints (JSON):
  GET /api/cluster      → last auto_schedule sidecar (placement, recovery,
                          phase timings, profiles) or 404 in manual mode
  GET /api/heartbeats   → device_id → {last_ts_ns, free/total memory,
                          device_class}; latest snapshot from FailureDetector
  GET /api/gateway      → model/dtype/schedule_mode + current placement +
                          recovery + which devices are marked dead

Static:
  GET /                 → index.html (single-page dashboard)
  GET /static/*         → other static assets
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from radp.common.logging_utils import get_logger
from radp.common.types import DeviceId

if TYPE_CHECKING:
    from radp.coordinator.server import CoordinatorServer


# NOTE: pydantic evaluates these annotations at *class-creation time*, not
# just at type-check time, so `int | None` would break on Python 3.9 even
# with `from __future__ import annotations`. Use Optional[...] explicitly.
class _GenerateRequest(BaseModel):
    prompt: str
    max_tokens: int = Field(default=20, ge=1, le=2048)
    temperature: float = Field(default=0.0, ge=0.0, le=4.0)
    top_k: int = Field(default=0, ge=0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    seed: Optional[int] = None  # noqa: UP045
    eos_token_id: Optional[int] = None  # noqa: UP045


class _FailureRequest(BaseModel):
    device_id: str

log = get_logger(__name__)

_SIDECAR_PATH = Path("/tmp/radp_scheduler_stats.json")
_STATIC_DIR = Path(__file__).resolve().parent / "web_static"


def make_app(server: CoordinatorServer) -> FastAPI:
    app = FastAPI(title="RADP Dashboard", docs_url=None, redoc_url=None)

    @app.get("/api/cluster")
    def get_cluster() -> Any:
        if _SIDECAR_PATH.exists():
            try:
                return json.loads(_SIDECAR_PATH.read_text())
            except json.JSONDecodeError as e:
                return JSONResponse(
                    {"detail": f"sidecar parse error: {e}"}, status_code=500
                )
        return JSONResponse(
            {"detail": "no auto_schedule sidecar (manual mode or pre-schedule)"},
            status_code=404,
        )

    @app.get("/api/heartbeats")
    def get_heartbeats() -> Any:
        det = server.detector
        if det is None:
            return JSONResponse(
                {"detail": "detector not started"}, status_code=503
            )
        records = det.snapshot_records()
        return {
            str(d): {
                "last_ts_ns": r.last_ts_ns,
                "free_memory_bytes": r.free_memory_bytes,
                "total_memory_bytes": r.total_memory_bytes,
                "device_class": r.device_class,
            }
            for d, r in records.items()
        }

    @app.get("/api/gateway")
    def get_gateway() -> Any:
        gw = server.gateway
        dead: list[str] = []
        if gw is not None:
            # gateway tracks dead devices in its private _dead set; exposing
            # via the public-ish web API is fine since this is read-only.
            dead = sorted(str(d) for d in getattr(gw, "_dead", set()))
        return {
            "model_id": server.config.model_id,
            "schedule_mode": server.config.schedule_mode,
            "torch_device": server.config.torch_device,
            "dtype": server.config.dtype,
            "bind_address": server.config.bind_address,
            "workers": [
                {"id": str(w.device_id), "address": w.address}
                for w in server.config.workers
            ],
            "placement": [
                {
                    "device": str(s.device),
                    "start": int(s.start_layer),
                    "end": int(s.end_layer),
                }
                for s in server.placement
            ],
            "recovery": {str(j): str(k) for j, k in server.recovery.items()},
            "ready": gw is not None,
            "dead_devices": dead,
        }

    @app.post("/api/generate")
    def post_generate(req: _GenerateRequest) -> Any:
        """Streaming Generate via Server-Sent Events.

        Frame format: `data: {json}\\n\\n`. Token frames carry:
          - kind="token", token_id, text, is_first, step_seconds,
            stages: [{device, start, end, invoke_seconds}, …]
        Final frame: kind="done", n_tokens, wall_seconds.
        Error frame: kind="error", message.

        Implemented as a sync generator inside FastAPI's threadpool — the
        underlying gateway.generate_streaming yields on each decode step.
        """
        gw = server.gateway
        if gw is None:
            return JSONResponse(
                {"detail": "gateway not ready (still bootstrapping)"},
                status_code=503,
            )

        def event_stream() -> Any:
            n = 0
            t0 = time.perf_counter()
            try:
                for tok in gw.generate_streaming(
                    prompt=req.prompt,
                    max_tokens=req.max_tokens,
                    temperature=req.temperature,
                    top_k=req.top_k,
                    top_p=req.top_p,
                    eos_token_id=req.eos_token_id,
                    seed=req.seed,
                ):
                    payload = {
                        "kind": "token",
                        "token_id": tok.token_id,
                        "text": tok.text,
                        "is_first": tok.is_first,
                        "step_seconds": tok.step_seconds,
                        "stages": [
                            {
                                "device": str(s.device),
                                "start": s.start_layer,
                                "end": s.end_layer,
                                "invoke_seconds": s.invoke_seconds,
                            }
                            for s in tok.stages
                        ],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                    n += 1
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "kind": "done",
                            "n_tokens": n,
                            "wall_seconds": time.perf_counter() - t0,
                        }
                    )
                    + "\n\n"
                )
            except Exception as e:  # noqa: BLE001
                log.exception("generate stream failed")
                yield (
                    "data: "
                    + json.dumps({"kind": "error", "message": str(e)})
                    + "\n\n"
                )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/inject_failure")
    def post_inject_failure(req: _FailureRequest) -> Any:
        """Simulate a worker failure by adding the device to the gateway's
        `_dead` set and rebuilding the execution plan.

        Notes:
          * The remote worker process is NOT killed — this is purely a
            routing-side simulation. The next decode step on a victim stage
            will route to the backup per R, exactly as a real gRPC failure
            would after mark_dead. Reversible via /api/revive_device.
          * If the baseline has R = {} for this device, the next Generate
            attempt will surface a NoRecoveryError as an SSE error frame —
            that IS the demo's "catastrophic baseline" scenario.
        """
        gw = server.gateway
        if gw is None:
            return JSONResponse(
                {"detail": "gateway not ready"}, status_code=503
            )
        try:
            changed = gw.mark_dead(DeviceId(req.device_id))
        except Exception as e:  # NoRecoveryError or other
            return JSONResponse(
                {"detail": f"mark_dead failed: {e}",
                 "device_id": req.device_id}, status_code=409
            )
        return {
            "device_id": req.device_id,
            "changed": changed,
            "dead_devices": sorted(str(d) for d in getattr(gw, "_dead", set())),
        }

    @app.post("/api/revive_device")
    def post_revive_device(req: _FailureRequest) -> Any:
        """Reverse of /api/inject_failure — remove device from `_dead` and
        rebuild the execution plan. See gateway.mark_alive() for KV-cache
        caveats around mid-stream revives.
        """
        gw = server.gateway
        if gw is None:
            return JSONResponse(
                {"detail": "gateway not ready"}, status_code=503
            )
        changed = gw.mark_alive(DeviceId(req.device_id))
        return {
            "device_id": req.device_id,
            "changed": changed,
            "dead_devices": sorted(str(d) for d in getattr(gw, "_dead", set())),
        }

    @app.post("/api/clear_all_failures")
    def post_clear_all_failures() -> Any:
        """Revive every currently-dead device in one call (panic clear)."""
        gw = server.gateway
        if gw is None:
            return JSONResponse(
                {"detail": "gateway not ready"}, status_code=503
            )
        before = sorted(str(d) for d in getattr(gw, "_dead", set()))
        for d in list(getattr(gw, "_dead", set())):
            gw.mark_alive(d)
        after = sorted(str(d) for d in getattr(gw, "_dead", set()))
        return {"revived": before, "dead_devices_after": after}

    if _STATIC_DIR.exists():
        app.mount(
            "/static", StaticFiles(directory=str(_STATIC_DIR)), name="static"
        )

    @app.get("/")
    def index() -> Any:
        index_path = _STATIC_DIR / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return JSONResponse(
            {"detail": "index.html missing — web_static not bundled"},
            status_code=404,
        )

    return app


def start_web_api(server: CoordinatorServer, port: int) -> threading.Thread:
    """Spin up uvicorn in a daemon thread bound to 0.0.0.0:<port>.

    Daemonized so it dies when the coordinator process exits. We don't
    surface an explicit shutdown hook — coordinator restart kills it via
    systemd, which is sufficient for v0.
    """
    app = make_app(server)
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        access_log=False,
    )
    uvi = uvicorn.Server(config)

    def run() -> None:
        try:
            uvi.run()
        except Exception:  # noqa: BLE001
            log.exception("web api crashed")

    t = threading.Thread(target=run, name="radp-web-api", daemon=True)
    t.start()
    log.info("web dashboard listening on 0.0.0.0:%d", port)
    return t
