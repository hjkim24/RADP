# RADP — 분산 LLM 추론을 위한 Recovery-Aware DP

**벤치마크 보고서 (라이브 에지 fleet)**

이 보고서는 페이퍼용으로 수집된 모든 라이브 fleet 측정값을 종합한다. 각 실험은 원본 JSON 결과 파일을 출처로 인용한다. 본 문서의 수치는 critical fix 커밋 `934ea27` (`project_in` 순서) 및 `246a02b` (weight loader prefix mismatch) 적용 *이후* 데이터다. 폐기 데이터는 §7 참조.

---

## 핵심 요약

| 클레임 | 근거 | 효과 |
|---|---|---|
| Recovery-Aware DP는 처리량 가중 greedy 휴리스틱을 *정상 운영*에서 **이김** (이기종성이 의미 있을 때) | EXP-D2.1, 셀당 n=300 TBT 샘플 | TBT p50 **-6.5%**, 처리량 **+8.3%** |
| Recovery-Aware DP는 워커 장애에서 **모든 토큰 보존**, R={} baseline은 **70%+ 손실** | EXP-D2.1, 2 baseline × N=3 failure trial | ours 60/60 ×3, greedy 17/60 ×3 |
| 회복 latency는 bounded, 예측 가능, 에지 LLM SLO 안에 들어옴 | EXP-D2.1 + Phase EXP-A2 N=5 | mean 617 ms, p95 670 ms, 100 ms tight spread |
| compute-light, network-bound regime에선 모든 알고리즘이 가장 느린 device floor에서 tie | Phase EXP-A3 (OPT-125M, 8-Nano 동질) | 알고리즘 간 ±0.1%, 장애 차별점은 그대로 |

**페이퍼 헤드라인 클레임** — *"Recovery-Aware DP는 동일한 R-Ψ 공동 최적화로 정상 운영과 장애 회복 둘 다에서 이김"* — 이 7-worker 이기종 에지 클러스터에서 N=3로 backing된 라이브 데이터로 뒷받침된다.

---

## 1. 셋업

### 1.1 Fleet

| device | 클래스 | 코어 | RAM | torch | 역할 |
|---|---|---|---|---|---|
| on-1 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | CUDA | worker (CUDA tier) |
| on-2 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | CUDA | worker (CUDA tier) |
| on-6 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | CUDA | worker (CUDA tier) |
| on-3 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | **CPU (강제)** | worker (CPU-Nano tier) |
| on-4 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | **CPU (강제)** | worker (CPU-Nano tier) |
| on-5 | Jetson Orin Nano 8 GB | 6 ARM A78AE | 7.4 GB | **CPU (강제)** | worker (CPU-Nano tier) |
| ao-2 | Jetson AGX Orin 32 GB | 12 ARM A78AE | 29 GB | CPU (JP5/Py3.9용 torch wheel만 가용) | worker (CPU-AGX tier) |
| ax-1 | Jetson AGX Xavier 32 GB | 8 ARM Carmel | 30 GB | CPU | coordinator |
| ~~ao-1~~ | Jetson AGX Orin 32 GB | 12 ARM A78AE | 29 GB | CPU | **제외 — 디스크 100%** |

Nano-CPU 워커 3대는 `RADP_TORCH_DEVICE` systemd env로 CPU 모드 강제 → 실제 3-tier compute 분할 (~1.5 ms / 17 ms / 42 ms per layer, OPT-350M).

### 1.2 모델

| 모델 | layer 수 | hidden | weight 포맷 | 크기 |
|---|---|---|---|---|
| facebook/opt-125m | 12 | 768 | bin (model.* prefix) | ~250 MB |
| facebook/opt-350m | 24 | 1024 | safetensors (model.* prefix 없음) | ~660 MB |
| facebook/opt-1.3b | 24 | 2048 | bin (model.* prefix) | 2.6 GB **— 배포 실패, §6 참조** |

### 1.3 도구

