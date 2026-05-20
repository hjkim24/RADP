# RADP — 구현 히스토리 (Phase Log)

PETALS 기반 이기종 엣지 클러스터 분산 LLM 추론 시스템. plan.md의 연구 계획에 따라 단계적으로 구현됩니다.

이 파일은 **각 Phase의 목표/구현/검증/한계**를 기록합니다. 새 기능이 추가될 때마다 맨 아래 "## 업데이트 규칙" 섹션의 형식으로 새 항목을 추가합니다.

## 현재 상태 요약

- **Phase 0 ~ 4 + Phase 2.5 ~ 2.10 완료** (총 12개 Phase)
- **단위 테스트 48개 + slow 통합 테스트 12개 모두 통과**
- ruff ✓ / mypy strict (33 source files) ✓
- 지원 모델: OPT, LLaMA, Mistral (단일 safetensors/bin 파일 한정)
- Mac CPU에서 OPT-125M / SmolLM-135M 검증; Jetson 도착 시 config만 변경하면 즉시 동작

---

## Phase 0 — 프로젝트 스캐폴딩

**목표**: plan.md §4.1의 모듈 구조를 충실히 반영한 초기 디렉터리 + 타입 + 인터페이스 + 빌드 도구 구성.

**구현 결정**:
- 통신: **gRPC** (sync)
- 패키지 관리: **uv + pyproject.toml**
- 스캐폴딩 깊이: 인터페이스 + 타입 정의 (실제 로직은 `NotImplementedError` 스텁)
- 개발 도구: pytest + ruff + mypy strict

**핵심 파일**:
- [pyproject.toml](pyproject.toml) — uv/ruff/mypy/pytest 일괄 설정
- [radp/common/types.py](radp/common/types.py) — `Placement`, `RecoveryTable`, `DPResult`, `ClusterSpec` 등 핵심 dataclass
- [radp/common/proto/radp.proto](radp/common/proto/radp.proto) — gRPC 서비스 정의
- [scripts/gen_proto.sh](scripts/gen_proto.sh) — proto 코드 생성 헬퍼
- 각 모듈에 docstring + 타입 시그니처 스텁

**검증**: ruff ✓ / mypy strict ✓ / pytest collection (6 skipped, spec only) ✓

---

## Phase 1 — Recovery-Aware DP 알고리즘

**목표**: plan.md §3의 DP 본체 + 복구 테이블 결정 + 메모리 제약 검사. 하드웨어 의존성 없이 알고리즘 정합성 증명.

**구현**:
- [radp/coordinator/memory_check.py](radp/coordinator/memory_check.py) — `stage_self_memory`, `backup_memory_for`, `memory_check` (자기 + 백업 메모리 합)
- [radp/coordinator/recovery_table.py](radp/coordinator/recovery_table.py) — `determine_recovery_table` 그리디 휴리스틱 (`T_download + T_recompute` 최소화)
- [radp/coordinator/scheduler.py](radp/coordinator/scheduler.py) — `Scheduler.solve` (DP forward + backtracking), `uniform_placement` 헬퍼
- [radp/common/types.py](radp/common/types.py) — `ClusterSpec`에 `activation_bytes` 필드 추가

**검증 결과**:
- 단위 테스트 **15개 통과** (memory_check 6 + recovery_table 3 + scheduler 6)
- 핵심 케이스: 균질 2-디바이스 2-2 분할, 이기종 fast/mid/slow 가중 분할, SLO 위반 → infeasible, L<M → infeasible, R→DP end-to-end

**의도된 단순화** (plan.md §3.4와 일치):
- `R`은 라운드로빈 초기 placement 기준으로 한 번에 결정 (R–Ψ alternating 미구현)
- `memory_check`의 백업 burden은 라운드로빈 ref_placement로 추정
- SLO 체크는 TBT만 강제 (스테이지당 비용 ≤ TBT_SLO)

---

## Phase 1.5 — 프로파일러 (실측 인프라)

**목표**: Mac에서 실제 모델로 layer별 compute time + memory 측정. Jetson 도착 시 바로 재실행 가능한 인터페이스 확정.

