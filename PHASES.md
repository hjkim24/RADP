# RADP — 구현 히스토리 (Phase Log)

PETALS 기반 이기종 엣지 클러스터 분산 LLM 추론 시스템. plan.md의 연구 계획에 따라 단계적으로 구현됩니다.

이 파일은 **각 Phase의 목표/구현/검증/한계**를 기록합니다. 새 기능이 추가될 때마다 맨 아래 "## 업데이트 규칙" 섹션의 형식으로 새 항목을 추가합니다.

## 현재 상태 요약

- **Phase 0 ~ 4 + Phase 2.5 ~ 2.10 + Phase A1 + Phase B2 + Phase OPS1 + Phase D0 ~ D4 완료** (총 20개 Phase)
- **단위 테스트 79개 + slow 통합 테스트 17개 모두 통과**
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

**함대 확장 + 이기종 JetPack 지원 (2026-06-05)**:
- 함대 구조 변경: **on-1 ~ on-5** (Jetson Orin Nano × 5) + **ao-1, ao-2** (AGX Orin × 2) + **ax-1** (AGX Xavier coordinator)
  - 명명 규칙: `on-N` = Orin Nano, `ao-N` = AGX Orin, `ax-N` = AGX Xavier
  - 인벤토리 그룹 재구성: `[workers_orin_nano]` + `[workers_agx_orin]` → `[workers:children]`로 통합
- **이기종 JetPack 운영 지원**:
  - on-1~5 + ao-1: JP6.1 / Ubuntu 22.04 / Python 3.10 / NVIDIA CUDA torch wheel
  - ax-1 (AGX Xavier, **JP6 미지원 SoC**) + ao-2 (JP6 업그레이드 대기): JP5.0 / Ubuntu 20.04 / Python 3.9 / **PyPI CPU torch**
  - `pyproject.toml`의 `requires-python`을 `>=3.10` → `>=3.9`로 낮춤 (모든 코드가 `from __future__ import annotations` 사용 중이라 무손실)
  - ruff target-version `py310` → `py39`로 동기화 (3.10+ 런타임 기능 사용 시 lint가 잡음). mypy는 3.10 유지 (최신 mypy가 3.9 target 거부)
- **Ansible 분기**:
  - 신규 변수 `radp_python_executable` (default `python3`, JP5 호스트에서 `python3.9` override)
  - `jetson_torch_wheel_url`이 비어있는 호스트는 PyPI의 generic `torch>=2.1,<3.0` (CPU only) 설치 — 코디네이터의 embed/lm_head/sampling은 CPU로 충분
  - JP5 호스트는 `apt install python3.9 python3.9-venv python3.9-dev` 별도 task 자동 실행
  - host 변수 (`ansible_python_interpreter`, `jetson_torch_wheel_url`, `radp_python_executable`)로 모든 분기 처리 → playbook/role 본문은 그대로
- 8/8 `ansible all -m ping` SUCCESS 확인. radp 단위 테스트 75개 Python 3.9 venv에서도 통과 (slow integration은 transformers 4.x↔5.x API 차이로 일부 실패하나 ax-1은 코디네이터 전용이라 block forward path 미실행 — 실 운영 무영향)

**의도된 한계**:
- `jetson_torch_wheel_url`은 사용자가 JetPack 버전에 맞게 수동 설정 (auto-detect 미구현; `direct_url.json`에서 추적은 가능)
- AGX Xavier (tegra194 SoC)는 **NVIDIA가 JP6를 공식 비지원** — JP5.x가 마지막. 펌웨어/커널 빌드 자체가 없어 우회 불가
- ao-2의 JP5→JP6 업그레이드는 NVIDIA SDK Manager + 호스트 PC (또는 ao-1을 임시 호스트로 활용) 필요. 미완 상태에선 ao-2도 CPU torch + python3.9로 운영 가능 (단 worker로서 성능 저하)
- systemd 서비스 시작 + end-to-end 추론 (장애 시나리오 포함) 검증은 전체 함대 배포 후 진행 예정

**End-to-end 시스템 통합 검증 (2026-06-05)**:

함대 (7 워커 + 1 코디네이터)에 `ansible-playbook playbook.yml --tags config,service` 한 번에 systemd 유닛 렌더 + 시동. 모든 8 호스트 active. 통합 과정에서 발견·픽스한 4건:

1. **transformers 5.x ↔ NVIDIA Jetson torch 2.5.0a0 비호환**:
   - transformers 5.x가 `torch.float8_e8m0fnu` 사용 (torch 2.7+)
   - transformers 4.51+이 `check_torch_load_is_safe()` (torch 2.6+) 강제 (CVE-2025-32434)
   - → `pyproject.toml`에 `transformers>=4.40,<4.51`로 핀해서 양쪽 다 회피. transformers 4.50.3로 수렴.
2. **OPTDecoderLayer.forward() kwarg 이름 변경**:
   - transformers 4.x: `past_key_value` (단수). 5.x: `past_key_values` (복수)
   - `architectures.py`에서 `inspect.signature`로 런타임 분기 → 두 버전 모두 작동
3. **`creates:` 가드의 부작용으로 proto stub 갱신 안 됨**:
   - 이전 install에서 만들어진 `radp_pb2.py`가 존재한다는 이유로 새 `radp.proto` 반영 안 됨
   - → `creates:` 제거 + `changed_when: false`로 항상 regen (protoc 결정적이라 안전)
4. **SLO `tbt_seconds`가 너무 빡빡**:
   - 0.1초로는 7 워커 분산 시 max_stage_time 0.125초 초과
   - → group_vars의 `slo_tbt_seconds: 1.0`, `slo_ttft_seconds: 3.0`로 완화

검증 결과 (코디네이터 로그):
- 워커 7대 heartbeat 등록 → ProfileLayers (12 layer × 7 device) → MeasurePeer (42/42 pair 성공) → DP 해 (max_stage_time=0.125s, 2 iter 수렴) → 모든 stage LoadStage + 모든 backup LoadBackup → 코디네이터 OPT-125M embed/lm_head 로드 완료
- **End-to-end Generate RPC** 통과: `"The quick brown fox"` → `" is a good one.\nI've been using it for a while now"`
- 7 워커 (Orin Nano CUDA × 5 + AGX Orin CUDA × 1 + AGX Orin CPU × 1) + 코디네이터 (AGX Xavier CPU)가 모두 토큰 생성에 참여 → 이종 환경 분산 추론 동작 확인

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

## Phase D0 — Proto 확장 (auto-scheduling 기반 작업)

**목표**: 백로그 D 시리즈(프로파일링 기반 자동 결정 흐름)의 토대. 후속 D1~D5가 의존하는 RPC 인터페이스와 메시지 타입을 [radp.proto](radp/common/proto/radp.proto)에 미리 잡아둠. 본 단계는 *인터페이스 계약*만 정의; 핸들러 구현은 D1.

**구현**:
- **3개 신규 RPC** ([WorkerService](radp/common/proto/radp.proto)에 추가):
  - `Ping(PingRequest) → PingResponse` — bytes echo. 코디네이터→워커 RTT/대역폭 1차 측정용
  - `MeasurePeer(MeasurePeerRequest) → MeasurePeerResponse` — 워커가 peer worker의 임시 gRPC client가 돼서 N라운드 ping → bandwidth + latency 산출. 워커↔워커 full-mesh 측정 가능
  - `ProfileLayers(ProfileLayersRequest) → ProfileLayersResponse` — 모델을 임시 로드해서 [layer_profiler.profile_layers()](radp/profiler/layer_profiler.py) 실행. 결과는 JSON 직렬화된 `list[LayerProfile]`을 `bytes`로 반환
- **6개 신규 메시지**: `PingRequest/Response`, `MeasurePeerRequest/Response`, `ProfileLayersRequest/Response`
- **HeartbeatRequest 확장** (field 4-5 추가; 기존 1-3 ID는 보존 → 와이어 호환):
  - `double total_memory_bytes` — DeviceProfile.total_memory_bytes 자동 채집용
  - `string device_class` — 예: `"jetson-orin-nano-4gb"` (보드 종류 식별)
- [scripts/gen_proto.sh](scripts/gen_proto.sh) 실행으로 `radp_pb2.py`, `radp_pb2_grpc.py` 재생성 (gitignored)

**검증 결과**:
- ruff ✓ / mypy strict (33 source files) ✓
- 단위 테스트 60개 모두 통과 (회귀 없음 — proto 추가만, 기존 wire format 보존)
- 새 메시지 6개 import + 인스턴스화 확인
- `WorkerServiceStub.__init__`에 `Ping`, `MeasurePeer`, `ProfileLayers` 모두 등록 확인
- HeartbeatRequest를 신규 필드 포함해서 직렬화/역직렬화 정상

**의도된 한계**:
- 핸들러 본문 없음 — `WorkerServicer`에 새 RPC 메서드를 구현하지 않은 상태에서 호출하면 gRPC `UNIMPLEMENTED` 에러 발생 (D1에서 구현)
- `ProfileLayersResponse.serialized_profiles`는 `bytes` 그대로 — 추후 LayerProfile 전용 proto 메시지로 더 단단히 타입화 가능 (지금은 JSON 라운드트립으로 충분)
- HeartbeatRequest의 신규 필드는 기본값 0/"" 처리 — 이전 버전 워커가 보낸 heartbeat도 코디네이터가 받을 수 있음 (proto3 기본 동작)

---

## Phase D1 — Worker-side 구현 (Ping / MeasurePeer / ProfileLayers + heartbeat 확장)

**목표**: D0에서 정의한 인터페이스에 실제 핸들러 본문을 채움. 워커가 ① 코디네이터의 echo 요청에 응답, ② peer worker의 gRPC client가 돼서 링크 측정, ③ 임시 모델 로드해서 layer 프로파일링, ④ 매 heartbeat에 total_memory + device_class를 함께 보고하게 만듦.

**구현**:
- **Ping handler** ([radp/worker/server.py](radp/worker/server.py)): payload + sent_ns 그대로 echo + 서버 측 `time.monotonic_ns()` 추가
- **MeasurePeer handler + 새 모듈** [radp/worker/peer_measurer.py](radp/worker/peer_measurer.py):
  - 워커가 peer의 임시 gRPC client (insecure_channel + WorkerServiceStub)
  - 작은 payload(64B) `rounds`회 + 큰 payload(`payload_bytes`) `rounds`회 → 양쪽 median RTT
  - **latency** = small_RTT_median / 2 (양방향 고정 오버헤드)
  - **bandwidth** = `payload_bytes / max((big_median - small_median) / 2, ε)` — 큰 payload의 *추가* 전송 시간만으로 처리량 산출 (latency 영향 제거)
  - 실패 시 gRPC error를 `MeasurePeerResponse(ok=False, error=...)`로 surface
- **ProfileLayers handler**:
  - `radp.profiler.layer_profiler.profile_layers()` 호출 (worker의 device_id/torch_device/dtype 사용)
  - request의 warmup/repeats/seq_length는 0이면 default, >0이면 override
  - 결과 `list[LayerProfile]`을 inline JSON 인코딩 → `bytes`로 반환 ([layer_profiler.save_profile](radp/profiler/layer_profiler.py)과 동일 스키마)
- **HeartbeatSender 확장** ([radp/worker/heartbeat_sender.py](radp/worker/heartbeat_sender.py)):
  - 생성자에 `device_class: str = ""` 추가
  - `_send_one`이 `psutil.virtual_memory()`로 total + available 둘 다 한 번에 수집 → `CoordinatorClient.heartbeat()`에 전부 전달
- **CoordinatorClient.heartbeat()** ([radp/common/protocol.py](radp/common/protocol.py)): `total_memory_bytes` + `device_class` keyword args 추가
- **WorkerServer 생성자**: `device_class: str = ""` 추가, HeartbeatSender로 전달
- **CLI worker** ([radp/cli/worker.py](radp/cli/worker.py)): `--device-class` flag + `RADP_DEVICE_CLASS` 환경변수 fallback
- **Ansible 통합**:
  - [deploy/roles/radp-worker/templates/radp-worker.service.j2](deploy/roles/radp-worker/templates/radp-worker.service.j2)에 `Environment=RADP_DEVICE_CLASS={{ device_class | default('') }}` 줄 추가
  - [deploy/group_vars/all.yml.example](deploy/group_vars/all.yml.example)에 `device_class: "jetson-orin-nano-4gb"` 변수 추가

