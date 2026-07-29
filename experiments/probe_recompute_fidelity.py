"""LIVE cross-tier recompute-fidelity probe (Task 4).

Recomputes a fixed OPT-350M stage (layers 16-17, non-head) on two real
device tiers from the SAME input bytes and bit-compares the resulting KV
via ``experiments.fidelity_compare`` (imported, not reimplemented). Answers:
does recompute-based recovery (surgical/full_replay/reactive) actually
reproduce the same KV across a CUDA tier and a CPU tier, or does it
silently diverge?

Two modes:
  --board       run the forward on THIS board, dump KV, print one JSON line
                with its sha256 (called remotely via ansible; never run
                this by hand on the controller).
  --controller  (default) generate the fixed input once, ship + run on
                every tier via ansible, fetch the KV dumps back, compare,
                write experiments/results/b1_ft_fidelity.json.

Board runtime (device/dtype) is NOT ambient in an ansible shell — those
vars are systemd-unit-scoped for radp-worker (see
roles/radp-worker/templates/radp-worker.service.j2), not present in a
plain SSH shell. controller_main passes them explicitly per host (see
_BOARD_ENV) rather than relying on `os.environ` already having them set;
board_main still reads from env so the invocation is the single source of
truth for what ran.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

MODEL_ID = "facebook/opt-350m"
STAGE = (16, 17)
SEQ, HIDDEN_DIM, SEED = 8, 1024, 0
INPUT_FILE = "/tmp/radp_probe_input.pt"   # shipped identical to every board
DUMP_FILE = "/tmp/radp_probe_kv.bin"

TIERS = {"cuda": "on-1", "cpu": "on-3", "agx": "ao-1"}

# ponytail: hardcoded per-host runtime (ansible doesn't inherit the
# radp-worker systemd unit's Environment=), sourced from
# deploy/inventory.ini (model_torch_device) + group_vars/all.yml
# (model_dtype: float16 default). Upgrade to parsing inventory.ini if
# more tiers get added.
_BOARD_ENV = {
    "on-1": {"RADP_TORCH_DEVICE": "cuda", "RADP_DTYPE": "float16"},
    "on-3": {"RADP_TORCH_DEVICE": "cpu", "RADP_DTYPE": "float16"},
    "ao-1": {"RADP_TORCH_DEVICE": "cuda", "RADP_DTYPE": "float16"},
}
BOARD_RADP_DIR = "/home/isp/radp"  # on-1, on-3 (and ao-1) all run RADP from here

_INVENTORY = str(Path(__file__).resolve().parent.parent / "deploy" / "inventory.ini")


def board_main() -> None:
    import torch
    from radp.worker.stage_runner import StageRunner
    from radp.common.tensor_io import encode
    from radp.common.types import RequestId, LayerIdx, DeviceId
    from experiments.fidelity_compare import kv_sha256

    device = os.environ.get("RADP_TORCH_DEVICE", "cpu")
    dtype = os.environ.get("RADP_DTYPE", "float16")
    dev_id = os.environ.get("RADP_DEVICE_ID", "probe")

    # weights_only=True (as radp.common.tensor_io.decode already does) avoids
    # torch's FutureWarning on stderr — ansible's default callback glues a
    # task's stderr onto the end of its stdout with no separating newline,
    # which otherwise corrupts the trailing JSON line (confirmed live).
    payload = torch.load(INPUT_FILE, weights_only=True)   # {"hidden_states","attention_mask"} — identical bytes on every board
    runner = StageRunner(DeviceId(dev_id), torch_device=device, dtype=dtype)
    runner.load_primary(MODEL_ID, LayerIdx(STAGE[0]), LayerIdx(STAGE[1]))
    blob = encode(payload)
    runner.run(RequestId(1), blob, start=LayerIdx(STAGE[0]), end=LayerIdx(STAGE[1]), is_prefill=True)
    kv = runner.export_kv(RequestId(1), start=LayerIdx(STAGE[0]), end=LayerIdx(STAGE[1]))
    Path(DUMP_FILE).write_bytes(kv)
    print(json.dumps({"device": device, "dtype": dtype, "sha256": kv_sha256(kv), "n_bytes": len(kv)}))


def _ansible(host: str, *args: str) -> str:
    """Run `ansible <host> -i inventory.ini <args>` and return stdout (raises on
    non-zero). Mirrors experiments/b1_ft_fleet.py's _ansible invocation style."""
    cp = subprocess.run(
        ["ansible", host, "-i", _INVENTORY, *args],
        capture_output=True, text=True, timeout=300, check=True,
    )
    return cp.stdout


def _last_json_line(text: str) -> str:
    """The board prints one flat JSON object (no nested braces); ansible wraps
    it in banners and, confirmed live, sometimes glues a task's stderr
    directly onto the end of stdout with no separating newline (e.g. a torch
    warning). Scan lines in reverse and pull out a `{...}` substring — not
    just full-line match — so trailing glued text doesn't break parsing."""
    for line in reversed(text.splitlines()):
        m = re.search(r"\{[^{}]*\}", line)
        if m:
            try:
                json.loads(m.group(0))
                return m.group(0)
            except json.JSONDecodeError:
                continue
    raise ValueError(f"no JSON line in ansible output:\n{text}")