**구현**:
- [radp/common/model_utils.py](radp/common/model_utils.py): `ModelHandle` dataclass + `load_model` (CPU/CUDA/MPS) + `get_transformer_layers` (OPT/LLaMA/GPT-2 자동 감지) + `slice_stage` + KV cache 추정
- [radp/profiler/layer_profiler.py](radp/profiler/layer_profiler.py) — forward-hook 기반 per-layer 타이밍 + 파라미터 메모리 측정 + JSON I/O + 다중 디바이스 결과 병합
- [radp/profiler/network_profiler.py](radp/profiler/network_profiler.py) — JSON load/save + `uniform_network` 헬퍼 (라이브 측정은 Phase 2에서)
- [radp/cli/profile.py](radp/cli/profile.py) — `radp-profile` 실배선

**검증 결과**:
- 단위 테스트 27개 통과 (model_utils 6 + profilers 5 추가)
- **실제 OPT-125M 12레이어 프로파일링**: Mac CPU에서 layer당 ~1.3ms, ~30MB

---

## Phase 2 — 분산 추론 인프라 MVP

**목표**: prefill-only end-to-end. OPT-125M, 모든 워커가 전체 모델 보유 (스코프 단순화). gRPC sync.

**구현**:
- [radp/common/tensor_io.py](radp/common/tensor_io.py) — hidden_states + attention_mask 직렬화 (torch.save over BytesIO)
- [radp/common/protocol.py](radp/common/protocol.py) — `WorkerClient` / `CoordinatorClient` (256MB 메시지 한도)
- [radp/common/proto/__init__.py](radp/common/proto/__init__.py) — protobuf stub을 `Any`로 re-export (타입 깔끔)
- [radp/worker/stage_runner.py](radp/worker/stage_runner.py) — 모델 로드 + OPT 블록 슬라이스 실행
- [radp/worker/server.py](radp/worker/server.py) — `WorkerService` gRPC 서버
- [radp/coordinator/gateway.py](radp/coordinator/gateway.py) — embedding → 워커 파이프라인 → final_norm + lm_head
- [radp/coordinator/server.py](radp/coordinator/server.py) — `CoordinatorConfig` (YAML) + 배포 + `Generate` 스트리밍
- [radp/cli/coordinator.py](radp/cli/coordinator.py), [radp/cli/worker.py](radp/cli/worker.py) — SIGTERM/SIGINT 처리
- [experiments/configs/local_demo.yaml](experiments/configs/local_demo.yaml), [experiments/demo_local.sh](experiments/demo_local.sh) — 데모

**검증 결과**:
- 통합 테스트: 분산 파이프라인 logits == 단일 모델 forward logits (atol=5e-4)
- End-to-end 데모: `The quick brown fox` → ` is a good one.` (5 토큰, OPT-125M)

**의도된 한계** (이후 Phase에서 해결):
- Prefill만, KV cache 없음 → 매 토큰 전체 시퀀스 재처리 (Phase 2.6)
- OPT family만 (Phase 2.10)
- 모든 워커가 전체 모델 보유 (Phase 2.5)
- 장애 처리 없음 (Phase 3)

---

## Phase 2.5 — 진짜 가중치 슬라이싱

**목표**: 워커가 자기 stage만 메모리에 로드 (Jetson 4GB 제약 시뮬레이션). 큰 모델 적합성 결정.

**구현**:
- [radp/common/model_utils.py](radp/common/model_utils.py): `load_stage_blocks` — `OPTDecoderLayer(config, layer_idx)` 인스턴스를 layer 범위만큼 생성하고 safetensors/bin에서 해당 키만 읽어 weight load. **full model은 절대 로드 안 함**
- `_WeightReader`: safetensors + .bin 양쪽 형식 지원 (facebook/opt-125m은 main에 .bin만 존재)
- [radp/worker/stage_runner.py](radp/worker/stage_runner.py): `load_stage_blocks` 호출, 이미 로드된 stage는 백업으로 재사용
- [radp/coordinator/gateway.py](radp/coordinator/gateway.py): 코디네이터가 full model 로드 후 `decoder.layers` 즉시 free (embedding + lm_head만 유지)
- 메모리 측정: `measure_resident_bytes()` + 모든 load에 RSS 로그

**검증 결과**:
- 단위 테스트 41개 통과 (load_stage_blocks weight byte-match 추가)
- slow 통합 테스트 4개 통과 (모든 기존 테스트 + 새 weight 일치 테스트)

**실측 메모리 (OPT-125M, Mac CPU)**:
| 컴포넌트 | RSS | 비고 |
|---|---|---|
| Worker (primary 4 + backup 4 blocks) | 678–748 MB | 8/12 layers만 보유 (67%) |
| Coordinator (after free decoder.layers) | 664 MB | -165 MB |