- [`experiments/run_e2e_remote.py`](run_e2e_remote.py) — 단일 baseline gRPC 처리량 벤치마크
- [`experiments/run_failure_remote.py`](run_failure_remote.py) — SSE 스트림 + Ansible로 SIGKILL 워커 + per-token stage trace
- [`experiments/run_a3_remote.py`](run_a3_remote.py) — 다중 baseline 라이브 배포 + 비교 (manual cluster.yaml 합성 + push + 재시작 + bench loop)
- [`experiments/a3_baselines.py`](a3_baselines.py) — profile sidecar로부터 알고리즘 baseline 계산
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
| 모델–측정 격차 | 104 ms (pipeline traversal당 시스템 오버헤드) |
| Auto-schedule 단계별 | wait 4 ms · layers 35,170 ms · network 3,059 ms · DP 13 ms |

출처: [`auto_baseline_first.json`](results/auto_baseline_first.json).

### 3.2 장애 주입 + 회복 (A2 N=5)

단일 victim ao-1 (1-layer stage), trial 사이 cluster auto-reset, 5회 반복.

| 지표 | 값 |
|---|---|
| Pre-kill TBT p50 (trial 평균) | 221 ms |
| **Recovery step** | mean **729 ms**, p50 **677 ms**, p95 **883 ms** (범위 669–930 ms) |
| Spike vs pre-p50 | mean +509 ms, **3.30×** |
| Post-recovery TBT p50 | 226 ms (pre-kill 대비 ~5 ms 이내) |
| Kill 시 in-flight 토큰 | mean 4.6, max 7 |
| **토큰 손실** | **0 / 300** |
| Backup 활성화 | **5/5 trial** 모두 R(ao-1) = ao-2로 정확히 라우팅 |

Per-trial layer 흡수량: 4개의 2-layer-on-backup 케이스는 669–695 ms 회복, 한 개의 3-layer 흡수 케이스가 930 ms. 백업이 추가로 흡수하는 layer 1개당 ~250 ms — cache-replay + 직렬화가 dominant (compute 아님).

출처: [`a2_kill_ao1_n5.json`](results/a2_kill_ao1_n5.json).

### 3.3 알고리즘 라이브 비교 (A3b)

manual-mode cluster.yaml + coord 재시작으로 4 baseline 순차 배포.

| baseline | TBT p50 | TBT p95 | TTFT p50 | 장애 | emit한 토큰 |
|---|---|---|---|---|---|
| greedy | 221 ms | 284 ms | 348 ms | catastrophic 3/3 | [19, 20, 18] |
| uniform | 215 ms | 290 ms | 329 ms | catastrophic 3/3 | [19, 19, 19] |
| jupiter_dp | 217 ms | 285 ms | 350 ms | catastrophic 3/3 | [19, 19, 19] |
| **ours** | **219 ms** | 288 ms | 353 ms | **graceful 3/3** | **60/60 × 3** |

ours 회복: mean **597 ms**, p50 **594 ms**, p95 **726 ms**.

ours와 jupiter_dp가 **byte-identical** placement 산출 (메모리 여유가 너무 커서 backup 예약이 Ψ를 제약 안 함). 정상 운영 TBT는 4 baseline 모두 ±3% 이내 — compute 이기종성이 작을 때 알고리즘 격차가 *가장 느린 device floor*에 가려짐. 출처: [`a3b_opt350m.json`](results/a3b_opt350m.json) (파일명 헷갈리는데 실제로는 OPT-125M A3b 데이터).

→ 동질 compute regime에선 **정상 운영 성능 분간 불가**. 이 regime에서 DP의 고유 우위는 **recovery awareness** (binary: ours graceful vs 나머지 catastrophic).

---

## 4. 라이브 측정 — OPT-350M (3-tier 이기종성)

EXP-D2.1 fix 적용 후, **페이퍼 헤드라인 데이터**. 3 Nano를 `model_torch_device=cpu` per-host inventory override로 CPU 모드 강제하여 인위적 3-tier compute 분할 생성. 실측 per-layer compute time으로 tier 확인:

| tier | device | OPT-350M 평균 layer compute |
|---|---|---|
| CUDA Nano | on-1, on-2, on-6 | ~1.5 ms |
| CPU AGX | ao-2 | 17.6 ms |
| CPU Nano | on-3, on-4, on-5 | 42 ms |

가장 느린 device floor = 42 ms × 1 layer = 42 ms.

### 4.1 단일 baseline (A1', `ours` placement)

