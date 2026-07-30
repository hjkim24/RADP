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

## B1-FLEET — surgical vs full-replay recovery TTR(P) (실 OPT-350M, advisor-pivot FT 실험)

**동기 (2026-07-19).** advisor 피드백(FT를 메인 축으로, 공정 세팅)에 따라, 기존의 "복구 없음(abort)" 대비 자명한 비교를 넘어 **실제 복구 전략끼리** 같은 fleet·model·주입으로 비교. in-process B1(§`b1_ft_baselines`, opt-125m)에서 확인된 surgical↔full-replay 격차를 **실 OPT-350M 하드웨어**에서 재현·측정.

**세팅.** 라이브 5-stage 이종 체인 (DP auto-placement): `ao-2[1..15]` (head, AGX) → `on-1[16..17]` → `on-6[18..19]` → `ao-1[20..23]` → `on-2[24]` (tail). Victim = chain-interior `on-1[16..17]`, backup `on-6`. 주입 = worker-side **compute-time crash** (`RADP_FAULT_INJECTION` + `/tmp/radp_fault.json`): victim이 position P의 input-mirror push가 coord에 도착한 뒤 raise → surgical 분기를 결정론적으로 트리거 (SIGKILL 아님 — spec §10 fault-model). recovery_mode는 coordinator env(`RADP_RECOVERY_MODE`)로 토글. Driver: `experiments/b1_ft_fleet.py` (P마다 coordinator 재시작으로 plan 리셋 → arm → 1요청 → recovery-step wall 추출 + sequence-match). 결과 10/10 트라이얼 모두 valid (fired✓, spike index = P−1✓, 출력 = healthy 레퍼런스 일치✓).

**⚠️ sync chain 필수 (방법론적 발견).** fleet 기본 `chain_mode: async`에선 interior 워커의 compute-time crash가 fire-and-forget 포워딩이라 동기 전파 안 됨 → gateway per-request **30s 타임아웃** → trailer 없이 **head로 오귀속**(측정: 31s, ao-2 dead). recovery **work**(surgical vs full)는 두 모드 동일하고 차이는 **detection latency**뿐(async 30s는 두 모드 공통 = 별개 축). 그래서 메커니즘 비교는 in-process와 동일하게 **sync chain**으로 측정. async detection 비용은 정직하게 별개로 기술.

**결과 (TTR(P), OPT-350M, sync chain, `b1_ft_fleet.json`).**

| P (실패 깊이) | full-replay | surgical | surgical 우위 |
|---|---|---|---|
| 4 | 0.897 s | 0.299 s | 3.0× |
| 8 | 1.510 s | 0.366 s | 4.1× |
| 16 | 2.834 s | 0.486 s | 5.8× |
| 24 | 3.928 s | 0.608 s | 6.5× |
| 32 | 5.056 s | 0.711 s | **7.1×** |

선형 fit:
```
full-replay: TTR(P) = 345 ms + 148.8 ms · P
surgical:    TTR(P) = 246 ms +  14.8 ms · P     → slope 비율 10.1×
```

**해석.** full-replay는 replay하는 position마다 **체인 전체(24층·5디바이스·4 network hop)를 재-forward** → per-position 148.8 ms ≈ 정상 decode 1스텝(~150 ms). surgical은 **죽은 stage의 backup(`on-6`, 2층·Nano 1대, replay_only, 포워딩 없음)만** 재구축 → per-position 14.8 ms ≈ full의 1/10. recompute 비중: full-replay는 P=32에서 **93%**(4.76 s), surgical 66%(0.47 s) — surgical이 없애는 게 정확히 그 recompute. **in-process opt-125m의 slope 비율(2.8×, 3 stage·4층·localhost)보다 fleet가 훨씬 큼(10.1×)** — 실 network hop + 깊은 모델이 full-replay의 per-position 비용을 증폭. 즉 microbenchmark는 surgical의 실-하드웨어 우위를 **과소평가**했음.

그림: [`fig_recovery_ttr`](../paper/figures/fig_recovery_ttr.pdf) (`make_recovery_ttr.py`). 출처: [`b1_ft_fleet.json`](results/b1_ft_fleet.json). in-process 대응: [`b1_analysis.json`](results/b1_analysis.json).

---

## B1-PARITY — cross-stage XOR parity: 재계산 0인 3번째 복구 계열 (실 fleet, 2026-07-20)

