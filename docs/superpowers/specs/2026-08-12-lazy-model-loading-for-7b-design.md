# Lazy model loading for 7B-class models — design

**Status:** approved design, ready for an implementation plan
**Date:** 2026-08-12
**Motivation:** D2.9 established that OPT-350M sits far outside the ψ–R coupling
regime (largest stage 576 MB against ~5 GB of peer headroom). A 7B model puts a
single layer at ~420 MB, which is the scale at which recovery-hosting capacity
becomes scarce naturally rather than by capping reported free memory. Serving a
7B model on this fleet is the prerequisite for that measurement.

---

## 1. What is actually blocking 7B

The blocker recorded in `experiments/REPORT.md` §12.1 — "loader가 sharded 아니면
도움 안 됨" — is no longer accurate. Sharded, lazy loading already exists and
works:

- `model_utils._find_weights_location` resolves four checkpoint layouts:
  `safetensors`, `bin`, `safetensors_sharded`, `bin_sharded`.
- `model_utils._WeightReader` opens shards on demand and downloads them on
  demand (`_get_shard_safetensors` calls `hf_hub_download` per shard).
- `model_utils.load_stage_blocks` constructs only the blocks for `[start, end]`
  and fills them tensor by tensor.
- `stage_runner.load_primary` and `load_backup` already use that path.

What blocks 7B is that **three call sites still materialize the whole model**
through `load_model` (= `AutoModelForCausalLM.from_pretrained`):

| Site | Why it loads the model | Consequence at 7B |
|---|---|---|
| `radp/coordinator/gateway.py:129` | token embedding + tail modules | coordinator loads 13 GB |
| `radp/worker/stage_runner.py:135` (`load_head`) | `final_layer_norm`, `project_out`, `lm_head` | tail worker loads 13 GB |
| `radp/profiler/layer_profiler.py:56` | hooks every block for one timed forward | profiling loads 13 GB |

Each of these needs a few hundred megabytes of modules and pulls thirteen
gigabytes to get them.

A second, independent constraint: **`bin` checkpoints cannot be loaded lazily.**
`_get_shard_bin` calls `torch.load` on a whole shard, so resident memory tracks
shard size. `safetensors` shards are `mmap`-ed by `safe_open` and materialize
per tensor. This decides the target model.

## 2. Target model

**`NousResearch/Llama-2-7b-hf`** — safetensors, 2 shards, not gated.

Rejected alternatives:
- `facebook/opt-6.7b` — **bin only**, no safetensors. `torch.load` on a ~10 GB
  shard defeats the whole exercise. Same for `facebook/opt-2.7b` (single bin).
- `meta-llama/Llama-2-7b-hf` — same weights, `gated: manual`. Use it later if we
  want the canonical repo id in the paper; the Nous mirror unblocks work now.
- `mistralai/Mistral-7B-v0.1` — viable, but sliding-window attention is one more
  variable in a first live run of a non-OPT architecture.

`architectures.py` already carries the LLaMA/Mistral weight prefix
(`model.layers.{i}.`) and a RoPE `make_aux`, but **no Llama model has ever run on
this fleet**. First live use is part of this work.

## 3. Design

### 3.1 Lazy head/embedding modules (mirrors `load_stage_blocks`)

Add to `radp/common/model_utils.py`:

```python
def load_head_modules(
    model_id: str, *, dtype: str = "float32", torch_device: str = "cpu",
) -> HeadModules: ...
```

`HeadModules` carries exactly the modules the architecture's `head()` and
`embed()` need — for OPT `embed_tokens`, `embed_positions`, `final_layer_norm`,
`project_in`/`project_out`, `lm_head`; for LLaMA `embed_tokens`, `norm`,
`lm_head`. Each is constructed from `AutoConfig` and populated from
`_WeightReader` by key, exactly as `load_stage_blocks` does for blocks.

