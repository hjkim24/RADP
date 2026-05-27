# RADP — 구현 히스토리 (Phase Log)

PETALS 기반 이기종 엣지 클러스터 분산 LLM 추론 시스템. plan.md의 연구 계획에 따라 단계적으로 구현됩니다.

이 파일은 **각 Phase의 목표/구현/검증/한계**를 기록합니다. 새 기능이 추가될 때마다 맨 아래 "## 업데이트 규칙" 섹션의 형식으로 새 항목을 추가합니다.

## 현재 상태 요약

- **Phase 0 ~ 4 + Phase 2.5 ~ 2.10 + Phase A1 + Phase B2 + Phase OPS1 완료** (총 15개 Phase)
- **단위 테스트 60개 + slow 통합 테스트 14개 모두 통과**
- ruff ✓ / mypy strict (33 source files) ✓
- 지원 모델: OPT, LLaMA, Mistral (단일 + sharded safetensors/bin 모두)
- Mac CPU에서 OPT-125M / SmolLM-135M / SmolLM-1.7B (2-shard) 검증; Jetson은 **Ansible playbook 한 줄로 배포**

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

## Phase OPS1 — Ansible 기반 Jetson 함대 자동 배포

**목표**: N대의 Jetson + 코디네이터 호스트에 RADP를 한 줄 명령으로 설치/실행. 운영 오버헤드 0 (k8s 같은 daemon 없음). 노드 재부팅·프로세스 죽음·노드 통째 죽음 각각 다른 계층이 담당.

**구현**:
- **CLI env-var 지원** (Ansible/systemd 친화):
  - [cli/worker.py](radp/cli/worker.py): 모든 flag가 `RADP_DEVICE_ID` / `RADP_BIND` / `RADP_COORD` / `RADP_HEARTBEAT_INTERVAL_S` / `RADP_TORCH_DEVICE` / `RADP_DTYPE` 로 fallback
  - [cli/coordinator.py](radp/cli/coordinator.py): `--config` → `RADP_CONFIG`
  - systemd unit이 `Environment=` 줄로 깔끔하게 설정 가능 (long ExecStart 없음)
- **deploy/ 디렉터리** 신규:
  - [ansible.cfg](deploy/ansible.cfg) — SSH pipelining + ControlPersist, 8 forks
  - [playbook.yml](deploy/playbook.yml) — 3개 play: common(모든 노드) → workers → coordinator
  - [inventory.ini.example](deploy/inventory.ini.example) — 호스트별 IP + device_id 템플릿
  - [group_vars/all.yml.example](deploy/group_vars/all.yml.example) — 모델/placement/recovery/포트/heartbeat 전부 변수화
  - **roles/common**: OS 패키지 + NTP + 코드 sync (git) + venv + Jetson용 torch wheel + radp pip install + proto stub 생성 (idempotent)
  - **roles/radp-worker**: systemd unit 템플릿 + enable/start + handler로 `notify: restart radp-worker`
  - **roles/radp-coordinator**: `/etc/radp/cluster.yaml` 템플릿 렌더 (모든 워커 IP 자동 수집) + systemd unit + enable/start
  - [deploy/README.md](deploy/README.md) — 사용법 + tag별 부분 배포 + JetPack/torch wheel 가이드 + 트러블슈팅

**책임 분담**:
| 계층 | 도구 | 역할 |
|---|---|---|
| 배포/설정 (1회성) | Ansible | OS 셋업, 코드 sync, systemd unit 설치, cluster.yaml 렌더 |
| 프로세스 라이프사이클 | systemd | 부팅 시 자동 시작, `Restart=on-failure` |
| 분산 추론 + 장애 복구 | RADP (Phase 3) | heartbeat / activation cache replay / R-기반 라우팅 |

→ k8s 같은 런타임 daemon 불필요. 4GB Jetson에서 ~512MB 절약.

**자주 쓰는 명령**:
```bash
ansible-playbook playbook.yml                # 전체 배포
ansible-playbook playbook.yml --tags update  # 코드만 sync + 재시작
ansible-playbook playbook.yml --tags config  # cluster.yaml만 재렌더
ansible-playbook playbook.yml --limit '!jetson-2'
ansible workers -a "journalctl -u radp-worker -n 50"
```

**검증 결과**:
- ruff ✓ / mypy strict ✓ / 단위 테스트 60개 (CLI 회귀 없음)
- `ansible-playbook --syntax-check` 통과 (uvx ansible-core 사용)
- `ansible-inventory --list` 4개 group + 4개 host 정확히 인식

