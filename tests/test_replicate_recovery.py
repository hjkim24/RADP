import numpy as np
from radp.coordinator.replica_cache import ReplicaCache
from radp.common.types import DeviceId, LayerIdx, RequestId

R = RequestId(1)
SK = (16, 17)  # a stage's (start_layer, end_layer)


def test_store_get_concatenates_in_position_order():
    c = ReplicaCache(num_stages=3)
    c.store(R, SK, 0, b"\x01\x02")
    c.store(R, SK, 1, b"\x03\x04")
    assert c.get_stage_kv(R, SK) == b"\x01\x02\x03\x04"


def test_store_is_deduped():
    c = ReplicaCache(num_stages=3)
    c.store(R, SK, 0, b"\x01\x02")
    c.store(R, SK, 0, b"\xff\xff")  # re-arriving (stage, pos) ignored
    assert c.get_stage_kv(R, SK) == b"\x01\x02"


def test_get_missing_stage_returns_none():
    c = ReplicaCache(num_stages=3)
    assert c.get_stage_kv(R, SK) is None


def test_is_complete_detects_hole():
    c = ReplicaCache(num_stages=3)
    c.store(R, SK, 0, b"\x01\x02")
    c.store(R, SK, 2, b"\x05\x06")  # position 1 missing
    assert c.is_complete(R, SK, up_to_position=2) is False
    assert c.is_complete(R, SK, up_to_position=0) is True


def test_evict_keeps_sole_request():
    c = ReplicaCache(num_stages=1, max_bytes=1)  # tiny cap
    c.store(R, SK, 0, b"\x01\x02\x03\x04")  # over cap, but sole request
    assert c.get_stage_kv(R, SK) == b"\x01\x02\x03\x04"  # not evicted


def test_evict_drops_oldest_when_second_arrives():
    c = ReplicaCache(num_stages=1, max_bytes=4)
    c.store(R, SK, 0, b"\x01\x02\x03\x04")
    c.store(RequestId(2), SK, 0, b"\x05\x06\x07\x08")  # pushes over cap
    assert c.get_stage_kv(R, SK) is None            # oldest evicted
    assert c.get_stage_kv(RequestId(2), SK) is not None


# --- Task 3: end-to-end full-KV-replication recovery ------------------------
#
# Mirrors tests/test_parity_recovery.py's end-to-end harness (MODEL, _cfg,
# _healthy_reference, _kv_layers, in_process_cluster_with_mirror, deploy,
# wire_chain) -- copied rather than cross-imported, matching this codebase's
# convention (every *_recovery.py test file owns its own copy; see
# test_surgical_recovery.py). SLOW (drives a real opt-125m model) -- only the
# two e2e tests below are marked; the pure-logic unit tests above stay fast.
import logging
import time

import pytest
import torch

from experiments._harness import deploy, in_process_cluster_with_mirror, wire_chain
from radp.common.types import Stage as _Stage
from radp.coordinator.gateway import RequestGateway

MODEL = "facebook/opt-125m"  # small, 12 layers, fast


def _cfg():
    """3 stages (head + 2 non-head); victim worker-b, backup worker-c --
    identical topology to test_parity_recovery.py's _cfg (first non-head
    victim, so this is an apples-to-apples baseline comparison point)."""
    ids = ["worker-a", "worker-b", "worker-c"]
    placement = [
        _Stage(LayerIdx(1), LayerIdx(4), DeviceId("worker-a")),
        _Stage(LayerIdx(5), LayerIdx(8), DeviceId("worker-b")),
        _Stage(LayerIdx(9), LayerIdx(12), DeviceId("worker-c")),
    ]
    recovery = {
        DeviceId("worker-a"): DeviceId("worker-b"),
        DeviceId("worker-b"): DeviceId("worker-c"),
        DeviceId("worker-c"): DeviceId("worker-a"),
    }
    return ids, placement, recovery


def _healthy_reference(prompt, n, cfg=_cfg):
    ids, placement, recovery = cfg()
    with in_process_cluster_with_mirror(ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL,
        )
        attach(gw)
        ref = list(gw.generate(prompt, max_tokens=n))
        gw.close()
    return ref


