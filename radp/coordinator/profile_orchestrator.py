"""Profile-based auto-scheduling orchestrator (Phase D2).

The coordinator uses this at startup (Phase D3 wiring) to learn its fleet
from live measurements instead of a hand-written cluster.yaml. It drives:

  1. wait_for_workers()         — block until every expected worker has
                                  heartbeated at least once
  2. collect_layer_profiles()   — parallel ProfileLayers RPCs across workers;
                                  merge per-device compute_time into a single
                                  list[LayerProfile]
  3. collect_network_profile()  — full-mesh MeasurePeer; each (src, dst) pair
                                  goes through src's worker measuring its
                                  link to dst, so the result reflects the
                                  actual transport that the runtime will use
  4. build_device_profiles()    — combine heartbeat memory + relative compute
                                  speed (derived from layer profiles) into
                                  the DeviceProfile objects the scheduler
                                  consumes
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import grpc

from radp.common.logging_utils import get_logger
from radp.common.proto import radp_pb2, radp_pb2_grpc
from radp.common.types import (
    DeviceId,
    DeviceProfile,
    LayerIdx,
    LayerProfile,
    NetworkProfile,
)
from radp.coordinator.failure_detector import FailureDetector, HeartbeatRecord
from radp.profiler.layer_profiler import merge_profiles

log = get_logger(__name__)

_GRPC_OPTIONS: list[tuple[str, Any]] = [
    ("grpc.max_send_message_length", 256 * 1024 * 1024),
    ("grpc.max_receive_message_length", 256 * 1024 * 1024),
]


class ProfileOrchestrator:
    def __init__(
        self,
        worker_addresses: dict[DeviceId, str],
        detector: FailureDetector,
        *,
        rpc_timeout_seconds: float = 600.0,
    ) -> None:
        if not worker_addresses:
            raise ValueError("worker_addresses must be non-empty")
        self.worker_addresses = dict(worker_addresses)
        self.detector = detector
        self.rpc_timeout_seconds = rpc_timeout_seconds

    # ------------------------------------------------------------------
    # 1. Wait for workers to register via heartbeat
    # ------------------------------------------------------------------
    def wait_for_workers(
        self,
        *,
        timeout_seconds: float = 60.0,
        poll_interval_seconds: float = 0.5,
    ) -> dict[DeviceId, HeartbeatRecord]:
        """Block until every expected worker has heartbeated at least once.

        Raises TimeoutError if not all workers register within the deadline.
        """
        expected = set(self.worker_addresses.keys())
        deadline = time.monotonic() + timeout_seconds
        last_missing: set[DeviceId] = set(expected)
        while time.monotonic() < deadline:
            records = self.detector.snapshot_records()
            present = set(records.keys()) & expected
            missing = expected - present
            if not missing:
                log.info(
                    "all %d workers heartbeated: %s",
                    len(expected),
                    sorted(str(d) for d in expected),
                )
                return {dev: records[dev] for dev in expected}
            if missing != last_missing:
                log.info(
                    "waiting for workers (%d/%d): missing %s",
                    len(present),
                    len(expected),
                    sorted(str(d) for d in missing),
                )
                last_missing = missing
            time.sleep(poll_interval_seconds)
        raise TimeoutError(
            f"Workers did not all register within {timeout_seconds}s; "
            f"missing={sorted(str(d) for d in last_missing)}"
        )

    # ------------------------------------------------------------------
    # 2. Per-device layer profiling
    # ------------------------------------------------------------------
    def collect_layer_profiles(
        self,
        model_id: str,
        *,
        warmup: int = 0,
        repeats: int = 0,
        seq_length: int = 0,
    ) -> list[LayerProfile]:
        """ProfileLayers in parallel across all workers; merge into one list.

        Each worker reports `list[LayerProfile]` whose `compute_time` maps to
        its own device_id. `merge_profiles` collapses N such lists into a
        single list where every LayerProfile.compute_time has N entries.

        Per-worker failures bubble up: if any worker's ProfileLayers fails,
        this raises RuntimeError with the offending device_id in the message.
        """
        log.info(
            "collecting layer profiles for %s across %d workers",
            model_id, len(self.worker_addresses),
        )
        per_device: dict[DeviceId, list[LayerProfile]] = {}
        with ThreadPoolExecutor(max_workers=len(self.worker_addresses)) as pool:
            futures = {
                pool.submit(
                    self._profile_one, dev_id, address, model_id,
                    warmup, repeats, seq_length,
                ): dev_id
                for dev_id, address in self.worker_addresses.items()
            }
            for fut in as_completed(futures):
                dev_id = futures[fut]
                per_device[dev_id] = fut.result()
        # Preserve worker_addresses order so the merged list is reproducible.
        ordered = [per_device[d] for d in self.worker_addresses]
        merged = merge_profiles(*ordered)
        log.info(
            "layer profiles merged: %d layers, %d devices",
            len(merged), len(per_device),
        )
        return merged

    def _profile_one(
        self,
        device_id: DeviceId,
        address: str,
        model_id: str,
        warmup: int,
        repeats: int,
        seq_length: int,
    ) -> list[LayerProfile]:
        channel = grpc.insecure_channel(address, options=_GRPC_OPTIONS)
        try:
            stub = radp_pb2_grpc.WorkerServiceStub(channel)
            resp = stub.ProfileLayers(
                radp_pb2.ProfileLayersRequest(
                    model_id=model_id,
                    warmup=warmup,
                    repeats=repeats,
                    seq_length=seq_length,
                ),
                timeout=self.rpc_timeout_seconds,
            )
        finally:
            channel.close()
        if not resp.ok:
            raise RuntimeError(
                f"ProfileLayers failed on {device_id} ({address}): {resp.error}"
            )
        raw = json.loads(resp.serialized_profiles.decode("utf-8"))
        # Rehydrate as LayerProfile; the worker stamped its own device_id into
        # compute_time, so we don't need to inject anything here.
        return [
            LayerProfile(
                layer_idx=LayerIdx(int(entry["layer_idx"])),
                memory_bytes=int(entry["memory_bytes"]),
                compute_time={
                    DeviceId(k): float(v) for k, v in entry["compute_time"].items()
                },
            )
            for entry in raw
        ]

    # ------------------------------------------------------------------
    # 3. Full-mesh network profiling via worker→worker MeasurePeer
    # ------------------------------------------------------------------
    def collect_network_profile(
        self,
        *,
        payload_bytes: int = 1_048_576,
        rounds: int = 10,
    ) -> NetworkProfile:
        """For every (src, dst) pair (src ≠ dst), tell src to measure its
        link to dst via MeasurePeer. Returns a NetworkProfile populated for
        every directed pair the orchestrator can reach.

        Pairs whose MeasurePeer returns ok=False are *omitted* from the
        result (scheduler will treat them as ∞ comm time → infeasible). They
        are logged as warnings so the operator can investigate.
        """
        pairs: list[tuple[DeviceId, DeviceId]] = [
            (src, dst)
            for src in self.worker_addresses
            for dst in self.worker_addresses
            if src != dst
        ]
        log.info(
            "measuring network: %d ordered pairs (payload=%d, rounds=%d)",
            len(pairs), payload_bytes, rounds,
        )
        bandwidth: dict[tuple[DeviceId, DeviceId], float] = {}
        latency: dict[tuple[DeviceId, DeviceId], float] = {}
        # Limit concurrency a bit so we don't hammer a single worker with N-1
        # outbound MeasurePeer calls from N-1 different sources at once.
        with ThreadPoolExecutor(max_workers=max(len(pairs), 1)) as pool:
            futures = {
                pool.submit(
                    self._measure_pair, src, dst, payload_bytes, rounds
                ): (src, dst)
                for src, dst in pairs
            }
            for fut in as_completed(futures):
                src, dst = futures[fut]
                bw, lat, ok, err = fut.result()
                if not ok:
                    log.warning(
                        "MeasurePeer %s -> %s failed: %s", src, dst, err
                    )
                    continue
                bandwidth[(src, dst)] = bw
                latency[(src, dst)] = lat
        log.info(
            "network profile built: %d/%d pairs successful",
            len(bandwidth), len(pairs),
        )
        return NetworkProfile(bandwidth=bandwidth, latency=latency)

    def _measure_pair(
        self,
        src: DeviceId,
        dst: DeviceId,
        payload_bytes: int,
        rounds: int,
    ) -> tuple[float, float, bool, str]:
        src_addr = self.worker_addresses[src]
        dst_addr = self.worker_addresses[dst]
        channel = grpc.insecure_channel(src_addr, options=_GRPC_OPTIONS)
        try:
            stub = radp_pb2_grpc.WorkerServiceStub(channel)
            resp = stub.MeasurePeer(
                radp_pb2.MeasurePeerRequest(
                    peer_address=dst_addr,
                    payload_bytes=payload_bytes,
                    rounds=rounds,
                ),
                timeout=self.rpc_timeout_seconds,
            )
        except grpc.RpcError as e:
            return 0.0, 0.0, False, f"RpcError: {e}"
        finally:
            channel.close()
        return (
            float(resp.bandwidth_bps),
            float(resp.latency_seconds),
            bool(resp.ok),
            str(resp.error),
        )

    # ------------------------------------------------------------------
    # 4. Synthesize DeviceProfile objects from heartbeat + layer timings
    # ------------------------------------------------------------------
    @staticmethod
    def build_device_profiles(
        records: dict[DeviceId, HeartbeatRecord],
        layer_profiles: list[LayerProfile],
    ) -> list[DeviceProfile]:
        """compute_throughput is normalized to the fastest device (=1.0).

        Faster devices report shorter compute_time per layer; the throughput
        ratio is (fastest_total_time / this_device_total_time). Sums use
        every layer where this device has a measurement; layers absent from
        a device's map are skipped for that device (but typically all devices
        have all layers since they all profiled the same model).
        """
        per_device_total: dict[DeviceId, float] = {}
        for lp in layer_profiles:
            for dev, t in lp.compute_time.items():
                per_device_total[dev] = per_device_total.get(dev, 0.0) + float(t)
        if not per_device_total:
            raise ValueError("layer_profiles contained no compute_time entries")
        fastest = min(per_device_total.values())
        if fastest <= 0:
            raise ValueError(
                f"fastest device total time is non-positive: {fastest}"
            )
        profiles: list[DeviceProfile] = []
        for dev_id, hb in records.items():
            total = per_device_total.get(dev_id)
            throughput = float(fastest / total) if total and total > 0 else 0.0
            profiles.append(
                DeviceProfile(
                    id=dev_id,
                    total_memory_bytes=int(hb.total_memory_bytes),
                    compute_throughput=throughput,
                )
            )
        return profiles
