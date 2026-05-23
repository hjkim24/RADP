# RADP — 아키텍처 가이드

PETALS 기반 이기종 엣지 클러스터(Jetson Nano 등)에서 분산 LLM 추론을 수행하는 시스템. 핵심 기여는 **레이어 배치(Ψ)와 장애 복구(R)를 단일 DP 안에서 동시에 최적화하는 Recovery-Aware DP** ([plan.md](plan.md)).

이 문서는 **현재 코드베이스의 구조와 데이터 흐름**을 정리합니다. 구현 히스토리/Phase 로그는 [PHASES.md](PHASES.md) 참조.

---

## 1. 디렉터리 구조 한눈에

```
RADP/
├── radp/                         # 메인 패키지
│   ├── common/                   # 공통 타입 + 유틸 + 통신 프로토콜
│   │   ├── types.py              # ClusterSpec / Placement / RecoveryTable / DPResult / Cache 등 핵심 dataclass
│   │   ├── architectures.py      # ModelArchitecture 프로토콜 + OPT/LLaMA/Mistral 어댑터
│   │   ├── model_utils.py        # HF 모델 로드 + sharded safetensors 처리 + per-stage 가중치 슬라이싱
│   │   ├── tensor_io.py          # 워커 ↔ 코디네이터 activation 직렬화
│   │   ├── protocol.py           # gRPC sync 클라이언트 (WorkerClient / CoordinatorClient)
│   │   ├── logging_utils.py      # 통일된 로거 설정
│   │   └── proto/
│   │       └── radp.proto        # gRPC 서비스 + 메시지 정의 (수동 작성)
│   │
│   ├── coordinator/              # 마스터 노드(=클러스터 오케스트레이터)
│   │   ├── scheduler.py          # Recovery-Aware DP + alternating optimization
│   │   ├── recovery_table.py     # R 결정 휴리스틱 (download + recompute 비용)
│   │   ├── recovery_plan.py      # build_execution_plan: 죽은 노드를 R(j)로 대체
│   │   ├── memory_check.py       # plan.md §3.3 (1) 메모리 제약 (self + 백업)
│   │   ├── failure_detector.py   # heartbeat 추적 + 타임아웃 콜백
│   │   ├── activation_cache.py   # per-(request, stage) activation 히스토리 (replay 복구용)
│   │   ├── sampling.py           # greedy / temperature / top-k / top-p
│   │   ├── gateway.py            # 추론 파이프라인 driver: embed → 워커 chain → head → sample
│   │   └── server.py             # gRPC CoordinatorService 서버 + 배포 + heartbeat 수신
│   │
│   ├── worker/                   # 엣지 노드(=Jetson)
│   │   ├── stage_runner.py       # 자기 stage(blocks) 보유 + per-(request, stage) DynamicCache
│   │   ├── heartbeat_sender.py   # 주기적 코디네이터로 free-memory 보고
│   │   └── server.py             # gRPC WorkerService 서버
│   │
│   ├── profiler/                 # 오프라인 측정
│   │   ├── layer_profiler.py     # forward-hook 기반 per-layer 컴퓨트/메모리 측정
│   │   └── network_profiler.py   # 노드 간 대역폭/지연 (현재 JSON I/O만, 라이브 측정은 Phase 2.5+)
│   │
│   └── cli/                      # 엔트리포인트
│       ├── coordinator.py        # `radp-coordinator --config ...`
│       ├── worker.py             # `radp-worker --device-id ... --bind ... --coord ...`
│       └── profile.py            # `radp-profile --model-id ...`
│
├── experiments/                  # 벤치마크 + 분석
│   ├── _harness.py               # 공통 헬퍼: in-process 클러스터, 합성 spec, baseline placement
│   ├── run_normal.py             # live 정상 운영: TTFT/TBT/throughput
│   ├── run_failure.py            # live 장애 복구: cache-replay vs re-prefill
│   ├── run_concurrent.py         # live 동시 요청 throughput sweep
│   ├── run_algorithm.py          # 알고리즘 sweep: 메모리 민감도/이기종/runtime/alternating
│   ├── analyze.py                # 모든 결과 JSON → Markdown REPORT.md
│   ├── configs/                  # YAML 시나리오 설정
│   └── results/                  # JSON 출력 + REPORT.md (gitignored)
│
├── tests/                        # pytest 단위 + 통합 테스트
│   ├── conftest.py               # 공통 fixture: homogeneous/heterogeneous spec
│   ├── test_*.py                 # 단위 테스트 (빠름, 항상 실행)
│   └── test_*_integration.py     # 통합 테스트 (slow 마커, 실모델 다운로드)
│
├── scripts/                      # 빌드 + 자동화
│   ├── gen_proto.sh              # proto stub 생성
│   ├── git-hooks/commit-msg      # Conventional Commits 검증 훅
│   └── claude_hooks/             # Claude Code PostToolUse 훅 (auto-push)
│
├── plan.md                       # 원본 연구 계획
├── PHASES.md                     # 구현 히스토리 (Phase별)
├── ARCHITECTURE.md               # 이 파일
└── README.md                     # 빠른 시작
```