**의도된 한계**:
- 단일 safetensors / bin 파일만 (sharded 미지원, OPT-6.7B 같은 큰 모델은 다음 단계)
- 빈 layer 초기 random init → safetensors 덮어쓰기 → 잠깐 2× 메모리 피크

---

## Phase 2.6 — KV cache + autoregressive

**목표**: stateless re-prefill 제거. transformers 5.x `DynamicCache`로 워커 측 per-request KV 캐시 보관.

**구현**:
- proto: `EvictRequest` RPC 추가
- [radp/worker/stage_runner.py](radp/worker/stage_runner.py): `(request_id, stage_key) → DynamicCache`. `is_prefill=True`면 캐시 리셋, 아니면 in-place append. `evict_request` 메서드
- [radp/common/protocol.py](radp/common/protocol.py): `WorkerClient.evict_request`
- [radp/worker/server.py](radp/worker/server.py): `EvictRequest` 핸들러
- [radp/coordinator/gateway.py](radp/coordinator/gateway.py) **재설계**:
  - `_RequestState`로 per-request `past_length` + `generated_token_ids` 추적
  - `_prefill(id, prompt)` + `_decode_step(id)` 분리
  - `generate(prompt, max_tokens)`: prefill 1회 + decode (max_tokens-1)회 + 완료 시 워커에 `EvictRequest`
  - 장애 시 RpcError → mark_dead → 전체 re-prefill (백업은 KV 없으니까)

**검증 결과**:
- slow 통합 테스트: **분산 generate == single-model `model.generate()` 토큰 단위 일치**
- 속도: OPT-125M, 2 워커, 16 토큰 = 228ms (14.2 ms/token)

---

## Phase 2.7 — ActivationCache replay 복구

**목표**: 장애 시 전체 re-prefill 대신 죽은 stage만 history replay → 살아있는 워커 KV 보존.

**구현**:
- [radp/coordinator/activation_cache.py](radp/coordinator/activation_cache.py) **재설계**: 단일 blob → **append-only 히스토리 리스트** per `(request_id, stage_key)`. per-request LRU 제거 (replay 정합성)
- [radp/coordinator/gateway.py:_run_pipeline](radp/coordinator/gateway.py):
  - cache는 **성공 후에만** append (실패한 step은 자연히 제외)
  - RPC 실패 시: `mark_dead` → `_replay_stage_history` → plan 재조회 → 같은 step 재시도
- `_replay_stage_history`: 첫 entry는 `is_prefill=True`, 나머지는 False로 backup에 순차 전송 → backup `DynamicCache`가 죽은 워커 상태와 비트단위 일치

**검증 결과**:
- 단위 테스트 42개 통과 (activation_cache 5개: append/isolation/evict/LRU/recency)
- slow 통합 테스트: **mid-generation kill 후 recovered tokens == baseline tokens**

**Phase 2.6 vs 2.7 비교**:
| | Phase 2.6 | Phase 2.7 |
|---|---|---|
| 회복 전략 | 전체 re-prefill | 죽은 stage만 history replay |
| 다른 워커 KV | 버려짐 | 보존됨 |
| 회복 비용 | ~전체 prefill | ~1 stage × history 길이 |

---

## Phase 2.8 — Concurrent requests

**목표**: 여러 사용자가 동시에 generate 호출. Thread safety + 채널 풀링 + throughput.

**구현**:
- [radp/coordinator/gateway.py](radp/coordinator/gateway.py): **Persistent gRPC channel pool** + cached stubs. RunStage/EvictRequest가 채널 setup 비용 안 냄. `_get_stub(device_id)` 헬퍼 + `close()` cleanup
- [radp/worker/server.py](radp/worker/server.py) + [radp/coordinator/server.py](radp/coordinator/server.py): `max_workers=4 → 16`

**Thread safety 검증**:
- `itertools.count` — CPython atomic
- `_requests` dict — request_id별 분리 키
- `_dead`, `_execution_plan` — `_plan_lock`
- `ActivationCache` / `DynamicCache` — 자체 lock 또는 per-key 분리
- PyTorch nn.Module forward (inference) — concurrent-safe

**검증 결과**:
- slow 통합 테스트: **8 동시 generate → 모두 baseline과 동일한 토큰**
- Throughput (3-worker OPT-125M, Mac CPU):
  | C | tok/s | scaling |
  |---:|---:|---:|
  | 1 | 63 | 1.00× |
  | 2 | 100 | 1.58× |
  | 4 | 108 | 1.71× |
  | 8 | 89 | 1.41× (Mac CPU 포화) |