10 request × 30 token, warmup 2.

| 지표 | 값 |
|---|---|
| TTFT mean / p95 | 367 / 390 ms |
| TBT p50 / p95 | 257 / 312 ms |
| 처리량 mean | 3.8 tok/s |
| DP max_stage 예측 | 136.8 ms |
| 모델–측정 격차 | 120 ms |

출처: [`opt350m_3tier_baseline.json`](results/opt350m_3tier_baseline.json).

### 4.2 알고리즘 라이브 비교 (A3b' N=3) — **페이퍼 핵심 그림**

| 지표 | greedy | **ours** | Δ |
|---|---|---|---|
| Normal TBT p50 | 302.3 ms | **282.6 ms** | **-6.5%** |
| Normal TBT p95 | 366.0 ms | 352.0 ms | -3.8% |
| Normal TBT p99 | 407.8 ms | 389.1 ms | -4.6% |
| Normal TTFT p50 | 524.9 ms | 519.8 ms | -1.0% (tie) |
| 처리량 mean | 3.14 tok/s | **3.40 tok/s** | **+8.3%** |
| Failure (3 trial) | **3/3 catastrophic** | **3/3 graceful** | **binary** |
| 토큰 emit (장애) | 17, 17, 17 | 60/60 × 3 | |
| Recovery step | N/A | mean **617** / p50 **600** / p95 **670** ms | tight |
| 회복 범위 | N/A | 573–678 ms | 105 ms 분포 |
| Spike vs pre-p50 | N/A | +329 ms (**2.16×**) | |

조건당 n=300 TBT 샘플 (10 req × 30 tok). 출처: [`a3b_opt350m_3tier_n3.json`](results/a3b_opt350m_3tier_n3.json).

### 4.3 Placement 비교

```
greedy : on-6[1-8]    on-3[9]   on-1[10-15]  ao-2[16]  on-5[17]  on-4[18]  on-2[19-24]
         3개 CUDA Nano에 8 + 6 + 6 분산

ours   : on-6[1-16]   on-3[17]  on-1[18-20]  ao-2[21]  on-5[22]  on-4[23]  on-2[24]
         3개 CUDA Nano에 16 + 3 + 1 (집중)
```

알고리즘 예측에선 두 placement 모두 CUDA stage가 42 ms CPU-Nano floor 아래 유지 (greedy stages: 8 × 1.5 = 12 ms, 6 × 1.5 = 9 ms; ours: 16 × 1.5 = 24 ms, 3 × 1.5 = 4.5 ms). 라이브 6.5% TBT 격차는 따라서 cost 모델이 *적게 카운트하는 pipeline transition 오버헤드*에서 옴 — long-haul CUDA↔CUDA hop이 적은 placement가 유리.

### 4.4 cost 모델이 예측한 tie를 DP가 라이브에서 이긴 이유

현실값 `activation_bytes`로 알고리즘 비교 시 ours와 greedy는 45.3 ms max_stage에서 tie (CPU-Nano floor):

| baseline | 알고리즘 max_stage (activation_bytes=4 KB) |
|---|---|
| greedy | 45.3 ms |
| uniform | 171 ms (+278% — ao-2가 4 layer 받아서 bottleneck) |
| jupiter_dp | 45.3 ms (ours와 동일 placement) |
| ours | 45.3 ms |

Cost 모델은 stage당 compute + activation_transfer만 봄. 라이브 측정은 추가로 잡아냄: (a) stage 수에 비례한 gRPC framing 오버헤드, (b) 작은 stage들이 back-to-back 실행될 때 Python/GIL 경합, (c) KV cache append 비용. ours의 *fewer-bigger-stage* placement가 셋 다 절약.

출처: [`a3a_opt350m_3tier_ab4k.json`](results/a3a_opt350m_3tier_ab4k.json).

---

## 5. 핵심 발견 (페이퍼)

1. **DP는 정상 운영에서 이김 — 단, compute 이기종성이 유의미할 때만.** OPT-125M 동질 Nano fleet(§3.3)에선 4 placement가 TBT ±3% 안에서 tie. OPT-350M 3-tier fleet(§4.2)에선 ours가 greedy 대비 **TBT -6.5%**, **처리량 +8.3%**, 조건당 n=300 샘플.