---

## 2. 계층별 책임

### 2.1 `common/` — 모든 컴포넌트가 공유하는 contract + 유틸

**역할**: 코디네이터/워커/벤치마크 모두가 의존하는 가장 안정된 레이어. 여기를 바꾸면 전체에 파급 효과.

| 파일 | 핵심 export | 책임 |
|---|---|---|
| [types.py](radp/common/types.py) | `ClusterSpec`, `Placement`, `RecoveryTable`, `Stage`, `DPResult`, `AlternatingResult`, `SLO`, `DeviceProfile`, `LayerProfile`, `NetworkProfile` | DP 입출력과 시스템 전체 데이터 모델. 모두 frozen dataclass |
| [architectures.py](radp/common/architectures.py) | `ModelArchitecture` 프로토콜 + `OPTArchitecture` / `LlamaArchitecture` / `MistralArchitecture` + `get_architecture(model_type)` | 모델 패밀리별 (block 클래스, 가중치 키 prefix, embed/head, RoPE 등) 차이를 격리. 새 모델 추가 시 어댑터만 추가하면 됨 |
| [model_utils.py](radp/common/model_utils.py) | `ModelHandle`, `load_model`, `load_stage_blocks`, `WeightsLocation`, `_WeightReader` | HF 모델 다운로드/로드, **per-stage 가중치 슬라이싱** (워커가 자기 layer만 로드), single + sharded safetensors/bin 모두 처리 |
| [tensor_io.py](radp/common/tensor_io.py) | `encode(dict[str,Tensor]) -> bytes`, `decode(bytes) -> dict[str,Tensor]` | activation을 gRPC 페이로드로 직렬화 (torch.save over BytesIO) |
| [protocol.py](radp/common/protocol.py) | `WorkerClient`, `CoordinatorClient` | gRPC sync 클라이언트. context manager로 채널 자동 관리. (gateway는 별도로 persistent channel pool 운영) |
| [proto/radp.proto](radp/common/proto/radp.proto) | `WorkerService` (LoadStage/RunStage/LoadBackup/PromoteBackup/EvictRequest), `CoordinatorService` (Heartbeat/Generate) | gRPC 인터페이스. `scripts/gen_proto.sh`로 stub 재생성 |
| [logging_utils.py](radp/common/logging_utils.py) | `configure_logging()`, `get_logger(name)` | stderr 통일 포맷 |

### 2.2 `coordinator/` — 클러스터 마스터

**역할**: 사용자 요청을 받고, 워커 클러스터를 오케스트레이션. 메모리는 풍부하다 가정 (성능 좋은 보드).

