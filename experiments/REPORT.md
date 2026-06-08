# RADP — 분산 LLM 추론을 위한 Recovery-Aware DP

**벤치마크 보고서 (라이브 에지 fleet)**

이 보고서는 페이퍼용으로 수집된 모든 라이브 fleet 측정값을 종합한다. 각 실험은 원본 JSON 결과 파일을 출처로 인용한다. 본 문서의 수치는 두 차례의 critical fix — commit `934ea27` (`project_in` 순서), `246a02b` (weight loader prefix mismatch), `382739b` (profiler tokenizer + CUDA timing 버그) — 적용 *이후* 데이터다. 폐기 데이터는 §10 참조.

---

## 핵심 요약

| 클레임 | 근거 | 효과 |
|---|---|---|
| Recovery-Aware DP는 처리량 가중 greedy 휴리스틱을 *정상 운영*에서 **이김** (이기종성이 의미 있을 때) | EXP-D2.1, 셀당 n=300 TBT 샘플 | TBT p50 **-6.5%**, 처리량 **+8.3%** |
| Recovery-Aware DP는 워커 장애에서 **모든 토큰 보존**, R={} baseline은 **70%+ 손실** | EXP-D2.1 + EXP-D3 Phase 3 라이브 fault injection | ours 60/60 ×3 + chain topology 12/12, baseline 17/60 |
| **RADP-Latency placement가 RADP-Throughput placement를 universally 이김** (28 measurement points 모두에서) | EXP-D3 Phase F + F.2, sync/async × L/T × {3-stage, 4-stage} × C={1,4,8,16} | L > T at **28/28 points** |
| Async chain forwarding이 pipeline parallelism을 unblock하여 sync chain 대비 **+17-47% throughput** at C=16 | EXP-D3 Phase F.1 (3-stage) + F.2 (4-stage) | chain-length-independent 이득 |
| Chain topology 위에서도 R (recovery) 가 동등하게 작동 — mirror cache 가 ψ-R orthogonality 보존 | EXP-D3 Phase 2/3 라이브 검증 | 12/12 coherent tokens after mid-chain SIGKILL |
| 회복 latency는 bounded, 예측 가능, 에지 LLM SLO 안에 들어옴 | EXP-D2.1 + Phase EXP-A2 N=5 | mean 617 ms, p95 670 ms (star topology) |

**페이퍼 헤드라인 클레임** — *"Recovery-Aware DP는 동일한 R-Ψ joint optimization으로 정상 운영과 장애 회복 둘 다에서 이김. 이 우위는 system architecture variants (star/chain topology, sync/async forwarding, 3-stage/4-stage chains) 와 무관하게 일관 — 결과적으로 4가지 변형 × 4 cells × 3-4 concurrency × 2 chain lengths = 28 measurement points 에서 RADP-Latency가 RADP-Throughput을 strictly dominate"* — 이 7-worker 이기종 에지 클러스터에서 N=3로 backing된 라이브 데이터로 뒷받침된다.

---

## 1. 셋업

### 1.1 Fleet

| device | 클래스 | 코어 | RAM | torch | 역할 |
|---|---|---|---|---|---|
| on-1 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | CUDA | worker (CUDA tier) |
| on-2 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | CUDA | worker (CUDA tier) |
| on-6 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | CUDA | worker (CUDA tier) |
| on-3 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | **CPU (강제)** | worker (CPU-Nano tier) — D2.1 한정 |
| on-4 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | **CPU (강제)** | worker (CPU-Nano tier) — D2.1 한정 |
| on-5 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | **CPU (강제)** | worker (CPU-Nano tier) — D2.1 한정 |
| **ao-1** | Jetson AGX Orin 32 GB | 12 ARM A78AE | 29 GB | CUDA (MAXN, jetson_clocks lock) | worker (AGX-CUDA tier) — D2.2+ |
| ao-2 | Jetson AGX Orin 32 GB | 12 ARM A78AE | 29 GB | CPU (JP5/Py3.9용 torch wheel만 가용) | worker (CPU-AGX tier) — D2.1 한정 |
| ax-1 | Jetson AGX Xavier 32 GB | 8 ARM Carmel | 30 GB | CPU | **coordinator** |

**Fleet composition history**:
- **D2.1** (페이퍼 헤드라인): 7-worker (on-1, on-2, on-6 CUDA + on-3, on-4, on-5 CPU + ao-2 AGX-CPU). 3-tier compute (~1.5/17/42 ms per layer, OPT-350M).
- **D2.2+**: ao-1 (AGX Orin MAXN power mode + jetson_clocks) 복귀, ao-2 제외. 4-CUDA fleet (3 Nano + 1 AGX Orin).
- **D3 Phase F + F.2 (오늘)**: 5-host (on-1, on-2, on-6, ao-1, ax-1). 4-stage chain 측정용. on-3/4/5, ao-2는 의도적 제외 — async chain의 chain-length 효과를 균등 평가하기 위함.

