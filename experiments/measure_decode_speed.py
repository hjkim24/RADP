"""Quick microbench: prefill+decode latency with KV cache.

Spawns 2 in-process workers + a gateway and measures the time per generated
token, comparing prefill-time vs steady-state decode-time. Demonstrates the
KV-cache benefit: decode-step cost should be roughly constant (1 token per
worker call) regardless of context length.
"""

from __future__ import annotations

import time

from radp.common.logging_utils import configure_logging
from radp.common.protocol import WorkerClient
from radp.common.types import DeviceId, LayerIdx, Placement, Stage
from radp.coordinator.gateway import RequestGateway
from radp.worker.server import WorkerServer


def main() -> None:
    configure_logging()

    a = WorkerServer(DeviceId("worker-a"), "127.0.0.1:50091")
    b = WorkerServer(DeviceId("worker-b"), "127.0.0.1:50092")
    a.start()
    b.start()
    addrs = {
        DeviceId("worker-a"): "127.0.0.1:50091",
        DeviceId("worker-b"): "127.0.0.1:50092",
    }
    placement: Placement = [
        Stage(LayerIdx(1), LayerIdx(6), DeviceId("worker-a")),
        Stage(LayerIdx(7), LayerIdx(12), DeviceId("worker-b")),
    ]
    model_id = "facebook/opt-125m"

    try:
        for stage in placement:
            with WorkerClient(addrs[stage.device]) as client:
                client.load_stage(
                    device_id=stage.device,
                    start_layer=int(stage.start_layer),
                    end_layer=int(stage.end_layer),
                    model_id=model_id,
                )

        gateway = RequestGateway(
            placement=placement,
            recovery={},
            worker_addresses=addrs,
            model_id=model_id,
            torch_device="cpu",
            dtype="float32",
        )

        prompt = "The quick brown fox jumps over the lazy dog and then"
        n_tokens = 16

        # Warm pass to load HF tokenizer caches.
        gateway.generate(prompt, max_tokens=2)

        # Timed run.
        t0 = time.perf_counter()
        tokens = gateway.generate(prompt, max_tokens=n_tokens)
        elapsed = time.perf_counter() - t0
        print(f"generated {len(tokens)} tokens in {elapsed:.3f}s "
              f"({elapsed/len(tokens)*1000:.1f} ms/token)")
        print(f"  tokens: {tokens}")
        print(f"  text:   {gateway.handle.tokenizer.decode(tokens)!r}")

    finally:
        a.stop()
        b.stop()


if __name__ == "__main__":
    main()