**실 보드 검증 (2026-05-23, JetPack 6.1 / Jetson 환경)**:
- 5 worker + 1 coordinator 함대 inventory 채우고 SSH 키 + sudo 통신 확인 (`ansible all -m ping` ✓)
- jetson-4 1대에 `--tags install` full deploy: `/home/isp/radp/` 생성 + venv + torch 2.5.0 (CUDA True) + numpy 1.26.4 + radp + proto stubs 임포트 정상
- 발견된 호환성 이슈 2건 픽스 (commit `22b906a`):
  - **NumPy 2.x vs NVIDIA torch wheel ABI 충돌** → `pyproject.toml`에 `numpy<2` 핀
  - **`stdout_callback = yaml`** (community.general 12.0.0에서 제거됨) → `default + result_format=yaml`로 교체
- 나머지 4 worker + coordinator 전체 배포는 추가 보드 도착 후 일괄 진행 예정

**의도된 한계**:
- `jetson_torch_wheel_url`은 사용자가 JetPack 버전에 맞게 수동 설정 (auto-detect 미구현; `direct_url.json`에서 추적은 가능)
- JetPack 4 (Python 3.6)는 비지원 — pyproject의 `requires-python = ">=3.10"`이라 JetPack 6+ 권장
- systemd 서비스 시작 + end-to-end 추론 (장애 시나리오 포함) 검증은 전체 함대 배포 후 진행 예정

---

## Phase B2 — Sharded safetensors / bin 지원

**목표**: 큰 모델(OPT-6.7B, Llama-2-7B 등 5GB↑)이 HF에 단일 파일이 아닌 **shard로 저장됨** (`model.safetensors.index.json` + `model-00001-of-NNNNN.safetensors`). 현재는 단일 파일만 지원해서 이런 모델을 못 로드. 단계적으로 worker가 자기 layer 범위에 필요한 shard만 다운로드하도록 확장 → 에지 디바이스의 디스크/대역폭 절감.

**구현**:
- [common/model_utils.py](radp/common/model_utils.py):
  - `WeightsLocation` dataclass 신규: fmt ∈ {`safetensors`, `bin`, `safetensors_sharded`, `bin_sharded`}, path(single) 또는 index path(sharded), `weight_map`(sharded), `model_id`(sharded shard 다운로드용)
  - `_find_weights_file` → `_find_weights_location`: 단일 → sharded 순서로 시도, sharded면 index JSON 파싱
  - `_WeightReader` 재설계: 4가지 형식 모두 처리. sharded는 **lazy per-shard 다운로드 + 캐시** (`get_tensor(key)` 호출 시 해당 shard 처음이면 download + open, 이후 캐시 재사용)
  - `_get_shard_safetensors`, `_get_shard_bin` 헬퍼 추가
- `load_stage_blocks`: `_find_weights_location` 사용으로 single-line 변경 (나머지 로직 동일 — 다형성)

**핵심 트레이드오프**:
- 4-worker 클러스터, 32-layer Llama-2-7B (4 shard ≈ 3GB each): 각 워커가 자기 quarter만 → **shard 1-2개만 다운로드** (4× 절감)
- `keys()`는 weight_map만 보고 다운로드 0회 → 인덱스 조회 비용 무료
- 첫 layer 접근 시에만 shard 1개 다운로드, 같은 shard 내 추가 access는 캐시 hit

**검증 결과**:
- ruff ✓ / mypy strict ✓
- **단위 테스트 4개** (test_sharded_weights.py): 합성 sharded 레이아웃(HF 의존 없이 tmp 디렉터리에 직접 2-shard + index 작성) 기반:
  - keys() 다중 shard 통합 ✓
  - lazy shard 다운로드 + 캐시 (monkeypatch로 hf_hub_download 스텁) ✓
  - 단일 파일 회귀 없음 ✓
  - index JSON 파싱 정합성 ✓
- **slow 통합 테스트 2개** (test_sharded_integration.py): 실제 SmolLM-1.7B (~3.4GB, 2-shard):
  - `_find_weights_location` → `safetensors_sharded` 정확히 감지 ✓
  - `load_stage_blocks(model_id, 5, 8)` 결과가 full model load 후 slice [4:8]과 **byte-for-byte 일치** ✓
- 기존 slow 통합 12개 (OPT/SmolLM-135M 단일 파일) 회귀 없음 ✓