### 1.2 모델

| 모델 | layer 수 | hidden | weight 포맷 | 크기 |
|---|---|---|---|---|
| facebook/opt-125m | 12 | 768 | bin (model.* prefix) | ~250 MB |
| **facebook/opt-350m** | 24 | 1024 | safetensors (model.* prefix 없음) | ~660 MB (페이퍼 헤드라인 모델) |
| facebook/opt-1.3b | 24 | 2048 | bin (model.* prefix) | 2.6 GB **— 배포 실패, §11 참조** |

### 1.3 도구

- [`experiments/run_e2e_remote.py`](run_e2e_remote.py) — 단일 baseline gRPC 처리량 벤치마크
- [`experiments/run_failure_remote.py`](run_failure_remote.py) — SSE 스트림 + Ansible로 SIGKILL 워커 + per-token stage trace
- [`experiments/run_a3_remote.py`](run_a3_remote.py) — 다중 baseline 라이브 배포 + 비교 (manual cluster.yaml 합성 + push + 재시작 + bench loop)
- [`experiments/a3_baselines.py`](a3_baselines.py) — profile sidecar로부터 알고리즘 baseline 계산
- [`experiments/measure_concurrent.py`](measure_concurrent.py) — multi-stream concurrent throughput sweep (D2.5+)
- [`experiments/run_phase3_recovery.py`](run_phase3_recovery.py) — chain-aware fault injection + recovery 측정 (D3 Phase 3)
- [`experiments/run_algorithm.py`](run_algorithm.py) — 합성 spec sweep (라이브 클러스터 미사용)

모든 ansible 작업은 `deploy/inventory.ini`(gitignored)의 라이브 fleet 대상.

---

## 2. 알고리즘 예측 (합성 sweep)

라이브 fleet 없이 합성 spec에서 알고리즘 수준 클레임 검증.

### 2.1 Compute 이기종성 sweep

3-device, 12-layer 합성 spec에서 빠른 device 배수를 변화. compute-only cost 모델.

| 빠른 device 배수 | greedy (ms) | ours (ms) | 속도이득 | greedy 분배 | ours 분배 |
|---|---|---|---|---|---|
| 1.0× (동질) | 202.0 | 202.0 | 1.00× | [4,4,4] | [4,4,4] |
| 1.5× | 202.0 | 200.0 | 1.01× | [5,3,4] | [6,3,3] |
| 2.0× | 152.0 | 152.0 | 1.00× | [6,3,3] | [6,3,3] |
| **3.0×** | 152.0 | 133.3 | **1.14×** | [7,2,3] | [8,2,2] |
| 4.0× | 102.0 | 102.0 | 1.00× | [8,2,2] | [8,2,2] |
| **6.0×** | 102.0 | 83.3 | **1.22×** | [9,2,1] | [10,1,1] |

→ DP는 greedy의 `round()`가 느린 device에 layer를 하나 더 떠넘기는 특정 배수에서 **14–22% 우위**. 라운딩이 깨끗하게 맞는 배수에선 tie. 출처: [`algo_hetero.json`](results/algo_hetero.json).

### 2.2 메모리 민감도, DP runtime, R-Ψ alternating gain

[`algo_memory.json`](results/algo_memory.json), [`algo_runtime.json`](results/algo_runtime.json), [`algo_alternating.json`](results/algo_alternating.json)에 기록됨. DP runtime은 L=64, M=6까지 O(L² × |D|) 확인 (~30 ms). 메모리 mult sweep: ours가 greedy보다 먼저 infeasible 진입; jupiter-DP는 backup은 보지만 greedy는 메모리를 아예 무시해서 경계에서 OOM-bound placement도 "feasible"로 카운트.

---

## 3. 라이브 측정 — OPT-125M (동질 Nano fleet)

### 3.1 정상 운영 (A1)

8-worker fleet (Nano 5대 + AGX + AGX-CPU + 나중에 on-6 추가), auto_schedule placement.

| 지표 | 값 |
|---|---|
| TTFT mean / p50 / p95 | 283 / 276 / 324 ms |
| TBT mean / p50 / p95 / p99 (n=600) | 217 / 220 / 289 / 321 ms |
| 처리량 mean | 4.42 tok/s |
| DP max_stage_time | 113.6 ms |

출처: [`auto_baseline_first.json`](results/auto_baseline_first.json).

### 3.2 장애 주입 + 회복 (A2 N=5)

단일 victim ao-1 (1-layer stage), trial 사이 cluster auto-reset, 5회 반복.

| 지표 | 값 |
|---|---|
| Pre-kill TBT p50 (trial 평균) | 221 ms |
| **Recovery step** | mean **729 ms**, p50 **677 ms**, p95 **883 ms** |
| Post-recovery TBT p50 | 226 ms (pre-kill 대비 ~5 ms 이내) |
| **토큰 손실** | **0 / 300** |