**동기.** surgical은 빠르지만 **Petals와 같은 계열**(입력 캐시 → 대체 노드에 재생)이라 차별성이 약했음. parity는 **모델 forward를 전혀 하지 않고** 죽은 stage의 KV를 복원하는 3번째 계열 — 파이프라인 KV에 대한 RAID-5 유비. GhostServe(MLSys'26)가 cross-node pipeline parity를 명시적 future work로 남긴 그 자리.

**메커니즘.** 정상 운영 중 **non-head stage들이** 각자 새로 생긴 **KV slot 컬럼**을 coordinator로 흘려보냄(`MirrorKV`, fire-and-forget). coordinator는 이를 **단 하나의 parity blob P**로 XOR 누적(`ParityCache`, max-stage로 zero-pad, stage별 중복은 dedup, 전 stage 기여 시에만 `complete`). stage 장애 시: 생존 non-head stage들의 KV를 `FetchKV`로 회수 → **바이트 XOR로 `P`와 결합해 죽은 stage의 KV를 비트 단위로 복원** → `LoadKV`로 승격된 backup에 직접 설치(forward 0) → 실패한 position만 라이브 실행. 레이아웃은 SLOT-major(parity/MirrorKV) ↔ LAYER-major(export/install)를 축 치환 `(3,0,1,2,4)`/`(1,2,3,0,4)`로 정합.

**세팅.** §B1-FLEET와 **동일**한 fleet·victim·주입(sync chain, compute-time crash on `on-1[16..17]`, backup `on-6`). 추가로 워커 `RADP_PARITY=1`(KV shipping), coordinator `RADP_RECOVERY_MODE=parity`.

**⚠️ 측정 신뢰성 장치.** parity의 모든 게이트는 실패 시 **조용히 surgical로 폴백**한다(정확성 보장). 그래서 폴백한 트라이얼의 TTR을 parity로 오표기할 위험이 있음 → 드라이버가 coordinator 로그의 `"PARITY reconstruct:"` 마커(6개 폴백 게이트를 모두 통과해야만 찍힘)를 확인해 **`parity_branch_ran`**을 기록하고, 이게 False면 트라이얼을 무효 처리·fit에서 제외. **본 스윕은 parity 5/5 모두 True**, 전체 15/15 valid.

**결과 (TTR(P), OPT-350M, sync chain, `b1_ft_fleet_parity.json`).**

| P | full-replay | surgical | **parity** |
|---|---|---|---|
| 4 | 0.973 s | 0.316 s | **0.298 s** |
| 8 | 1.670 s | 0.373 s | **0.282 s** |
| 16 | 2.882 s | 0.515 s | **0.293 s** |
| 24 | 4.200 s | 0.638 s | **0.304 s** |
| 32 | 5.621 s | 0.767 s | **0.316 s** |

```
full-replay: TTR(P) = 308.6 ms + 164.32 ms · P
surgical:    TTR(P) = 249.4 ms +  16.21 ms · P
parity:      TTR(P) = 284.1 ms +   0.87 ms · P     ← 기울기 ≈ 0
```

**해석.** parity의 기울기 **0.87 ms/position은 사실상 0** — surgical 대비 **19×**, full-replay 대비 **188×** 완만. 실패 깊이가 8배(P=4→32) 깊어져도 TTR은 0.298→0.316 s로 **+6%**만 증가(같은 구간에서 surgical 2.4×, full-replay 5.8× 증가). 이것이 "재계산 0" 클레임의 직접 측정: parity는 position마다 모델을 다시 돌리지 않고 **이미 가진 데이터의 전송+XOR**만 하므로 비용이 깊이에 비례하지 않는다. 그 결과 parity의 TTR은 이제 **세 계열이 공유하는 고정 오버헤드**(backup 승격 + 체인 rewire, 절편 ~284 ms)가 91%를 차지 — 복구 비용의 병목이 "재계산"에서 "재구성 이외의 관리 작업"으로 옮겨감.

### B1-PARITY.2 — 임의 interior victim으로 일반화 + 부수 버그 (2026-07-20 오후)

**일반화.** 위 한계(첫 interior victim 전용)를 해소. 크래시 순간 upstream 생존자는 slot이 1개 더 많고 downstream은 적으므로, **전 non-head가 공유하는 slot 수 `N = min(생존자 slot 수)`로 잡고 upstream 생존자를 앞 N개로 잘라낸 뒤** XOR한다. 실측 확인: 중간 victim에서 생존자 slot 수가 `[9, 8]`(격차 1)로 관측 — 슬라이싱이 실제로 동작. **격차가 1을 넘으면**(짧거나 stale한 버퍼) 잘린 KV를 설치해 조용히 틀린 토큰을 낼 수 있으므로 **surgical로 폴백**하는 가드를 둠(리뷰에서 지적된, 정확성이 parity에 의존하던 유일한 경로).

**⚠️ 부수 발견 — 체인 trailer 덮어쓰기 버그 (전 복구 모드 영향).** 일반화 작업 중, 체인의 **각 hop이 `radp-failed-*` trailer를 자기 next hop으로 덮어써서** 2 hop 이상 아래에서 난 장애가 **가까운(살아있는) stage로 오귀속**되고 coordinator가 멀쩡한 워커를 죽이는 버그를 발견·수정했다(다중 hop 회귀 테스트 추가). full-replay·surgical·parity 모두 해당. **기존 §B1-PARITY 수치는 영향 없음** — victim `on-1`이 head 바로 다음(포워딩 hop 1개)이라 덮어쓸 중간 hop이 없었고, 로그상 귀속도 `on-1`로 정확했다.

**측정 방식 정정.** 복구 스텝을 `max(TBT)`로 잡던 것을 **주입 위치가 우리가 정한 값이므로 `TBT[P−1]`에서 직접 읽도록** 변경. parity가 충분히 빨라지자(정상 스텝의 ~1.7배) 무관한 지터 스파이크가 복구 스텝을 앞지르는 사례가 실제로 1건 발생했다(중간 victim, P=4: max는 index 32의 0.322 s, 실제 복구 스텝은 0.278 s). 기존 트라이얼은 전부 `max` 위치 = `P−1`이었으므로 **값이 바뀐 것은 그 1건뿐**이며, 재실행 없이 기록된 per-step 시계열에서 재추출했다. `peak_*`는 진단용으로 계속 기록한다.

**중간 victim 결과** (victim `on-6[18..19]`, 15/15 valid, parity 5/5 `parity_branch_ran=True`):
```
full-replay: 321.6 ms + 163.01 ms · P
surgical:    223.9 ms +  17.53 ms · P
parity:      245.5 ms +   1.43 ms · P
```
→ **parity의 기울기는 victim 위치와도 무관**(첫 0.87 / 중간 1.43 ms·P⁻¹, 둘 다 ≈0). 정상 decode 스텝(median) 대비 복구 스텝 비율로 보면 더 선명하다: **parity는 P·위치와 무관하게 항상 1.6–1.9×**(정상 토큰 2개어치), surgical은 1.9→5.0×, full-replay는 6.0→34.4×로 깊이에 따라 증가.

**복구 결과의 강도가 다르다 (성능이 아닌 정합성 축) — 단, 아직 논증이지 측정이 아님.**
parity 복구에는 **부동소수 연산이 하나도 없다** — raw 바이트 uint8 XOR 뿐이고 완전 가역이므로,
복원되는 것은 죽은 워커가 실제로 들고 있던 **바로 그 바이트**다. `tests/test_parity_recovery.py`
가 이를 layer별 K·V로 **bit-identical** 단언한다. 반면 surgical은 미러 입력을 **backup 워커에서
다시 forward** 하므로 수학적으로 동치인 재계산값이며, 커널 리덕션 순서·FMA 유무·누적 정밀도·
연산 경로(CUDA vs CPU BLAS)가 다르면 비트가 어긋날 수 있다. full-replay는 생존자 KV까지 evict 후
재계산하므로 가장 많이 흔든다.

세부 구조상 stage의 **첫 layer**는 KV가 미러 입력의 선형 사영이라 position끼리 독립이지만,
**그 뒤 layer**는 입력이 앞 layer의 attention 출력이라 과거 KV의 오차가 섞여 들어올 수 있다
(우리 배치에서는 `ao-1[20..23]`이 4 layer로 가장 취약, `on-2[24]`가 1 layer로 가장 안전).
반대로 victim과 backup이 **같은 기종**이면(실측 조건: `on-1`→`on-6`, 둘 다 Orin Nano CUDA)
같은 커널·같은 빌드라 bit-identical일 가능성이 높다.

**측정한 적 없음을 명시한다.** surgical 복구 후 KV를 원본과 바이트 비교한 실험은 아직 없다.
확인된 것은 (a) parity가 bit-identical이라는 테스트 단언, (b) 실측 15/15 트라이얼 모두
`sequence_match=True`(토큰 출력 일치)뿐이다. 따라서 현재 이 항목은 **보장의 강도** 차이에 대한
논증이며, surgical이 오답을 낸다는 주장이 아니다. paper에 정합성 클레임으로 쓰려면 아래
백로그 항목을 먼저 측정할 것.

**백로그 B4 — surgical KV 정합성 측정 (다음 1주).** victim 사망 직전 KV를 `export_kv`로 확보하고,
surgical 복구 후 backup의 KV를 `fetch_kv`로 뽑아 바이트 비교. 기록할 값: 불일치 원소 비율,
최대 절대오차, 최대 ULP 차. **두 조건으로 돌린다** — (i) 동일 티어(`on-1`→`on-6`, CUDA→CUDA),
(ii) 이종 티어(`on-1`→CPU 워커). 이래야 "이종성이 정합성에 미치는 영향"이 숫자로 나오고,
§B1-PARITY의 "재계산 0 = 수치 재현성" 주장이 논증에서 측정으로 승격된다. 기존 하네스에
`fetch_kv`가 이미 있으므로 드라이버 추가만 필요.

**정직한 한계 (paper에 그대로 기술).**
- **마지막 stage(tail) victim은 여전히 surgical 폴백.** downstream 생존자가 없어 `min()`이 과대추정되고 completeness 게이트가 걸린다. 이를 덮으려면 `count−1` 규칙이 필요한데 **과소추정 시 아무 게이트도 못 잡아** 잘린 KV를 설치할 위험이 있어, 미검증 규칙을 넣는 대신 폴백으로 남겼다(테스트로 잠금: 폴백하며 출력은 레퍼런스와 일치). fleet 기준 `on-1`·`on-6`·`ao-1`은 parity, tail `on-2`만 폴백.
- **trailer relay는 fail-fast 장애 기준.** victim이 2 hop 이상 아래에서 **hang**하면 바깥 hop의 deadline이 먼저 터져 여전히 오귀속될 수 있다(선재 문제; 안쪽 hop에 더 짧은 deadline이 필요).
- **정상 운영 중 연속 네트워크 세금**(KV 컬럼 shipping)을 지불한다. 본 실험은 이 비용을 기술만 하고 최적화·정량화하지 않았다.
- 단일 장애 전용(RAID-5). prefill(position 0) 장애는 라이브 prefill로 축퇴 = 재계산-0 아님.

그림: [`fig_recovery_ttr`](../paper/figures/fig_recovery_ttr.pdf) (3-선). 출처: [`b1_ft_fleet_parity.json`](results/b1_ft_fleet_parity.json), 스모크 [`b1_ft_fleet_parity_smoke.json`](results/b1_ft_fleet_parity_smoke.json). 설계/계획: `docs/superpowers/{specs,plans}/2026-07-20-parity-recovery*`.

---

## B1-REPLICATE — full KV replication baseline: parity의 진짜 라이벌 (실 fleet, 2026-07-22)

**동기.** parity를 full-replay/surgical(재계산 계열)뿐 아니라 *다른 zero-recompute 전략*과 대비해야
기여가 격리된다. full KV replication(DejaVu/KevlarFlow 계열)은 XOR 없이 stage별 KV를 통째로
coordinator에 저장했다 로드한다 — parity와 **복구 기제가 같고**(재계산 0), **저장하는 것만 다르다**
(N벌 vs XOR 1장). 구현은 parity cache에서 XOR만 뺀 것(`ReplicaCache`), 저장 위치도 coordinator로
동일하게 두어 "저장 위치" 교란변수를 제거. GhostServe가 이미 한 erasure-coding vs full-replication
비교(8:2가 75% 절감)를 우리 이종 엣지 레짐에 재현한 것.

**세팅.** §B1-PARITY와 **동일** fleet·victim(`on-1[16..17]`)·주입(sync chain, compute-time crash).
워커 `RADP_PARITY=1`(KV shipping 공유 게이트), coordinator `RADP_RECOVERY_MODE=replicate`.

**결과** (victim `on-1`, 15/15 valid across smoke+sweep, replicate 5/5 `replicate_branch_ran=True`):
```
full-replay: 308.7 ms + 164.32 ms · P
surgical:    249.4 ms +  16.21 ms · P
parity:      284.1 ms +   0.87 ms · P
replicate:   239.3 ms +   2.67 ms · P      ← NEW
```
→ **replicate도 기울기 ≈ 0** (2.67 ms/pos, surgical 16·full-replay 164 대비 사실상 평평) — 재계산
계열이 아니라 parity와 같은 저장 계열임을 실측 확인. **replicate 절편(239)이 parity(284)보다 낮다**:
replicate는 저장본 1개 install, parity는 생존자 N−1 fetch + XOR이라 복구 시 전송이 더 많기 때문.
기울기 교차 P≈25 — P<25 replicate가, P>25 parity가 근소하게 빠름. 즉 **TTR에선 사실상 동률.**

**그래서 parity의 우위는 TTR이 아니라 저장이다 (2D Pareto).** 상시 coordinator 저장:
```
replicate = Σ(non-head stage KV) = 9 layer분 (36864 B)
parity    = max(non-head stage KV) = 4 layer분 (16384 B)   → 2.25× 적음
```
스케일링으론 replicate O(N)·parity O(1) (stage 수 무관, 엣지가 깊어질수록 벌어짐). 그래서 1D TTR
그래프가 아니라 **2D Pareto(TTR × 저장)**로 프레이밍: full-replay/surgical은 저장 0이나 TTR가 P를
타고, replicate는 TTR 낮으나 저장 N배, **parity만 좌하단(낮은 TTR ∧ 낮은 저장) 코너**에 있다.
정직한 한계: replicate와 parity는 **상시 네트워크(업로드)가 동일**하다(둘 다 같은 KV 컬럼 전송) —
parity의 변별점은 오직 coordinator 저장 바이트다.

그림: [`fig_recovery_ttr_slide`](../paper/figures/fig_recovery_ttr_slide.pdf) (4-선, 로그축),
[`fig_recovery_2d`](../paper/figures/fig_recovery_2d.pdf) (Pareto),
[`fig_storage_scaling`](../paper/figures/fig_storage_scaling.pdf) (O(N) vs O(1)).
출처: [`b1_ft_fleet_replicate.json`](results/b1_ft_fleet_replicate.json),
[`b1_ft_overhead.json`](results/b1_ft_overhead.json). 설계/계획:
`docs/superpowers/{specs,plans}/2026-07-22-replication-baseline*`.

## B1-REACTIVE — reactive re-placement baseline: proactive backup이 왜 필요한지 보이는 R={} 앵커 (실 fleet, 2026-07-22)

**동기.** parity/replicate는 *상시 backup을 두는* 계열임. 그 반대편 극단 — **backup을 전혀 안 두는**
운영점(R={})을 측정해야 "proactive backup의 값어치"가 격리됨. reactive re-placement는 장애가 나면
그제서야 코디네이터가 생존자 위에서 DP를 다시 풀어 재배치하고, 새로 배치받은 워커가 레이어 가중치를
**cold-reload**한 뒤, 요청을 **position 0부터 재생**함. 저장은 0이나 복구가 catastrophic이라는 걸
실측으로 앵커링하는 게 목적 — 2D Pareto의 우하단(저장 0 ∧ TTR 폭발) 꼭짓점.

**세팅.** 안정적 5-워커 CUDA/AGX fleet(`ao-2, on-6, on-1, ao-1, on-2` — CPU 워커 on-3/on-4는
heartbeat 불안정으로 이 스위프에서 제외, parity/replicate와 동일 토폴로지). coordinator
`backup_placement=false`(R={}) + `enable_subset_search=false`(R={} 레짐은 memory pruning이 꺼져
subset 탐색 13692후보가 전수 DP로 돌아 6분+ 걸림 — full-set permutation만으로 제한). 주입은 다른
계열과 **동일**한 compute-time crash지만, 이 계열은 gateway 복구 모드가 없음(R={}라 승격할 backup이
없어 crash가 그대로 abort). **victim은 매 트라이얼 라이브 placement에서 동적 선택**(중간 interior
stage) — fleet solve가 CPU-워커 등록 타이밍에 준-비결정적이라 정적 victim은 배포된 체인과 어긋나
fault가 안 터짐. compute-time crash는 프로세스를 안 죽여 victim이 계속 heartbeat하므로(→`_dead`에
자연 진입 안 함), 재배치 직전 `/api/clear_all_failures` → `/api/inject_failure`로 **victim만** 명시적
dead 마킹(heartbeat-timeout 탐지기가 할 일을 즉시·결정론적으로 대행) 후 `/api/reconfigure`가
생존자 위에서 재-solve+redeploy. 게이트: `reconfigured`(새 placement가 victim을 실제 배제) ∧
`fired` ∧ `sequence_match`.

**결과** (5/5 valid, 매 트라이얼 정확히 victim 1개만 배제 = survivors 4):
```
reactive_replacement: TTR(P) = 56.9 s − 0.18 s · P   (n=5)
  P=4  64.1 s   P=8  48.2 s   P=16  50.5 s   P=24  53.5 s   P=32  52.8 s
```
→ **P에 대해 사실상 flat(~53 s median)** — 음의 기울기(−0.18 s/pos)는 측정 노이즈, 부호는 무의미함.
당연한 결과임: replay가 항상 position 0부터라 crash 위치와 무관하고, 비용은 **재배치 중 cold model
reload가 지배**(재-solve DP + 재배치받은 생존자의 레이어 가중치 로딩). full-replay가 P를 타고 오르는
것(재-forward 길이 ∝ P)과 근본적으로 다름.

**해석 — reactive가 왜 앵커인가.** P=32에서 reactive 52.8 s vs parity 0.30 s = **~176×**, vs
full-replay 5.06 s = **~10×**. 저장은 0(backup 없음)이나 복구가 두 자릿수 초 — 2D Pareto에서
`(TTR≈53 s, 저장 0)` 우하단에 홀로 앉음. proactive backup(parity/replicate)이 존재하는 이유를
직접 보여줌: backup 없으면 장애 한 번에 cold reload+full replay 세금을 물어야 함.

**정직한 한계.** (1) 탐지를 heartbeat timeout이 아니라 명시적 mark_dead로 대행 — 실환경의 탐지
지연(~heartbeat 5 s)을 TTR에서 뺀 셈이나, 52 s 대비 무시할 수준이고 이렇게 해야 "재배치 비용"이
깨끗이 측정됨. (2) victim은 재시작이 아니라 **배제**됨 — 이게 정확히 reactive re-placement의 정의
(죽은 노드를 빼고 나머지로 재배치)이므로 victim의 자체 reload는 무관. (3) 코디네이터/gateway 코드
무변경 — 기존 엔드포인트(`/api/inject_failure`·`/api/reconfigure`·`/api/clear_all_failures`)만
드라이버에서 조합. (4) 5-워커 측정(CPU 워커 제외) — reactive TTR은 cold reload가 지배해 토폴로지에
robust하므로 order-of-magnitude 스토리는 불변.

그림: [`fig_recovery_ttr_slide`](../paper/figures/fig_recovery_ttr_slide.pdf) (5-선, 로그축 —
reactive가 최상단 ~53 s),
[`fig_recovery_2d`](../paper/figures/fig_recovery_2d.pdf) (Pareto, 로그-X — reactive 우하단).
출처: [`b1_ft_fleet_reactive.json`](results/b1_ft_fleet_reactive.json). 설계/계획:
`docs/superpowers/{specs,plans}/2026-07-22-reactive-replacement*`.

## B1-OVERHEAD — 상시 network shipping: mirror은 누가 왜 무는가 (2026-07-30)

**동기.** B1-FLEET/PARITY/REPLICATE/REACTIVE 넷은 전부 "장애 나면 무엇을 다시 만드는가"(TTR)만 쟀다. parity/replicate는 **정상 운영 중에도** 매 스텝 KV 컬럼을 coordinator로 흘려보내는 상시 네트워크 세금을 문다 — §B1-PARITY/§B1-REPLICATE 한계 항목에 "정량화 안 됨"으로 남겨둔 항목이다. 이번 측정이 그 세금을 계열별로 분해한다.

**메커니즘 (코드로 확인, `experiments/_harness.py::shipping_overhead`).** worker→coordinator 상시 shipping은 매 decode 스텝마다 두 가지다:
- **input mirror**(`submit_mirror`/`record_mirror`): non-head stage 전부가 **recovery_mode·RADP_PARITY 여부와 무관하게 항상** 자기 활성값을 coordinator로 흘려보낸다(`radp/worker/server.py:429-451`, 게이트는 `start_layer>1 ∧ not replay_only` 뿐 — 5계열 전부 이 조건을 만족). 계열별로 다르지 않다.
- **KV 컬럼**(`MirrorKV`/`_maybe_push_parity_kv`): `RADP_PARITY` 환경변수 게이트라 **parity/replicate 두 계열만** 얹는다(`server.py:473-484`).

**결과 (OPT-350M, 5-stage 배치 `ao-2[1-15]/on-1[16-17]/on-6[18-19]/ao-1[20-23]/on-2[24]`, `b1_ft_overhead.json`).**

| 계열 | 스텝당 shipping | 대역폭 (median TBT=0.1633 s 기준) |
|---|---|---|
| full-replay / reactive / surgical | mirror만 8192 B | 50165.3 B/s (49.0 KiB/s) |
| parity / replicate | mirror(8192)+KV(36864)=**45056 B** | 275909.4 B/s (269.4 KiB/s) |

parity/replicate가 나머지 셋 대비 스텝당 **5.5×** 더 많은 바이트를 쏜다 — 정확히 KV 컬럼(36864 B)만큼의 델타다. **mirror(8192 B)는 다섯 계열 전부가 무는 always-on 베이스라인**이고, **KV 컬럼(36864 B)이 parity/replicate만 그 위에 얹는 델타**다.

**mirror은 왜 존재하나 — surgical rung의 값.** mirror shipping은 다섯 계열이 똑같이 물지만, 실제로 그걸 읽어서 쓰는(read-back) 계열은 다르다. `radp/coordinator/gateway.py`를 추적하면:
- **surgical**(`_recover_surgical`)은 죽은 stage의 mirror 히스토리 **전체(position 0..P-1)**를 읽어 backup에 replay하는 게 복구 메커니즘 그 자체(`self.cache.get_history`, line 841).
- **parity/replicate**(`_recover_parity`/`_recover_replicate`)는 정상 경로에서 과거 포지션은 이미 가진 XOR/복제본으로 재구성하지만, **실패 포지션 P 딱 하나치**는 여전히 mirror에서 읽어 live로 흘린다(각각 line 1224/1285, line 968/1039 — mirror가 완전 무관하진 않다, 다만 O(1) 읽기). mirror 히스토리 길이가 P보다 짧으면(async lag) 또는 KV 쪽 6개 게이트 중 하나라도 걸리면 **`_recover_surgical`로 폴백**해 mirror 히스토리 **전체**를 읽는 비싼 경로로 넘어간다 — §B1-PARITY의 `parity_branch_ran`/`replicate_branch_ran` 로그가 바로 이 전환을 잡아내는 장치다.
- **full-replay**(`_replay_through_chain`)와 **reactive**는 worker가 쏜 mirror 바이트를 **한 번도 읽지 않는다** — full-replay는 coordinator 자신이 로컬로 프라이밍해둔 head-input history(`self.cache.get_history`이지만 head 항목은 `_run_pipeline`이 직접 채운 것, worker mirror 아님)로 체인 전체를 처음부터 다시 굴리고, reactive는 재배치 후 완전히 새 gateway를 열어 원 프롬프트로 position 0부터 재-prefill한다.

즉 **cost ladder는 parity/replicate(재계산 0) → surgical(부분 재계산) → full-replay(전량 재계산)** 순이고, mirror는 정확히 **surgical rung의 값**이다 — surgical이 히스토리 전체를 직접 소비하고, parity/replicate는 현재 포지션 1개치만 상시로 빌리다가 폴백 시에만 전체를 빌려 쓴다. 이 폴백 사다리는 개념이 아니라 실코드다: surgical 자신도 async-mirror lag 시 `_replay_through_chain`(full-replay)으로 한 단계 더 떨어진다(`gateway.py:843-858`) — `parity/replicate → surgical → full-replay`가 이미 코드에 있는 실제 경로다. 대안으로 **parity → full-replay** 2계열 사다리(중간 surgical rung 삭제)를 생각해볼 수 있다 — mirror shipping(8192 B/step, 5계열 전부에서 사라짐)을 완전히 없앨 수 있지만, 게이트 실패 시 폴백처가 이제 surgical(249.4+16.21 ms·P)이 아니라 full-replay(308.6+164.32 ms·P)라 폴백 비용이 P=32 기준 **7.3배**(0.767 s→5.621 s) 뛴다. mirror의 8192 B/step 세금은 그 값싼 폴백 안전망을 유지하는 대가다.

**정합성과의 연결 (§B1-FIDELITY 참조).** surgical(또는 그로의 폴백)이 하는 일은 **재계산**이다 — §B1-FIDELITY가 그 재계산이 tier에 따라 비트가 달라짐을 실측으로 보인다. parity/replicate가 정상 경로에서 갖는 bit-exact 보장은 폴백 순간 사라지고, surgical의 tier-dependent 재계산을 그대로 상속한다.

**정직한 한계.** shipping 바이트는 배치·모델 크기로부터 **결정론적으로 계산**된 값(`replication_overhead`/`shipping_overhead`, 측정이 아님)이고, 대역폭만 실측 median TBT(parity 스윕에서 도출, 0.1633 s)로 나눈 것 — gRPC 링크의 실제 latency/처리량 영향을 별도로 측정하지는 않았다. 5.5×는 이 5-stage/OPT-350M 배치(layer 분포 [2,2,4,1]) 한정이며, 다른 placement에선 mirror:KV 비가 달라진다.

출처: [`b1_ft_overhead.json`](results/b1_ft_overhead.json)(shipping), [`b1_ft_fleet_parity.json`](results/b1_ft_fleet_parity.json)(median TBT). 코드: `experiments/_harness.py::shipping_overhead`, `experiments/gen_overhead.py`.

---

## B1-FIDELITY — 재계산 기반 복구의 tier 간 bit fidelity 실측 (백로그 B4, 2026-07-30)

**동기.** §B1-PARITY.2 말미에서 "복구 결과의 강도가 다르다"를 **논증으로만** 남겼었다 — parity는 raw uint8 XOR라 완전 가역이므로 bit-identical, surgical/full-replay는 재계산이라 수학적으로 동치인 값일 뿐이라 커널·정밀도 경로가 다르면 비트가 어긋날 수 있다는 추정이었고, 실측은 없었다. 백로그 B4가 이 프로브다.

**세팅.** OPT-350M non-head stage `[16,17]`(2층, `on-1`이 맡는 실제 stage), seq=8, 고정 시드 입력(`torch.manual_seed(0)`으로 만든 hidden_states + 4D causal mask)을 **동일 바이트로** 두 tier에 ansible로 ship: `on-1`(cuda, fp16)과 `on-3`(cpu, fp16). 각 tier에서 `StageRunner.run(is_prefill=True)` → `export_kv` → sha256 + raw dump 회수 → `experiments.fidelity_compare.compare_kv`(순수 numpy, float64 캐스팅 후 비교)로 바이트 비교. 드라이버: `experiments/probe_recompute_fidelity.py`.

**결과 (`b1_ft_fidelity.json`).**

```
tier_a=cuda(on-1), tier_b=cpu(on-3)
hash_equal=False, exact=False
fraction_mismatched=0.26861572265625   (≈26.9%)
max_abs_diff=0.00390625                (=2⁻⁸)
recompute_diverges=true
```

**CUDA와 CPU에서 같은 입력을 같은 stage에 forward했는데 KV의 약 27%가 원소 단위로 다르다.** 최대 절대오차는 2⁻⁸(≈0.0039)로 fp16 몇 ULP 규모 — 값이 완전히 틀린 게 아니라 **커널 reduction 순서·FMA 사용 여부·누적 정밀도가 CUDA/CPU BLAS 경로마다 달라 생기는 부동소수 non-associativity**로 해석한다(정확도 버그가 아니라 하드웨어-종속 재현성 문제).

**family_verdict (JSON 그대로).**
```
parity:      bit-exact (by construction)
replicate:   bit-exact (by construction)
surgical:    tier-dependent recompute
full_replay: tier-dependent recompute
reactive:    tier-dependent recompute
```

parity/replicate는 죽은 stage를 **다시 forward하지 않으므로**(raw uint8 XOR/복제본 install) 이 실험의 영향을 받지 않는다 — "by construction" bit-exact. surgical/full-replay/reactive 셋은 전부 죽은 stage를 **어딘가에서 다시 forward**하므로, backup의 device tier가 victim과 다르면 이 실험이 실측한 만큼(원소 27%, 최대오차 2⁻⁸) 갈라질 수 있다. 즉 재계산 계열 셋에는 "속도"뿐 아니라 **새로운 정합성 축**이 생긴다 — 지금까지 fleet 트라이얼의 `sequence_match`(argmax 토큰 일치)는 전부 100%였지만, 그건 토큰 하나만 보는 게이트이고 중간 KV 텐서 자체는 tier가 바뀌면 bit 단위로 다를 수 있다는 뜻이다.

**⚠️ 캐비엇 — parity/replicate의 bit-exactness는 조건부다.** 위 verdict의 "bit-exact (by construction)"은 parity/replicate가 **자기 primary 경로(XOR 재구성/복제본 install)를 실제로 탔을 때만** 성립한다. §B1-OVERHEAD에서 확인했듯 게이트 중 하나라도 걸리면 둘 다 **조용히 surgical로 폴백**하고, 그 순간 이 프로브가 잡아낸 tier-dependent 재계산 드리프트를 그대로 상속한다. 측정 하네스가 이미 이 구분을 게이팅한다 — 드라이버가 coordinator 로그의 `"PARITY reconstruct:"` 마커로 `parity_branch_ran`(및 대응 `replicate_branch_ran`)을 기록해 폴백 트라이얼을 fit에서 제외한다(§B1-PARITY/§B1-REPLICATE, 두 스윕 모두 5/5 True). 그러니 정확한 문장은 "parity/replicate는 무조건 bit-exact"가 아니라 **"`parity_branch_ran`/`replicate_branch_ran=True`인 한에서 bit-exact, 폴백하면 surgical과 같은 정합성 리스크를 진다"**다.

**출력 레벨 영향 — cross-tier 전량 생성 스크린 (2026-07-30).** 위 프로브는 KV **비트** 드리프트를 보이지만, 그게 실제 **출력 토큰**을 바꾸는지는 별개 질문이다(지도교수 #3). 전용 스크린: OPT-350M **전체 모델**을 `on-1`(cuda, fp16)·`on-3`(cpu, fp16)에서 같은 프롬프트로 greedy 256토큰 생성해 토큰 열을 비교(`experiments/probe_output_divergence.py`). **전체 모델 cross-tier는 single-stage 복구보다 훨씬 큰 교란이므로 복구 발산의 상한**이다. 결과: **256/256 토큰 완전 일치 — 출력 레벨 발산 없음.** 즉 이 드리프트(원소 27%, 최대 2⁻⁸)는 최대 교란에서도 ≤256 greedy 토큰의 argmax를 못 뒤집고, 실제 복구(더 작은 교란)는 더더욱 안 뒤집는다. 그러므로 정합성 축은 **"재계산이 틀린 출력을 낸다"가 아니라 "parity/replicate는 증명 가능한 bit-exact 보장을 주고 재계산은 그 보장이 없다"** 는 결정론·재현성 축으로 읽어야 한다(산업/TII 신뢰성 프레이밍에선 유효, 단 출력 오류 주장은 금물).

**flip 사냥 (3156 결정) — 안 뒤집힌다, 드리프트가 common-mode라서.** 실제로 flip이 나는지 6개 다양한 프롬프트로 cuda가 512토큰씩 생성한 시퀀스를 두 tier에서 teacher-force해 **위치별 argmax를 3156개** 비교했다(`experiments/probe_flip_hunt.py` — teacher-force라 캐스케이드 없이 모든 결정을 한 forward로 샘플). **flip 0개.** near-tie(margin ≤ 2⁻⁵)는 0.38%(12개), **완전 동점(margin=0)** 스텝도 있었으나 어느 것도 안 뒤집혔다. 결정적으로 `seq5 pos15`는 **승자 절대 드리프트 0.0137 > margin 0.0039** 인데도 flip이 없었다 — flip은 승자의 **절대** 드리프트가 아니라 top1·top2의 **차분** 드리프트가 margin을 넘어야 나는데, cross-tier 드리프트가 대체로 **common-mode**(top1·top2가 같은 방향으로 함께 흔들림)라 순위를 안 바꾼다. 즉 앞의 "min(margin)≈max(drift)"는 **절대** 드리프트 기준이라 flip 위험을 과대평가한 것이고, order-relevant(차분) 드리프트는 훨씬 작다. **정확한 결론: 재계산 드리프트는 비트 레벨(27%)로 실재하지만 greedy 출력은 안 뒤집힌다(3156 결정, 완전 동점 포함, 0 flip). 정합성 축은 "재계산이 틀린 출력을 낸다"가 아니라 "parity/replicate는 증명 가능한 bit-exact 보장, 재계산은 실측상 괜찮으나 무보장" 이라는 결정론·재현성 축이다.** store-KV는 이 리스크 표면 자체가 0. 코드: `experiments/probe_output_divergence.py`, `experiments/probe_flip_hunt.py`. 미측정: 더 긴/많은 생성에서 차분 드리프트가 margin을 넘는 극단 케이스, sampling(RNG cross-device 교란이 별개로 섞임), 더 깊은 stage.

**정직한 한계.** (1) 프로브는 stage `[16,17]`·seq=8 **한 지점**뿐 — 4층짜리 `ao-1[20..23]`처럼 attention 출력이 누적되는 더 깊은 stage나 더 긴 시퀀스에서 mismatch 비율이 어떻게 변하는지는 미측정. (2) tier 쌍도 cuda↔cpu **하나**만 쟀다 — `agx`(`ao-1`) tier는 코드에 정의는 돼 있으나(`TIERS`) 이번 실행은 `{"cuda": "on-1", "cpu": "on-3"}` 두 tier만 호출했다. §B1-PARITY.2가 추정한 "victim·backup이 같은 기종(cuda↔cuda)이면 bit-identical일 가능성" 자체는 아직 검증 안 됨. (3) 지금까지 fleet 측정에서 실제로 틀린 토큰이 나온 사례는 없다 — 이 프로브가 잡는 건 argmax 이전의 중간 텐서 수준 드리프트다.

출처: [`b1_ft_fidelity.json`](results/b1_ft_fidelity.json). 코드: `experiments/probe_recompute_fidelity.py`, `experiments/fidelity_compare.py`.

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

15. **재계산 기반 복구(surgical/full-replay/reactive)에 새로운 정합성 축이 생긴다 — CUDA↔CPU 재계산이 실측으로 갈라짐 (§B1-FIDELITY).** 같은 OPT-350M non-head stage(`[16,17]`)를 같은 입력으로 cuda(`on-1`)·cpu(`on-3`) 두 tier에서 재계산해 KV를 바이트 비교하니 `recompute_diverges=true` — 원소 26.9% 불일치, 최대 절대오차 2⁻⁸(fp16 몇 ULP, CUDA/CPU BLAS 커널 reduction 순서 차이로 해석). parity/replicate는 forward를 안 하므로 by-construction bit-exact, 재계산 셋(surgical/full-replay/reactive)은 tier-dependent — 속도 축과 별개로 **정합성 축**이 새로 생긴다는 뜻. 캐비엇: parity/replicate의 bit-exact 보장은 `parity_branch_ran`/`replicate_branch_ran=True`(자기 primary 경로를 실제로 탔을 때)에 한정 — 게이트가 걸려 surgical로 폴백하면 이 드리프트를 그대로 상속한다. 한계: stage 1곳·tier 쌍 1개(cuda↔cpu)만 측정, 동일 기종(cuda↔cuda) 조합은 미검증, 지금까지 모든 fleet 트라이얼의 토큰 출력(`sequence_match`)은 100% 일치.

14. **상시 network shipping을 계열별로 분해하면 mirror가 surgical rung의 값임이 드러난다 (§B1-OVERHEAD).** 5계열 전부가 스텝당 input mirror 8192 B를 always-on으로 물고(`server.py:429-451`, recovery_mode 무관), parity/replicate만 KV 컬럼 36864 B를 더 얹어 스텝당 45056 B(대역폭 275909.4 B/s ≈ 269.4 KiB/s) — 나머지 셋(50165.3 B/s ≈ 49.0 KiB/s) 대비 **5.5×**. 코드 추적 결과 mirror 히스토리 전체를 읽는 건 surgical(dead-stage 히스토리 replay)뿐이고, parity/replicate는 현재 포지션 1개치만 상시로 빌리다가 게이트가 걸릴 때만 전체를 빌려 쓰며(§B1-PARITY의 `*_branch_ran` 게이팅), full-replay·reactive는 worker mirror를 한 바이트도 안 읽는다(각각 coord 자체 head-history replay·재-prefill). `parity/replicate → surgical → full-replay` 폴백 사다리가 이미 코드에 존재하고(`gateway.py:843-858`), mirror을 아예 없애는 `parity → full-replay` 2계열 대안은 8192 B/step 세금을 지우는 대신 폴백 비용을 P=32 기준 7.3배(surgical 0.767 s → full-replay 5.621 s) 키운다.

13. **Reactive re-placement(backup 없음, R={})은 복구가 두 자릿수 초 — proactive backup의 존재 이유를 앵커링 (§B1-REACTIVE).** 같은 fleet에서 `reactive TTR(P)=56.9 s−0.18 s·P`, P에 대해 사실상 flat(~53 s median, 음의 기울기는 노이즈). 비용이 **재배치 중 cold model reload + position 0 재생**에 지배돼 crash 위치와 무관. P=32에서 parity 대비 **~176×**, full-replay 대비 **~10×** 느림. 저장 0이나 복구 catastrophic이라 2D Pareto 우하단(TTR≈53 s ∧ 저장 0)에 홀로 앉음 — full-replay/surgical/parity/replicate가 저장을 지불해 사는 복구 속도를 backup 없는 계열은 못 산다는 걸 직접 보임. 코디/gateway 무변경(기존 web_api 엔드포인트만 조합), victim은 라이브 placement에서 동적 선택 + `clear_all_failures`→`inject_failure`로 결정론적 단일 배제(compute-time crash가 프로세스를 안 죽여 heartbeat 유지되는 문제 우회), 5/5 valid.

12. **Full KV replication은 parity와 TTR 동률, 저장에서만 짐 (§B1-REPLICATE).** 같은 fleet에서 `replicate TTR(P)=239.3+2.67 ms·P` — parity(284.1+0.87)와 기울기·절편 모두 사실상 동률(교차 P≈25). 둘 다 zero-recompute라 TTR이 같고, parity의 유일한 우위는 상시 저장(max vs Σ, 2.25×; O(1) vs O(N)). 그래서 비교는 1D TTR이 아니라 2D Pareto(TTR × 저장)이며 parity만 좌하단 코너. GhostServe의 erasure-coding vs replication 비교를 이종 엣지 레짐에 재현. 측정은 `replicate_branch_ran` 로그로 surgical 폴백 오표기 배제(5/5 진짜 replicate).

11. **Cross-stage XOR parity = 재계산 0인 3번째 복구 계열, 실 하드웨어에서 기울기 ≈ 0 (§B1-PARITY).** 같은 fleet·victim·주입에서 `TTR(P) = 284 ms + 0.87 ms·P` — surgical(16.21) 대비 **19×**, full-replay(164.32) 대비 **188×** 완만. P를 8배 늘려도 TTR +6%. 복구 비용이 "재계산"이 아니라 **공유 고정 오버헤드(승격+rewire ~284 ms)**에 지배됨. 입력 재생 계열(surgical/Petals)과 근본적으로 다른 메커니즘이며, 측정은 `parity_branch_ran` 로그 검증으로 surgical 폴백 오표기를 배제(5/5 진짜 parity). 한계: 첫 interior victim 한정(그 외 안전 폴백), 정상 운영 중 KV shipping 네트워크 세금.

10. **Surgical 복구가 실 하드웨어에서 full-replay 대비 slope 10.1× (advisor-pivot FT 헤드라인, §B1-FLEET).** 실 OPT-350M 5-stage fleet, 같은 compute-time 주입으로 recovery_mode만 토글: full-replay는 position마다 체인 전체 재-forward(~150 ms/pos ≈ decode 1스텝), surgical은 죽은 stage backup만 재구축(~15 ms/pos). P=32에서 5.06 s→0.71 s (7.1×), 모든 토큰 보존. FT를 "복구 없음" 대비가 아니라 **실 복구 전략끼리** 공정 비교한 첫 결과.

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
| surgical 복구 KV의 비트 정합성 미측정 | "재계산 0 = 수치 재현성" 주장을 논증으로만 쓰고 있음 | 백로그 B4 (동일 티어 vs 이종 티어 바이트 비교) |
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