**의도된 한계**:
- 다운로드 단위는 shard 단위 (텐서 단위 streaming 아님). 한 shard 안의 일부 layer만 필요해도 shard 전체 다운로드. 텐서별 HTTP range request는 다음 단계 후보
- 단일 process 안에서만 shard 캐시 공유 (워커 간 공유 디스크라면 OS file cache로 자연스럽게 절감되긴 함)

---

## Phase A1 — R-Ψ alternating optimization

**목표**: plan.md §3.4의 "구현 단순화" 해소. 단일샷 DP (라운드로빈 기준 R 1회 결정)에서 (R, Ψ) joint fixed point를 찾는 alternating 알고리즘으로 확장. plan.md §7.2의 향후 확장 항목.

**구현**:
- [common/types.py](radp/common/types.py): `AlternatingResult`, `AlternatingIterationLog` dataclass 추가
- [coordinator/scheduler.py:_forward](radp/coordinator/scheduler.py): `ref_placement` 파라미터 받도록 리팩토링 (기존 default는 round-robin → 단일샷 회귀 없음)
- [coordinator/scheduler.py:solve_alternating](radp/coordinator/scheduler.py): 메인 alternating 루프
  - 매 iteration: Ψ_{i-1}로 R_i 결정 → ref=Ψ_{i-1}로 DP → 새 Ψ_i
  - 자가 일치 검증: Ψ_i가 ITS OWN backup burden에서도 memory_check 통과하는지 확인
  - 수렴: `(R_i == R_{i-1}) AND (Ψ_i == Ψ_{i-1}) AND self_consistent(Ψ_i)`
  - 안전망: max_iterations 도달 시 본 적 있는 best self-consistent fallback
- [coordinator/scheduler.py:_memory_self_check](radp/coordinator/scheduler.py): placement를 ITS OWN reference로 memory_check 재실행
- [experiments/run_algorithm.py](experiments/run_algorithm.py): `run_alternating_gain` 시나리오 추가 (loose vs tight memory × homo/hetero)

**찾아낸 버그 (Phase 1 유산)**:
[recovery_table.py:determine_recovery_table](radp/coordinator/recovery_table.py)가 누적 backup reservation을 추적하지 않아 모든 소스가 fastest peer로 R을 몰빵 → 실제론 메모리 초과로 infeasible인데 R 결정 단계에서 못 잡음. **수정**: `reserved: dict[DeviceId, int]`를 도입해 순차 할당하며 차감, 다른 backup이 이미 잡고 있으면 다음 후보로 넘어감.

**검증 결과**:
- ruff ✓ / mypy strict ✓
- 단위 테스트 56개 통과 (alternating 8개 추가):
  - homogeneous → 2 iter 만에 수렴
  - heterogeneous → alternating ≤ single-shot 보장
  - max_iterations=1 → converged=False, self-consistent fallback 반환
  - infeasibility / NoRecoveryError 전파
  - explicit initial_placement 전달

**실험 결과 (6 시나리오)**:
| | scenario | single max(s) | alt max(s) | iters | Δ% |
|---|---|---:|---:|---:|---:|
| | homogeneous_3x12_loose | 0.202 | 0.202 | 2 | 0.00% |
| | strong_hetero_3x12_loose | 0.113 | 0.113 | 2 | 0.00% |
| | homogeneous_4x12_loose | 0.152 | 0.152 | 2 | 0.00% |
| | strong_hetero_4x12_loose | 0.102 | 0.102 | 2 | 0.00% |
| | **strong_hetero_4x12_tight** | **0.152** | **0.152** | **3** | **0.00%** (다른 fixed point) |
| | strong_hetero_5x12_tight | 0.127 | 0.127 | 2 | 0.00% |

**해석**: 모든 시나리오에서 alternating ≤ single-shot. tight memory 케이스(`strong_hetero_4x12_tight`)는 **다른 (R, Ψ) fixed point [5,2,2,3] vs single의 [4,2,3,3]**을 찾았으나 max_stage_time은 동일. 즉:
- **Phase 1 단순화는 실제로 대부분 케이스에서 near-optimal** (긍정적 결과)
- alternating의 가치: (a) 수학적 엄밀성/수렴 증명, (b) tied optima 탐색, (c) tight-memory edge에서 R 재분배 보장

**의도된 한계**:
- 수렴은 보장되지 않음 (alternating optimization의 본질적 특성). max_iterations safeguard로 처리
- 자가 일치 검증은 binary (pass/fail) — soft penalty가 더 견고한 수렴 동작을 줄 수 있음
- objective는 여전히 max_stage_time만 최적화 (R의 download time은 cost로 들어가지 않음)

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