---

## Phase 2.9 — Sampling + EOS

**목표**: greedy 외 temperature/top-k/top-p/seed + EOS-aware stopping.

**구현**:
- [radp/coordinator/sampling.py](radp/coordinator/sampling.py) **신규**: `sample_next_token(logits, *, temperature, top_k, top_p, generator)` — `temperature=0`이면 greedy (현재 동작)
- [radp/coordinator/gateway.py](radp/coordinator/gateway.py): `generate()`에 `temperature`, `top_k`, `top_p`, `eos_token_id`, `seed` 인자. `_prefill`/`_decode_step`이 `sampler: Callable` 받음. EOS 매칭 시 즉시 break
- 재현성: seed가 있으면 per-request `torch.Generator` 생성
- [radp/common/proto/radp.proto](radp/common/proto/radp.proto): `GenerateRequest`에 5개 필드 추가 (zero default → 후방 호환)
- [radp/common/protocol.py](radp/common/protocol.py), [radp/coordinator/server.py](radp/coordinator/server.py): forward

**검증 결과**:
- 단위 테스트 48개 통과 (sampling 6개 추가)
- slow 통합 테스트: greedy 결정성 ✓, seed=42 재현성 ✓, sampling ≠ greedy ✓, EOS 즉시 stop ✓

---

## Phase 2.10 — 모델 확장 (LLaMA / Mistral)

**목표**: OPT-only 하드코딩 제거 → LLaMA/Mistral 등 RoPE 기반 모델 지원.

**구현**:
- [radp/common/architectures.py](radp/common/architectures.py) **신규**: `ModelArchitecture` 프로토콜 + 3개 어댑터
  - `OPTArchitecture`: 학습된 position embeddings, `model.decoder.layers.{i}.` prefix
  - `LlamaArchitecture` / `MistralArchitecture` (공통 `_RoPEArchitecture` 베이스): RoPE, `model.layers.{i}.` prefix, worker가 자체 rotary_emb 생성, `position_ids` + `cache_position` + `position_embeddings` 전부 전달
  - `get_architecture(model_type)` 레지스트리
- [radp/common/model_utils.py](radp/common/model_utils.py): `load_stage_blocks`가 `config.model_type` → 어댑터 디스패치
- [radp/worker/stage_runner.py](radp/worker/stage_runner.py): worker가 architecture + aux modules 보유, `_run_blocks` 어댑터 호출
- [radp/coordinator/gateway.py](radp/coordinator/gateway.py): `_embed` / `_head` / decoder 접근 모두 어댑터 위임