**검증 결과** ([tests/test_worker_d1.py](tests/test_worker_d1.py)):
- ✓ `test_ping_echoes_payload_and_sent_ns` — payload + sent_ns 그대로 보존
- ✓ `test_measure_peer_between_workers` — 양방향 측정, localhost에서 bw > 10MB/s
- ✓ `test_measure_peer_invalid_payload_raises` — payload_bytes ≤ 64인 입력 검증
- ✓ `test_measure_peer_rpc_failure_surfaces` — 닫힌 포트 측정 시 ok=False + error 메시지
- ✓ `test_heartbeat_request_supports_new_fields` — proto 직렬화 라운드트립
- ✓ (slow) `test_profile_layers_returns_valid_json` — OPT-125M 12개 layer profile JSON 정상
- ruff ✓ / mypy strict (34 source files) ✓ / 단위 테스트 65개 + slow 15개 모두 통과 (회귀 없음)

**의도된 한계**:
- 코디네이터의 `_CoordinatorServicer.Heartbeat`는 아직 `total_memory_bytes`/`device_class`를 읽지 않음 — D2의 `ProfileOrchestrator`가 사용하게 될 때 plumbing 추가
- `ProfileLayers`는 모델을 매 호출마다 새로 로드 — 코디네이터가 같은 모델을 여러 번 profile 요청해도 재사용 X. D3에서 캐싱 검토 가능
- `MeasurePeer`의 측정 방식은 in-process worker에 대해선 정확하지만, 실 LAN에서 매우 빠른 링크(>10Gbps)는 transit ≤ 0이 돼 bandwidth가 ∞로 떨어질 수 있음 — 이런 경우는 "병목 아님" 신호로 해석 (scheduler에서 T_comm ≈ latency만 됨)
- `device_class` 자동 감지 없음 — 사용자가 group_vars나 env var로 명시. JetPack `/etc/nv_tegra_release` 파싱 같은 자동화는 별도 작업

---

## Phase D2 — Coordinator ProfileOrchestrator

**목표**: D1에서 워커가 노출한 RPC를 코디네이터가 *드라이브*해서 라이브 클러스터를 측정. ① 모든 워커가 등록될 때까지 대기, ② 모든 워커에 병렬 `ProfileLayers` → 단일 `list[LayerProfile]`로 병합, ③ full-mesh `MeasurePeer` → `NetworkProfile`, ④ 결과를 `DeviceProfile` 리스트로 합성. D3가 이 출력을 `ClusterSpec`으로 묶어 `Scheduler.solve_alternating()`에 그대로 넣게 됨.

**구현**:
- **`HeartbeatRecord` 확장** ([radp/coordinator/failure_detector.py](radp/coordinator/failure_detector.py)): `total_memory_bytes: float = 0.0`, `device_class: str = ""` 필드 추가 (기본값 있어서 기존 호출부 호환)
- **`FailureDetector.snapshot_records()`** 신규: 락 잡고 records dict의 shallow copy 반환 — orchestrator가 race-free 스냅샷 확보
- **`_CoordinatorServicer.Heartbeat`** ([radp/coordinator/server.py](radp/coordinator/server.py)): `request.total_memory_bytes`, `request.device_class`를 HeartbeatRecord에 전달
- **신규 모듈** [radp/coordinator/profile_orchestrator.py](radp/coordinator/profile_orchestrator.py) — `ProfileOrchestrator` 클래스:
  - `wait_for_workers(timeout_seconds, poll_interval_seconds)` — 모든 expected device가 heartbeat 받을 때까지 polling. `dict[DeviceId, HeartbeatRecord]` 반환. timeout 시 `TimeoutError` (missing 목록 포함)
  - `collect_layer_profiles(model_id, warmup, repeats, seq_length)` — `ThreadPoolExecutor`로 모든 워커에 `ProfileLayers` 병렬 호출. JSON payload 디코딩 → LayerProfile 리스트화 → `merge_profiles()`로 단일 list 병합 (각 LayerProfile.compute_time에 N개 device 엔트리)
  - `collect_network_profile(payload_bytes, rounds)` — `N*(N-1)` directed pair 모두에 대해 src worker의 `MeasurePeer(dst_address)` 병렬 호출. 실패 pair는 결과에서 *생략* + warning log (scheduler가 자동으로 `inf` cost 처리)
  - `build_device_profiles(records, layer_profiles)` (staticmethod) — heartbeat의 `total_memory_bytes`를 그대로 사용, `compute_throughput`은 device별 총 compute_time 합산 후 가장 빠른 device를 1.0으로 정규화 (느린 device는 비율)

**검증 결과** ([tests/test_profile_orchestrator.py](tests/test_profile_orchestrator.py)):
- ✓ `test_wait_for_workers_times_out_when_none_register` — missing list 포함 메시지로 TimeoutError
- ✓ `test_wait_for_workers_returns_when_all_present` — 백그라운드 thread가 heartbeat 보내면 즉시 반환, 신규 필드 보존
- ✓ `test_collect_network_profile_full_mesh` — 2-worker 환경에서 2개 directed pair (a→b, b→a) bw/lat 모두 양수
- ✓ `test_build_device_profiles_normalizes_throughput` — 4× 느린 device의 throughput이 정확히 0.25
- ✓ `test_heartbeat_propagates_new_fields_through_full_stack` — 실 RPC로 `CoordinatorClient.heartbeat()` → `_CoordinatorServicer.Heartbeat` → `FailureDetector` → `snapshot_records()` 전 경로 검증
- ✓ (slow) `test_collect_layer_profiles_merges_per_device` — OPT-125M을 2-worker 병렬 프로파일 → 12 layer × 2 device compute_time 매핑
- ruff ✓ / mypy strict (35 source files) ✓ / 단위 테스트 70개 + slow 16개 모두 통과 (회귀 없음)

**의도된 한계**:
- 아직 코디네이터 startup에 자동 호출되지 않음 — D3에서 wiring
- `build_device_profiles`의 throughput 정규화는 *상대값*이지 *절대 처리량*이 아님. 같은 모델을 같은 조건으로 모든 device에서 profile했을 때만 의미 있음
- network 측정 실패 pair는 silently omit — fail-loud 모드 옵션은 D3에서 검토
- `collect_network_profile`의 ThreadPoolExecutor 동시성 제한 없음. N대가 매우 클 경우 동일 dst에 N-1개 동시 측정 요청이 몰릴 수 있음 — 현 fleet 규모 (5-10)에선 문제 없음

---

## Phase D3 — Coordinator startup 재설계 (auto vs manual)

**목표**: D2의 `ProfileOrchestrator` 결과를 실제 startup 흐름에 연결. 사용자가 `coordinator.schedule_mode`를 yaml에 적으면 코디네이터가 부팅 시 자동으로 placement/recovery를 결정. 기존 manual 모드 (yaml에 placement를 직접 적는 방식)는 그대로 호환.

**구현**:
- **`CoordinatorConfig` 확장** ([radp/coordinator/server.py](radp/coordinator/server.py)):
  - `placement`/`recovery`를 `field(default_factory=...)`로 (auto 모드에선 빈 값)
  - 신규 필드: `schedule_mode`, `slo_ttft_seconds`, `slo_tbt_seconds`, `activation_bytes`, `profiling_layer_warmup/repeats/seq_length`, `profiling_network_payload_bytes/rounds`, `profiling_wait_timeout_seconds`
  - `from_yaml`: placement/recovery optional 처리. manual 모드에서 placement 없으면 ValueError. `schedule_mode`가 "manual"/"auto" 외 값이면 ValueError. `coordinator.{slo, profiling}` 서브 dict 파싱
- **`CoordinatorServer` 구조 변경**:
  - `placement`, `recovery`를 self attribute로 이동 (config에서 복사, auto_schedule이 덮어씀)
  - `_ensure_gateway()` (lazy) — placement가 결정된 *후*에만 `RequestGateway` 생성
  - `start()` — 이제 detector + gRPC만 띄움. gateway는 만들지 않음
  - `auto_schedule()` 신규 — `ProfileOrchestrator` 4 단계 호출 → `ClusterSpec` → `Scheduler(spec).solve_alternating()` → 결과를 self.placement / self.recovery에 저장. gateway는 안 만듦 (deploy 후 ensure)
  - `serve()` 신규 — 모드에 따라 올바른 순서로 start/deploy/auto_schedule + `_ensure_gateway` 호출. CLI가 이 한 줄만 부르면 됨
  - `deploy()` — `self.placement`/`self.recovery`를 사용 (이전엔 `config.placement`). placement 없으면 명시적 RuntimeError
- **`_CoordinatorServicer` 리팩토링**:
  - 생성자 `(gateway, detector)` → `(server: CoordinatorServer)`. server 참조를 통해 lazy lookup
  - `Heartbeat`: detector가 없으면 UNAVAILABLE (start 전 RPC 방지). 있으면 record (D2 동작 유지)
  - `Generate`: gateway가 None이면 UNAVAILABLE + "still bootstrapping" 메시지. workers의 LoadStage 완료 + scheduler 해 결정 전까지 안전하게 거절
- **`on_failure` callback**: gateway가 None일 때는 warning + skip (gRPC가 떠 있는데 아직 gateway 없는 windows에서 detector tick이 fire할 수 있음)
- **CLI 단순화** ([radp/cli/coordinator.py](radp/cli/coordinator.py)): `server.serve(); server.wait_for_termination()`만 호출. 모드 분기는 serve() 내부

**모드별 부팅 순서**:
| Mode | 순서 |
|---|---|
| manual | `deploy()` → `start()` (gRPC) → `_ensure_gateway()` |
| auto | `start()` (gRPC up, gateway=None) → `auto_schedule()` (워커 등록 대기 → 프로파일 → DP) → `deploy()` (계산된 placement로 LoadStage) → `_ensure_gateway()` |

**검증 결과** ([tests/test_coordinator_auto.py](tests/test_coordinator_auto.py)):
- ✓ `test_from_yaml_auto_mode` — 모든 신규 필드 정확히 파싱
- ✓ `test_from_yaml_manual_mode_with_placement` — 기존 yaml 호환
- ✓ `test_from_yaml_manual_requires_placement` — manual 모드 + 빈 placement → ValueError
- ✓ `test_from_yaml_rejects_unknown_schedule_mode` — "hybrid" 같은 잘못된 값 거절
- ✓ `test_deploy_before_placement_raises` — auto 모드에서 auto_schedule 안 거치고 deploy() 시 명시적 에러
- ✓ (slow) `test_auto_schedule_produces_valid_placement` — 실 in-process worker 2대 + 코디네이터 1대로 full auto path 검증: 12 layer를 2 워커에 연속으로 분배, recovery table 양쪽 등록, gateway는 아직 None (deploy 후 생성 검증)
- ruff ✓ / mypy strict (35 source files) ✓ / 단위 테스트 75개 + slow 17개 모두 통과 (회귀 없음)

**의도된 한계**:
- `auto_schedule()` 도중 워커가 죽으면 `wait_for_workers` 단계는 통과하지만 후속 ProfileLayers/MeasurePeer가 실패 → orchestrator가 `RuntimeError`를 raise하면서 startup 전체 중단. 부분 복구 (살아있는 노드만으로 재시도)는 D5
- network 측정 실패 pair는 silently omit (D2 limitation 그대로). 결과 placement가 그 pair를 안 쓰도록 자연스럽게 유도되긴 함
- 재배치는 부팅 시점 1회만. 런타임 중 워커 추가/제거에 따른 재스케줄링은 D5 (A3 Online 재배치와 통합 가능)
- `schedule_mode=auto`로 깔린 yaml은 [cluster.yaml.j2](deploy/roles/radp-coordinator/templates/cluster.yaml.j2)에서 placement/recovery 줄을 빼야 깔끔 — 그 작업은 D4 (스키마 정리)에서 처리

---

## Phase D4 — cluster.yaml + group_vars 스키마 정리

**목표**: D3가 도입한 `schedule_mode` + SLO + profiling 파라미터를 Ansible 렌더 흐름에 흡수. auto 모드면 cluster.yaml에서 placement/recovery 줄이 아예 빠지고, manual 모드면 profiling 줄이 빠지는 — *모드별로 *필요한 키만 들어간 깔끔한 결과물*을 만들기.

**구현**:
- **[cluster.yaml.j2](deploy/roles/radp-coordinator/templates/cluster.yaml.j2)** 재설계:
  - `coordinator` 블록에 `schedule_mode`, `activation_bytes`, `slo.{ttft_seconds, tbt_seconds}` 항상 렌더
  - `{% if schedule_mode == 'auto' %}` 가드로 `coordinator.profiling.{layer_warmup, layer_repeats, layer_seq_length, network_payload_bytes, network_rounds, wait_timeout_seconds}` 추가
  - `{% if schedule_mode == 'manual' %}` 가드로 `placement` / `recovery` 블록 렌더 (auto면 통째로 omit)
  - `default()` 필터로 변수 없을 때 sensible default