- **동시 다중 장애 대응** (plan.md §7.2): R(j)가 단일 백업. 후보 리스트로 확장 가능. 에지 디바이스 메모리 제약상 보류 (사용자 결정, 2026-05-20).
- **Backpressure / queue**: 동시 요청이 thread pool 넘으면 자연 큐잉만; admission control 없음
- **Online 재배치**: 부하 변화에 따른 동적 placement 조정 없음
- **bitsandbytes int4**: CUDA 전용 → Mac에선 float32만 검증
- **Jetson 실측**: 1대(jetson-4) 환경 셋업 (torch CUDA + numpy + radp + proto) 검증 완료 (2026-05-23). 5+1 전체 함대 배포 + systemd 서비스 + end-to-end 추론(정상/장애) 검증은 추가 보드 도착 후 진행

---

## 남은 작업 후보 (백로그)

새 Phase를 시작할 때 이 목록에서 골라 진행한다. 우선순위는 사용자 결정 시점에 정함. 각 항목은 plan.md 참조 + 예상 작업 깊이로 정렬.

### A. 알고리즘 / 논문 기여 강화 (plan.md §7.2 / §8)

| | 항목 | 내용 | 예상 깊이 |
|---|---|---|---|
| **A2** | **동시 다중 장애 대응** | `R(j): DeviceId → list[DeviceId]`로 확장. 1차/2차 백업 후보. 동시 2-node 장애에서도 복구. 메모리 제약 다시 검토 필요. | 중 |
| **A3** | **Online 재배치** | 부하 변화/노드 추가·제거 시 placement 동적 재최적화. 진행 중인 요청 마이그레이션 정책 필요. | 큼 |
| **A4** | **Proactive 예측 복구** | 하드웨어 텔레메트리(온도, 메모리 압력 등) → 장애 사전 감지 → 미리 backup promotion. plan.md §8 "향후 연구 방향". | 큼 |

### B. 운영 검증 / 실데이터 (논문 실험 데이터)

| | 항목 | 내용 | 예상 깊이 |
|---|---|---|---|
| **B1** | **실제 Jetson Nano 클러스터 검증** | OPT-6.7B INT4를 4GB Jetson × 3-4대에서 실제 구동. plan.md §6.1 환경. config만 변경 → 코드 변경 없음. 실측 데이터로 REPORT.md 업데이트. | 중 (하드웨어 의존) |
| ~~**B2**~~ | ~~**Sharded safetensors 지원**~~ | **완료** (위 Phase B2 섹션 참조) | — |
| **B3** | **bitsandbytes int4 적용** | CUDA 환경에서 int4 양자화로 메모리 4× 절감. plan.md §6.2 OPT-6.7B INT4 / LLaMA-7B INT4 시나리오. | 소 (CUDA 환경 필요) |

### C. 시스템 완성도

| | 항목 | 내용 | 예상 깊이 |
|---|---|---|---|
| **C1** | **Backpressure / admission control** | 동시 요청이 thread pool 한도 넘을 시 큐잉 정책 + SLO 기반 거절. 메모리 압력 시 신규 요청 거부. | 중 |
| **C2** | **True streaming Generate** | 현재 `gateway.generate`는 전체 토큰 생성 후 일괄 yield. 토큰 단위 실시간 streaming으로 변경 → TTFT 사용자 체감 ↑. recovery 흐름과 함께 재설계 필요. | 중 |
| **C3** | **Beam search / 더 다양한 sampling** | 현재 greedy + temperature/top-k/top-p. Beam search는 별도 path. nucleus + repetition penalty 등 추가. | 소-중 |

### D. 프로파일링 기반 자동 결정 흐름 (Auto-Scheduling)

**배경**: 현재 `cluster_placement`/`cluster_recovery`는 사용자가 [deploy/group_vars/all.yml](deploy/group_vars/all.yml)에 손으로 적음. Scheduler는 코드로 완성돼 있지만 호출되는 곳이 없음. `network_profiler.profile_network()`는 `NotImplementedError`. 이 갭을 메워 코디네이터가 부팅 시 실측 → DP → 자동 placement까지 일관 처리하게 만드는 작업.