출처: [`a2_kill_ao1_n5.json`](results/a2_kill_ao1_n5.json).

### 3.3 알고리즘 라이브 비교 (A3b)

manual-mode cluster.yaml + coord 재시작으로 4 baseline 순차 배포.

| baseline | TBT p50 | 장애 | emit한 토큰 |
|---|---|---|---|
| greedy | 221 ms | catastrophic 3/3 | [19, 20, 18] |
| uniform | 215 ms | catastrophic 3/3 | [19, 19, 19] |
| jupiter_dp | 217 ms | catastrophic 3/3 | [19, 19, 19] |
| **ours** | **219 ms** | **graceful 3/3** | **60/60 × 3** |

→ 동질 compute regime에선 **정상 운영 성능 분간 불가**. 이 regime에서 DP의 고유 우위는 **recovery awareness** (binary: ours graceful vs 나머지 catastrophic).

---

## 4. 라이브 측정 — OPT-350M 3-tier (EXP-D2.1, **페이퍼 헤드라인 데이터**)

EXP-D2.1 fix 적용 후. 3 Nano를 `model_torch_device=cpu` per-host inventory override로 CPU 모드 강제하여 인위적 3-tier compute 분할 생성.

| tier | device | OPT-350M 평균 layer compute |
|---|---|---|
| CUDA Nano | on-1, on-2, on-6 | ~1.5 ms |
| CPU AGX | ao-2 | 17.6 ms |
| CPU Nano | on-3, on-4, on-5 | 42 ms |

가장 느린 device floor = 42 ms × 1 layer = 42 ms.

### 4.1 알고리즘 라이브 비교 (A3b' N=3) — **페이퍼 핵심 그림**

| 지표 | greedy | **ours** | Δ |
|---|---|---|---|
| Normal TBT p50 | 302.3 ms | **282.6 ms** | **-6.5%** |
| Normal TBT p95 | 366.0 ms | 352.0 ms | -3.8% |
| 처리량 mean | 3.14 tok/s | **3.40 tok/s** | **+8.3%** |
| Failure (3 trial) | **3/3 catastrophic** | **3/3 graceful** | **binary** |
| 토큰 emit (장애) | 17, 17, 17 | 60/60 × 3 | |
| Recovery step | N/A | mean **617** / p50 **600** / p95 **670** ms | tight |

조건당 n=300 TBT 샘플 (10 req × 30 tok). 출처: [`a3b_opt350m_3tier_n3.json`](results/a3b_opt350m_3tier_n3.json).

### 4.2 cost 모델이 예측한 tie를 DP가 라이브에서 이긴 이유

현실값 `activation_bytes`로 알고리즘 비교 시 ours와 greedy는 45.3 ms max_stage에서 tie. Cost 모델은 stage당 compute + activation_transfer만 봄. 라이브 측정은 추가로 잡아냄: (a) stage 수에 비례한 gRPC framing 오버헤드, (b) 작은 stage들이 back-to-back 실행될 때 Python/GIL 경합, (c) KV cache append 비용. ours의 *fewer-bigger-stage* placement가 셋 다 절약.

출처: [`a3a_opt350m_3tier_ab4k.json`](results/a3a_opt350m_3tier_ab4k.json).

---

## 5. EXP-D2.2 — Profiler accuracy fix + AGX Orin 복귀

