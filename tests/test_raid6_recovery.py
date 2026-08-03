"""RAID-6 (k=2) double-failure KV recovery — two simultaneous non-head victims
reconstructed via P+Q GF solve, bit-exact, output matches the healthy reference.
Slow/model test — run under .venv-py39."""
import logging
import time

import numpy as np
import pytest
import torch

pytestmark = pytest.mark.slow

from experiments._harness import deploy, in_process_cluster_with_mirror, wire_chain
from radp.common.types import Stage as _Stage, LayerIdx, DeviceId, RequestId
from radp.coordinator.gateway import RequestGateway

MODEL = "facebook/opt-125m"


def _cfg5():
    """head + 4 non-head. Kill the two interior non-head stages (c, d): survivor
    b is UPSTREAM (one extra slot), survivor e is DOWNSTREAM (victim slot count).
    Ranks by start_layer: b=0, c=1, d=2, e=3."""
    ids = ["wa", "wb", "wc", "wd", "we"]
    placement = [
        _Stage(LayerIdx(1), LayerIdx(3), DeviceId("wa")),
        _Stage(LayerIdx(4), LayerIdx(6), DeviceId("wb")),
        _Stage(LayerIdx(7), LayerIdx(8), DeviceId("wc")),
        _Stage(LayerIdx(9), LayerIdx(10), DeviceId("wd")),
        _Stage(LayerIdx(11), LayerIdx(12), DeviceId("we")),
    ]
    recovery = {
        DeviceId("wa"): DeviceId("wb"), DeviceId("wb"): DeviceId("wc"),
        DeviceId("wc"): DeviceId("wa"), DeviceId("wd"): DeviceId("we"),
        DeviceId("we"): DeviceId("wa"),
    }
    return ids, placement, recovery