**디자인 결정 (2026-05-27)**:
1. **Scheduler + 모니터링은 코디네이터에서** — Mac/별도 orchestrator 아님. 코디네이터 startup이 모든 걸 책임. 보드 추가/제거 시 부팅 한 번으로 재계산.
2. **네트워크 측정은 gRPC Ping/Echo로** — iperf3 등 외부 도구 아님. RADP 자체 transport 사용 → 실 워크로드 대표성 ↑. proto 확장 필요.

**Phase 분할** (의존성: P0 → P1 → P2 → P3 → P4 → P5):

| | 항목 | 내용 | 예상 깊이 |
|---|---|---|---|
| **D0** | **Proto 확장** | `WorkerService`에 `Ping`, `MeasurePeer`, `ProfileLayers` 3개 RPC 추가. `HeartbeatRequest`에 `total_memory_bytes`, `device_class` 필드. `bash scripts/gen_proto.sh` 재생성. | 소 (1-2h) |
| **D1** | **Worker-side 구현** | (a) `Ping` 에코 핸들러. (b) `MeasurePeer` — 워커가 peer worker의 gRPC client가 돼서 N라운드 ping, bw+lat 산출. (c) `ProfileLayers` — `radp.profiler.layer_profiler.profile_layers()` 호출, 모델 임시 로드/언로드. (d) heartbeat에 total_memory + device_class 포함. | 중 (3-4h) |
| **D2** | **Coordinator ProfileOrchestrator** | 신규 [radp/coordinator/profile_orchestrator.py](radp/coordinator/profile_orchestrator.py). `wait_for_all_workers()` (heartbeat 대기 + DeviceProfile 수집), `collect_layer_profiles(model_id)` (병렬 `ProfileLayers` RPC), `collect_network_profile()` (full-mesh `MeasurePeer`). | 중 (3-4h) |
| **D3** | **Coordinator startup 재설계** | server.py 부팅 흐름 변경: cluster.yaml 로드(토폴로지만) → gRPC 시작 → 워커 등록 대기 → ProfileOrchestrator 실행 → `Scheduler(spec).solve_alternating()` → 결과로 워커에 LoadStage/LoadBackup. CLI 플래그 `--schedule-mode={auto,manual}` 추가 (manual은 기존 동작). | 중 (2-3h) |
| **D4** | **cluster.yaml 스키마 정리** | auto 모드면 `placement`/`recovery` 필드 생략. `coordinator.schedule_mode`, `coordinator.slo`, `coordinator.profiling.{layer_warmup, layer_repeats, network_payload_bytes, network_rounds}` 신규. [cluster.yaml.j2](deploy/roles/radp-coordinator/templates/cluster.yaml.j2) + group_vars/all.yml 수정. | 소 (1h) |
| **D5** | **(선택) 주기적 재측정 + 동적 재배치** | N분마다 ProfileOrchestrator 재실행 → diff 임계 이상이면 scheduler 재호출 → 워커 drain/swap. A3(Online 재배치)와 사실상 통합 가능. | 큼 |

**검증 마일스톤**:
- **MVP1** (D0 + D1.a/c + D2 partial): 코디네이터가 layer profile 자동 수집 — 로그에 "5 workers × 12 layers" 출력
- **MVP2** (D3 + uniform network placeholder): 자동 placement 결정까지 — 로그에 "scheduler decided: jetson-1: 1-3, ..." 출력 + Generate 정상
- **MVP3** (D1.b + D2 complete): 실측 네트워크 통합 — 5×5 bw/lat 매트릭스 + 그 기반 placement
- **완성** (D4): 사용자가 placement를 yaml에 적지 않아도 시스템 정상 가동

**현 수동 흐름과의 매핑**:
- 지금: `group_vars/all.yml`에 `cluster_placement` 적음 → cluster.yaml 렌더 → 코디네이터 그대로 사용
- D 완료 후: `group_vars/all.yml`에는 model + SLO + profiling 파라미터만 → 코디네이터 startup에 자동 결정

### 권장 선택 가이드

- **논문 기여 강화**: **A2** (동시 다중 장애) — plan.md §7.2 명시 항목, 측정 가능한 차별점
- **시스템 자동화 강화**: **D** (Auto-Scheduling) — 사용자가 yaml에 placement 안 적어도 됨. 보드 추가/변동에 강함. 논문에서 "프로파일링 기반 적응형" 어필 가능
- **실증 강화**: **B1 + B2** — 진짜 큰 모델로 실데이터 생성
- **사용자 체감 개선**: **C2** (true streaming) — 데모/UX 임팩트 큼

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