def _kv_layers(buf, n_layers, n_heads, head_dim, np_dtype):
    """Split layer-major export_kv bytes into per-layer (K, V) numpy arrays."""
    arr = np.frombuffer(buf, dtype=np_dtype)
    N = arr.size // (n_layers * 2 * n_heads * head_dim)
    arr = arr.reshape(n_layers, 2, n_heads, N, head_dim)
    return [(arr[li, 0], arr[li, 1]) for li in range(n_layers)]


def _assert_replicate_recovery(
    monkeypatch, caplog, *, cfg, victim_dev, backup_dev, force_incomplete=False
):
    """Drive one replicate recovery and assert:
    (a) the REPLICATE branch runs (falls back to surgical iff
        ``force_incomplete``);
    (b) when it does NOT fall back, the reconstructed backup KV is
        bit-identical to the victim's, per layer for K and V;
    (c) the recovered sequence equals the wired reference either way --
        correctness never depends on replicate.
    """
    from radp.coordinator.gateway import RequestGateway

    monkeypatch.setenv("RADP_PARITY", "1")  # worker ships KV columns (shared gate)
    prompt, n, kill_at = "The quick brown fox", 12, 4
    reference = _healthy_reference(prompt, n, cfg)

    ids, placement, recovery = cfg()
    victim_stage = next(s for s in placement if s.device == DeviceId(victim_dev))
    dead_key = (int(victim_stage.start_layer), int(victim_stage.end_layer))
    with in_process_cluster_with_mirror(ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(
            placement=placement, recovery=recovery,
            worker_addresses=addrs, model_id=MODEL,
            recovery_mode="replicate",
        )
        attach(gw)
        gw.generate(prompt, max_tokens=2)  # warmup BEFORE installing the fault

        # The REAL completeness check -- used to time the crash so the
        # stored columns are actually there regardless of force_incomplete.
        real_is_complete = gw.replica_cache.is_complete
        if force_incomplete:
            # Force the dead stage's stored columns to look incomplete to
            # the gateway, without disturbing what's actually stored --
            # exercises the replicate -> surgical fallback ladder.
            gw.replica_cache.is_complete = lambda *a, **k: False

        # Spy: only meaningful when NOT forcing incomplete.
        surgical_calls = {"n": 0}
        orig_surgical = gw._recover_surgical

        def spy_surgical(*a, **k):
            surgical_calls["n"] += 1
            return orig_surgical(*a, **k)

        gw._recover_surgical = spy_surgical

        # Capture the KV bytes the gateway installs onto the promoted backup
        # (only fires on the true replicate success path -- surgical rebuilds
        # via forward replay, not LoadKV).
        c_runner = servers[DeviceId(backup_dev)].runner
        orig_install = c_runner.install_kv
        installed: dict = {}

        def spy_install(request_id, *, start, end, kv_bytes, num_positions):
            if (int(start), int(end)) == dead_key:
                installed["bytes"] = bytes(kv_bytes)
                installed["N"] = int(num_positions)
            return orig_install(
                request_id, start=start, end=end,
                kv_bytes=kv_bytes, num_positions=num_positions,
            )

        c_runner.install_kv = spy_install

        rid = gw.new_request_id()
        b_runner = servers[DeviceId(victim_dev)].runner
        orig_run = b_runner.run
        state = {"calls": 0, "tripped": False}
        victim: dict = {}

        def flaky_run(request_id, activation_blob, *, start, end, is_prefill):
            if int(request_id) == int(rid) and (int(start), int(end)) == dead_key:
                state["calls"] += 1  # call k -> position k-1 (prefill = pos 0)
                if state["calls"] - 1 == kill_at and not state["tripped"]:
                    state["tripped"] = True
                    # Snapshot the victim's KV (slots 0..N-1) BEFORE crashing.
                    victim["N"] = b_runner.kv_seq_len(
                        rid, start=LayerIdx(dead_key[0]), end=LayerIdx(dead_key[1])
                    )
                    victim["bytes"] = b_runner.export_kv(
                        rid, start=LayerIdx(dead_key[0]), end=LayerIdx(dead_key[1])
                    )
                    # Wait until BOTH the mirrored input for pos kill_at AND
                    # the stored columns for slots 0..N-1 have really landed
                    # (using the real check, not the possibly-patched one),
                    # then crash.
                    deadline = time.time() + 8.0
                    while time.time() < deadline and not (
                        len(gw.cache.get_history(rid, dead_key)) > kill_at
                        and real_is_complete(
                            rid, dead_key, up_to_position=victim["N"] - 1
                        )
                    ):
                        time.sleep(0.01)
                    raise RuntimeError(
                        f"simulated {victim_dev} mid-stage crash after mirror+kv"
                    )
            return orig_run(
                request_id, activation_blob, start=start, end=end,
                is_prefill=is_prefill,
            )

        b_runner.run = flaky_run

        with caplog.at_level(logging.WARNING, logger="radp.coordinator.gateway"):
            gw._prefill(rid, prompt)
            for _ in range(1, n):
                gw._decode_step(rid)
        recovered = list(gw._requests[rid].generated_token_ids)
        gw._evict_everywhere(rid)
        n_heads, head_dim, np_dtype, _ = gw._kv_dims()
        gw.close()

    assert state["tripped"], "fault never injected — recovery path not exercised"

    if force_incomplete:
        # (a) incomplete stored columns -> fell back to surgical, never
        #     claimed a REPLICATE reconstruct.
        assert surgical_calls["n"] >= 1, (
            "forced-incomplete replicate cache did not fall back to "
            "surgical:\n" + caplog.text
        )
        assert "REPLICATE reconstruct" not in caplog.text, (
            "replicate reconstruct ran despite forced-incomplete stored "
            "columns:\n" + caplog.text
        )
    else:
        # (a) fault fired, REPLICATE branch ran, surgical fallback did NOT.
        assert "REPLICATE reconstruct" in caplog.text, (
            "replicate branch did not run — recovery took another path:\n"
            + caplog.text
        )
        assert surgical_calls["n"] == 0, (
            "replicate fell back to surgical instead of reconstructing:\n"
            + caplog.text
        )
        assert "bytes" in installed, "gateway never installed reconstructed KV"

        # (b) reconstructed KV bit-identical to victim's original (per
        # layer, K & V).
        assert installed["N"] == victim["N"], (
            f"slot count mismatch: installed={installed['N']} victim={victim['N']}"
        )
        n_layers = dead_key[1] - dead_key[0] + 1
        recon_layers = _kv_layers(
            installed["bytes"], n_layers, n_heads, head_dim, np_dtype
        )
        vic_layers = _kv_layers(victim["bytes"], n_layers, n_heads, head_dim, np_dtype)
        for li, ((rk, rv), (vk, vv)) in enumerate(zip(recon_layers, vic_layers)):
            assert torch.equal(
                torch.from_numpy(rk.copy()), torch.from_numpy(vk.copy())
            ), f"reconstructed K != victim K at layer {li}"
            assert torch.equal(
                torch.from_numpy(rv.copy()), torch.from_numpy(vv.copy())
            ), f"reconstructed V != victim V at layer {li}"

    # (c) recovered sequence == healthy wired reference either way --
    # correctness never depends on replicate.
    assert len(recovered) == n
    assert recovered == reference, f"recovered={recovered}\nreference={reference}"


@pytest.mark.slow
def test_replicate_recovery_matches_reference(monkeypatch, caplog):
    """FIRST non-head victim (worker-b, backup worker-c): stored columns are
    complete, so recovery reconstructs via replicate with zero forwards and
    never falls back to surgical."""
    _assert_replicate_recovery(
        monkeypatch, caplog, cfg=_cfg,
        victim_dev="worker-b", backup_dev="worker-c",
    )


@pytest.mark.slow
def test_replicate_falls_back_when_incomplete(monkeypatch, caplog):
    """If the dead stage's stored columns look incomplete to the gateway
    (ReplicaCache.is_complete forced False), recovery falls back to
    surgical; output still matches the reference -- correctness never
    depends on replicate."""
    _assert_replicate_recovery(
        monkeypatch, caplog, cfg=_cfg,
        victim_dev="worker-b", backup_dev="worker-c",
        force_incomplete=True,
    )