def _healthy_reference(prompt, n):
    ids, placement, recovery = _cfg5()
    with in_process_cluster_with_mirror(ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(placement=placement, recovery=recovery,
                            worker_addresses=addrs, model_id=MODEL)
        attach(gw)
        ref = list(gw.generate(prompt, max_tokens=n))
        gw.close()
    return ref


def _kv_layers(buf, n_layers, n_heads, head_dim, np_dtype):
    arr = np.frombuffer(buf, dtype=np_dtype)
    N = arr.size // (n_layers * 2 * n_heads * head_dim)
    arr = arr.reshape(n_layers, 2, n_heads, N, head_dim)
    return [(arr[li, 0], arr[li, 1]) for li in range(n_layers)]


def test_raid6_double_recovery_matches_reference(monkeypatch, caplog):
    monkeypatch.setenv("RADP_PARITY", "1")
    prompt, n, kill_at = "The quick brown fox", 12, 4
    reference = _healthy_reference(prompt, n)

    ids, placement, recovery = _cfg5()
    v1, v2 = "wc", "wd"                         # the two interior victims
    key1 = (7, 8)
    key2 = (9, 10)
    with in_process_cluster_with_mirror(ids) as (addrs, servers, attach):
        deploy(addrs, placement, model_id=MODEL, recovery=recovery)
        wire_chain(addrs, placement)
        gw = RequestGateway(placement=placement, recovery=recovery,
                            worker_addresses=addrs, model_id=MODEL,
                            recovery_mode="parity", parity_k=2)
        attach(gw)
        gw.generate(prompt, max_tokens=2)       # warmup before the fault

        surgical = {"n": 0}
        orig_surgical = gw._recover_surgical
        def spy(*a, **k):
            surgical["n"] += 1
            return orig_surgical(*a, **k)
        gw._recover_surgical = spy

        # Snapshot both victims' KV, capture installs on both backups.
        installed = {}
        for bdev, dkey in [("wa", key1), ("we", key2)]:
            r = servers[DeviceId(bdev)].runner
            orig = r.install_kv
            def make(orig, dkey):
                def spy_install(request_id, *, start, end, kv_bytes, num_positions):
                    if (int(start), int(end)) == dkey:
                        installed[dkey] = bytes(kv_bytes)
                    return orig(request_id, start=start, end=end,
                                kv_bytes=kv_bytes, num_positions=num_positions)
                return spy_install
            r.install_kv = make(orig, dkey)

        rid = gw.new_request_id()
        c_runner = servers[DeviceId(v1)].runner
        orig_run = c_runner.run
        victim_kv = {}
        state = {"calls": 0, "tripped": False}

        def flaky_run(request_id, activation_blob, *, start, end, is_prefill):
            if int(request_id) == int(rid) and (int(start), int(end)) == key1:
                state["calls"] += 1
                if state["calls"] - 1 == kill_at and not state["tripped"]:
                    state["tripped"] = True
                    for dev, dkey in [(v1, key1), (v2, key2)]:
                        r = servers[DeviceId(dev)].runner
                        victim_kv[dkey] = r.export_kv(
                            rid, start=LayerIdx(dkey[0]), end=LayerIdx(dkey[1]))
                    # wait for both mirrors + full P/Q, then mark both dead & crash
                    deadline = time.time() + 8.0
                    n_slots = c_runner.kv_seq_len(
                        rid, start=LayerIdx(key1[0]), end=LayerIdx(key1[1]))
                    while time.time() < deadline and not (
                        len(gw.cache.get_history(rid, key1)) > kill_at
                        and len(gw.cache.get_history(rid, key2)) > kill_at
                        and all(gw.parity_cache.is_complete(rid, s)
                                for s in range(n_slots))):
                        time.sleep(0.01)
                    gw.mark_dead(DeviceId(v1))
                    gw.mark_dead(DeviceId(v2))
                    raise RuntimeError("simulated double crash wc+wd")
            return orig_run(request_id, activation_blob, start=start, end=end,
                            is_prefill=is_prefill)

        c_runner.run = flaky_run

        with caplog.at_level(logging.WARNING, logger="radp.coordinator.gateway"):
            gw._prefill(rid, prompt)
            for _ in range(1, n):
                gw._decode_step(rid)
        recovered = list(gw._requests[rid].generated_token_ids)
        gw._evict_everywhere(rid)
        n_heads, head_dim, np_dtype, _ = gw._kv_dims()
        gw.close()

    assert state["tripped"], "double fault never injected"
    assert surgical["n"] == 0, "RAID-6 fell back to surgical:\n" + caplog.text
    for dkey in (key1, key2):
        assert dkey in installed, f"no reconstructed install for {dkey}"
        n_layers = dkey[1] - dkey[0] + 1
        rec = _kv_layers(installed[dkey], n_layers, n_heads, head_dim, np_dtype)
        vic = _kv_layers(victim_kv[dkey], n_layers, n_heads, head_dim, np_dtype)
        for li, ((rk, rv), (vk, vv)) in enumerate(zip(rec, vic)):
            assert torch.equal(torch.from_numpy(rk.copy()), torch.from_numpy(vk.copy()))
            assert torch.equal(torch.from_numpy(rv.copy()), torch.from_numpy(vv.copy()))
    assert recovered == reference, f"recovered={recovered}\nreference={reference}"


def test_double_dispatch_precedes_head_attribution():
    """The RAID-6 double dispatch must fire off self._dead BEFORE attribution.

    Regression for the live-fleet failure: when the two victims are the FIRST
    two non-head stages (adjacent to the head) and the gRPC trailer is lost,
    _attribute_chain_failure misblames the HEAD, which — if the dispatch sat
    after the head-check — trips the head-check and forces a surgical fallback
    even though both victims are non-head and recoverable. The dead set is
    authoritative, so dispatch must precede attribution.
    """
    gw = RequestGateway(
        placement=[_Stage(LayerIdx(1), LayerIdx(4), DeviceId("h")),
                   _Stage(LayerIdx(5), LayerIdx(6), DeviceId("a")),
                   _Stage(LayerIdx(7), LayerIdx(8), DeviceId("b")),
                   _Stage(LayerIdx(9), LayerIdx(12), DeviceId("c"))],
        recovery={DeviceId("h"): DeviceId("a"), DeviceId("a"): DeviceId("b"),
                  DeviceId("b"): DeviceId("c"), DeviceId("c"): DeviceId("a")},
        worker_addresses={DeviceId("h"): "localhost:0", DeviceId("a"): "localhost:0",
                          DeviceId("b"): "localhost:0", DeviceId("c"): "localhost:0"},
        model_id=MODEL, recovery_mode="parity", parity_k=2,
    )
    gw._dead = {DeviceId("a"), DeviceId("b")}   # two head-ADJACENT victims, pre-marked
    calls = {}

    def fake_double(rid, hs, err, pos, dead_nonhead):
        calls["double"] = sorted(int(s.start_layer) for s in dead_nonhead)
        return ("stage", "resp")

    gw._recover_parity_double = fake_double
    # Attribution would blame the HEAD (the lost-trailer live bug); if the fix
    # regresses, the head-check fires and we reach surgical instead of double.
    gw._attribute_chain_failure = lambda hs, err: gw.placement[0]
    gw._recover_surgical = lambda *a, **k: calls.setdefault("surgical", True)

    gw._recover_parity(RequestId(1), gw.placement[0], error=None, current_position=5)
    assert calls.get("double") == [5, 7], f"double not dispatched first: {calls}"
    assert "surgical" not in calls, "regressed: head-check tripped a surgical fallback"