def _ship_probe_code(host: str) -> None:
    """The board's /home/isp/radp checkout predates this probe — ship this
    file + its fidelity_compare.py dependency there before running --board.
    Without this, `python -m experiments.probe_recompute_fidelity --board`
    on the board 404s on import (ModuleNotFoundError)."""
    src_dir = Path(__file__).resolve().parent
    for fname in ("probe_recompute_fidelity.py", "fidelity_compare.py"):
        _ansible(host, "-m", "copy", "-a",
                 f"src={src_dir / fname} dest={BOARD_RADP_DIR}/experiments/{fname}")


def controller_main(tier_hosts: dict[str, str]) -> None:
    import torch
    from transformers.modeling_attn_mask_utils import _prepare_4d_causal_attention_mask
    from experiments._harness import RESULTS_DIR
    from experiments.fidelity_compare import compare_kv
    import numpy as np

    # 1. generate the fixed input ONCE on CPU, save, ship identical bytes to each board.
    # StageRunner.run() (layers 16-17, a non-head stage) expects the SAME
    # already-4D causal attention mask the real coordinator bakes once at the
    # head of the pipeline (radp/coordinator/gateway.py _prefill:
    # `_prepare_4d_causal_attention_mask(attention_mask_2d, input_ids.shape,
    # hidden, past_key_values_length=0)`) and then carries through every
    # stage unchanged. A raw 2D mask of ones (as if this stage embedded its
    # own input) makes OPTAttention index a 2D tensor as if it were 4D and
    # crashes with "too many indices for tensor of dimension 2" — confirmed
    # live on on-1 during the standalone StageRunner smoke test.
    torch.manual_seed(SEED)
    hidden_states = torch.randn(1, SEQ, HIDDEN_DIM, dtype=torch.float16)
    attention_mask_2d = torch.ones(1, SEQ, dtype=torch.long)
    attention_mask_4d = _prepare_4d_causal_attention_mask(
        attention_mask_2d, (1, SEQ), hidden_states, past_key_values_length=0
    )
    payload = {"hidden_states": hidden_states, "attention_mask": attention_mask_4d}
    torch.save(payload, INPUT_FILE)

    results = {}   # tier -> {sha256, device, dtype, dump_path}
    for tier, host in tier_hosts.items():
        _ship_probe_code(host)
        _ansible(host, "-m", "copy", "-a", f"src={INPUT_FILE} dest={INPUT_FILE}")
        env_prefix = " ".join(f"{k}={v}" for k, v in _BOARD_ENV.get(host, {}).items())
        cmd = f"cd {BOARD_RADP_DIR} && {env_prefix} .venv/bin/python -m experiments.probe_recompute_fidelity --board"
        out = _ansible(host, "-m", "shell", "-a", cmd)
        meta = json.loads(_last_json_line(out))
        local_dump = f"/tmp/radp_probe_kv_{tier}.bin"
        _ansible(host, "-m", "fetch", "-a", f"src={DUMP_FILE} dest={local_dump} flat=yes")
        meta["dump_path"] = local_dump
        results[tier] = meta

    # 2. compare each tier pair
    pairs = []
    tiers = list(results)
    for i in range(len(tiers)):
        for j in range(i + 1, len(tiers)):
            ta, tb = tiers[i], tiers[j]
            a = Path(results[ta]["dump_path"]).read_bytes()
            b = Path(results[tb]["dump_path"]).read_bytes()
            cmp = compare_kv(a, b, np.float16)
            pairs.append({"tier_a": ta, "tier_b": tb,
                          "hash_equal": results[ta]["sha256"] == results[tb]["sha256"], **cmp})

    diverges = any(not p["hash_equal"] for p in pairs)
    verdict = {
        "parity": "bit-exact (by construction)",
        "replicate": "bit-exact (by construction)",
        "surgical": "tier-dependent recompute" if diverges else "bit-exact (recompute, measured)",
        "full_replay": "tier-dependent recompute" if diverges else "bit-exact (recompute, measured)",
        "reactive": "tier-dependent recompute" if diverges else "bit-exact (recompute, measured)",
    }
    out = {"model": MODEL_ID, "stage": list(STAGE), "seq": SEQ,
           "tiers": {t: {k: results[t][k] for k in ("device", "dtype", "sha256")} for t in results},
           "pairs": pairs, "recompute_diverges": diverges, "family_verdict": verdict}
    (RESULTS_DIR / "b1_ft_fidelity.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({"recompute_diverges": diverges, "pairs": pairs}, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--board", action="store_true", help="run the forward on THIS board")
    p.add_argument("--controller", action="store_true", help="fan out to tiers + compare (default)")
    args = p.parse_args()
    if args.board:
        board_main()
    else:
        controller_main({"cuda": "on-1", "cpu": "on-3"})  # add "agx": "ao-1" if the first pair diverges


if __name__ == "__main__":
    main()