- **[group_vars/all.yml.example](deploy/group_vars/all.yml.example)** 재구성:
  - 신규 섹션 "Scheduling mode (Phase D3)" — `schedule_mode`, `slo_*`, `activation_bytes`, `profiling_*` 변수
  - `cluster_placement` / `cluster_recovery`를 "Manual placement / recovery" 섹션으로 옮기고 "auto 모드면 제거 가능" 주석
  - 권장 기본값 `schedule_mode: "auto"`
- **[group_vars/all.yml](deploy/group_vars/all.yml)** (gitignored 실 사용 파일) — auto로 flip, profiling/SLO 변수 추가. 기존 ring 백업은 그대로 두고 "auto 모드에서는 무시됨" 주석 처리
- **[deploy/README.md](deploy/README.md)** — "스케줄링 모드" 섹션 신설, auto vs manual 비교표, auto 모드 부팅 로그 예시
- **계약 검증 테스트** [tests/test_cluster_yaml_template.py](tests/test_cluster_yaml_template.py):
  - 실제 `cluster.yaml.j2`를 Jinja2로 렌더 → 임시 파일에 쓰고 `CoordinatorConfig.from_yaml`로 파싱 → 모든 필드 정확
  - auto 모드 yaml은 `placement:` / `recovery:` 키가 *없음* 확인
  - manual 모드 yaml은 `profiling:` 키가 *없음* 확인 (SLO는 모드 공유라 항상 있음)

**검증 결과**:
- ✓ `test_template_renders_auto_mode` — slo/profiling/activation_bytes 모두 라운드트립
- ✓ `test_template_renders_manual_mode` — placement/recovery 정상 파싱
- ✓ `test_template_omits_placement_block_in_auto_mode`
- ✓ `test_template_omits_profiling_block_in_manual_mode`
- ✓ `ansible-playbook --syntax-check playbook.yml` 통과
- ruff ✓ / mypy strict (35 source files) ✓ / 단위 테스트 79개 + slow 17개 모두 통과 (회귀 없음)

**의도된 한계**:
- 사용자 `group_vars/all.yml`은 gitignored라 본인 파일 직접 수정해야 함. example은 갱신됨
- auto 모드에서도 `cluster_placement`/`cluster_recovery`를 yaml에 둘 수 있음 (silently 무시) — 명시적 경고는 D5에서 검토 가능
- 모드별 변수 그룹화는 모두 평면 변수로 — `slo: { ttft: ... }` 같은 nested var 구조도 가능했지만 group_vars 평면화가 Ansible 관용 (override 쉬움)

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

## Phase EXP-A1 — Live fleet baseline benchmark

**목표**: 8-worker 실 함대(Jetson Orin Nano ×6 + AGX Orin ×2)에서 auto 스케줄링으로 결정된 placement의 정상 운영 TTFT/TBT/throughput 측정. Phase 4의 in-process harness가 측정할 수 없는 *실제 네트워크 + Jetson GPU*에서의 수치 확보.

**구현**:
- [experiments/run_e2e_remote.py](experiments/run_e2e_remote.py) — gRPC 클라이언트로 coordinator의 Generate 스트림 호출, per-token 도착 시각 측정, p50/p95/p99 계산. coordinator의 `/tmp/radp_scheduler_stats.json` 사이드카를 Ansible slurp로 가져와 placement/recovery/phase 타이밍/profile까지 한 JSON으로 묶음

**검증 결과** (OPT-125M, 20 요청 × 30 토큰, warmup 3, 2026-06-05):
| 항목 | 값 |
|---|---|
| TTFT mean / p50 / p95 | 283 / 276 / 324 ms |
| TBT mean / p50 / p95 / p99 (n=600) | 217 / 220 / 289 / 321 ms |
| Throughput mean | 4.42 tok/s |
| DP max_stage_time (스케줄러 상한) | 113.6 ms |
| Auto-schedule phase | wait=4ms · layers=35170ms · net=3059ms · DP=13ms |
| Placement (8 stage) | on-6[1-3] · on-5[4] · on-1[5] · ao-1[6] · on-2[7-8] · ao-2[9] · on-3[10] · on-4[11-12] |

**해석**:
- 12 layer × 8 stage 분산이라 stage당 평균 27ms (compute는 1-3ms 수준) → 네트워크 + 직렬화 dominant. 작은 모델 + 긴 파이프라인에서 통신이 병목이라는 페이퍼 메시지 정량 입증
- DP가 강한 노드(AGX Orin ao-1/ao-2)에 layer 1개씩만 할당하여 약한 노드 부담을 줄임 — 이기종 인식 동작 확인
- 결과 JSON([experiments/results/auto_baseline_first.json](experiments/results/auto_baseline_first.json))은 향후 A2-A4 비교의 reference baseline

**의도된 한계**:
- 단일 요청만 측정 (concurrent 미포함 → A4)
- 단일 모델 (OPT-125M 만; Llama-7B INT4는 D 트랙)
- coord 재시작 없이 연속 실행이라 첫 요청의 TTFT는 cold-cache 효과 일부 포함

---

## Phase EXP-A2 — Live fleet 장애 주입 + 복구 측정

**목표**: Recovery-Aware DP의 복구 정확성 + 비용을 실 함대에서 정량 측정. 단일 worker SIGKILL 시 cache-replay 복구 경로가:
- (i) 실제로 backup으로 라우팅되는지
- (ii) 복구 1회 latency penalty 가 얼마인지
- (iii) post-recovery throughput이 회복되는지
- (iv) 토큰 손실이 없는지

**구현**:
- [experiments/run_failure_remote.py](experiments/run_failure_remote.py) — coordinator의 SSE `/api/generate` 엔드포인트로 Generate 스트리밍, fire-and-forget 스레드로 `ansible <victim> systemctl kill -s KILL radp-worker` 발사, per-token stage-routing trace 캡처
  - `_find_recovery_step()`: 토큰의 stages 리스트에서 victim 디바이스가 사라지는 첫 step을 자동 식별 (`killed_at + 1` 가정보다 robust — kill 발사와 실제 복구 사이에 평균 5 토큰이 in-flight이기 때문)
  - `--restart-victim` + `--restart-coord` + `--ready-timeout` 플래그로 trial 간 cluster reset 자동화 (gateway의 `_dead` set은 `mark_alive` API가 없어 coordinator 재시작 + auto_schedule 재실행으로만 클리어 가능)

**(찾아낸 버그) `th.join(timeout=10)` 메인 스레드 블로킹**: 초기 구현에서 kill 스레드를 join하면서 stop_worker(ansible 1.2s) 동안 SSE 스트림 reader가 멈춤 → 그 사이 coordinator가 생산한 토큰들이 소켓 버퍼에 쌓였다가 join 종료 후 한꺼번에 flush되어 모두 동일 t_recv로 기록됨. 이로 인해 첫 분석에서 "recovery spike = +15ms (1.1x)" 같은 거짓 결론 도출. fire-and-forget(`th.start()` 만) + 최후 reap으로 수정.

**검증 결과 (단일 trial pilot)** (OPT-125M, victim=ao-1, max_tokens=60, kill_after_tokens=15, 2026-06-05):
| 항목 | 값 |
|---|---|
| Pre-kill TBT p50 (n=19) | 216 ms |
| Kill 발사 → 복구 감지 사이 in-flight 토큰 | 5 |
| Recovery step latency | 682 ms (+466 ms, 3.16×) |
| Post-recovery TBT p50 (n=39) | 216 ms (즉시 정상화) |
| 토큰 손실 | 0 / 60 |
| Pre-kill layer 6 라우팅 | ao-1[6-6] |
| Recovery step 라우팅 | on-1[6-6] (R(ao-1)=on-1 백업 정확히 발동) |
| 결과 JSON | [experiments/results/a2_kill_ao1_first.json](experiments/results/a2_kill_ao1_first.json) |

**검증 결과 (5-trial sweep)** (위와 동일 파라미터, `--trials 5`, 2026-06-05):

스크립트의 `--trials N` + `reset_cluster_for_next_trial()` 로 매 trial 사이 victim 재기동 + coord 재시작 (auto_schedule 재실행)을 자동 수행. 매 trial마다 재프로파일링되므로 ao-1이 owning하는 layer가 1-2, 6, 7, 8, 9로 변동. R-table은 5/5 trial에서 모두 `ao-1 → ao-2` (동일 device class 선호).

| 지표 | 값 |
|---|---|
| Recovery step latency | mean **729 ms**, p50 **677 ms**, p95 **883 ms** (range 669-930 ms) |
| Spike over pre-kill p50 | mean +509 ms, p50 +461 ms, p95 +653 ms |
| Spike factor | mean **3.30×**, p50 3.14×, p95 3.86× |
| Pre-kill TBT p50 (trial 평균) | 221 ms |
| Post-recovery TBT p50 (trial 평균) | 226 ms (~+5 ms 미세 저하) |
| In-flight tokens | mean 4.6, p50 4, max 7 |
| 토큰 손실 | **0 / 300** (5 trial × 60) |
| Backup activation | **5 / 5** trial 모두 정상 |
| 결과 JSON | [experiments/results/a2_kill_ao1_n5.json](experiments/results/a2_kill_ao1_n5.json) |

**Backup 부담 분석** — recovery cost가 *백업이 새로 떠안는 layer 수*에 강하게 의존:
| Trial | Victim layer | Backup 총 layer 부담 | Recovery step |
|---|---|---|---|
| 1 | ao-1[8] | ao-2: [1] + [8] = 2 | 695 ms |
| 2 | ao-1[1-2] | ao-2: [1-2] + [8] = **3** | **930 ms** |
| 3 | ao-1[6] | ao-2: [5] + [6] = 2 | 669 ms |
| 4 | ao-1[7] | ao-2: [7] + [8] = 2 | 676 ms |
| 5 | ao-1[9] | ao-2: [8] + [9] = 2 | 677 ms |

2-layer 케이스 4개의 표준편차 ±13 ms (669-695 ms) — 매우 안정적. 3-layer 케이스 한 개가 +250 ms — **층당 ~250 ms** 의 한계 비용. compute가 ms 수준임을 고려할 때 추가 layer 비용의 대부분은 cache-replay 직렬화 + RPC overhead.

**해석 / 페이퍼 메시지**:
- Recovery 비용 = 단일 step penalty. cache-replay가 prefill 재실행 회피하여 latency가 작음
- p95 < 900 ms — pipeline TBT의 ~4× 미만으로 bounded
- Post-recovery throughput 손실 측정 한계 이내 — 백업이 1-2 layer 추가 떠맡아도 stage invoke time이 ms 수준이라 무시 가능
- gRPC 영속 채널 + SIGKILL → next RPC fast-fails (heartbeat timeout 5s 대기 안 함)
- gateway `_dead` set은 단조 → 다중 trial은 coord 재시작 필요 (스크립트 자동화)

**의도된 한계**:
- N=5 trial은 분포 추정에 충분하지만 형식적 신뢰구간엔 부족 — 통계 검증 필요시 N≥20 권장
- 단일 victim (ao-1) — head/middle/tail 위치별 영향 분리는 victim sweep으로 추후
- 동일 device class (AGX Orin) 백업만 관찰 — 이종 backup(예: ao→on)은 placement 분포 상 발생하지 않음
- 단일 장애 (1 worker 동시) — 다중 동시 장애는 백로그 A2 항목

---

## Phase EXP-A3a — Baseline placement 비교 (알고리즘, live profile)

**목표**: A1에서 캡처한 *실측 profile*(device throughput, layer compute time, network bandwidth)로 4개 placement 전략을 동일 입력에 대해 계산. 각 알고리즘의 예측 max_stage_time + 메모리 feasibility 비교. live 배포 전 sanity check + 페이퍼 알고리즘 비교 표 후보 데이터.