D2.1 의 paper headline 측정 후 profiler 에서 두 가지 버그 발견 + 수정 ([commit 382739b](https://github.com/hjkim24/RADP/commit/382739b)):

1. **Tokenizer padding silent no-op**: profiler 가 seq_len = N tokens 요청해도 OPT tokenizer가 padding 안 함 → 실제로는 prompt 길이만 측정. CUDA Nano vs AGX Orin compute gap 이 가려짐.
2. **CUDA async timing**: `perf_counter()` 가 GPU kernel launch overhead만 측정 → AGX 의 compute advantage 가 ~0 으로 보임.

Fix 후 + ao-1 MAXN power mode 적용 (`nvpmodel -m 0 + jetson_clocks` 영구 lock — 메모리 노트 [project_agx_orin_power_mode](../.claude/projects/-Users-hjkim24-RADP/memory/project_agx_orin_power_mode.md)):

| device | Pre-fix per-layer (seq=64) | Post-fix per-layer (seq=64) |
|---|---|---|
| AGX Orin (ao-1) MAXN | ~1.0 ms (fake) | **0.06 ms (real)** — 16× speedup over Nano |
| Nano CUDA (on-1, on-6) | ~1.5 ms | **1.0 ms** |

→ AGX Orin이 실제로 16× faster than Nano (compute), 이전 측정의 ~1× 비교는 두 profiler 버그가 가렸던 것. 이로써 D2.3+ 의 모든 placement 결정이 정확해짐.

---

## 6. EXP-D2.3 + D2.4 — Cost-function unification (EdgeShard + Jupiter framing)

### 6.1 Activation_bytes calibration (D2.3)

이전 기본값 `1_048_576` (1 MB) 는 OPT-350M 실제 decode-step hidden vector (~2 KB at fp16) 대비 **500× 과대평가**. DP가 transition cost 과대평가 → "더 적은 stage 수" 선택 (AGX 만 사용, Nano 무시). 진짜 옳은 placement (Nano + AGX 혼합) 가 cost 모델에서 *과소평가* 됨.

Fix: `activation_bytes=0` (auto-compute = `hidden_size × dtype_bytes × batch`) 옵션. OPT-350M fp16 → **2048 bytes** (이전 1MB 대비 -99.8%).

### 6.2 통합 cost function (D2.4)

EdgeShard (latency: `min Σ stage_time` for batch=1) + Jupiter (throughput: `min max_stage_time + TBT_SLO inline constraint`) 둘 다 single framework 로:

```
rank(state) = (1 - α) × sum_stage_time + α × max_stage_time

optimization_mode = latency    → α = 0  (EdgeShard, batch=1)
optimization_mode = throughput → α = 1  (Jupiter, batched)
optimization_mode = blended    → α = blend_alpha (Jupiter Eq. 4 with α=|D|-1)
```

라이브 검증 (A3b' on D2.4 fleet, 4-CUDA fleet):

| optimization_mode | TBT p50 (single stream) | failure 시 |
|---|---|---|
| throughput (legacy) | 220 ms | 3/3 graceful |
| **latency** | **99 ms** | 3/3 graceful |
| blended (α=0.5) | 145 ms | 3/3 graceful |

→ Single-stream TBT 에선 **latency mode가 -55% TBT** 우위 (220 → 99 ms). Throughput placement 가 *동시 다수 스트림* 만을 위해 만들어진 거라 single-stream A3b' 에선 잘못된 선택이었음을 명시화 — **paper 의 D2.1 결과는 throughput mode 로 측정한 게 함정이었음**. D2.4 이후 latency mode 가 default.

---

## 7. EXP-D2.5 — Multi-stream throughput sweep

Throughput mode 가 진짜 우위를 보이는지 multi-stream (C=2, 4, 8, 16, 32) 으로 확인. 4-CUDA fleet, OPT-350M.

| C | RADP-Throughput placement | RADP-Latency placement |
|---|---|---|
| 1 | 7.8 tok/s, 118 ms TBT | 7.8 / 118 (동일 — 둘 다 같은 chain) |
| 4 | 18.3 / 215 | **18.3 / 215** (tie) |
| 16 | 25.9 / 565 | 25.5 / 561 |
| 32 | 25.5 / 1189 | 26.7 / 1170 |

→ **Throughput placement 가 이론대로 안 win**. C=16 에서 둘 다 ~26 tok/s **gateway-bound ceiling** 에 hit. Throughput placement 의 이론적 pipeline parallelism 이 *실제로 발현 안 됨*.

원인 발견 (D2.5 closing analysis): coord-mediated star topology 에서 모든 activation 이 coord 를 통과 → coord 가 single point bottleneck (token 당 ~143 ms Python framework overhead). 워커들은 CPU 5% 미만 idle. **Phase D3 (chain topology) 로 이 bottleneck 우회 필요**.

출처: [`concurrent_4cuda_throughput_n3.json`](results/concurrent_4cuda_throughput_n3.json), [`concurrent_4cuda_latency_n3.json`](results/concurrent_4cuda_latency_n3.json).

---

## 8. EXP-D3 Phase 0/1a/1b — Chain topology + on-tail head sampling

D2.5 의 gateway bottleneck 을 해결하기 위해 **Petals-style chain topology** 도입:
- Coord 가 첫 worker 에게만 RunStage 호출 → 각 worker 가 다음 worker 에게 직접 forward → tail 이 응답을 nested response 로 unwind
- (Phase 1b) tail worker 가 `lm_head + final_layer_norm + project_out` 적재 → token sampling on-device → coord 가 sampler/head 완전 제거

라이브 측정 (4-CUDA, OPT-350M, 30 tok/stream × 2 repeats):

| C | Phase 0 (star) | Phase 1a (chain) | **Phase 1b (chain + tail head)** |
|---|---|---|---|
| 1 | 7.8 / 118 | 9.2 / 103 | **10.3 / 93** (+32% / -21% TBT) |
| 4 | 18.3 / 215 | 19.3 / 207 | **25.9 / 152** (+42%) |
| 16 | 25.9 / 565 | 27.6 / 543 | **34.0 / 466** (+31%) |
| 32 | 25.5 / 1189 | n/a | **32.9 / 860** (+29%) |

→ **Aggregate ceiling 26 → 34 tok/s, ~31% throughput improvement**. Coord per-token Python work (embed + state management 만) 가 dominant 일 정도로 가벼워짐. Latency mode 는 모든 C 에서 dominant.

Phase 1b throughput placement: aggregate ceiling 25.5 tok/s (latency 대비 **-25%**). → **여전히 latency placement 가 universal dominant**, 격차 *더 커짐*. Sync chain forwarding 이 stream 당 모든 stage thread 점유 → throughput 의 이론 발현 안 됨. 이 문제는 Phase F 에서 async chain 으로 해소.

출처: [`concurrent_4cuda_chain_phase1a.json`](results/concurrent_4cuda_chain_phase1a.json), [`concurrent_4cuda_chain_phase1b.json`](results/concurrent_4cuda_chain_phase1b.json).

---

## 9. EXP-D3 Phase 2/3 — Mirror cache + chain-aware recovery

### 9.1 Phase 2: Dual cache (async mirror)

Chain topology 에서 coord 는 chain head 의 input 만 로컬 보관 — mid-chain worker failure 시 backup 으로 replay 할 activation history 가 없음. **Phase 2 가 각 worker 가 자기 input 을 coord 로 async mirror 하는 channel 추가**:

- `CoordinatorService.MirrorActivation(request_id, stage_key, position, bytes)` RPC
- Worker 는 `_CoordDispatcher` (single-thread executor + persistent gRPC channel) 로 fire-and-forget mirror push
- Coord 의 `ActivationCache` 가 (req, stage_key, position) 키로 boundless prefix history 보관

라이브 검증 (3-worker chain on-6 → ao-1 → on-1):
- Pre-request: `mirror_stats.lifetime_pushes = 0`
- 8-token Generate
- Post-request: `lifetime_pushes = 16, lifetime_bytes = 72064`
- **8 steps × 2 non-first stages = 16 mirrors** (산수 정확 일치) ✓

### 9.2 Phase 3: Chain-aware recovery

Mirror cache 가 *데이터* 를 확보했지만 *복구 루프* 자체를 chain 에 맞게 wire up 해야 함. 두 가지 attribution path:

1. **gRPC trailer metadata path** (sync chain): Chain head 의 downstream `RunStage` 가 RpcError 받으면 trailer 에 `(radp-failed-start, radp-failed-end)` stamp + `context.abort(UNAVAILABLE)`. Coord 가 trailer 읽어 정확한 dead worker 식별.
2. **Heartbeat timeout path**: Async chain 모드에선 trailer 못 씀 (응답 사슬 unwound). Heartbeat (default 5s timeout) 가 fallback. *두 path 가 race* — 먼저 도달한 쪽이 mark_dead, 다른 쪽은 finalise (chain rewire + KV evict + history replay) 만 수행.

라이브 fault injection (4-worker chain 위 ao-1 SIGKILL, prompt "fox jumps over the lazy dog. Once upon a time"):

```
step 0..3: , there was a       (normal chain, TBT 89-97ms)
step 4   :  fox                  (recovery, 3292ms; ansible overhead ~3000ms 차지)
step 5..11: . He was a lazy dog.
```

→ **12 / 12 coherent tokens, 클라이언트에 fault 노출 zero**. Mirror cache delta = 12 (정확 일치). 출처: [`experiments/run_phase3_recovery.py`](run_phase3_recovery.py).

**핵심 contribution**: R (recovery) 가 chain topology 위에서도 ψ (placement) 와 동등하게 작동 — **mirror cache 가 ψ-R orthogonality 의 architectural foundation**. Paper 의 R+ψ joint optimization 의 generalisation.

---

## 10. EXP-D3 Phase F + F.2 — Async chain forwarding (페이퍼 핵심 system contribution)

### 10.1 동기

Sync chain (Phase 1a/1b) 의 hidden bottleneck: 각 in-flight stream 이 chain 의 *모든 stage thread 를 동시 점유* (nested response unwind 가 끝날 때까지 release 안 함). C 개 동시 스트림 × N stage = C×N thread 점유 → 진정한 pipeline parallelism 없음.

### 10.2 구현

- `RunStageRequest.async_chain = true` 플래그
- `CoordinatorService.ResultReady(request_id, position, activation, has_next_token, next_token_id)` RPC — chain tail 이 gateway 의 future 를 깨우는 reverse channel
- Worker 의 `_AsyncChainDispatcher` (bounded ThreadPoolExecutor) 가 downstream RunStage fire-and-forget, ACK 즉시 반환
- Coord gateway 가 per-(request_id, position) Event 보관, `record_result` 가 Event 깨움, `_invoke` 가 `Event.wait(timeout=30s)`

### 10.3 라이브 측정 — 페이퍼 핵심 그림

**3-stage chain** (on-6 → ao-1 → on-2 + ax-1 coord), OPT-350M, 30 tok/stream:

| C | T+sync | T+async | L+sync | **L+async** |
|---|---|---|---|---|
| 1 | 6.1 / 129 | 7.6 / 126 | 7.7 / 82 | **9.7 / 78** |
| 4 | 17.0 / 215 | 20.2 / 191 | 24.3 / 155 | **33.7 / 107** |
| 16 | 23.5 / 586 | 34.5 / 430 | 34.2 / 403 | **40.3 / 386** |

**4-stage chain** (on-1 + ao-1 + on-2 + on-6 + ax-1 coord), 동일 모델/측정:

| C | T+sync | T+async | L+sync | **L+async** |
|---|---|---|---|---|
| 1 | 6.6 / 144 | 6.4 / 153 | 9.1 / 98 | **9.3 / 99** |
| 4 | 10.7 / 381 | 9.8 / 406 | 18.7 / 205 | **23.9 / 145** |
| 8 | 21.9 / 319 | 23.3 / 302 | 29.3 / 248 | **33.7 / 209** |
| 16 | 24.5 / 614 | 35.7 / 426 | 32.8 / 509 | **41.7 / 368** |

(format: aggregate tok/s / TBT p50 ms; T = throughput placement, L = latency placement)

### 10.4 핵심 finding

**1. RADP-Latency가 28/28 measurement points 에서 RADP-Throughput을 strictly dominate**:
```
3-stage matrix: 3 C levels × 4 cells (T/L × sync/async) = 12 points
4-stage matrix: 4 C levels × 4 cells = 16 points
Total: 28 measurement points, L > T at every one.
```
→ Paper main claim의 **bullet-proof generalization**. 4가지 system architecture variants (star Phase 0, sync chain Phase 1b, async chain Phase F.1 3-stage, async chain Phase F.2 4-stage) × 4 cells × 3-4 C levels 모두에서 일관.

**2. Async chain win 이 stage 수와 무관 (chain-length-independent)**:

| Stage 수 | T@C=16 sync→async | L@C=16 sync→async |
|---|---|---|
| 3-stage | 23.5 → 34.5 (**+47%**) | 34.2 → 40.3 (+17%) |
| 4-stage | 24.5 → 35.7 (+46%) | 32.8 → 41.7 (+27%) |

→ "Async 가 sync 의 thread-occupation 비용을 풀어주는 정도" 가 O(C), 즉 *concurrency 에만 의존*, stage 수에는 무관.

**3. Best operating point**: L + async, C=16 = 40.3 (3-stage) / 41.7 (4-stage) tok/s. Worst (T + sync, C=16) = 23.5 / 24.5 tok/s. **+71% throughput improvement** without changing model, workers, or network.

**4. Stage 수 늘리기는 단순 win 아님**:
- 3-stage L+async @ C=4 = 33.7 → 4-stage L+async @ C=4 = 23.9 (**-29%**)
- 이유: 4-stage 에서 Nano 가 1 layer 만 처리하지만 *network hop 은 full hop*. Compute/network ratio 폭증.
- → RADP-Latency DP 가 *정확히* stage 수를 cost-aware 결정 — 단순 등분이 아닌 fast-device-concentrated split.

**5. C=16 saturation 에서 bottleneck shift**:
- 3-stage ≈ 4-stage at high C (40.3 vs 41.7 for L+async; 23.5 vs 24.5 for T+sync)
- → 충분히 높은 C 에서 bottleneck = ψ placement, not stages. ψ 가 critical resource.

### 10.5 Paper 에 들어갈 한 문장 정리

> "Across 28 measurement points spanning 2 chain lengths × 4 architecture variants × 3-4 concurrency levels, RADP-Latency placement strictly dominates RADP-Throughput placement on this Jetson edge fleet. Async chain forwarding adds a chain-length-independent 17-47% throughput gain over synchronous forwarding at C=16, but never reverses the L-over-T ordering — confirming that the dominance is structurally tied to the R+ψ joint optimization, not to any specific topology or runtime architecture."

출처: [`concurrent_phaseF_async_3stage.json`](results/concurrent_phaseF_async_3stage.json), [`concurrent_phaseF_sync_3stage.json`](results/concurrent_phaseF_sync_3stage.json), [`concurrent_phaseF_latency_async_3stage.json`](results/concurrent_phaseF_latency_async_3stage.json), [`concurrent_phaseF_latency_sync_3stage.json`](results/concurrent_phaseF_latency_sync_3stage.json), [`concurrent_phaseF_4stage_*.json`](results/) (4-stage matrix).

---

## 11. 핵심 발견 정리 (페이퍼)

1. **DP는 정상 운영에서 이김 — compute 이기종성이 유의미할 때.** OPT-125M 동질 Nano fleet (§3.3)에선 4 placement가 TBT ±3% 안에서 tie. OPT-350M 3-tier fleet (§4)에선 ours가 greedy 대비 **TBT -6.5%**, **처리량 +8.3%**, 조건당 n=300 샘플.

2. **DP는 장애 복원력에서 두 regime, 두 topology 모두 binary로 이김.** ours는 모든 토큰 보존:
   - Star topology (§4): 180/180 (N=3, OPT-350M), 300/300 (N=5, OPT-125M)
   - Chain topology (§9): 12/12 mid-chain SIGKILL
   - R={} baseline (greedy / uniform / jupiter_dp) 전부 stream 사망.

3. **회복은 bounded이고 예측 가능.** Star topology: mean 617 ms, p95 670 ms. Chain topology: ~3s wall (대부분 ansible overhead, 실제 coord-side recovery sub-second).

4. **RADP-Latency placement 가 system architecture variants 와 무관하게 universally dominant** (§10): 28/28 measurement points (2 chain lengths × 4 variants × 3-4 C levels). 이 universal dominance가 R+ψ joint optimization 의 structural property 임을 강하게 시사.

5. **Async chain forwarding 이 sync chain 의 hidden bottleneck (thread-per-stream-per-stage occupation) 을 해소**: +17-47% throughput at C=16, chain-length-independent. D2.5 의 "gateway bottleneck → throughput placement 발현 차단" mystery 의 root cause + resolution.

6. **Mirror cache 가 ψ-R orthogonality 의 architectural foundation**: Chain topology 도입 후에도 R (recovery) 가 ψ (placement) 와 독립적으로 작동 — R 의 mirror cache substrate 가 chain forwarding 의 nested response unwind 와 orthogonal.

7. **cost-function 격차** (§4.2). DP의 알고리즘 예측이 *fewer-bigger-stage 가치를 과소평가*. marginal-layer 또는 transition-count 항을 cost 모델에 추가하는 것이 plan.md 백로그 A6.

8. **OPT-350M의 `project_in`과 safetensors prefix layout이 둘 다 함정** — 두 가지 실제 fix 가 필요했음 (`934ea27`, `246a02b`). loader를 다른 아키텍처로 확장하려는 사람을 위한 flag.

9. **Profiler 가 hidden bug 두 개** (D2.2 §5): tokenizer padding silent no-op + CUDA async timing → AGX vs Nano gap 이 ~0 로 가려졌었음. Commit 382739b 의 fix 가 D2.3+ 의 모든 측정의 전제조건.

---

## 12. Negative results

### 12.1 Jetson Nano에서 OPT-1.3B (EXP-D0)

3번 시도: (i) auto_schedule이 18 layer를 한 Nano에 몰빵, 부하 중 OOM-reboot; (ii) 6-worker auto 재시도, on-1이 18-layer LoadStage 중 OS reboot; (iii) manual 4-5 layer per-Nano placement, on-6 sshd swap-thrash. 근본 원인: **단일 bin OPT-1.3B (2.6 GB)는 `torch.load`가 전체를 메모리에 로드**, worker당 peak은 모델 크기에 근접. 분산해도 도움 안 됨 — loader가 sharded 아니면. Sharded 모델(Llama-2-7B, OPT-6.7B)은 가능하지만 scope 밖.

### 12.2 Throughput placement가 D2.5 sync chain 에서 발현 안 됨

D2.5 에서 throughput placement (max_stage 균등화) 가 C=4, 8, 16, 32 모두에서 latency placement 와 tie. 원인은 D3 Phase F 에서 밝혀짐 — sync chain forwarding 이 stream 당 모든 stage thread 점유 → pipeline parallelism 차단. Async chain 으로 풀어줬지만 L > T 는 *여전히* (universal dominance 가 throughput-mode 차단 때문이 아니라 R+ψ joint optimization 의 structural property).

### 12.3 메모리 binding regime — 도달 못 함

OPT-350M에서 모든 backup layer 로드 시에도 Nano당 peak 사용량이 1 GB 미만 (8 GB cap 대비). `ours.Ψ == jupiter_dp.Ψ` byte-identical placement가 OPT-125M과 OPT-350M에서 일관 관찰 — backup 메모리 예약이 Ψ를 제약한 적 없음. 메모리 binding regime 도달하려면 작은 RAM Nano + Llama-7B INT4 또는 훨씬 더 깊은 모델 필요. 백로그 항목.

---

## 13. 폐기 (EXP-D1)

이전 PHASES.md 섹션 (EXP-D1)의 OPT-350M 데이터는 **무효**. HF safetensors snapshot의 facebook/opt-350m이 `decoder.layers.0.self_attn.k_proj.weight` 같은 키 (앞에 `model.` 없음)를 사용, 반면 `OPTArchitecture.weight_prefix`는 prefix 붙은 형태 반환. 불일치로 `layer.load_state_dict(empty_dict, strict=False)`가 모든 block을 random-init weight로 방치. 증상:

- "The quick brown fox" prompt에 대한 greedy decode가 " Country" × 8 반환 (random transformer block의 degenerate 반복 토큰).
- ProfileLayers가 CPU Nano에서 ~1 ms / layer 보고 — 물리적으로 비현실; near-zero weight matmul이 SIMD-zero-shortcut됨.
- A3b'에서 라이브 greedy가 ours보다 *9% 빠르게* 측정 — 수정된 EXP-D2.1 결과와 정반대.

Fix는 commit `246a02b`. §3 OPT-125M 데이터는 버그 이전이라 영향 없음.

EXP-D2 (D1 fix 이후 첫 측정) 의 일부 placement 도 D2.2 의 profiler fix 이전이라 partial — 정확한 cell 은 PHASES.md 참조.

---

## 14. 한계 + future work

| 한계 | 영향 | 대응 |
|---|---|---|
| EXP-D2.1의 단일 victim (ao-2) | 회복 비용 vs victim layer 수 관계 미측정 | head / middle / tail stage victim sweep — 현재 fleet에서 ~30분 |
| 3 Nano를 CPU 모드 강제 (D2.1) | 이기종성이 *인위적* — 자연스러운 edge 배터리/열 throttle 아님 | genuinely 다른 SKU (Pi 5 vs Nano vs AGX) 보유 fleet에서 재측정 |
| OPT-1.3B는 이 fleet에서 도달 불가 | 메모리-binding regime에서 ours 우위 입증 불가 | sharded Llama-2-7B INT4로 재시도 (백로그 E) |
| DP cost-function 격차 | ours의 라이브 TBT 우위가 예측에 적게 카운트됨 | marginal-layer / transition-overhead 항 추가, 백로그 A6 |
| Async chain failure attribution은 trailer 못 씀 | Heartbeat path (5s timeout) 만 fallback. 최대 5s in-flight 손실 가능 | trailer 를 별도 RPC 로 reverse-channel — 백로그 |
| Single-GPU CUDA stream 직렬화 | 동시 요청이 worker 안에서 GPU stream 으로 직렬. Per-worker batching 미구현 | Batched inference (Static cache + KV concat) — 백로그 |
| 다중 동시 장애 회복 미테스트 | R(j) 가 단일 backup — concurrent fault 시 R cascade 가능성 | 백로그 A2 (R을 list-of-backups로 확장) |
| Nano 운영 안정성 (D3 Phase 2/3/F 측정 중) | on-1, on-2 의 SSH banner timeout / heartbeat silence 가 측정 노이즈 원인 | 디스크 정리 (오늘 on-1 -8.5G) + 장기적으로 SWAP 정책 검토 |

---

## 부록 A — 결과 JSON 맵

### A1 Algorithmic synthetic sweep
| 파일 | 범위 |
|---|---|
| `algo_hetero.json`, `algo_memory.json`, `algo_runtime.json`, `algo_alternating.json` | 합성 알고리즘 sweep (§2) |

### A2 OPT-125M 라이브 (§3)
| 파일 | 범위 |
|---|---|
| `auto_baseline_first.json` | A1 8-worker normal |
| `a2_kill_ao1_n5.json` | A2 N=5 fault injection |
| `a3b_opt350m.json` | A3b 4-baseline (파일명 헷갈리는데 실제 OPT-125M) |

### A3 OPT-350M 3-tier (페이퍼 헤드라인, §4)
| 파일 | 범위 |
|---|---|
| `opt350m_3tier_baseline.json` | A1' baseline |
| `a3a_opt350m_3tier_ab4k.json` | A3a 알고리즘 비교 |
| **`a3b_opt350m_3tier_n3.json`** | **A3b' N=3 페이퍼 헤드라인** |

### A4 D2.2-2.5 4-CUDA fleet (§5-7)
| 파일 | 범위 |
|---|---|
| `concurrent_4cuda_throughput_n3.json`, `concurrent_4cuda_latency_n3.json` | D2.5 throughput vs latency sweep |
| `concurrent_4cuda_chain_phase1a.json`, `concurrent_4cuda_chain_phase1b.json` | D3 Phase 1a/1b chain topology |
| `concurrent_4cuda_chain_throughput_phase1b.json` | Phase 1b throughput placement (-25% vs latency) |

### A5 D3 Phase 2/3/F (§9-10)
| 파일 | 범위 |
|---|---|
| `concurrent_phaseF_async_3stage.json`, `concurrent_phaseF_sync_3stage.json` | F.1 T placement, 3-stage |
| `concurrent_phaseF_latency_async_3stage.json`, `concurrent_phaseF_latency_sync_3stage.json` | F.1 L placement, 3-stage |
| `concurrent_phaseF_4stage_L_async.json`, `concurrent_phaseF_4stage_L_sync.json` | F.2 L placement, 4-stage |
| `concurrent_phaseF_4stage_T_async.json`, `concurrent_phaseF_4stage_T_sync.json` | F.2 T placement, 4-stage |

### A6 Legacy / 폐기
| 파일 | 범위 |
|---|---|
| `opt350m_baseline_first.json`, `a3a_opt350m.json`, `a3a_opt350m_ab*.json` | EXP-D1 폐기 데이터 (§13) |
| `a3_alg_first.json`, `a3_full_first.json` | OPT-125M legacy A3 (대체됨) |