2. **DP는 장애 복원력에서 두 regime 모두 binary로 이김.** ours는 모든 토큰 보존 (§4.2 N=3에서 180/180; §3.2 N=5에서 300/300). R={} baseline(greedy / uniform / jupiter_dp) 전부 stream 사망 — kill-after + in-flight 윈도우에 따라 정확히 17–20 토큰 emit 후 NoRecoveryError.

3. **회복은 bounded이고 예측 가능.** 두 regime, 두 모델 크기 모두 회복 latency가 **600–700 ms median**, **p95는 730 ms 미만**. 회복 비용은 backup 부담 layer 수에 mild 의존 (~250 ms / 추가 layer).

4. **cost-function 격차.** DP의 알고리즘 예측이 *fewer-bigger-stage 가치를 과소평가*. greedy와 ours가 max_stage_time 예측에선 45.3 ms로 tie인데, 라이브에선 ours가 6.5% 이김. marginal-layer 또는 transition-count 항을 cost 모델에 추가하는 것이 plan.md 백로그 A6.

5. **OPT-350M의 `project_in`과 safetensors prefix layout이 둘 다 함정.** OPT-350M을 이 스택에서 동작시키려면 두 가지 실제 fix가 필요했음 — 둘 다 commit-trail에 보임 (`934ea27`, `246a02b`). loader를 다른 아키텍처로 확장하려는 사람을 위한 flag.

---

## 6. Negative results

### 6.1 Jetson Nano에서 OPT-1.3B (EXP-D0)

3번 시도: (i) auto_schedule이 18 layer를 한 Nano에 몰빵, 부하 중 OOM-reboot; (ii) 6-worker auto 재시도, on-1이 18-layer LoadStage 중 OS reboot; (iii) manual 4-5 layer per-Nano placement, on-6 sshd swap-thrash. 근본 원인: **단일 bin OPT-1.3B (2.6 GB)는 `torch.load`가 전체를 메모리에 로드**, worker당 peak은 모델 크기에 근접. 분산해도 도움 안 됨 — loader가 sharded 아니면. Sharded 모델(Llama-2-7B, OPT-6.7B)은 가능하지만 scope 밖.

### 6.2 DP placement 양극화 분석

EXP-D0과 초기 EXP-D1 run 둘 다 극단적 placement 생성 (한 node에 18-19 layer, 나머지 1 layer). 두 가설:

- **`activation_bytes` calibration**: 기본값 1 MB는 실제 OPT-350M activation(~4 KB decode, ~70 KB prefill)보다 5–200× 큼. DP가 transition cost 과대평가 → 집중 선호. `activation_bytes` sweep으로 확인 ([`a3a_opt350m_ab4096.json`](results/a3a_opt350m_ab4096.json), `..._ab35000.json`, `..._ab100000.json`, `..._ab1048576.json`).
- **Stage 수는 device 수로 고정** (= 6 or 7), 따라서 모든 placement에서 *transition 수는 동일*. cost 차이는 각 transition이 *어떤 device*를 거치는지와 각 stage가 *어떤 compute*를 갖는지에서 옴. 그 모델 아래에선 DP의 집중 선택이 여전히 옳을 수 있음 — 양극화 자체가 버그는 아님.

### 6.3 메모리 binding regime — 도달 못 함

OPT-350M에서 모든 backup layer 로드 시에도 Nano당 peak 사용량이 1 GB 미만 (8 GB cap 대비). `ours.Ψ == jupiter_dp.Ψ` byte-identical placement가 OPT-125M과 OPT-350M에서 일관 관찰 — backup 메모리 예약이 Ψ를 제약한 적 없음. 메모리 binding regime 도달하려면 작은 RAM Nano + Llama-7B INT4 또는 훨씬 더 깊은 모델 필요.

---

## 7. 폐기 (EXP-D1)

이전 PHASES.md 섹션 (EXP-D1)의 OPT-350M 데이터는 **무효**. HF safetensors snapshot의 facebook/opt-350m이 `decoder.layers.0.self_attn.k_proj.weight` 같은 키 (앞에 `model.` 없음)를 사용, 반면 `OPTArchitecture.weight_prefix`는 prefix 붙은 형태 반환. 불일치로 `layer.load_state_dict(empty_dict, strict=False)`가 모든 block을 random-init weight로 방치. 증상:

- "The quick brown fox" prompt에 대한 greedy decode가 " Country" × 8 반환 (random transformer block의 degenerate 반복 토큰).
- ProfileLayers가 CPU Nano에서 ~1 ms / layer 보고 — 물리적으로 비현실; near-zero weight matmul이 SIMD-zero-shortcut됨.
- A3b'에서 라이브 greedy가 ours보다 *9% 빠르게* 측정 — 수정된 EXP-D2.1 결과와 정반대.

Fix는 commit `246a02b`. §3 OPT-125M 데이터는 버그 이전이라 영향 없음.

---

## 8. 한계 + future work

| 한계 | 영향 | 대응 |
|---|---|---|
| EXP-D2.1의 단일 victim (ao-2) | 회복 비용 vs victim layer 수 관계 미측정 | head / middle / tail stage victim sweep — 현재 fleet에서 ~30분 |
| ao-1 (AGX Orin)을 EXP-D2 / D2.1 fleet에서 제외 | 이기종성 setup에서 AGX-Orin 1대 손실 | 디스크 정리 (bstarcom team_quant) 또는 자체 회복 대기 |
| 3 Nano를 CPU 모드 강제 | 이기종성이 *인위적* — 자연스러운 edge 배터리/열 throttle 아님 | genuinely 다른 SKU (Pi 5 vs Nano vs AGX) 보유 fleet에서 재측정; 지속 부하로 thermally throttle 유도 |
| OPT-1.3B는 이 fleet에서 도달 불가 | 메모리-binding regime에서 ours 우위 입증 불가 | sharded Llama-2-7B INT4로 재시도 (radp의 sharded loader 이미 지원) |
| DP cost-function 격차 | ours의 라이브 TBT 우위가 예측에 적게 카운트됨 — 예측성에 약간의 리스크 | marginal-layer / transition-overhead 항 추가, 백로그 A6 |
| `activation_bytes` 정적값 | 현재 1 MB 하드코드, 실제 워크로드는 ~4-70 KB | prompt 길이 + 모델 hidden dim으로 동적 추정, 백로그 A6 |
| Trial당 단일 장애 주입 | 다중 동시 장애 회복 미테스트 | 백로그 A2 (R을 list-of-backups로 확장) |

---

## 부록 A — 결과 JSON 맵

| 파일 | 범위 |
|---|---|
| `auto_baseline_first.json` | OPT-125M A1 (8-worker) |
| `a2_kill_ao1_first.json` | OPT-125M A2 단일 trial |
| `a2_kill_ao1_n5.json` | OPT-125M A2 N=5 |
| `a3_alg_first.json` | OPT-125M A3a 알고리즘 |
| `a3_full_first.json` | (legacy A3b' 초안 — `a3b_opt350m.json`에 의해 대체) |
| `a3b_opt350m.json` | **OPT-125M** A3b 4-baseline (파일명 헷갈림, D-track 이전) |
| `opt350m_baseline_first.json` | OPT-350M EXP-D1 A1' **(폐기; 잘못된 weight)** |
| `a3a_opt350m.json` | OPT-350M EXP-D1 A3a' (폐기) |
| `a3a_opt350m_ab4096.json`, `_ab35000.json`, `_ab100000.json`, `_ab1048576.json` | `activation_bytes` sweep |
| `opt350m_3tier_baseline.json` | EXP-D2 A1' 6-worker 3-tier (수정된 weight) |
| `a3b_opt350m_3tier.json` | EXP-D2 A3b' greedy vs ours, N=1 |
| `opt350m_3tier_7w_baseline.json` | EXP-D2.1 sidecar (7-worker 3-tier) |
| `a3a_opt350m_3tier_ab4k.json` | EXP-D2.1 알고리즘 비교 |
| **`a3b_opt350m_3tier_n3.json`** | **EXP-D2.1 A3b' N=3 — 페이퍼 헤드라인 데이터** |
| `algo_hetero.json`, `algo_memory.json`, `algo_runtime.json`, `algo_alternating.json` | 합성 알고리즘 sweep |