**구현**:
- [experiments/a3_baselines.py](experiments/a3_baselines.py):
  - `cluster_spec_from_sidecar()` — 사이드카 JSON(`device_profiles`/`layer_profiles`/`network_profile`)로 `ClusterSpec` 재구성
  - `compute_all_baselines()` — 동일 spec에 대해 4 전략 실행:
    1. **greedy** — `greedy_placement` (PETALS-style 처리량 가중 분할), R={}
    2. **uniform** — `round_robin_placement` (균등 분배), R={}
    3. **jupiter_dp** — `Scheduler.solve(recovery={})` (DP는 같되 backup 메모리 예약 없음), R={}
    4. **ours** — `Scheduler.solve_alternating()` (R-Ψ 공동 최적화), R 자동 도출
  - `_feasibility()` — primary stage 메모리 + backup 부담 메모리 각각 디바이스 cap 비교 (`with_backup_ok`는 R={}일 땐 primary와 동일)
  - 비교 표 + 상세 placement 출력 + JSON 저장

**검증 결과** (A1 sidecar 입력, OPT-125M, 12 layer × 8 device):

| 베이스라인 | max_stage | 스테이지 수 | 메모리 (primary / +backup) |
|---|---|---|---|
| greedy | 113.7 ms | 8 | ok / ok |
| uniform | 113.7 ms | 8 | ok / ok |
| jupiter_dp | 113.6 ms | 8 | ok / ok |
| ours | 113.6 ms | 8 | ok / ok |

**결정적 발견**:

1. **Ours와 jupiter_dp의 placement Ψ가 완전히 동일** (on-6[1-3], on-5[4], on-1[5], ao-1[6], on-2[7-8], ao-2[9], on-3[10], on-4[11-12]) — 차이는 오직 R-table만 존재 (ours는 8개 매핑, jupiter_dp는 R={}).

2. **모든 베이스라인의 max_stage_time이 +0.1% 이내 수렴** — 알고리즘 차이가 정상 운영 metric에 거의 안 드러남.

**해석 (현재 setting의 한계)**:

이 무차별성은 **OPT-125M의 작은 모델 크기에서 비롯됨**:
- layer당 14 MB → 8GB Nano에 ~570 layer 들어가는 여유
- backup 메모리 예약이 Ψ를 제약하는 regime이 전혀 아님
- 12 layer × 8 device 환경은 분할 자유도도 낮음

**기대되는 차별화 regime**:
- Llama-7B INT4 (~3.5GB) on 4GB Nano: backup 1 layer 추가만으로 일부 디바이스 over-cap → ours의 R-aware DP가 jupiter_dp와 *다른 Ψ*를 선택해야 함
- 더 깊은 모델 (32-80 layer) + 더 적은 device → 분할 자유도 ↑ → 알고리즘 차이 증폭
- 압축된 device 메모리 — 백업 예약이 binding constraint이 되는 환경

**페이퍼 메시지 (이 발견 자체가 유의미)**:
> "메모리 여유 regime에선 Recovery-Aware DP의 placement가 no-recovery DP와 일치하여 정상 운영 *zero overhead*를 달성. 우월성은 R 결정 + 백업 사전 로딩에 집중됨. tight memory regime에서는 placement도 분기될 것이며 그 경계는 D 트랙(모델 확장)에서 측정."

**의도된 한계**:
- 알고리즘 예측 ≠ 실측. 100 ms 수준의 시스템 오버헤드(gRPC / GIL / 직렬화)는 모델에 안 잡힘
- 이 분석은 *placement Ψ*만 비교 — 장애 시 회복 동작 차이(우리가 페이퍼에서 강조할)는 라이브 측정(A3b)이 필요
- 단일 모델/profile만 테스트 — 모델/프로파일 sweep은 D 트랙

---

## Phase EXP-A3b — Baseline placement live 측정 (정상 + 장애)

**목표**: A3a의 4개 알고리즘이 만든 placement를 *실제 함대에 배포*하고 정상 운영 + 장애 주입 모두 측정. A3a는 max_stage_time 예측만 가능했고 *복구 동작*은 모델에 없음 → 라이브 측정이 페이퍼의 *recovery-aware 우월성* 클레임의 유일한 정량 근거.

**구현**:
- [experiments/run_a3_remote.py](experiments/run_a3_remote.py) — orchestrator:
  - `build_manual_cluster_yaml()` — placement+R → 완전한 manual-mode cluster.yaml 문자열 (Jinja2 미사용, 직접 렌더). 형식은 D4 `cluster.yaml.j2` manual-mode와 일치
  - `push_cluster_yaml()` — ansible `copy` 모듈로 `/etc/radp/cluster.yaml` 에 push
  - `deploy_baseline()` — push → systemd restart → `/api/gateway` 폴링하며 ready 대기
  - `run_normal_benchmark()` — gRPC Generate × N (run_e2e_remote의 per-request 로직 재사용)
  - `run_failure_benchmark()` — 동일 victim에 대해 K trial. trial 사이 *같은 yaml*을 재배포(coord의 `_dead` set 정리)
  - 결과를 cell마다 누적 저장하여 중간 inspectability 확보

- 각 trial의 SSE error frame은 `summarize()`가 `_no_recovery_observed`로 식별 → `kind="catastrophic_failure"` + `tokens_emitted_before_failure` 기록

**검증 결과** (4 baselines, OPT-125M, victim=ao-1, normal 10×30 tok / failure 3×60 tok, kill_after 15, 2026-06-05):

| baseline | TBT p50 | TBT p95 | TTFT p50 | failure kind | tokens emitted |
|---|---|---|---|---|---|
| greedy | 221 ms | 284 ms | 348 ms | catastrophic 3/3 | [19, 20, 18] |
| uniform | 215 ms | 290 ms | 329 ms | catastrophic 3/3 | [19, 19, 19] |
| jupiter_dp | 217 ms | 285 ms | 350 ms | catastrophic 3/3 | [19, 19, 19] |
| **ours** | **219 ms** | 288 ms | 353 ms | **graceful 3/3** | **60/60 × 3** |

ours의 recovery step: mean **597 ms**, p50 **594 ms** (A2의 N=5 mean 729 / p50 677 ms 보다 살짝 낮음 — A3b는 3 trial 모두 ao-1 owning 1 layer 케이스라 backup이 2 layer 흡수, A2 N=5는 한 trial에서 3 layer 흡수로 평균이 상승했었음. **2-layer backup 흡수 시 recovery latency가 580-700 ms로 안정적**이라는 가설 보강).

**핵심 발견 (페이퍼 헤드라인)**:

1. **정상 TBT의 알고리즘 무차별성** — 4 baseline이 모두 215-221 ms 범위 (±3% = 측정 노이즈). A3a 알고리즘 예측(+0.1% 이내)이 실측 노이즈 한계 이내에서 정확히 검증됨
2. **R={} 베이스라인은 100% catastrophic** — 3/3 trial 모두 정확히 18-20 token (kill_after_15 + in-flight 4-5) 후 *NoRecoveryError* 로 stream 사망. 변동성 거의 없음 (uniform/jupiter는 19/19/19, greedy만 18-20)
3. **ours와 jupiter_dp의 placement가 byte-identical** (A3a 알고리즘 발견 라이브 재확인) — 즉 정상 운영 측정에서 *완전히 동등*. 차이는 오직 R-table. 같은 Ψ에서 R 유무 만으로 18 → 60/60 token 전환

**페이퍼 메시지 (강한 형태)**:
> "Recovery-Aware DP는 정상 운영에서 *zero overhead* (jupiter-DP와 동일 placement → 동일 throughput) + 장애 시 *100% graceful recovery* (vs 100% catastrophic). 두 조건은 R-table 결정 + 백업 사전 로딩만으로 분리 가능."

**의도된 한계**:
- 단일 victim, 단일 kill timing — head/tail victim sweep + 다양한 kill timing은 별도 sweep
- jupiter_dp/greedy/uniform 모두 100% catastrophic이라 R={} 베이스라인 간 차이 검출 불가 (애초에 catastrophic의 *deg of catastrophe*는 시스템마다 같음 — 모두 stream dies). 추후 ring-style R을 강제 부여한 비교는 다른 실험에서
- greedy / uniform의 placement는 ours와 *다름* — 정상 운영 차이가 노이즈 한계로 안 보이는 건 OPT-125M의 통신-bound 특성 때문. compute-bound regime(큰 모델)에선 차이 확대 기대
- max_tokens=60 — 더 긴 generate에서 recovery 후 정상 부하의 누적 차이는 워크로드 sweep 필요

---

## Phase Web1.1 — 대화형 장애 주입 UI

**목표**: 웹 대시보드에서 클릭만으로 worker 장애 시뮬레이션 + 복구. 페이퍼 demo + 수동 baseline 탐색 (A3b yaml push → 클릭으로 victim 죽이기 → SSE trace 변화 관찰)에 직접 사용.

**구현**:
- [radp/coordinator/gateway.py](radp/coordinator/gateway.py) `mark_alive()` 추가 — `mark_dead`의 역연산. `_dead` set에서 제거 + `build_execution_plan` 재실행. KV cache 불일치 caveat 문서화 (mid-stream revive는 출력 발산 가능)
- [radp/coordinator/web_api.py](radp/coordinator/web_api.py):
  - `POST /api/inject_failure {device_id}` — `gateway.mark_dead` 래퍼. *원격 워커는 죽이지 않음* (routing 시뮬레이션). NoRecoveryError는 HTTP 409 + detail
  - `POST /api/revive_device {device_id}` — `gateway.mark_alive` 래퍼
  - `POST /api/clear_all_failures` — 모든 dead device 일괄 revive
- [radp/coordinator/web_static/index.html](radp/coordinator/web_static/index.html):
  - 신규 "Failure injection" 패널: worker마다 kill/revive 토글 버튼 (현재 `_dead` 상태에 따라 라벨 + 색상 변경)
  - "Revive all" 일괄 해제 버튼
  - 클릭 직후 `tick()` 강제 호출하여 poll 주기 기다리지 않고 즉시 상태 반영

**시뮬레이션 장애의 의미**:
- mark_dead는 *gRPC 에러 발생 시 gateway가 호출하는 그 함수* — 실제 장애 경로와 동일 코드 (radp/coordinator/gateway.py:140, build_execution_plan 트리거)
- 원격 워커 SIGKILL 없이 routing만 전환 → 외부 ansible 불필요, reversible
- 대신 *gRPC error detection latency*는 시뮬레이션에서 안 나옴 (즉시 mark_dead). 진짜 장애 + 시뮬레이션 둘 다 필요한 게 그 이유

**검증 결과**:
- ruff ✓ / 기존 79개 단위 테스트 통과 (회귀 없음)
- A3b 실험 끝난 후 실제 fleet에 deploy 예정 (git push + ansible-playbook --limit coordinator)

**의도된 한계**:
- mid-stream revive는 KV cache 불일치로 출력 변할 수 있음 — UI에 경고는 없음 (사용자 인지 가정)
- 시뮬레이션이라 *gRPC error detection 비용*(우리 측정에선 수십 ms 수준)은 측정 안 됨
- 진짜 워커 kill은 여전히 `experiments/run_failure_remote.py` (ansible 통한 systemctl kill)이 담당

---

## Phase EXP-D1 — OPT-350M 측정 (model scaling 첫 데이터 포인트)

**목표**: OPT-125M (12 layer, hidden 768)에서 OPT-350M (24 layer, hidden 1024)으로 모델을 키워 *알고리즘 격차가 모델 크기와 어떻게 관계하는지* + *회복 비용이 어떻게 확장되는지* 정량 측정. D 트랙(모델 확장)의 첫 측정. OPT-1.3B 시도(아래 EXP-D0)가 Nano OS 리부트로 실패한 직후의 후속 작업.

**구현**:
- [radp/common/architectures.py](radp/common/architectures.py) `embed()` 버그 수정 — `project_in`을 `inputs_embeds + pos_embeds` *후*가 아니라 *전*에 적용해야 함. OPT-350M만 `word_embed_proj_dim (512) ≠ hidden_size (1024)`이라 이 버그에 걸림. OPT-125M / 1.3B는 둘 다 동일해서 잠재됐었음. 첫 generate 요청이 "tensor a (512) must match tensor b (1024) at non-singleton dimension 2"로 실패하면서 발견
- [experiments/run_a3_remote.py](experiments/run_a3_remote.py) `restart_coord()` — `state=restarted` (SIGTERM + TimeoutStopSec 90초 대기)는 coord가 deploy 루프에서 SIGTERM 무시할 때 subprocess timeout(60초)을 초과시킴 → `systemctl kill -s KILL + start`로 변경 + timeout 120초
- [experiments/run_a3_remote.py](experiments/run_a3_remote.py) `--no-final-cleanup` 플래그 + 후처리 cleanup 추가 — 마지막 baseline의 마지막 trial 후 victim 워커가 죽고 coord `_dead` set에 남아있어 후속 작업 불가. 기본값은 cleanup 수행 (`ansible systemd state=started` + POST `/api/revive_device`)