| 파일 | 핵심 export | 책임 |
|---|---|---|
| [scheduler.py](radp/coordinator/scheduler.py) | `Scheduler.solve(R)`, `Scheduler.solve_alternating()`, `uniform_placement(...)` | **Recovery-Aware DP 본체** (forward + backtracking) + R-Ψ alternating (Phase A1) |
| [recovery_table.py](radp/coordinator/recovery_table.py) | `determine_recovery_table(spec, placement)` | 휴리스틱: 각 노드의 백업을 `T_download + T_recompute` 최소화 + 누적 reservation 추적 |
| [recovery_plan.py](radp/coordinator/recovery_plan.py) | `build_execution_plan(Ψ, R, dead)`, `inverse_recovery(R)` | 죽은 노드 j 자리에 R(j)를 끼워 넣은 실행 계획 생성 |
| [memory_check.py](radp/coordinator/memory_check.py) | `memory_check(node, [start,end], R, placement, layers)` | plan.md §3.3 (1): self + Σ(R⁻¹(node) 백업) ≤ Mem(node) |
| [failure_detector.py](radp/coordinator/failure_detector.py) | `FailureDetector.record(hb)`, `tick()`, `mark_failed(id)`, `start()/stop()` | heartbeat 데드라인 추적 + 백그라운드 ticker + 콜백 호출 |
| [activation_cache.py](radp/coordinator/activation_cache.py) | `ActivationCache.append/get_history/evict_request` | per-(request, stage) **활성화 히스토리** 저장. 장애 시 backup 워커에 replay → KV 캐시 복원 (Phase 2.7) |
| [sampling.py](radp/coordinator/sampling.py) | `sample_next_token(logits, temperature, top_k, top_p, generator)` | 단일 토큰 샘플링 (greedy 또는 nucleus 등) |
| [gateway.py](radp/coordinator/gateway.py) | `RequestGateway.generate(prompt, ...)`, `mark_dead`, `close()` | **추론 파이프라인 driver** — 이 시스템의 심장. 자세한 흐름은 §3.2 참조 |
| [server.py](radp/coordinator/server.py) | `CoordinatorConfig.from_yaml`, `CoordinatorServer.deploy()/start()` | YAML 파싱 + 워커에 LoadStage/LoadBackup push + gRPC 서비스 시작 + FailureDetector 와이어업 |

### 2.3 `worker/` — 엣지 노드 (Jetson)

**역할**: 자기에게 할당된 layer slice 실행. 메모리 빠듯하다 가정 (4GB Jetson Nano).

| 파일 | 핵심 export | 책임 |
|---|---|---|
| [stage_runner.py](radp/worker/stage_runner.py) | `StageRunner.load_primary/load_backup/promote_backup/evict_request/run` | **여러 stage를 동시 보유**(primary + 임의 개수의 backup) + per-(request, stage) `DynamicCache` 관리 + 아키텍처 어댑터 통해 block forward 수행 |
| [heartbeat_sender.py](radp/worker/heartbeat_sender.py) | `HeartbeatSender.start()/stop()` | 백그라운드 스레드, 주기적으로 코디네이터에 `(device_id, free_memory_bytes, ts_ns)` 전송 |
| [server.py](radp/worker/server.py) | `WorkerServer.start()/stop()` | gRPC WorkerService 서버 + HeartbeatSender 시작/종료 라이프사이클 |

### 2.4 `profiler/` — 오프라인 측정

| 파일 | 책임 |
|---|---|
| [layer_profiler.py](radp/profiler/layer_profiler.py) | HF 모델 로드 후 PyTorch forward hook으로 per-layer 컴퓨트 시간/메모리 측정 → `list[LayerProfile]` JSON 저장 |
| [network_profiler.py](radp/profiler/network_profiler.py) | 현재 JSON load/save + `uniform_network` 헬퍼만. 라이브 측정은 Phase 2+ |

### 2.5 `cli/` — 엔트리포인트 (pyproject.toml의 `[project.scripts]`로 노출)

| 명령 | 동작 |
|---|---|
| `uv run radp-coordinator --config X.yaml` | YAML 로드 → `CoordinatorServer.deploy()` → `.start()` |
| `uv run radp-worker --device-id D --bind H:P [--coord H:P]` | `WorkerServer` 시작, coord 주어지면 heartbeat |
| `uv run radp-profile --model-id M --device-id D --output J` | layer 프로파일 측정 + JSON 저장 |