Which modules a family needs, and under which weight keys, belongs in
`architectures.py` beside `weight_prefix` — that file is already the seam for
per-family layout differences. Add one method to the architecture protocol:

```python
def head_module_spec(self, config) -> list[HeadModuleSpec]: ...
```

where each `HeadModuleSpec` names the attribute, how to construct it from
config, and its weight-key prefix. `load_head_modules` walks that list. Adding a
family later means adding a spec, not a new loader.

Both `gateway.py:129` and `stage_runner.load_head` then call
`load_head_modules` instead of `load_model`, and keep the modules on the object
they already keep `handle` on.

**Tied embeddings:** LLaMA-2 does not tie `lm_head` to `embed_tokens`, but some
families do, and the checkpoint then has no separate `lm_head.weight` key.
`load_head_modules` must fall back to the embedding weight when the config says
`tie_word_embeddings` and the key is absent.

`load_model` stays where it is — the profiler's old path and any small-model
convenience use keep working, and nothing else has to change at once.

### 3.2 Block-wise profiler

`layer_profiler.profile_layers` currently loads the whole model, hooks all
blocks, and runs one timed forward. Replace with a per-layer loop:

```
for i in 1..L:
    blocks = load_stage_blocks(model_id, i, i, ...)
    hidden = synthetic [1, seq_length, hidden_size] tensor
    warmup, then repeat timed calls of arch.run_block(blocks[0], hidden, ...)
    record median; free blocks
```

A decoder block's real input *is* a hidden state — `stage_runner` already
invokes blocks exactly this way via `arch.run_block`, so the calling convention
and the `aux` (RoPE) construction are reused, not re-derived. `make_aux` takes
only `(config, dtype, device)`, so it needs no model.

Timing is unaffected in kind: transformer blocks are dense matmuls whose cost
depends on tensor shape, not tensor values. Peak memory drops from the whole
model to one block. Layers are also measured in isolation rather than under the
memory pressure of 31 co-resident siblings, which is closer to how a worker
actually holds a stage.

The output type (`list[LayerProfile]` with `memory_bytes` and `compute_time`) is
unchanged, so the scheduler and every downstream consumer are untouched.

Cost: L separate load/warmup/measure cycles instead of one forward. Slower, and
that is accepted.

### 3.3 CUDA-only profiling for 7B

`on-3`/`on-4` are CPU-forced with `compute_throughput` ≈ 0.011. A 7B block on
those may take seconds per call, making a full profile impractical. The profile
run for 7B covers the CUDA tier; CPU-only nodes keep their existing role as
backup hosts, which needs memory and bandwidth, not a layer profile.

If a CPU-node profile is wanted later it is a separate, longer run.

## 4. Prerequisites (ops, before any code lands)

A node that touches shard 1 needs ~10 GB free disk for it. Current state:

| Node | Free disk | HF cache | Action |
|---|---|---|---|
| ax-1 (coordinator) | **80 MB (100% full)** | 0 | see §4.1 — cannot simply be purged |
| on-1 | 9.4 GB | 14 GB | purge cache |
| on-6 | 12 GB | 31 GB | purge cache |
| on-2 | 22 GB | 12 GB | purge if needed |
| on-3 | 34 GB | 8.1 GB | ok |
| on-4 | 31 GB | 9.2 GB | ok |
| ao-2 | 33 GB | 1.3 GB | ok |
| ao-1 | — | — | **offline** (no ICMP, no SSH) |

Purging `~/.cache/huggingface` is authorised on the workers.

### 4.1 The coordinator has nowhere to put a shard — OPEN DECISION

ax-1's 27 GB breaks down as `/usr` 14 GB (JetPack, CUDA toolkit), `/home/isp`
9.6 GB, `/opt` 2.6 GB. None of it is HF cache, and `/usr` is not safely
reclaimable. Meanwhile the coordinator needs `embed_tokens` (shard 1) *and*
`norm` + `lm_head` (shard 2), so under the shard-download model it would pull
the entire 13 GB — onto a disk with 80 MB free.