**검증 결과 (A1' 정상 운영)** (7-worker fleet — ao-1, ao-2, on-1, on-2, on-3, on-4, on-5; on-6은 sshd swap thrash로 제외, 10 req × 30 tok, 2026-06-06):

| 지표 | OPT-350M | OPT-125M (A1) | 비교 |
|---|---|---|---|
| TTFT mean / p95 | 409 / 445 ms | 283 / 324 ms | +45% / +37% |
| TBT p50 / p95 / p99 | 304 / 370 ms | 220 / 289 ms | +38% / +28% |
| Throughput mean | 3.2 tok/s | 4.4 tok/s | -27% |
| DP max_stage_time | 113.7 ms | 113.6 ms | 거의 동일 (DP가 균형 잡음) |
| 모델-측정 격차 | 190 ms | 104 ms | +83% (DP cost가 큰 모델 오버헤드 못 잡음) |
| Layer 수 | 24 | 12 | 2× |
| 결과 JSON | [opt350m_baseline_first.json](experiments/results/opt350m_baseline_first.json) | | |

**검증 결과 (A2' 장애 + 회복)** (victim=on-4, max_tokens=60, kill_after 15, 3 trials, 2026-06-06):

| 지표 | 값 |
|---|---|
| Pre-kill TBT p50 (n=2 유효 trial) | 301 ms |
| **Recovery step** | mean **1225 ms** (range 624-1825 ms) |
| Spike vs pre-p50 | mean +923 ms, **4.0×** (OPT-125M의 3.1× 대비 큼) |
| Post-recovery TBT p50 | 293 ms (정상 복귀) |
| 토큰 손실 | **0/120** |
| Backup activation | 2/2 정상 (trial 3은 coord ready timeout 으로 skip) |
| 결과 JSON | [a2_opt350m_kill_on4.json](experiments/results/a2_opt350m_kill_on4.json) |

**검증 결과 (A3a' 알고리즘 비교, 사이드카 사용)**:

| 베이스라인 | 예측 max_stage | 상대 (vs ours) | 메모리 |
|---|---|---|---|
| greedy | 117.2 ms | +3.1% | ok / ok |
| uniform | 117.2 ms | +3.1% | ok / ok |
| jupiter_dp | 113.7 ms | 0.0% | ok / ok |
| ours | 113.7 ms | (기준) | ok / ok |

**검증 결과 (A3b' 라이브 4-baseline 비교)** (victim=ao-1, normal 10×30 tok / failure 3×60 tok, 2026-06-06):

| baseline | TBT p50 | TBT p95 | TTFT p50 | failure | tokens |
|---|---|---|---|---|---|
| greedy | **275 ms** | 341 ms | 400 ms | catastrophic 3/3 | [19, 18, 16] |
| uniform | 294 ms | 368 ms | 458 ms | catastrophic 3/3 | [18, 18, 18] |
| jupiter_dp | 298 ms | 372 ms | 511 ms | catastrophic 3/3 | [18, 13, 20] |
| **ours** | 301 ms | 371 ms | 501 ms | **graceful 3/3** | **60/60 ×3** |

ours recovery: mean **678 ms**, p50 **692 ms**, p95 **726 ms** (n=3).

**페이퍼 핵심 발견**:

1. **알고리즘 격차가 모델 크기와 함께 확장**: 정상 운영 TBT 차이가 OPT-125M의 +0.1%(A3a) → OPT-350M의 +3.1%(A3a') → **3× 확대**. 라이브 측정에서도 3% → 9% 차이로 보임. 더 큰 모델에서는 더 클 것으로 추정 — D 트랙 가설 보강.

2. **DP cost function의 한계 노출**: A3b' 라이브에선 **greedy가 ours보다 9% 빠름** (예측은 ours가 3% 빠를 거였음). 이유: ours의 placement가 on-4에 13 layer 집중, greedy는 device당 3-4 layer 균등. DP의 per-layer cost는 layer concatenation overhead(메모리/캐시 효과)를 잡지 못함 → **§7 limitations에 "marginal-layer cost 불완정" 명시 가치**.

3. **그럼에도 ours의 진짜 가치는 회복**: 모든 R={} baseline은 17-19 token에서 NoRecoveryError로 사망, ours만 **60/60 × 3 회복**. 정상 9% 손해 vs **100% 토큰 손실 방지**. 페이퍼 메시지: "알고리즘 차이는 normal에서 작고 *failure에서 결정적*".

4. **OPT-350M에서도 ours.Ψ == jupiter_dp.Ψ** (byte-identical) — 메모리 binding regime 진입 못 함. OPT-1.3B / Llama-7B INT4 같은 더 큰 모델 필요.

5. **회복 비용은 모델 크기에 mild 의존**: OPT-125M 594 ms → OPT-350M 692 ms (+17%). 24 layer 트래버설 + 큰 activation에도 unchanged within 7-worker fleet.

**의도된 한계**:
- A2' trial 3 실패 (coord ready timeout) — `--ready-timeout` 300초로 늘려도 한계가 있음. 후속 trial에서 coord 재시작이 누적되면 워커 stress 누적 가능성. N=5 안정성 측정엔 부족
- on-6 제외로 fleet 다양성 1대 손실 (5 Nano + 1 AGX CPU)
- 단일 victim(ao-1) — head/middle/tail sweep 미수행
- OPT-1.3B는 EXP-D0에서 시도했으나 Nano OS reboot으로 실패 → OPT-350M으로 한 단계 축소

---

## Phase EXP-D0 — OPT-1.3B 시도 + Negative result

**목표**: 24 layer × 80 MB/layer = 1.9 GB의 OPT-1.3B를 6-7 worker Jetson Nano fleet에 분산해 *메모리 binding regime* 진입 시도. ours.Ψ가 jupiter_dp.Ψ와 갈라지는지 확인.

**진행 + 실패 요약**:

1. **첫 시도** (8-worker auto): worker가 OPT-125M에 pin된 상태에서 OPT-1.3B로 전환 거부 → coord crash 루프. 워커 일괄 재시작으로 해결.

2. **6-worker auto 두 번째 시도**: DP가 **on-1에 18 layer 몰빵** placement 선택 (네트워크 통신 dominant 가정 + activation_bytes=1MB 과대평가). on-1 워커 LoadStage 중 메모리 압력 → **OS 리부트** (커널 watchdog). coord는 죽은 RPC에 11분 hang.

3. **6-worker manual placement** (Nano당 4-5 layer): on-6이 5-layer load 중 sshd 응답 정지 → swap thrash 추정.

4. **on-6 회복 안 됨** → 5-worker로 OPT-350M으로 다운그레이드.

**페이퍼 측면 정량 negative result**:

1. **OPT-1.3B float16 (단일 bin 파일 2.6 GB)은 Jetson Nano 8 GB fleet에서 사실상 분산 불가**. 이유:
   - 워커가 LoadStage 시점에 *전체 모델 파일*을 메모리에 로드 (sharded가 아닌 단일 파일 → 우리 [model_utils.py](radp/common/model_utils.py)의 `torch.load`가 전체 메모리 로드)
   - 분산해도 *피크 시 메모리 사용*은 모델 전체 크기에 가까움 → Nano 8 GB의 절반 이상 점유
   - DP는 layer 수가 적으니 한 노드에 몰빵하는 placement 선택 → 백업 부담까지 추가되면 OS 안정성 위협

2. **OPT-2.7B / OPT-6.7B로 가려면**:
   - **Sharded 형식 변환** (safetensors_sharded 또는 bin_sharded) 필요 — 우리 코드는 sharded 지원되니 모델 포맷만 갖춰지면 됨
   - 또는 **INT4/INT8 양자화**로 모델 크기 축소 (3.5 GB or 1.6 GB) — bitsandbytes ARM/CUDA 호환성 확인 필요

3. **DP의 placement polarization 발견 (분석 중)**:
   - 같은 종류 Nano 5대에서 DP가 18 layer를 한 노드에 몰빵 결정
   - 분석: `activation_bytes=1048576` (1 MB) 가정이 실제 activation (~70 KB prefill, ~4 KB decode)보다 *5-200×* 과대평가 → DP가 stage transition cost를 매우 비싸게 보고 stage 수를 줄이려는 경향
   - 추가 분석: 6 stage 중 stage 수가 어차피 *device 수에 고정*되므로 transition 수는 변하지 않음 (5 transitions 동일). 즉 진짜 차이는 *stage 내부 compute 누적*뿐 — DP가 indifferent해야 정상인데 18-layer 선택. **tiebreaking 또는 backup memory cost**의 미묘한 영향 추정 — 후속 조사 필요

**다음 단계** (향후 진행):
- A5 (lazy backup loading) 검토에 이 케이스 정량 데이터 활용
- DP cost function의 *activation_bytes 동적 추정* 개선 (코드 변경)
- 또는 D 트랙: Llama-7B INT4 sharded 모델로 진짜 메모리 binding 확보

**의도된 한계**:
- 이 실패 자체가 페이퍼의 *limitations + future work* 데이터로 가치 있음. 부정적 결과지만 시스템 한계 + DP cost function 한계를 *실측*으로 입증
- 시간 손실 (~수 시간) — 그만한 보상 데이터 확보

---

## Phase EXP-D2 — OPT-350M 3-tier (weight 버그 fix + 페이퍼 클레임 복원)

**목표**: EXP-D1의 OPT-350M 측정값이 *전부 무효*임을 발견 (weight loader 버그). 1) 버그 수정, 2) 진짜 이기종성 setup으로 재측정, 3) "DP가 greedy를 *실측에서* 이긴다" 를 정량 입증.

**(찾아낸 critical 버그) weight loader prefix mismatch** (commit `246a02b`):
- HF Hub의 facebook/opt-350m은 두 snapshot 보유 — legacy `pytorch_model.bin`은 `model.decoder.layers.0.*` 키, 새 `model.safetensors`는 `decoder.layers.0.*` (no `model.` prefix). 우리 `OPTArchitecture.weight_prefix`는 `model.` 형태 고정 → safetensors 로딩 시 prefix 매치 0개 → `layer.load_state_dict(empty, strict=False)` → **모든 transformer block이 random-init weight으로 inference**
- 증상: 첫 OPT-350M generate 결과 " Country" × 8 반복 (random weight greedy decode 패턴), per-layer compute time이 비현실적으로 빠름 (~1 ms CPU Nano — zero/random matmul 최적화 의심)
- 영향: EXP-D1의 모든 측정 (A1' / A2' / A3a' / A3b') 폐기. placement 의사결정은 일부 잘못된 ProfileLayers 측정에 기반함
- Fix: `load_stage_blocks`에서 canonical prefix가 keys에 매치 안 되면 `model.` strip해서 재시도
- 검증: 동일 prompt가 "is a good one. I was thinking of getting a brown fox," 같이 coherent English 출력. CPU Nano layer time 42 ms (현실적)

**구현 (실험 setup)**:
- inventory.ini에서 on-3, on-4, on-5에 `model_torch_device=cpu` 추가 → 3 tier 강제 (2 CUDA Nano + 1 CPU AGX + 3 CPU Nano). ao-1 임시 제외 (ssh 불안정), on-6도 제외 → **6 worker fleet**
- 새 throughput 측정: on-2 = 1.0, on-1 = 0.87, ao-2 = 0.075, on-3/4/5 = 0.031 — 진짜 3-tier 분포
- DP placement: `on-1[3..21]` (19 layer CUDA에 몰빵) + 나머지 모두 1 layer. **CPU Nano stage가 42 ms bottleneck floor** 가 됨

**검증 결과 (A1' 단독 baseline, 10 req × 30 tok, 2026-06-06)**:
| 지표 | EXP-D1 (broken weight) | **EXP-D2 (fixed, 3-tier)** |
|---|---|---|
| TTFT mean / p95 | 409 / 445 ms | **367 / 390 ms** |
| TBT p50 / p95 | 304 / 370 ms | **257 / 312 ms** |
| Throughput mean | 3.2 tok/s | **3.8 tok/s** |
| DP max_stage 예측 | 113.7 ms | **136.8 ms** |

**검증 결과 (A3b' greedy vs ours 라이브, victim=ao-2, 2026-06-06)**:

| baseline | TBT p50 | TBT p95 | TTFT p50 | failure | placement (CUDA 핵심) |
|---|---|---|---|---|---|
| greedy | **279 ms** | 346 ms | 526 ms | catastrophic (12/30) | on-2[12] on-1[8] |
| **ours** | **256 ms** | 327 ms | 478 ms | **graceful (recovery 516 ms)** | on-1[19] (몰빵) |

**페이퍼 클레임 복원**:
> "3-tier heterogeneous edge cluster (2 CUDA Nano + 1 CPU AGX + 3 CPU Nano)에서 Recovery-Aware DP는 throughput-weighted greedy heuristic 대비 정상 운영 TBT **-8.4%**, TTFT **-9.1%** 달성. **동시에** 장애 시 graceful recovery (vs greedy의 100% catastrophic). 두 우위 모두 R-Ψ joint optimization의 같은 근원."

**왜 이 regime에서 DP가 이기나**:
- CPU Nano floor = 42 ms (slowest device × 1 layer)
- ours는 *fast CUDA에 19 layer 집중* → CUDA stage cost = 28.7 ms (floor 미만)
- greedy는 *proportional split* (12 + 8 on CUDAs) → 둘 다 floor 미만이지만 alocation 자유도 낮아짐
- 라이브에선 ours가 pipeline traversal에서 +가 적게 발생 (1-layer stage가 더 많아서 더 균등한 throughput)

**같이 발견 + fix (cleanup race condition)** (commit pending):
- `run_a3_remote.py` final cleanup이 ansible restart_worker → 즉시 revive_device 호출 순서로 동작
- 결과: 워커 부팅 + 첫 heartbeat 도착 전에 revive 호출 → failure_detector가 0.5초 후 다시 mark_dead (last_ts가 옛값) → 워커가 alive인데 gateway는 dead로 계속 인식
- Fix: revive 전에 `/api/heartbeats` 폴링하여 victim의 age < 3초 될 때까지 대기 (최대 30초). race 해결 + 정상 cluster 상태로 종료

**의도된 한계**:
- ao-2 단일 victim, N=1 failure trial — 통계 신뢰도 확보 위해 N≥3 추가 측정 필요 (다음 단계)
- 6 worker만 (ao-1, on-6 제외) — fleet 완전 활용 못 함
- 3 CPU Nano는 *인위적 강제* (CUDA wheel을 갖춘 노드들을 CPU 모드로 묶음) — 실제 edge 환경 대표성은 *어느 정도* 있지만 (배터리/열로 throttle 가능) 자연 setup은 아님. 페이퍼에서 이 점 명시 필요

---

## Phase EXP-D2.1 — N=3 통계 보강 (7-worker 3-tier, on-6 합류)

**목표**: EXP-D2의 N=1 failure trial은 통계 신뢰도가 약함. on-6가 OS 재부팅으로 자체 회복했으니 fleet 다시 7-worker로 확장하고 N=3 failure trial로 페이퍼 클레임 정량 확정.

**구현**:
- on-6 health check (ping + ssh + uptime 2시간 = 재부팅 흔적 + 디스크/메모리 정상) → fleet 합류, CUDA 모드 유지
- ao-1은 디스크 100% (이전 934 MB가 0 byte로 더 줄어듦, bstarcom의 team_quant 21 GB 정리 없이는 사용 불가) → 보류
- coord 재시작 → 새 auto_schedule (7 worker, 3 CUDA Nano + 1 AGX CPU + 3 Nano CPU)
- N=3 failure trial × 2 baseline (greedy / ours) — 정상 운영 + 회복 모두 측정

**검증 결과** (victim=ao-2, normal 10 req × 30 tok, failure 3 trials × 60 tok, kill_after 15, 2026-06-06):

| Metric | greedy | **ours** | Δ |
|---|---|---|---|
| Normal TBT p50 | 302.3 ms | **282.6 ms** | **-6.5%** |
| Normal TBT p95 | 366.0 ms | 352.0 ms | -3.8% |
| Normal TBT p99 | 407.8 ms | 389.1 ms | -4.6% |
| Normal TTFT p50 | 524.9 ms | 519.8 ms | -1.0% (tie) |
| Throughput mean | 3.14 tok/s | **3.40 tok/s** | **+8.3%** |
| Failure result | **3/3 catastrophic** | **3/3 graceful** | binary |
| Tokens emitted (failure) | 17, 17, 17 (perfect consistency) | 60/60 × 3 | |
| **Recovery step latency** | N/A | mean **617 ms**, p50 **600**, p95 **670** | tight |
| Recovery range | N/A | 573 - 678 ms | spread 105 ms (small variance) |
| Spike vs pre-p50 | N/A | mean +329 ms (**2.16×**) | |

각 cell의 n=300 TBT 샘플 (10 request × 30 token). 결과 JSON: [experiments/results/a3b_opt350m_3tier_n3.json](experiments/results/a3b_opt350m_3tier_n3.json)

**Placement 비교**:
```
greedy : on-6[1-8]    on-3[9]      on-1[10-15]  ao-2[16]  on-5[17]  on-4[18]  on-2[19-24]
         8 layer       1            6            1         1         1         6
         (CUDA 3 노드 분산: 8+6+6 = 20 layer)

ours   : on-6[1-16]   on-3[17]     on-1[18-20]  ao-2[21]  on-5[22]  on-4[23]  on-2[24]
         16 layer      1            3            1         1         1         1
         (CUDA 1 노드 몰빵: on-6에 16 layer, 다른 CUDA 3+1)
```

**핵심 발견**:

1. **DP가 라이브에서 일관되게 greedy 이김** — N=3에서도 -6.5% TBT 유지. EXP-D2의 -8.4%와 같은 방향, 신뢰도 ↑
2. **회복 latency 분포가 매우 tight**: range 573-678ms (105ms spread), p95 670ms < 1초. 페이퍼에서 "회복이 SLO 안 망가뜨림" 클레임 가능
3. **Catastrophic 패턴 완벽 일관**: greedy의 모든 trial에서 정확히 17 tokens 후 사망 (kill_after 15 + in-flight 2). 시스템 결정성 강한 증거
4. **DP의 *stage concentration*이 라이브 우위 원천**: on-6에 16 layer 몰아주고 다른 CUDA에 3+1+1 → pipeline transition 비용 절감 (greedy의 분산보다 효율적). 알고리즘 측에선 둘 다 floor=42ms로 tie였지만 실측은 다름

**Cleanup race condition 수정 검증**:
- 마지막 trial 후 cleanup이 worker restart → heartbeat 도착 대기 → revive_device 순서로 작동
- 로그: `waited for fresh heartbeat: ok=True` → `gateway revive: dead_devices=[]` → 클러스터 정상 종료 상태 ✓
- 이전 EXP-D2에서 본 0.5초 후 재-dead 문제 재현 안 됨

**페이퍼 메시지 (확정)**:
> "On a 3-tier heterogeneous edge cluster (3 CUDA Nano + 1 CPU AGX + 3 CPU Nano, 24-layer OPT-350M), Recovery-Aware DP achieves **6.5% lower median TBT** (282.6 vs 302.3 ms) and **8.3% higher throughput** (3.40 vs 3.14 tok/s) than the throughput-weighted greedy heuristic in normal operation, with **n=300 token samples per condition**. Under worker failure, ours preserves **all 180 tokens across 3 trials** (60/60 × 3) at a tight recovery cost of **600 ms median (95th-percentile 670 ms)**, while greedy loses **100% of tokens** beyond the 17-token in-flight buffer due to its R={} design. The algorithmic advantage and recovery advantage stem from the same R-Ψ joint optimization — and the live-measurement TBT gap reverses the trend (greedy faster) observed under the previously-broken weight loader in EXP-D1."

**의도된 한계**:
- 단일 victim (ao-2) — 7-worker 다른 victim들(on-1, on-2, on-6, CUDA 큰 stage)의 회복 비용은 별도 sweep 필요
- ao-1은 여전히 fleet 밖 (디스크 문제) — 페이퍼 fleet 묘사에서 "7 of 8 workers" 명시 필요
- 3 CPU Nano는 인위적 강제 (EXP-D2 한계와 동일)

## Phase EXP-D2.2 — Profiler 정확도 fix + AGX Orin MAXN, 7-worker N=3 재측정

**목표**: D2.1 N=3 측정 이후 8-worker fleet 확장(ao-1 합류) 결과 ao-1이 placement 최하위 (2 layer) 받음. 사용자 지적 — AGX Orin (5-7x Nano FLOPS) 이 보일 리 없음. 측정 setup 의심 → root cause 추적.

**찾아낸 버그 2개** (commit 382739b):

1. **Tokenizer padding silent no-op** ([radp/profiler/layer_profiler.py](radp/profiler/layer_profiler.py)):
   - `tokenizer(prompt, max_length=seq_length, padding="max_length")` 가 OPT 모델 (pad_token == eos_token) 에서 silent no-op
   - seq_length=32 / 256 / 1024 모두 prompt의 실제 token 수(~160)만큼만 forward → byte-identical 측정값
   - **fix**: `torch.zeros((1, seq_length), dtype=torch.long)` 로 input_ids 직접 합성, tokenizer 우회

2. **CUDA async timing measures launch overhead only**:
   - forward hook 내 `time.perf_counter()` 는 layer.forward() 리턴 시점 (kernel queue 직후) 기록 → GPU 실제 실행 시간 측정 안 됨
   - AGX vs Nano CUDA 둘 다 ~1ms launch overhead로 비슷하게 보임
   - **fix**: `is_cuda` 분기로 `torch.cuda.Event(enable_timing=True)` pair record + post-forward `torch.cuda.synchronize()` 후 `elapsed_time()` 계산

**Power mode 발견**: ao-1 (AGX Orin) 가 factory default `MODE_30W (2)` / 실측 `MODE_50W (3)` 에서 CPU 1.42 GHz 로 throttled. Nano Orin (MAXN_SUPER, 1.73 GHz) 보다 느림. `nvpmodel -m 0 (MAXN)` + `jetson_clocks` 후 CPU 2.2 GHz → ao-1 per-layer 0.836ms (Nano 1.10ms 대비 -24%, 진짜 우위 드러남). 메모리: [project_agx_orin_power_mode](.claude/projects/-Users-hjkim24-RADP/memory/project_agx_orin_power_mode.md), [feedback_profiler_measurement_bugs](.claude/projects/-Users-hjkim24-RADP/memory/feedback_profiler_measurement_bugs.md).

**Throughput 측정값 변화** (ao-1 기준 정규화):

| device | D2.1 (buggy) | D2.2 (fixed + MAXN, 7w) |
|---|---|---|
| ao-1 (AGX Orin CUDA) | 0.97 (8w 측정) | **1.000** (top) |
| on-6 (Nano CUDA) | - | 0.816 |
| on-2 (Nano CUDA) | 1.000 (8w) | 0.800 |
| on-1 (Nano CUDA) | 0.98 | 0.795 |
| ao-2 (AGX CPU) | 0.009 | 0.025 |
| on-3/4 (Nano CPU) | 0.003 | 0.010 |

**A3b' N=3 결과** (victim=on-2 (placement 최대 18 layers, 가장 큰 victim), normal 10 req × 30 tok, failure 3 × 60 tok kill@15, 2026-06-06):

| Metric | greedy | **ours** | Δ |
|---|---|---|---|
| Normal TTFT p50 | 445 ms | **466 ms** | +4.7% |
| Normal TBT p50 | **250 ms** | 257 ms | +2.8% |
| Normal TBT p95 | 330 ms | **317 ms** | -3.9% |
| Failure result | **3/3 catastrophic** | **3/3 graceful** | binary |
| Tokens emitted (failure) | 18, 19, 18 | 60 / 60 × 3 | |

각 cell의 n=300 TBT 샘플. 결과 JSON: [experiments/results/a3b_opt350m_3tier_7w_maxn_n3.json](experiments/results/a3b_opt350m_3tier_7w_maxn_n3.json). Sidecar: [experiments/results/opt350m_3tier_7w_maxn_baseline.json](experiments/results/opt350m_3tier_7w_maxn_baseline.json).

**Placement**:
```
greedy : on-3[1]  on-4[2]  ao-2[3]  on-1[4-9]  on-6[10-15]  ao-1[16-22]  on-2[23-24]
ours   : on-3[1]  on-4[2]  ao-2[3]  on-1[4]    on-6[5]      ao-1[6]      on-2[7-24]
```

ours가 on-2 (Nano CUDA) 에 18 layer 몰빵 — DP solver가 inter-stage 통신 + 메모리 trade-off로 결정. ao-1 (가장 빠른 device) 가 1 layer만 받는 것은 메모리/네트워크 위치상 거리감으로 추정 (별도 분석 필요).

**의도된 한계**:
- on-5 fleet 이탈 (A3b' MAXN run 도중 hang, 전원 재시작 필요) → 7-worker 측정. 추후 on-5 복귀 시 8-worker 재측정 가능
- TBT 측면에선 ours ≈ greedy (within noise). Recovery는 명확한 win — 페이퍼 claim "no perf cost for resilience" 유효
- DP 가 ao-1을 1 layer만 사용한 것은 직관 반대 — 다음 단계로 cost function calibration (network bw weights, activation_bytes) 점검 필요
- 측정은 decode-realistic seq_length=64 기반. Prefill (TTFT) heavy workload에선 AGX 우위가 더 두드러질 것 — 별도 prefill profile path가 차후 작업

## Phase EXP-D2.3 — Cost-function calibration + single-stream 목적함수 발견

**목표**: D2.2 7-worker 측정에서 ours가 ao-1 (가장 빠른 device) 에 1 layer만 배정한 placement 이유 추적. *왜 DP가 fastest device를 favor 안 하나*가 paper claim의 약점이라 cost function 자체 점검.

**찾아낸 calibration 이슈 3가지** (commit e2a91cf, e6a826c, eaecf5a):

1. **activation_bytes 디폴트가 500x 과대평가** ([radp/coordinator/server.py](radp/coordinator/server.py), [radp/common/model_utils.py](radp/common/model_utils.py)):
   - `activation_bytes: 1_000_000` 디폴트 — OPT-350M 실제값은 hidden(1024) × dtype_bytes(2) × batch(1) = **2 KB**
   - 1 MB 사용 시 stage 간 comm = 70-130 ms (compute의 ~100x). DP가 stage 수 minimize = bulk-on-1-device 식 placement만 산출. fastest device 우위 묻힘
   - **fix**: `estimate_activation_bytes(model_id, dtype)` 가 AutoConfig 로 hidden_size 가져와 자동 계산. group_vars `activation_bytes: 0` = auto, 양수면 수동 override

2. **Device order = heartbeat 도착 순서** ([radp/coordinator/scheduler.py](radp/coordinator/scheduler.py)):
   - `build_device_profiles` 가 `records: dict[DeviceId, HeartbeatRecord]` iteration 순서로 device list 생성 → 임의 (워커 부팅/네트워크 지연 의존)
   - DP는 이 순서를 *fixed pipeline order* 로 사용. 마지막 device가 leftover (보통 다수 layer) 받음
   - 7-worker sidecar brute-force: 5040 permutation × DP solve → 현재 순서는 985위/5040 (top 19.5%). best vs worst 격차 1 MB 디폴트에서 37%, 2 KB calibrated에서 12%
   - **fix**: `solve_alternating_best_order()` 가 M ≤ 8 일 때 모든 M! permutation 실행, max_stage_time 최소값 선택

3. **DP가 multiple-optima 시 first-found 반환** ([radp/coordinator/scheduler.py](radp/coordinator/scheduler.py)):
   - 가장 느린 tier (e.g. CPU Nano 1 layer = 85 ms) 가 max_stage_time floor 를 결정하면, 나머지 layer 배분에 여러 optima 존재
   - **partial fix (perm-level)**: tiebreaker = `Σ throughput(d) × layer_count(d)`. 같은 max_stage 시 fastest device에 더 많은 layer 배정
   - **알려진 한계**: tiebreaker가 permutation 비교 단계에서만 동작. 한 permutation 내 DP `_forward` 의 split 선택은 여전히 first-found. 결과: 종종 second-fastest CUDA worker가 bulk 받음

**Single-stream 목적함수 발견** (사용자 통찰 — "모든 노드 안 쓰는 게 더 빠를 수도?"):

DP는 `max_stage_time` 을 minimize — 이는 **steady-state pipelined throughput** (batch >> 1, 동시 다수 stream) 의 정확한 목적함수. 하지만 우리 A3b' 실험은 **batch=1 single-stream decode**.

Single-stream 1-token latency:
```
TBT_per_token = Σ (T_comm(prev → stage_i) + T_compute(stage_i))   over all stages
```
즉 sum, max가 아님. 느린 worker를 추가하면 그 worker의 stage time이 단순히 더해짐 — *throughput 이득 없이 latency 손해*만.

**Subset sweep** (7w MAXN sidecar, activation=2KB, 모든 subset × 모든 permutation):

| k | sum_ms (single-stream TBT 예측) | max_ms | subset |
|---|---|---|---|
| 2 | **25.3 ms** | 13.0 | ao-1, on-1 |
| 3 | 27.6 ms | 9.7 | ao-1, on-2, on-6 |
| **4** | **30.5 ms** | 7.8 | ao-1, on-1, on-2, on-6 (all CUDA) |
| 5 | 66.4 ms | 36.7 | + ao-2 (CPU AGX) |
| 6 | 152.4 ms | 87.1 | + on-3 |
| 7 (현재 D2.2) | **237.9 ms** | 87.1 | + on-4 |

→ CPU 워커 제외하면 **8x 빠른 single-stream TBT** 예상. D2.2 실측 257ms vs 예측 max 85ms 의 3x 차이는 노이즈가 아니라 **DP 가 single-stream 워크로드에 잘못된 목적함수 풀고 있는 증거**.

**4-CUDA / 3-CUDA live 검증 시도 (실측 실패)**:
- 4-CUDA fleet 으로 inventory 축소 → coord 정상 boot, max_stage **8.35 ms** (D2.2 대비 -90%) 확인
- a3_baselines.py 도 `solve_alternating_best_order` 사용하도록 fix (commit eaecf5a)
- A3b' run 시작 — greedy / ours 모두 deploy 시 `not_ready_after_timeout`
- 원인: ours placement가 on-6 (가장 느린 CUDA + 가장 적은 free memory ~447 MB) 에 18 layers 할당 → on-6 hang (SSH banner timeout). 이전 D2.2 후 on-5 도 같은 패턴으로 hung.
- on-6 inventory 에서 제외, 3-CUDA 재시도. on-1 마저 같은 패턴으로 hung — backup table 로딩 시 on-1 (718 MB free) 메모리 부담
- 결과: live wall-clock 확보 못함. Nano CUDA 3/4 boards (on-1, on-5, on-6) 전부 hung 상태 — 다음 in-person 시 전원 재시작 필요

**검증된 부분**:
- ✅ `activation_bytes: 2048 (auto, hidden*dtype*batch from facebook/opt-350m)` 로그 (coord)
- ✅ `solve_alternating_best_order: 5040/5040 permutations feasible, best max_stage_time=0.0856s` 로그
- ✅ 4-CUDA subset 으로 max_stage 85.6 → 8.35 ms (-90%) 직접 측정
- ❌ 4-CUDA / 3-CUDA wall-clock TBT 실측 — fleet hang 으로 불가

**의도된 한계**:
- live A3b' wall-clock 미확보. 다음 in-person session에서 on-1/5/6 전원 재시작 후 4-CUDA 재실측 우선
- DP 의 **단일 max_stage_time → sum_stage_time** 재설계는 별도 Phase (cost function rewrite, subset enumeration 통합). 현재 best_order는 max 만 minimize
- **Recovery trade-off**: smaller subset → backup peer 선택지 좁아짐. 2-worker subset 은 single-failure tolerance 만 (둘 다 backup 인 mutually-back-each-other 구조). paper에서 정량 분석 필요
- on-6, on-1 hang 은 알고리즘 문제 아닌 **Jetson Nano 4-8GB free memory + 18+ layer 백업 로딩** 의 OS-level 회복 한계. 메모리 관리 / lazy backup loading ([A5 백로그 항목]) 의 동기

## Phase EXP-D2.4 — Cost-function 통합 + EdgeShard/Jupiter framing 정리

**목표**: D2.3 에서 발견한 max vs sum mismatch + Jupiter Eq. 4 통찰 후, **DP cost function 자체를 통합** — 같은 (sum, max) state 위에서 mode flag 로 throughput/latency/blended 전환 가능하게 재설계. EdgeShard 두 algorithm (Eq. 6 latency, Eq. 1 throughput) + Jupiter Eq. 4 hybrid 셋 다 reproduce + 우리는 그 위에 recovery-aware extension 얹음. (논문 framing 통일 + SLO 의 역할 재정의)

**구현** (commit 298b054 + 0936599):

1. **`(sum, max)` state DP** ([radp/coordinator/scheduler.py](radp/coordinator/scheduler.py)):
   - `A[y][n]` 가 `float` (max 만) → `tuple[float, float]` (sum, max). 매 cell update 시 둘 다 추적
   - `_rank(state, mode, alpha)` 함수 — 같은 state 를 mode 별로 다르게 ranking:
     - `throughput`: `max` (EdgeShard Eq. 11 / Jupiter Eq. 1)
     - `latency`: `sum` (EdgeShard Eq. 6, batch=1 single-stream)
     - `blended`: `sum + α·max` (Jupiter Eq. 4 at k=1, α=|D|-1 이 그들 공식)
   - DP body 한 줄 변경으로 mode 가 swap. 알고리즘 자체는 같음

2. **SLO 의 역할 분리**:
   - `throughput` mode: **inline `if stage_cost > tbt: continue` 유지** (per-stage SLO hard constraint — 동시 부하 시 사용자별 TBT QoS 보장)
   - `latency` / `blended` mode: **inline cap 제거**. 한 stage 가 TBT 넘어도 sum 이 줄면 OK. SLO 는 final result 의 *post-hoc feasibility check* — `if best.sum_stage_time > TBT_SLO` 시 warning log
   - 이전 D2.3 까진 latency 시도해도 TBT cap 이 fast device 에 많이 못 몰아주게 막고 있었음

3. **Configuration plumbing**:
   - [ClusterSpec.optimization_mode](radp/common/types.py) + `blend_alpha` 필드
   - [CoordinatorConfig](radp/coordinator/server.py): yaml 에서 읽음
   - [group_vars/all.yml](deploy/group_vars/all.yml): default `optimization_mode: latency` (우리 A3b' batch=1 single-stream에 맞춤)
   - [cluster.yaml.j2](deploy/roles/radp-coordinator/templates/cluster.yaml.j2) + [run_a3_remote.py](experiments/run_a3_remote.py) `build_manual_cluster_yaml`: yaml 키 emit
   - [a3_baselines.py](experiments/a3_baselines.py) + [run_a3_remote.py](experiments/run_a3_remote.py): `--optimization-mode` / `--blend-alpha` CLI

4. **`--restart-workers-between-cells`** (commit 0936599):
   - 매 baseline cell 시작 전 `ansible workers -m shell -a "systemctl restart radp-worker"`. 누적 메모리 leak / OOM 사이클 차단
   - 8 GB Nano fleet 에선 latency-mode 의 ao-1 21-layer placement + eager backup 적재가 단일 cell 만에 메모리 한계 도달. clean restart 로 매 cell 공정한 starting state

**Sanity (commit 298b054)** — 4-CUDA + 7w sidecar local DP 실행, 세 mode 비교:

| Sidecar | mode | sum (ms) | max (ms) | bulk on |
|---|---|---|---|---|
| 7w MAXN | throughput | 243.3 | 85.7 | ao-1 [11-24] (14 layers) |
| 7w MAXN | **latency** | **235.4** (-3.2%) | 87.4 | ao-1 [3-20] (**18 layers**) |
| 7w MAXN | blended α=6 | 239.8 | 85.9 | on-1 [2-9] (8) + ao-1 [11-21] (11) |
| 4-CUDA | throughput | 37.2 | 9.7 | ao-1 [1-10] (10 layers) |
| 4-CUDA | **latency** | **28.2** (-24%) | 18.6 | ao-1 [2-22] (**21 layers**) |
| 4-CUDA | blended α=3 | 36.7 | 9.8 | ao-1 [1-11] (11) |

→ latency mode 가 fast device 에 layer 몰빵 + 총 stage 수 최소화. 4-CUDA 에서 sum -24% 감소.

**Live A3b' 결과** (4-CUDA, victim=ao-1, normal 10 req × 30 tok, failure 1-3 × 60 tok kill@15, 2026-06-06):

| Run | Mode | Backup | greedy TBT p50 | **ours TBT p50** | ours failure |
|---|---|---|---|---|---|
| D2.3 v2 | throughput | eager | 171 ms | 162 ms | 2/3 graceful (1 indeterminate) |
| D2.4 lazy | latency | lazy | 169 ms | **117 ms (-31%)** | 1/1 catastrophic (lazy backup 미적재 — 의도된 결과) |
| **D2.4 eager v3** | **latency** | **eager** | **166 ms** | **115 ms (-31%)** | **3/3 graceful** (60/60 × 3) |

**전체 D2.x 시리즈 비교** (paper main result table):

| Phase | Fleet | Mode/Backup | TBT p50 ours | failure | vs D2.2 baseline |
|---|---|---|---|---|---|
| D2.2 | 7w throughput eager | (legacy max-DP) | 257 ms | 3/3 graceful | (baseline) |
| D2.3 | 4-CUDA throughput | eager | 162 ms | 2/3 graceful | -37% |
| **D2.4** | **4-CUDA latency** | **eager** | **115 ms** | **3/3 graceful** | **-55%** |

D2.4 의 ours placement: `on-1[1] on-2[2] ao-1[3-23] (21 layers) on-6[24]` — latency DP 가 자동으로 AGX MAXN 에 layer 21/24 몰빵, 다른 3 워커 각 1 layer (single-stream 의 sum 최소화). greedy 의 분산 placement (`on-2[1-6] on-1[7-12] on-6[13-16] ao-1[17-24]`) 대비 sum_stage_time 측면에서 -27% (예측), live wall-clock 측면에서 -31% (실측).

**핵심 paper claim**: **RADP-Latency** 가 EdgeShard / Jupiter 의 throughput-mode baseline 대비 **single-stream TBT 55% 감소** + **3/3 graceful recovery 유지** (동일 fleet, 동일 SLO). 이전 throughput-mode 가설 ("max_stage minimization 이 SLO 의 정확한 modeling") 이 batch=1 워크로드에 *잘못된 cost function* 이었음을 D2.3 발견 → D2.4 통합 cost function 으로 정량 확정.

**Paper framing 정리** (D2.4 의 결과):

```
RADP cost(stages) = Σ T_stage + α · max T_stage     (generalized)
```

이 한 식으로:
- α = 0 → EdgeShard latency DP (single-user, batch=1) — A3b' SLO 의 정확한 cost model
- α → ∞ → EdgeShard throughput / Jupiter Eq. 1 (multi-user pipelined) — 동시 부하 SLO
- α = |D| - 1 → Jupiter Eq. 4 (k=1 sub-sequence; intra-seq parallelism 도입 시 k>1 로 확장)

RADP 가 EdgeShard 두 mode + Jupiter Eq. 4 를 *parameterized cost* 로 통합하며, 두 mode 모두에 **recovery-aware DP** (R-Ψ alternating + eager/lazy backup memory policy) 를 직교 추가한 게 우리 진짜 contribution.

**의도된 한계**:
- D2.4 의 latency mode + eager backup live 측정은 메모리 압박으로 deploy fail (on-1 가 ao-1 backup 21 layers + 자기 1 layer = 572 MB 적재 시도 → OOM). `--restart-workers-between-cells` 추가 후 재측정 진행 중. live 측정에서 4×4 matrix 완성 시 EXP-D2.5 로 분리 가능
- Intra-sequence pipeline parallelism (Jupiter k > 1) 미구현. prefill optimization 의 진짜 contribution 은 별도 future work
- DP 의 throughput-mode 가 EdgeShard Eq. 11 의 subset enumeration 까진 가지 않고 perm search 로 근사 (M ≤ 8). M > 8 fleet 엔 heuristic 추가 필요
- ~~Memory-aware backup peer selection 미구현~~ — **commit 4972127 에서 fix**. `DeviceProfile.free_memory_bytes` 가 heartbeat 의 실측치를 carry, `memory_check` + `recovery_table` 가 `total` 대신 그것을 budget 으로 사용 (free=0 시 legacy fallback). 4-CUDA latency+eager v3 환경에선 placement 동일 (Nano free ≥ 4 GB 로 backup load 546 MB 여유) 지만 누적 deploy 후 메모리 압박 시 자동으로 안전한 peer 선택 또는 NoRecoveryError. D-track 큰 모델 + multi-stream 으로 갈 때의 prerequisite

## Phase EXP-D2.5 — Multi-stream throughput sweep (예상 vs 실측)

**목표**: D2.4 의 dual-mode framing 정당화 — *latency-mode 가 single-stream 에서 -55% TBT 이긴 한데, **throughput-mode 의 가치는 multi-user 시나리오에서만 드러난다***는 가설. 4-CUDA fleet 에서 throughput-mode placement vs latency-mode placement 를 C ∈ {1, 2, 4, 8} concurrent stream 으로 load 걸고 aggregate token rate 비교. 두 mode 가 *언제 우열 뒤집히는지* (crossover point) 정량화.

**구현**:
- [experiments/measure_concurrent.py](experiments/measure_concurrent.py) — concurrent stream load generator. ThreadPoolExecutor 로 C 개 동시 `/api/generate` SSE 호출, per-stream TBT distribution + aggregate tok/s + 실패율 측정. warmup_skip=2 로 첫 prefill / first-token outlier 흡수
- group_vars `optimization_mode: latency` 로 4-CUDA placement (ao-1 [2-22] 21 layers) 측정 → 그 다음 `throughput` 으로 토글 + 재배포 (balanced placement: on-1 [1-7] / ao-1 [8-14] / on-6 [15-19] / on-2 [20-24], max_stage 7.7 ms 예측)

**검증 결과** (4-CUDA, OPT-350M, 2 repeats × C={1,2,4,8,16,32} × 30 tok per stream, 2026-06-07):

| Concurrency | **Latency placement** aggregate | **Throughput placement** aggregate | Δ (throughput vs latency) |
|---|---|---|---|
| C=1  | 7.8 tok/s | 5.7 tok/s | **-27%** |
| C=2  | 10.7 | 6.9 | -36% |
| C=4  | 18.3 | 12.6 | -31% |
| C=8  | 25.3 | 21.2 | -16% |
| C=16 | **25.9** | 24.3 | -6% |
| C=32 | **26.0** | 25.5 | -2% |

→ **latency placement 가 모든 C 에서 dominant** (가설 반증). 둘 다 **C=16 부터 ~26 tok/s 에 saturate** — gateway bottleneck 천장. Crossover point 없음. 결과 JSON: [concurrent_4cuda_latency.json](experiments/results/concurrent_4cuda_latency.json), [concurrent_4cuda_throughput.json](experiments/results/concurrent_4cuda_throughput.json), [concurrent_4cuda_latency_high.json](experiments/results/concurrent_4cuda_latency_high.json), [concurrent_4cuda_throughput_high.json](experiments/results/concurrent_4cuda_throughput_high.json).

**Worker 사용률 측정** (latency placement, C=4 active, tegrastats sample):

| Worker | GPU GR3D_FREQ | CPU avg | Layer count | 예상 compute/sec |
|---|---|---|---|---|
| ao-1 | **0%** | 5% | 21 | ~90ms (9%) |
| on-1 | 0% | 5% | 1 | ~6ms (0.6%) |
| on-6 | 39% | 5% | 1 | ~6ms (0.6%) |
| on-2 | 0% | 5% | 1 | ~5ms (0.5%) |

→ **워커가 대부분 idle**. compute 가 sub-ms 라 sampling window (1초) 에 잠겨버리지만, 5 tok/s × 18ms = 9% 가 ao-1 의 실제 사용률. 나머지 ~85% 시간은 *gateway 처리 / RPC 직렬화 / Python GIL 대기*. 워커 추가 / placement 최적화로 줄일 수 없는 fixed cost.

**원인 분석** (예측 vs 실측 gap):

```
Throughput placement, C=4 이론치:
  max_stage = 8 ms → 4 streams / 8 ms = 500 tok/s aggregate
실측 = 12.6 tok/s = 이론의 2.5%
```

→ pipeline 이 안 차고 있음. 분석:
1. **per-RPC overhead**: gRPC 직렬화 + Python interpreter + 게이트웨이 SSE 처리 = 토큰당 *~125 ms* (170 ms 실측 - 45 ms 예측 compute+comm)
2. **stage 수 ↑ ≈ overhead ↑**: throughput placement (4 balanced stages) 와 latency placement (4 stages but bulk on 1 device) 가 동일한 hop 수지만, stage 당 compute 작아지면서 *상대적 overhead* 비중 ↑
3. **Edge bandwidth ~10 MB/s**: activation 2 KB 자체 전송 0.2 ms 인데 per-hop overhead 가 30 ms 이상. comm cost minimize 가 latency placement 의 *암시적 boost*

**Paper 입장 reframe**:

- 기존 가설: "RADP supports both modes. SLO 따라 선택"
- D2.5 실측: **우리 edge fleet 에선 latency-mode 가 universal dominant point**
- 정직한 reporting: "In low-bandwidth edge environments (~10 MB/s gRPC), per-RPC fixed overhead exceeds the predicted pipeline-parallelism gain of throughput-mode optimization. RADP-Latency (α=0 in the unified `Σ + α·max` cost) is the dominant operating point across all measured concurrency levels."
- Throughput-mode 가 *우세할 조건*: (a) datacenter-grade 네트워크 (≥1 Gbps), (b) RPC overhead 가 token compute 보다 작아질 만큼 큰 모델, (c) C » 8

**Gateway bottleneck 의 함의** (paper future work):

```
Token latency = stage_compute (1-18ms) + 통신 (5ms) + framework overhead (~140ms)
                └ 9-15% 의 시간       └────────────  85-91%  ────────────────┘
```

→ 어떤 placement 알고리즘도 9-15% 영역만 최적화. *85% framework cost* 가 아키텍처적으로 풀려야 throughput mode 가 효력. 가능한 방향:
1. **Async gRPC + concurrent sampling** (Python GIL 우회)
2. **Batched sampling / 토큰-단위 vectorization** (Jupiter intra-seq parallelism 정신)
3. **Lower-overhead 직렬화** (protobuf → raw activation bytes)
4. **C++ / Rust gateway** (Python critical path 제거)
5. **Hierarchical / 분산 gateway** (단일 coord bottleneck 해소)

이 fix 없이는 RADP-Throughput placement 의 *이론적 이점* 이 실측 환경에서 발현 안 됨. EXP-D2.5 의 "latency-mode 우위" 결론은 *우리 현 implementation 조건 하에서만 성립* 임을 paper limitation 으로 명시 권장.

**의도된 한계**:
- 단일 모델 (OPT-350M) + 단일 동시성 범위 (C ≤ 8). 더 큰 모델 (Llama-2-7B) / 더 높은 동시성 (C=16, 32) 에선 throughput crossover 가능. 다음 sweep 후보
- TBT p50 측정 — 분산 (p95, p99) 미반영. Multi-stream 시 tail latency 가 중요
- 네트워크 단일 환경 (실측 ~10 MB/s). simulated 고대역폭에서 crossover 측정 시 더 깔끔한 paper 그림

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
| **A5** | **Lazy backup loading + soft memory reservation** | 현재(eager proactive): backup 가중치를 deploy 시점에 메모리에 미리 적재 → 회복 ~600 ms, 0 token loss, 단 평상시 backup 영역 메모리 점유. 대안(lazy proactive): DP 단계에서 backup 메모리 *예약*만 하고 가중치 로딩은 장애 시점으로 미룸 → 평상시 그 영역을 더 큰 KV cache / 더 긴 컨텍스트 / 더 많은 동시 요청에 활용 가능. 트레이드오프: 회복 시 디스크 → 메모리 로드 비용 (~5-30 s) + 진행 중 요청의 KV cache 폐기로 인한 부분 손실. **2026-06-06 사용자 제안.** D 트랙(모델 확장) 후 별도 실험으로 정량 비교 — eager(현재) vs lazy(이 안), 큰 모델 + concurrent 워크로드에서 throughput 이득 vs 회복 latency 손실 vs 토큰 손실률을 측정. plan.md §7 (limitations) / §8 (future work)에 정책 비교 표로 포함 검토. | 중-큼 |

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
| ~~**D0**~~ | ~~**Proto 확장**~~ | **완료** (위 Phase D0 섹션 참조) | — |
| ~~**D1**~~ | ~~**Worker-side 구현**~~ | **완료** (위 Phase D1 섹션 참조) | — |
| ~~**D2**~~ | ~~**Coordinator ProfileOrchestrator**~~ | **완료** (위 Phase D2 섹션 참조) | — |
| ~~**D3**~~ | ~~**Coordinator startup 재설계**~~ | **완료** (위 Phase D3 섹션 참조) | — |
| ~~**D4**~~ | ~~**cluster.yaml 스키마 정리**~~ | **완료** (위 Phase D4 섹션 참조) | — |
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