### 2.6 `experiments/` + `tests/`

- **벤치마크**: `experiments/_harness.py`가 in-process 클러스터를 빌드 → 각 run_*.py가 시나리오 수행 → `results/<name>.json` 저장 → `analyze.py`가 합쳐 Markdown
- **테스트**: 단위는 빠름 (`pytest`), 통합은 `@pytest.mark.slow` (HF 모델 다운로드 필요, `pytest -m slow`)

---

## 3. End-to-End 워크플로우

### 3.1 시스템 부팅 / 배포

```
┌──────────────┐
│ YAML config  │  (model_id, workers[], placement, recovery)
└──────┬───────┘
       │
       ▼  CoordinatorConfig.from_yaml
┌──────────────────────────────────────────────────────────────┐
│ CoordinatorServer.deploy():                                  │
│   for stage in placement:                                    │
│      WorkerClient(addrs[stage.device]).load_stage(...)       │
│   for k, [j,...] in inverse_recovery(R):                     │
│      for each j:                                             │
│         WorkerClient(addrs[k]).load_backup(j_stage, ...)     │
└─────────────────────┬────────────────────────────────────────┘
                      │  각 RPC가 워커 측에서:
                      ▼
┌──────────────────────────────────────────────────────────────┐
│ Worker StageRunner.load_primary / load_backup:               │
│   load_stage_blocks(model_id, start, end):                   │
│     - _find_weights_location → single 또는 sharded 감지       │
│     - 각 layer마다 OPTDecoderLayer/LlamaDecoderLayer 인스턴스 │
│     - prefix 매칭으로 자기 layer 가중치만 load (~stage 크기)  │
│   _stages[(start, end)] = blocks                             │
└─────────────────────┬────────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────────────┐
│ CoordinatorServer.start():                                   │
│   - RequestGateway 생성:                                      │
│       * load_model(model_id)  (coord용 embed/head/lm_head)   │
│       * decoder.layers = ModuleList()  (블록 비움 → 메모리)   │
│       * persistent gRPC channel per worker                   │
│   - FailureDetector 시작 (heartbeat ticker)                  │
│   - gRPC CoordinatorService 시작                             │
└──────────────────────────────────────────────────────────────┘
```

**동시에 워커 측**: `WorkerServer.start()` → gRPC 시작 + `HeartbeatSender.start()` → 0.5s마다 코디네이터에 `(device_id, free_mem)` 보고.

### 3.2 정상 추론 (Phase 2.6 KV cache + Phase 2.9 sampling)