Three ways out, to be decided before the plan is written:

- **(a) Free space on ax-1.** Purge `/home/isp/.cache` and whatever else in the
  9.6 GB home is disposable. Cheapest to try, uncertain yield, and unlikely to
  reach 13 GB.
- **(b) Move the coordinator to `ao-2`.** 33 GB free, 29 GB RAM, CUDA, JP6.1.
  Zero code — an inventory change and a redeploy. It makes `ao-2` both
  coordinator and worker, and it changes the fleet topology relative to every
  prior measurement. That matters less than usual right now because `ao-1` is
  already offline, so the topology has changed regardless.
- **(c) Pre-extract a head bundle.** Build a ~600 MB safetensors file offline
  containing only the embedding and tail tensors, and have the coordinator load
  that instead of touching shards. Keeps the coordinator on ax-1 and is the
  smallest thing to *ship*, but it adds a build step and a distribution artifact
  that §6 otherwise rules out.

**Recommendation: try (a), fall back to (b).** (b) is zero code and reversible,
and the fleet has already lost its original topology. (c) is worth building only
if the coordinator must stay on ax-1 for a reason we do not currently have.

`ao-1` being down is not a blocker for this work — the fleet still has one AGX
(`ao-2`, 29 GB, CUDA) plus the Nanos — but it does reduce the device pool for
the later coupling measurement.

## 5. Testing

- **Unit, no fleet:** `load_head_modules` on a small model (`facebook/opt-125m`)
  returns modules whose parameters are numerically identical to the same modules
  taken from a full `load_model`. This is the correctness gate for §3.1 and runs
  in CI-time.
- **Unit:** tied-embedding fallback — a config with `tie_word_embeddings=True`
  and no `lm_head.weight` key yields an `lm_head` sharing the embedding weight.
- **Unit:** block-wise profiler on `opt-125m` produces one `LayerProfile` per
  layer with positive `compute_time`, and its per-layer times stay within a
  reasonable factor of the current whole-model profiler on the same host.
- **Memory, on hardware:** load head modules for Llama-2-7B on a Nano and assert
  resident bytes stay under 1 GB. This is the claim the whole design rests on;
  it must be measured, not assumed.
- **Live:** profile Llama-2-7B on the CUDA tier, solve a placement, deploy, and
  generate correctly for at least one prompt.

## 6. Out of scope

- **The ψ–R coupling measurement itself.** That is the next piece of work and
  gets its own plan; this one ends when 7B serves.
- **Lazy loading of `bin` checkpoints.** Sidestepped by choosing a safetensors
  model. If a `bin`-only model becomes necessary, converting it to safetensors
  offline is cheaper than writing a streaming `torch.load`.
- **Quantization (INT4/INT8).** Orthogonal, and it would change the memory
  arithmetic the coupling experiment depends on.
- **Layer-granular re-sharding / a local weight distribution service.** Real
  edge value, but not needed to reach 7B: shard-level download plus mmap already
  bounds resident memory, and disk is solvable by purging caches.

## 7. Risks

| Risk | Handling |
|---|---|
| Llama-2 architecture has never run on this fleet | The unit test in §5 compares against `load_model` output, so a wrong weight key fails before deployment |
| Head-module key layouts differ across checkpoints of one family (already seen: OPT's `model.` prefix present in one snapshot, absent in another) | Reuse the prefix-detection `load_stage_blocks` already does |
| ax-1 disk is full and its 26 GB is unidentified | Prerequisite task; nothing is deleted before the cause is known |
| Coordinator has only ~7 GB memory available | Head modules are ~0.5 GB, well inside it — but §5's memory test covers the coordinator's module set too |
| Profiling 7B is slow enough to be impractical even on CUDA | Measure one layer first and extrapolate before committing to a full run |
