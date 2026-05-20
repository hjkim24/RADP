"""`radp-profile` CLI: run the layer profiler against a HF model + dump JSON."""

from __future__ import annotations

import argparse

from radp.common.logging_utils import configure_logging, get_logger
from radp.common.types import DeviceId
from radp.profiler.layer_profiler import profile_layers, save_profile

log = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="radp-profile")
    p.add_argument("--model-id", required=True, help="HF model identifier, e.g. facebook/opt-125m")
    p.add_argument("--device-id", required=True, help="Logical cluster device id this run profiles.")
    p.add_argument("--output", required=True, help="Output JSON path.")
    p.add_argument("--dtype", default="float32", choices=["float32", "float16", "bfloat16"])
    p.add_argument("--torch-device", default="cpu", help="torch device string (cpu, cuda, mps).")
    p.add_argument("--warmup", type=int, default=3)
    p.add_argument("--repeat", type=int, default=10)
    p.add_argument("--seq-length", type=int, default=64)
    p.add_argument("--kv-cache-max-seq", type=int, default=256)
    return p.parse_args()


def main() -> None:
    configure_logging()
    args = _parse_args()
    log.info(
        "profiling %s for device=%s on %s",
        args.model_id,
        args.device_id,
        args.torch_device,
    )
    profiles = profile_layers(
        model_id=args.model_id,
        device_id=DeviceId(args.device_id),
        dtype=args.dtype,
        torch_device=args.torch_device,
        warmup=args.warmup,
        repeat=args.repeat,
        seq_length=args.seq_length,
        kv_cache_max_seq=args.kv_cache_max_seq,
    )
    save_profile(profiles, args.output)
    log.info("wrote %d layer profiles to %s", len(profiles), args.output)


if __name__ == "__main__":
    main()