```
User → CoordinatorClient.Generate(prompt, max_tokens, temperature, ...)
         │
         ▼  CoordinatorService.Generate (server.py)
       Gateway.generate(prompt, max_tokens, sampling params):
         │
         ├─ sampler = sample_next_token (closure with seed-tied torch.Generator)
         │
         ├─ _prefill(request_id, prompt):
         │    ┌───────────────────────────────────────────────────────────┐
         │    │ input_ids = tokenizer(prompt)                             │
         │    │ hidden = arch.embed(decoder, input_ids, ...)              │
         │    │   (OPT: embed_tokens + embed_positions)                   │
         │    │   (LLaMA: embed_tokens only; RoPE is per-block)           │
         │    │ attention_mask_4d = _prepare_4d_causal_attention_mask     │
         │    │ for stage in current_execution_plan:                      │
         │    │    blob = encode({hidden, attention_mask})                │
         │    │    try:                                                   │
         │    │       result = WorkerClient(stage).run_stage(             │
         │    │                 blob, request_id, start, end,             │
         │    │                 is_prefill=True)                          │
         │    │    except RpcError:                                       │
         │    │       gateway.mark_dead(stage.device)                     │
         │    │       _replay_stage_history(request_id, stage_key)        │
         │    │       (retry — see §3.3)                                  │
         │    │    cache.append(request_id, stage_key, blob)              │
         │    │    hidden = decode(result)["hidden_states"]               │
         │    │ logits = arch.head(decoder, lm_head, hidden)              │
         │    │ next_id = sampler(logits[0, -1, :])                       │
         │    │ requests[request_id] = _RequestState(past_length=seq_len, │
         │    │                                       generated=[next_id])│
         │    └───────────────────────────────────────────────────────────┘
         │
         └─ loop max_tokens-1 times:
              _decode_step(request_id):
                 prev_token = state.generated[-1]
                 past_len = state.past_length + len(state.generated) - 1
                 hidden = arch.embed(decoder, [[prev_token]], past_kv_length=past_len)
                 attention_mask_4d = causal mask covering past_len+1
                 # 같은 _run_pipeline, is_prefill=False:
                 #   워커 StageRunner.run() 호출 시 cache.get_seq_length(first_layer_idx)
                 #   가 past_len 반환 → RoPE position 정렬 → block forward → cache append
                 logits = head(hidden)
                 next_id = sampler(logits[0, -1, :])
                 state.generated.append(next_id)
                 if eos_token_id and next_id == eos: break

         finally:
            evict_everywhere(request_id)  # 모든 워커에 EvictRequest

       return token_ids → tokenizer.decode → GenerateChunk stream → user
```

### 3.3 장애 복구 (Phase 3 감지 + Phase 2.7 cache replay)

```
시점 t0: 워커 b 가 SIGKILL/네트워크 단절.

A) 비동기 감지 경로 (heartbeat 타임아웃):
   HeartbeatSender(b) 중단 → coordinator는 hb 미수신
   FailureDetector.tick() (백그라운드, 1s 주기):
     now_ns - records[b].last_ts_ns > timeout_seconds?
        → mark_dead(b) 콜백 호출
   on_failure(b):
     gateway.mark_dead(b)  →  execution plan 재계산 (build_execution_plan):
       plan = [..., R(b) takes b's stage range, ...]
     CoordinatorServer는 promote_backup(b) RPC를 R(b)에게 호출

B) 동기 감지 경로 (활성 RPC 실패):
   _run_pipeline 중 stage[idx].device가 b인데 b 죽음
   → grpc.RpcError 발생
   → mark_dead(b)
   → _replay_stage_history(request_id, stage_key):
        history = activation_cache.get_history(request_id, stage_key)
        new_owner = build_execution_plan에서 b 자리에 들어간 R(b)
        for i, blob in enumerate(history):
            WorkerClient(new_owner).run_stage(blob, request_id,
                                              is_prefill=(i==0))
        → new_owner의 DynamicCache가 b가 가지고 있던 상태로 재구축됨
   → plan 다시 조회 → 현재 stage 재시도 (이번엔 new_owner로)

결과:
   - 살아있는 워커들의 KV는 그대로 보존
   - new_owner는 b의 가중치(LoadBackup 시점에 이미 메모리에 보유)와 history로 즉시 인계
   - 토큰 시퀀스는 baseline과 동일 (Phase 2.7 통합 테스트로 보장)
```

### 3.4 동시 요청 (Phase 2.8)

- gRPC 서버의 ThreadPoolExecutor(max_workers=16)가 동시 Generate 처리
- 각 Generate는 `gateway.generate()`를 독립 thread에서 호출
- thread safety:
  - `_request_counter = itertools.count(1)` — CPython atomic
  - `_requests[request_id]` — request_id별 분리 키, 충돌 없음
  - `_dead`, `_execution_plan` — `_plan_lock` 보호
  - `ActivationCache`, `DynamicCache` — 자체 lock
  - PyTorch nn.Module forward(inference) — concurrent-safe
  - Persistent gRPC channels — thread-safe
- 워커 측도 동일: 같은 `nn.ModuleList(blocks)`를 여러 thread가 동시 호출 OK, cache는 (request_id, stage_key) 분리

---

## 4. 핵심 데이터 구조