**찾아낸 버그 (critical)**:
[stage_runner.py:151](radp/worker/stage_runner.py#L151)의 `cache.get_seq_length()`가 **기본 `layer_idx=0`을 조회**. Worker B가 layer 15-29만 보유하면 layer 0 슬롯은 비어 `0` 반환 → RoPE position 정렬 오류 → decode step 3부터 토큰 불일치. **수정**: `cache.get_seq_length(layer_idx=start-1)`로 자기 stage의 첫 layer 명시.

**검증 결과**:
- 단위 테스트 48개 통과
- slow 통합 테스트 12개 통과: OPT 11개 + **LLaMA SmolLM-135M (분산 generate == single-process model.generate, 토큰 일치)**

**의도된 한계**:
- 단일 safetensors / bin 파일만 (sharded 미지원)
- Mistral은 코드 경로만 동일 (실제 검증 미실시)

---

## Phase 3 — 장애 감지 + 복구 (intermediate; Phase 2.6 이전 구현)

**목표**: heartbeat 기반 장애 감지 + 동기 RPC 실패 감지 + 워커 multi-stage 보유 + 신규 요청 fallback 라우팅.

**구현**:
- [radp/worker/heartbeat_sender.py](radp/worker/heartbeat_sender.py): psutil 기반 free-memory + 주기적 heartbeat
- [radp/coordinator/failure_detector.py](radp/coordinator/failure_detector.py): heartbeat 추적 + 백그라운드 ticker + `mark_failed()` 동기 진입
- [radp/coordinator/activation_cache.py](radp/coordinator/activation_cache.py): per-request × per-stage LRU 캐시 (Phase 2.7에서 history 형식으로 재설계)
- [radp/coordinator/recovery_plan.py](radp/coordinator/recovery_plan.py): `build_execution_plan(Ψ, R, dead)` — 죽은 stage를 R(j)로 대체
- [radp/worker/stage_runner.py](radp/worker/stage_runner.py): **multi-stage 보유** — primary + 다수 backup, run(start, end)로 라우팅
- [radp/coordinator/server.py](radp/coordinator/server.py): Heartbeat 수신 → detector, deploy()가 primary + backup 둘 다 push, FailureDetector 콜백으로 promote_backup 자동 호출
- proto에 `start_layer`/`end_layer` 추가 (RunStageRequest)

**검증 결과**:
- 단위 테스트 41개 (activation_cache 4 + failure_detector 4 + recovery_plan 4 추가)
- slow 통합 테스트: 장애 후 출력 일치 atol=5e-4
- **3-워커 실데모 (SIGKILL worker-b)**: heartbeat timeout → recovery_plan 재계산 → worker-c 백업으로 라우팅 → 동일한 출력

**의도된 단순화**:
- Promote는 bookkeeping flip (워커가 이미 full model 보유 — Phase 2.5에서 가중치 슬라이싱으로 변경)
- 단일 노드 장애만 (plan.md §7.2와 일치)

---

## Phase 4 — 벤치마크 + 분석 인프라

**목표**: plan.md §6의 실험 시나리오 1~4 측정 가능한 harness + 자동 보고서.

**구현**:
- [experiments/_harness.py](experiments/_harness.py): in-process 클러스터 컨텍스트 매니저, baseline placement 전략 (greedy/jupiter-DP/ours), `make_synthetic_spec`, `max_stage_time`, JSON I/O
- [experiments/run_normal.py](experiments/run_normal.py): live OPT-125M throughput / TTFT / TBT
- [experiments/run_failure.py](experiments/run_failure.py): (A) mid-decode cache replay 단위 측정 + (B) e2e wall-clock 비교 (baseline / cache-replay / re-prefill)
- [experiments/run_algorithm.py](experiments/run_algorithm.py): 메모리 민감도 + 이기종 효과 + DP 런타임 sweep (algorithmic)
- [experiments/run_concurrent.py](experiments/run_concurrent.py): throughput vs concurrency
- [experiments/analyze.py](experiments/analyze.py): 모든 JSON → Markdown 보고서
- [experiments/results/REPORT.md](experiments/results/REPORT.md): 생성된 보고서

**핵심 결과 (Mac CPU, OPT-125M)**:
| 항목 | 값 |
|---|---|
| Normal TTFT / TBT | 27 ms / 13 ms |
| Normal throughput | 66 tok/s |
| Failure baseline / cache-replay / re-prefill | 127 / 141 / 145 ms |
| Hetero 6× fast device speedup (ours/greedy) | 1.22× |
| DP runtime @ L=64 M=6 | ~30 ms (O(L²×|D|) 확인) |
| Memory mult=2.0 | ours infeasible, jupiter feasible (backup 미고려) |

---

## 알려진 한계 (현재)

- **Sharded safetensors 미지원**: OPT-6.7B / Llama-2-7B 같은 멀티-shard 모델은 단계적 로딩 추가 필요
- **R-Ψ alternating optimization** (plan.md §7.2): 현재는 라운드로빈 placement 기준 R 1회 결정
- **Backpressure / queue**: 동시 요청이 thread pool 넘으면 자연 큐잉만; admission control 없음
- **Online 재배치**: 부하 변화에 따른 동적 placement 조정 없음
- **bitsandbytes int4**: CUDA 전용 → Mac에선 float32만 검증
- **Jetson 실측**: 코드는 그대로 동작 가능하나 하드웨어 도착 후 재실험 필요

---

## 업데이트 규칙 (Claude 메모)

새 기능을 구현해 통과시키면, 이 파일에 새 섹션을 추가한다. 형식:

```markdown
## Phase X — <이름>

**목표**: <한 문장>

**구현**:
- [path/to/file](path/to/file) — <한 줄 요약>
- ...

**(필요 시) 찾아낸 버그**: <상세>

**검증 결과**:
- 단위 테스트 N개
- slow 통합 테스트 ...
- (있다면) 실측 수치 표

**의도된 한계**: <차후에 다룰 것>
```

그리고 맨 위 "## 현재 상태 요약"의 숫자 (테스트 카운트, source 파일 수, Phase 개수)를 갱신한다.