### `ClusterSpec` ([types.py](radp/common/types.py))

DP의 입력. 다음을 묶음:
- `devices: list[DeviceProfile]` — id, total_memory_bytes, compute_throughput
- `layers: list[LayerProfile]` — layer_idx, memory_bytes, compute_time per device
- `network: NetworkProfile` — bandwidth/latency per device pair
- `slo: SLO` — ttft_seconds, tbt_seconds
- `activation_bytes: int` — 스테이지 간 activation 크기 (T_comm 계산)

### `Placement = list[Stage]`

순서가 의미 있는 파이프라인. `Stage(start_layer, end_layer, device_id)`. 첫 stage가 입력, 마지막 stage가 출력.

### `RecoveryTable = dict[DeviceId, DeviceId]`

`R[j] = k` ⇔ j 죽으면 k가 인계 (단일 백업; Phase A2에서 list로 확장 후보).

### DynamicCache (transformers 5.x)

워커가 `(request_id, stage_key) → DynamicCache`로 보유. transformers의 native cache 타입. 각 block의 attention이 자기 `layer_idx`로 K/V 추가/조회. **첫 layer_idx ≠ 0인 워커는 `cache.get_seq_length(layer_idx=start-1)`로 정확한 past_length 조회 필수** (Phase 2.10에서 발견된 버그 수정).

### `AlternatingResult` ([types.py](radp/common/types.py))

Phase A1의 `Scheduler.solve_alternating()` 출력:
- `placement`, `recovery`, `max_stage_time` — 최종 (Ψ, R)
- `iterations: int`, `converged: bool` — 수렴 여부
- `history: list[AlternatingIterationLog]` — iteration별 (max_stage, self_consistent, psi_changed, r_changed) 로그

---

## 5. 알고리즘 핵심 한눈에

### Recovery-Aware DP ([scheduler.py:_forward](radp/coordinator/scheduler.py))

```
A[y][n] = min over split ∈ [n-1, y-1]:
              max(A[split][n-1],  T_stage(split+1..y, d_n) + T_comm(d_{n-1}, d_n))
            subject to:
              memory_check(d_n, split+1, y, R, ref_placement, layers)
              T_stage + T_comm ≤ SLO.tbt
```

- 시간 복잡도: O(L² × |D|) — L=레이어 수, |D|=디바이스 수
- backtracking: `choice[y][n]` 보고 [1..L]을 단계적으로 쪼개기

### R 결정 ([recovery_table.py](radp/coordinator/recovery_table.py))

각 j에 대해, k ∈ D\{j} 중 비용 최소:
```
cost(j, k) = T_download(j → k) + T_recompute(k, j_layers)
constraint: Mem(k) - self_usage(k) - reserved[k] ≥ stage_bytes(j)
```
**순차적**으로 R[j] = best_k 결정하며 `reserved[best_k] += stage_bytes(j)`. 다음 source j'는 이미 예약된 만큼 차감된 free로 후보 평가 (Phase A1에서 추가된 cumulative tracking).

### R-Ψ Alternating ([scheduler.py:solve_alternating](radp/coordinator/scheduler.py))

```
Ψ₀ = uniform_placement (round-robin)
for i in 1..max_iterations:
    R_i = determine_recovery_table(spec, Ψ_{i-1})
    Ψ_i = DP(spec, R_i, ref=Ψ_{i-1})
    self_consistent = memory_self_check(Ψ_i, R_i)
    if best_consistent is None or (self_consistent and max_stage < best):
        best_consistent = current
    if R_i == R_{i-1} and Ψ_i == Ψ_{i-1} and self_consistent:
        return converged
    prev_R, prev_Ψ = R_i, Ψ_i
return best_consistent  # fallback
```

---

## 6. 확장 포인트

### 새 모델 패밀리 추가

[architectures.py](radp/common/architectures.py)에 어댑터 추가:
```python
class MyArchitecture:
    name = "my_model_type"  # config.model_type 매칭
    def make_block(self, config, layer_idx): ...
    def weight_prefix(self, layer_idx): ...    # safetensors 키 prefix
    def get_decoder(self, model): ...           # 임베딩/노름 보유 모듈
    def embed(self, decoder, input_ids, attention_mask_2d, past_kv_length): ...
    def head(self, decoder, lm_head, hidden): ...
    def make_aux(self, config, dtype, device): ...   # rotary_emb 같은 보조 모듈
    def run_block(self, block, hidden, attention_mask, cache, past_length, aux): ...
```
레지스트리 `_REGISTRY`에 `"my_model_type": MyArchitecture()` 추가. 끝.

### 새 sampling 전략

[sampling.py](radp/coordinator/sampling.py)의 `sample_next_token`에 파라미터 추가 + 로직. Gateway는 `closure` 형태로 전달하므로 호출처는 변경 없음.

### 새 장애 복구 전략

[recovery_plan.py:build_execution_plan](radp/coordinator/recovery_plan.py) 또는 [gateway.py:_run_pipeline](radp/coordinator/gateway.py)의 에러 핸들러 수정. 현재는 "단일 백업으로 즉시 대체 + cache replay".

### 새 placement 전략 (baseline 비교용)

[experiments/_harness.py](experiments/_harness.py)의 `greedy_placement`, `dp_placement`, `dp_placement_no_recovery` 옆에 추가.

---

## 7. 실행 / 테스트 가이드

### 셋업
```bash
uv sync --extra dev                       # 의존성 + 개발 도구
bash scripts/gen_proto.sh                 # gRPC stub 생성
git config core.hooksPath scripts/git-hooks  # commit-msg 훅 활성화
```

### 테스트
```bash
uv run pytest -q                          # 단위 (~2초, 60개)
uv run pytest -m slow                     # 통합 (HF 모델 다운로드, ~2-3분)
uv run ruff check radp tests experiments
uv run mypy radp                          # strict, 33 source files
```

### 데모
```bash
bash experiments/demo_local.sh            # 1 coord + 2 worker, prompt → token
bash experiments/demo_failure.sh          # 3 worker, mid-run kill, recovery
```

### 벤치마크
```bash
uv run python -m experiments.run_normal     --requests 5 --max-tokens 12
uv run python -m experiments.run_failure    --max-tokens 10 --kill-after-tokens 4
uv run python -m experiments.run_concurrent --concurrencies 1 2 4 8
uv run python -m experiments.run_algorithm  # 알고리즘 sweep
uv run python -m experiments.analyze --out experiments/results/REPORT.md
```

### 새 phase 워크플로 (Claude 자동)
1. 작업 → 검증 통과
2. PHASES.md 새 섹션 + 카운트 갱신
3. 사용자에게 "이상 없으면 commit+push할까요?" 확인
4. OK 받으면 `git commit -m "feat(...): phase X - ..."` → commit-msg 훅이 형식 검증 → PostToolUse 훅이 자동 `git push`

---

## 8. 현재 지원 매트릭스

| 항목 | 지원 |
|---|---|
| **모델 패밀리** | OPT, LLaMA, Mistral (+ 어댑터 추가로 GPT-2 등) |
| **가중치 형식** | single safetensors, single bin, **sharded safetensors, sharded bin** |
| **양자화** | float32 / float16 / bfloat16. (int4는 bitsandbytes 의존, CUDA 환경에서) |
| **장치** | CPU (검증됨), CUDA (코드 준비됨), MPS (코드 준비됨) |
| **장애 처리** | 단일 노드 장애 동기/비동기 감지 + cache-replay 복구 + re-prefill fallback |
| **동시 요청** | thread-safe (max 16 동시 RPC 워커당) |
| **샘플링** | greedy + temperature + top-k + top-p + seed (재현성) + EOS-aware stopping |
| **검증된 모델 (Mac CPU)** | OPT-125M, SmolLM-135M, SmolLM-1.7B |

[PHASES.md](PHASES.md)에 각 기능의 Phase별 도입 시점 + 의도된 한계 + 백로그 정리.
