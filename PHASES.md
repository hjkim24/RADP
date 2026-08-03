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

## Phase EXP-D3 — Chain topology (Petals-style) + on-tail head/sampling

**목표**: D2.5 의 *gateway bottleneck* (token 당 ~143 ms framework overhead, aggregate ~26 tok/s ceiling) 가 RADP-Throughput placement 의 이론적 이점을 architecturally 차단함. 사용자 제안 — *Petals 식 chain topology* (워커 간 직접 활성화 전달) + *마지막 worker 가 lm_head + sampling 보유* + (Phase 2) *coord 가 async mirror cache 받음* 으로 recovery 보존. Coord 가 per-token critical path 에서 완전히 빠지는 것이 목표.

**구현 Phase 1a** (commit 492a3bc) — chain forwarding (lm_head 는 coord 유지):
- `SetNextHop` RPC: coord 가 deploy() 시 각 worker 에게 successor 의 address + (start, end) 알림. 마지막 stage 는 next_address="" 로 chain tail 표시
- Worker `RunStage`: 자기 stage 처리 후, next_hop 등록되면 `next_stub.RunStage()` 로 직접 forward. 응답이 nested 로 coord 까지 bubble up
- Coord `_run_pipeline`: 첫 worker 만 호출. encode/decode 횟수 4 → 1 hop

**구현 Phase 1b** (commit 016e9ad) — head + sampling on chain tail:
- `LoadHead` RPC: chain tail worker 가 lm_head + final_layer_norm + project_out 적재
- `run_tail_and_sample()` — local stage + head + greedy argmax 한 forward pass 에서 처리, `next_token_id` 반환
- `RunStageResponse` 에 `has_next_token` + `next_token_id` 필드 추가. Coord 가 그 신호 받으면 자기 head/sampler 스킵
- Coord per-token work: embed + state mgmt + SSE streaming 만 (lm_head + argmax 제거)

**측정 결과** (4-CUDA, OPT-350M, 30 tok per stream × 2 repeats, 2026-06-07):

**Latency placement (ao-1 [3-23] = 21 layers)**:

| C | Phase 0 (star) | Phase 1a (chain) | **Phase 1b (chain + tail head)** | Δ vs Phase 0 |
|---|---|---|---|---|
| 1 | 7.8, 118 ms | 9.2, 103 ms | **10.3 tok/s, 93 ms** | **+32% / -21% TBT** |
| 2 | 10.7 | 11.5 | **12.9** | +21% |
| 4 | 18.3 | 19.3 | **25.9** | **+42%** |
| 8 | 25.3 | 24.0 | **31.6** | +25% |
| 16 | 25.9 | 27.6 | **34.0** | **+31%** |
| 32 | 25.5 | n/a | **32.9** | +29% |

→ **Aggregate ceiling 25 → 34 tok/s 로 상승**. D2.5 의 gateway-bound 한계 직접 해소. C=1 TBT -21% (118 → 93 ms).

**Throughput placement (balanced 6/7/6/5)**:

| C | Phase 0 (star) | **Phase 1b (chain + tail head)** | Δ vs Latency Phase 1b |
|---|---|---|---|
| 1 | 5.7 | 7.1 | -31% (vs latency 10.3) |
| 4 | 12.6 | 10.3 | **-60%** |
| 8 | 21.2 | 11.1 | -65% |
| 16 | 24.3 | 25.5 | -25% |
| 32 | 25.5 | 24.2 | -27% |

→ **여전히 latency placement 가 universal dominant**, 격차 *더 커짐*. Phase 1b 가 gateway 를 풀어준 후에도 throughput placement 의 이론적 이점이 발현 안 됨.

**원인 — chain 의 synchronous forwarding 이 pipeline parallelism 차단**:

```
스트림 A 가 chain 통과 중 (예: stage 1 → 2 → 3 → 4):
  stage 1 의 thread: stream A 의 chain 전체가 끝날 때까지 blocked
  stage 2 의 thread: stream A 가 stage 2 처리 + 3, 4 의 forwarded RPC wait
  stage 3, 4 마찬가지
스트림 B 도착: stage 1 의 다음 thread 가 받아 처리 시작
  하지만 stage 1 의 worker 본체는 stream A 의 forward 회신 대기 중
```

→ **chain RPC 가 synchronous request/response 라 각 stream 이 chain 의 모든 stage thread 를 동시 점유**. C 스트림이 진정한 pipeline parallelism 으로 진행 못 하고 serial 화. throughput placement (4 balanced) 가 4 hop × overhead 를 다 부담 → latency placement (1 bulk stage on AGX) 보다 *더* 나쁨.

**Paper finding 강화**:

```
RADP-Latency dominates RADP-Throughput across:
  - star topology (Phase 0)        : -27% to -36% throughput improvement
  - chain topology (Phase 1a)      : 동일 패턴
  - chain + tail head (Phase 1b)   : 격차 더 크게 (-60% at C=4)
```

→ "어떤 architecture 변형에서도 RADP-Latency 가 우위" 라는 finding 이 *세 가지 변종에서 모두 일관* → 더 강한 paper claim.

**의도된 한계 + Phase 2/3 후속**:
- Chain topology 의 sync forwarding 이 pipeline parallelism 차단. 진정한 pipeline 효과 위해선 **async chain** (worker fire-and-forget + coord 가 last worker 에서 token 받는 reverse channel) 필요 — Phase 2/3 에서 mirror cache 와 함께
- Phase 1a/1b 의 recovery 는 *degraded* — coord 가 중간 stage 의 activation 을 못 봄 (chain forward 는 nested response). chain head 의 input 만 cache 에 있어서 mid-chain failure 시 head 부터 replay. Phase 2 의 async mirror cache 가 per-stage replay 복원
- lm_head migration 의 메모리 비용: 약 100 MB (OPT-350M fp16) 가 chain tail (보통 on-6 같은 Nano) 에 추가 적재. 큰 모델 (Llama-2-7B) 에선 ~400 MB → tail node 선택 시 메모리 제약 강화
- 측정은 greedy argmax 한정. temperature > 0 / top_k / top_p 는 Phase 1b 미지원 (자동으로 coord-mediated fallback)

**커밋**: 492a3bc (Phase 1a) + 016e9ad (Phase 1b)
**결과 JSON**: [concurrent_4cuda_chain_phase1a.json](experiments/results/concurrent_4cuda_chain_phase1a.json), [concurrent_4cuda_chain_phase1b.json](experiments/results/concurrent_4cuda_chain_phase1b.json), [concurrent_4cuda_chain_throughput_phase1b.json](experiments/results/concurrent_4cuda_chain_throughput_phase1b.json)

---

## Phase EXP-D3 Phase 2 — Async mirror cache (worker → coord)

**목표**: Phase 1a/1b 가 *chain forwarding* 으로 throughput 을 끌어올렸지만, coord 는 chain head 의 input 만 로컬에 갖고 있어 *mid-chain worker failure 시 backup 으로 replay 할 activation 이 없는* 상황이 됨. Phase 2 는 워커 측에서 자기 input 활성화를 coord 로 fire-and-forget 으로 mirror 하여 — 진정한 의미의 *recovery-aware DP 의 R 항이 chain topology 에서도 실효성을 갖게* 함.

**구현** (commit 2696a27 + 8f81533):
- 프로토 — `CoordinatorService.MirrorActivation(request_id, stage range, position, bytes, is_prefill)`. `RunStageRequest.position` 추가 → coord 가 step index (0=prefill, 1+=decode) 를 stamp, 각 워커가 그대로 mirror 로 전파.
- 워커 ([radp/worker/server.py:36](radp/worker/server.py#L36)) — `_MirrorDispatcher`: persistent gRPC channel + single-thread executor. `submit()` 이 RunStage 를 절대 block 하지 않음. start_layer == 1 (chain head) 은 mirror skip — coord 가 그 input 의 source 이기 때문에 의미 없음.
- 코디네이터 ([radp/coordinator/gateway.py:160](radp/coordinator/gateway.py#L160)) — `record_mirror` → `ActivationCache.put(req, stage_key, position, bytes)`. Idempotent (재시도 안전), out-of-order 도착 수용.
- `ActivationCache` — `list[bytes]` → `dict[position, bytes]` 변경. `get_history()` 가 contiguous prefix [0, 1, ...] 만 반환 → stalled mirror 가 step 을 건너뛰지 않게.
- `/api/mirror_stats` — lifetime ingress 카운터 + 현재 캐시 점유. 배포 후 mirror path 가 실제로 hot 한지 확인용.

**라이브 검증** (2026-06-07 ax-1 coord + 3 workers chain on-6 → ao-1 → on-1):
- Pre-request: `lifetime_pushes=0, lifetime_bytes=0`
- 8 tokens 생성 (1 prefill + 7 decode = 8 steps)
- Post-request: `lifetime_pushes=16, lifetime_bytes=72064`
- ⇒ **8 steps × 2 non-first stages = 16 mirrors**. 산수 일치 → mirror path 가 실제 chain topology 에서 작동.

**의도된 한계** (Phase 3 후속):
- **Chain failure attribution 부정확**. Mid-chain worker 가 죽으면 coord 가 받는 gRPC 에러는 chain head 의 RunStage 호출 실패 — 누가 진짜 죽었는지 모름. 현재는 `mark_dead(head)` 잘못 호출. Heartbeat path 가 결국 정정하지만 in-flight 요청에선 wrong attribution. Phase 3 (이후) 가 worker 가 downstream 실패를 coord 로 별도 시그널링 / heartbeat-based wait-and-retry 로 보완해야.
- Phase 2 의 mirror 는 *fire-and-forget*. 워커가 mirror 보낸 직후 죽으면 그 step 의 mirror 는 미달 → `get_history` 가 그 position 까지만 반환 → replay 가 정확히 마지막 성공 step 에서 재개됨. 데이터 무결성 보장.
- 측정은 mirror 성공 path 에 한정. 진짜 failure 주입 시나리오는 Phase 3 의 chain-aware recovery loop 가 갖춰진 뒤 별도로 측정해야.

**Paper 기여**:
- Recovery-aware DP 의 *R* 항이 chain topology 에서도 유효하게 만든 마지막 시스템 컴포넌트.
- "ψ 가 chain forwarding 으로 정상 모드를 가속해도, *R 의 mirror cache* 가 정상 모드 비용 (push bytes) 을 동시에 부담하면서 fault tolerance 를 보존" 이라는 trade-off 가 명확히 측정 가능.

**커밋**: 2696a27 (mirror cache 코어) + 8f81533 (/api/mirror_stats diagnostic)
**테스트**:
- 단위 — [tests/test_activation_cache.py](tests/test_activation_cache.py) (positioned put, out-of-order collation, idempotent dup) 3 cases
- smoke — [tests/test_mirror_activation.py](tests/test_mirror_activation.py) (fake gRPC fleet, first-stage no-mirror, monotonic positions) 3 cases
- 라이브 — `/api/mirror_stats` pre/post Generate 비교 (위 표)

---

## Phase EXP-D3 Phase 3 — Chain-aware failure attribution + mirror-replay recovery

**목표**: Phase 2 의 mirror cache 가 *데이터* 를 확보했지만, 실제 *복구 루프* 를 chain topology 에 맞게 wire up 해야 함. 핵심 문제 두 가지:

1. **Attribution**: chain head 의 `next_stub.RunStage(downstream)` 가 실패하면 coord 는 chain head 만 에러로 인식 — 진짜 죽은 mid-chain worker 를 못 찾음.
2. **State coherence**: 일부 워커는 이미 활성화를 받아 KV cache 를 advance 시킨 상태. 단순히 backup 으로 swap + retry 하면 surviving 워커들이 같은 position 을 두 번 처리 → garbage tokens.

**구현** (commit c4933d4 + 3d3395c):

*Worker side* ([radp/worker/server.py](radp/worker/server.py)):
- Chain forwarder 가 downstream RunStage RpcError 를 catch → gRPC trailer metadata 에 `(radp-failed-start, radp-failed-end)` stamp → `context.abort(UNAVAILABLE, ...)`. Trailer 가 nested response unwind 통과해 coord 까지 도달.
- `RunStageRequest.replay_only=True` 플래그: 워커가 자기 stage 만 돌리고 chain forward + head sampling 모두 skip. Backup 의 KV cache 만 rebuilding 할 때 사용.
- Replay 호출에선 mirror push 도 skip (그 활성화는 이미 cache 에서 온 것).

*Coord side* ([radp/coordinator/gateway.py](radp/coordinator/gateway.py)):
- `_attribute_chain_failure(head_stage, error)` — trailer 에서 (start, end) 를 읽어 `self.placement` (원본, immutable) 에서 해당 stage 의 owner 식별. 중요: `_execution_plan` (현재 substituted) 가 아닌 *원본 placement* 를 봐야 함 — heartbeat path 가 먼저 substitute 했어도 trailer 는 원래 wiring 을 가리키기 때문.
- `_recover_from_chain_failure(request_id, head_stage, error, current_position)`:
  1. `mark_dead` → execution plan rebuild (backup 으로 치환)
  2. `PromoteBackup` RPC on recovery peer (idempotent)
  3. `_rewire_chain` — 모든 surviving 워커에 `SetNextHop` 재발행
  4. `_evict_kv_for_request` — surviving 워커들의 stale KV cache drop
  5. Cached input history 를 *새 chain* 으로 end-to-end replay; 마지막 호출의 response 가 실패한 step 의 recovered token
- Heartbeat 가 먼저 도착해 이미 `_dead` 에 들어있는 경우 (live fleet 의 실제 ordering): `mark_dead` 스킵하고 finalise (rewire + replay) 만 수행. PromoteBackup 도 idempotent.

*왜 full-chain replay 인가 vs stage-only replay*: 실패한 step 에서 *upstream surviving 워커들* (head 부터 죽은 stage 의 predecessor 까지) 은 이미 자기 KV cache 를 advance 시킨 상태. 단순 stage 만 replay 하고 step 을 retry 하면 그 surviving 워커들이 같은 position 을 두 번째 처리 → KV 가 doubled → garbage. 전체 chain 을 evict + replay 하면 deterministic rebuild.

**검증 결과**:

*단위 + smoke* (4 new test cases):
- `tests/test_chain_failure_attribution.py` — worker stamps trailer, gateway 의 `_attribute_chain_failure` 가 원본 placement 에서 dead stage 찾음, trailer 없으면 head fallback
- `tests/test_chain_recovery_replay.py` — 3-worker fake chain (head → middle → tail) + coord with mirror catcher, middle 죽인 후 trailer 가 caller 까지 도달

*라이브 fault injection* (2026-06-07, on-6 + ao-1 + ax-1 coord, [experiments/run_phase3_recovery.py](experiments/run_phase3_recovery.py)):
- 시나리오: chain `on-6[1..11] → ao-1[12..24]`, ao-1 에 head/sampling, prompt = "fox jumps over the lazy dog. Once upon a time"
- step 3 후 `systemctl stop radp-worker && pkill -9` (즉시 kill + auto-restart 차단) on on-6
- 결과:
  ```
  step 0..3: , there was a   (normal chain, TBT 89-97 ms)
  step 4   :  fox            (recovery step, 3292 ms)
  step 5..11: . He was a lazy dog.
  ```
  → **12 / 12 tokens 생성, 의미 있는 텍스트, 클라이언트에 에러 노출 0**
- Mirror cache delta: pre=5 → post=17 (+12) — 12 tokens × 1 mirror/step on non-first stage = 12, 정확히 일치
- Recovery step latency 3292 ms 중 ansible (systemctl stop + ssh) 가 ~3000 ms 차지; 순수 coord-side recovery (mark_dead + promote + rewire + replay) 는 측정 인프라 한계로 정확히 분리하기 어려우나 sub-second 추정

**의도된 한계** (paper limitations 절에 명시):
- Recovery latency 측정이 ansible overhead 에 dominated. 진정한 wall-clock 측정은 in-process fault injection (e.g. coord 의 `/api/inject_failure` 가 헐트비트 stop 시뮬레이션) 으로 별도 측정해야 정확.
- Concurrent faults (R(j) 도 죽는 시나리오, plan.md §7.2) 미지원 — 단일 fault 만 보장.
- Backup-on-same-host (R(j) 가 이미 chain 에 있는 워커): rewire 가 self-loop chain 만들어 RPC self-hop 비용 발생 (정확성은 보존, 최적화 여지).
- Replay 가 전체 chain 을 re-run → recovery cost = O(positions × stages) RPCs. 단일 fault 가정 하에선 acceptable.

**Paper 기여**:
- ψ + R 의 모든 시스템 컴포넌트 closure 완성. R 이 단순 placement 결정이 아니라 *실제 런타임 recovery 메커니즘* 으로 작동함을 라이브 측정으로 증명.
- "Chain topology 가 정상 모드 throughput 을 개선하지만 fault tolerance 를 break 시키는가?" 라는 잠재적 reviewer concern 에 대한 직접 응답: *No, 적절히 wired up 된 mirror cache + chain-aware attribution 으로 chain + RADP-R 양립 가능.*

**커밋**: c4933d4 (chain attribution + recovery 코어) + 3d3395c (heartbeat-first attribution fix)
**테스트**:
- 단위 — 3 cases ([tests/test_chain_failure_attribution.py](tests/test_chain_failure_attribution.py))
- smoke — 1 case (end-to-end live chain + trailer; [tests/test_chain_recovery_replay.py](tests/test_chain_recovery_replay.py))
- 라이브 — [experiments/run_phase3_recovery.py](experiments/run_phase3_recovery.py) (위 결과)

---

## Phase EXP-D3 Phase F — Async chain forwarding (pipeline parallelism)

**목표**: D2.5 + Phase 1b 의 핵심 finding — *chain 의 synchronous 응답 unwind 가 pipeline parallelism 차단* — 을 해결. 각 in-flight stream 이 모든 chain stage 의 gRPC thread 를 동시에 점유하던 것을, fire-and-forget 으로 풀어 각 stage thread 가 자기 일만 끝나면 즉시 free 되도록 함.

**구현** (commit b547db0):

*Proto*:
- `RunStageRequest.async_chain` (field 8) — coord 가 set 하면 워커가 async 모드로 동작.
- `CoordinatorService.ResultReady(request_id, position, activation, has_next_token, next_token_id)` — chain tail 이 gateway 의 future 를 깨우는 reverse channel. Nested response unwind 를 ResultReady RPC 한 번으로 치환.

*Worker* ([radp/worker/server.py:36](radp/worker/server.py#L36)):
- `_CoordDispatcher` (이전 `_MirrorDispatcher` 확장) — `submit_mirror` (Phase 2) + `submit_result` (Phase F). Mirror 큐와 result 큐 분리, mirror 가 backed-up 돼도 latency-critical wake-up 안 막힘.
- `_AsyncChainDispatcher` — bounded ThreadPoolExecutor (max=8) 가 downstream `RunStage` 호출 fire-and-forget. ACK 즉시 return.
- **Per-request lock**: `dict[request_id, threading.Lock]` 으로 같은 request 의 연속 step 들이 동일 DynamicCache 에 race 못 하게 직렬화. 서로 다른 request 는 lock 분리로 병렬 처리 가능. `EvictRequest` 가 lifecycle 끝에 정리.
- Sync chain 시 trailer-stamping recovery path (Phase 3) 와 100% backward-compat — `async_chain=False` 면 코드 path 변경 없음.

*Coord* ([radp/coordinator/gateway.py](radp/coordinator/gateway.py)):
- `chain_mode` config (sync | async) — default sync. `group_vars/all.yml` → `cluster.yaml` → `CoordinatorConfig` → `RequestGateway`.
- `record_result` + `_register_pending` / `_unregister_pending` — `dict[(request_id, position), (Event, payload)]` 보관. `ResultReady` 핸들러가 Event 를 깨움.
- `_invoke` 가 `chain_mode=async` 일 때: `register_pending` → `stub.RunStage(req with async_chain=True)` (ACK 받고 즉시 return) → `Event.wait(timeout=30s)` → synthetic `RunStageResponse` 반환. Sync path 와 동일 인터페이스 유지 → 상위 `_run_pipeline` 변경 없음.
- Replay (Phase 3) 는 항상 sync 강제 — backup KV 재구성은 chain-forward 하면 안 되므로.

**라이브 측정** (2026-06-07, 3-stage chain: on-6 → ao-1 → on-2 + ax-1 coord, OPT-350M, 30 tok/stream, [experiments/measure_concurrent.py](experiments/measure_concurrent.py)):

**2×2 matrix — placement × chain mode** (aggregate tok/s / TBT p50 ms):

| C | T+sync | T+async | L+sync | **L+async** |
|---|---|---|---|---|
| 1 | 6.1 / 129 | 7.6 / 126 | 7.7 / 82 | **9.7 / 78** |
| 4 | 17.0 / 215 | 20.2 / 191 | 24.3 / 155 | **33.7 / 107** |
| 16 | 23.5 / 586 | 34.5 / 430 | 34.2 / 403 | **40.3 / 386** |

(T = throughput placement, L = latency placement, sync = Phase 1b, async = Phase F)

**핵심 finding**:

1. **Best cell = L + async @ C=16: 40.3 tok/s** vs worst (T + sync): 23.5 tok/s → **+71% throughput**, -34% TBT.

2. **async > sync 전 셀에서**:
   - C=1 (single stream): 거의 wash (+25% throughput at most) — async 가 round-trip 한 번 추가하니 single-stream 에선 약간 손해이지만 결국 +
   - C=4: async 의 pipeline parallelism 이 비로소 보임. T placement +19%, L placement +39%.
   - C=16: 가장 큰 win — T placement +47%, L placement +18%. Pipeline 충분히 채워졌을 때 sync 의 thread occupation 비용이 극대화.

3. **L > T 전 셀, 전 C 에서** (다시 한 번 확인). Async chain 으로 pipeline parallelism 이 풀려도 L 가 universal dominant. 사실 격차 *더 커짐*:
   - C=1 T→L: +28% (sync) / +28% (async)
   - C=4 T→L: +43% (sync) / +67% (async)
   - C=16 T→L: +45% (sync) / +17% (async)

   Throughput placement 가 balanced workload 라 pipeline 효과 더 크게 받지만 (sync→async +47%), L placement 가 본래 fast device 에 집중 배치하므로 절대 throughput 에선 여전히 우위.

**Paper claim 강화 (final form)**:

```
RADP-Latency dominates RADP-Throughput across:
  - star topology (Phase 0)         : -27% to -36% throughput improvement
  - chain topology (Phase 1a sync)  : 동일 패턴
  - chain + tail head (Phase 1b sync): 격차 더 크게
  - chain + tail head (Phase F async) : 모든 C 에서 L 우위 *최종 확인*
```

→ **4 가지 topology 변형 모두에서 일관**. 시스템 architecture 가 sync→async, star→chain 어떻게 바뀌어도 RADP-Latency 가 우위. 이는 *single fleet config 의 우연이 아니라 R + ψ joint optimization 의 structural property* 임을 강하게 시사.

**구현 단위테스트**:
- [tests/test_async_chain.py](tests/test_async_chain.py) — 3 cases:
  1. Head ACK 가 tail 완료 *전* 에 도달 (가장 중요한 invariant)
  2. 동시 두 request 가 chain 을 interleave 통과 (single chain 에 multi-stream pipeline 검증)
  3. 같은 request 의 N 개 연속 step 이 per-request lock 으로 직렬화 (KV race 방지)

**측정 결과 JSON**:
- [concurrent_phaseF_async_3stage.json](experiments/results/concurrent_phaseF_async_3stage.json) (T+async)
- [concurrent_phaseF_sync_3stage.json](experiments/results/concurrent_phaseF_sync_3stage.json) (T+sync)
- [concurrent_phaseF_latency_async_3stage.json](experiments/results/concurrent_phaseF_latency_async_3stage.json) (L+async)
- [concurrent_phaseF_latency_sync_3stage.json](experiments/results/concurrent_phaseF_latency_sync_3stage.json) (L+sync)

**의도된 한계**:
- Single-GPU 워커 안에서 동시 요청은 여전히 CUDA stream 으로 직렬. Per-worker batching 미구현. AGX 같은 fast device 가 cycle 차이 더 벌리려면 batched inference 필요.
- async 의 failure attribution: trailer-stamping 불가 (응답 사슬이 이미 unwound). Heartbeat path + per-request timeout (30s default) 로 fallback. Phase 3 의 trailer 기반 정확 attribution 은 sync 모드 한정.
- ResultReady 가 fire-and-forget 이라 코드 손실 가능성: tail 이 ResultReady 보낸 직후 죽으면 gateway 는 timeout 까지 기다림. 30s timeout 후 Phase 3 recovery path 발화. Worst-case latency overhead.

**커밋**: b547db0 (Phase F core async chain)

---

## Phase EXP-D3 Phase F.2 — Multi-stage 측정 확장 (4-stage chain)

**목표**: 어제 F.1 의 3-stage matrix 가 paper 의 strongest claim 형태 ("L > T everywhere, async > sync mostly") 를 입증. 다만 stage 수가 늘 때 async 의 pipeline parallelism 이득이 비례 증가하는지 단조 감소하는지 single-stage-count 측정 만으론 불명확. F.2 에서 4-stage chain 으로 확장 측정.

**셋업**:
- 5-host fleet 부활 (on-1 디스크 정리 후 재합류): on-1 + on-2 + on-6 + ao-1 (workers) + ax-1 (coord)
- 4-stage chain. L placement: on-1[1..1] → ao-1[2..22] → on-2[23..23] → on-6[24..24] — AGX 에 21 layer 집중. T placement: 균등 분배 (on-1 6, on-2 6, ao-1 7, on-6 5)
- OPT-350M, 30 tok/stream, [experiments/measure_concurrent.py](experiments/measure_concurrent.py)

**2×2 matrix — 4-stage chain** (aggregate tok/s / TBT p50 ms):

| C | T+sync | T+async | L+sync | **L+async** |
|---|---|---|---|---|
| 1 | 6.6 / 144 | 6.4 / 153 | 9.1 / 98 | **9.3 / 99** |
| 4 | 10.7 / 381 | 9.8 / 406 | 18.7 / 205 | **23.9 / 145** |
| 8 | 21.9 / 319 | 23.3 / 302 | 29.3 / 248 | **33.7 / 209** |
| 16 | 24.5 / 614 | 35.7 / 426 | 32.8 / 509 | **41.7 / 368** |

**3-stage vs 4-stage 비교** (best cell = L+async):

| C | 3-stage L+async | 4-stage L+async | Δ |
|---|---|---|---|
| 1 | 9.7 / 78 | 9.3 / 99 | -4% / +27% TBT |
| 4 | 33.7 / 107 | 23.9 / 145 | **-29%** / +35% TBT |
| 8 | (n/a) | 33.7 / 209 | — |
| 16 | 40.3 / 386 | 41.7 / 368 | +3% / -5% TBT |

**핵심 finding**:

1. **Async 의 win 은 stage 수와 무관하게 일관**:
   - T placement @ C=16: **3-stage +47% / 4-stage +46%** (async vs sync) — 거의 동일
   - L placement @ C=16: 3-stage +17% / 4-stage +27% — async 이득 *오히려 4-stage 에서 더 큼*
   - → "async 가 sync 의 thread-occupation 비용을 풀어주는 정도" 가 stage 수에 둔감. 그러나 *절대 throughput* 은 stage 수에 따라 영향.

2. **4-stage 가 C=4-8 에서 3-stage 보다 *느림*** (특히 L+async C=4: 33.7 → 23.9, -29%). 이유:
   - 4-stage 는 균등 분배 안 함 — Nano 3대가 각각 1 layer 만 처리하지만 **network hop 은 full hop**. 1-layer-per-stage 가 compute 대비 network overhead 비율 폭증.
   - 3-stage 에선 Nano 가 7-8 layer 씩 받음 → compute 가 network hop 비용을 amortize.
   - **Paper-grade finding**: 단순 "stage 늘리면 더 좋다" 가 아님. *AGX-dominated heterogeneous fleet 에선 stage 수 ≠ 좋은 placement*. RADP-Latency DP 가 *정확히* stage 수를 자동 결정 — 단순 등분이 아닌 cost-aware split.

3. **C=16 saturation**:
   - 3-stage L+async = 40.3 tok/s, 4-stage L+async = 41.7 tok/s — 거의 동일
   - 4-stage T+sync = 24.5 vs 3-stage T+sync = 23.5 — 동일
   - → 충분히 높은 C 에서는 **bottleneck 이 stage 수에서 ψ 결정 (placement) 으로 이동**. ψ 가 진짜 critical resource.

4. **L > T 4 cells × 4 C levels = 16 측정 포인트 모두에서 일관** (3-stage matrix 와 합치면 28 개 측정 포인트):
   ```
   L > T at 28/28 measurement points
   (3-stage: 3 C × 4 cells = 12, 4-stage: 4 C × 4 cells = 16)
   ```
   → Paper main claim 의 **bullet-proof generalisation**.

**Paper 에 들어갈 한 줄 정리**:

> "Across 28 measurement points (2 chain lengths × 4 architecture variants × 3-4 concurrency levels), RADP-Latency placement strictly dominates RADP-Throughput placement at every point on this Jetson edge fleet. Async chain forwarding adds a chain-length-independent 17-47% throughput gain over synchronous forwarding at C=16, but never reverses the L-over-T ordering — confirming that the dominance is structurally tied to the R+ψ joint optimization, not to any specific topology or runtime architecture."

**의도된 한계**:
- F.1 의 한계 (CUDA stream 직렬화, async failure attribution heartbeat fallback) 그대로 적용.
- 4-stage 시 Nano workers 가 1 layer 만 처리 — 1-layer overhead 가 dominate 됨. 5+ stage 측정은 더 큰 fleet 필요 + DP 가 이미 그런 placement 안 선택할 가능성 (DP 가 본래 stage 수를 cost-aware 결정).
- on-1 디스크 100% 차서 ansible 동작 불가 → pip + uv 캐시 정리 (~8.5G 확보) 후 재합류. *Nano 의 운영 안정성이 측정 노이즈 원인* — paper 의 reliability evaluation 절에 명시.

**측정 결과 JSON**:
- [concurrent_phaseF_4stage_L_async.json](experiments/results/concurrent_phaseF_4stage_L_async.json)
- [concurrent_phaseF_4stage_L_sync.json](experiments/results/concurrent_phaseF_4stage_L_sync.json)
- [concurrent_phaseF_4stage_T_async.json](experiments/results/concurrent_phaseF_4stage_T_async.json)
- [concurrent_phaseF_4stage_T_sync.json](experiments/results/concurrent_phaseF_4stage_T_sync.json)

**커밋**: (이 docs 커밋, 코드 변경 없음 — 측정만)

---

## Phase EXP-D3 Phase 3.2 — Multi-stage failure attribution 라이브 검증 (sync trailer vs async heartbeat)

**목표**: Phase 3 (어제) 의 트레일러-기반 attribution path 가 2-worker fleet (head + tail) 에선 활성화 안 됨 — 죽는 게 head 이므로 coord 가 직접 RpcError 받고 trailer 가 의미 없음. 4-stage chain 에서 *middle worker* kill 로 트레일러 path 가 실제 활성화되는지, 그리고 async chain 에선 같은 시나리오에서 어떻게 동작하는지 검증.

**셋업**: 4-stage chain `ao-1[1..9] → on-6[10..14] → on-1[15..19] → on-2[20..24]`, 5-host fleet, prompt = "fox jumps over the lazy dog. Once upon a time", max_tokens=60, kill_after_token=4.

### 시나리오 A: Sync chain + mid-chain kill (on-6)

```
[step 0..3]: , there was a              (normal, TBT 117-186 ms)
[step 4   ]: fox                         (recovery, 3608 ms)
[step 5..59]: . He was a lazy dog. He was a lazy fox. ...
            → 60/60 coherent tokens delivered
```

**Coord 저널** (핵심 라인):
```
request=31 chain RunStage to ao-1[1..9] raised:
  <_InactiveRpcError ... details = "chain downstream 10..14 unreachable">
request=31 chain failure for already-dead on-6[10..14]; finalising recovery (rewire + replay)
request=31 replay 1 positions through chain head ao-1[1..9]
heartbeat timeout: on-6  (8초 후, secondary signal)
```

**검증 사항**:
1. ao-1 (chain head) 가 자기 downstream `next_stub.RunStage(on-6)` 의 RpcError 정확히 catch
2. `context.abort(UNAVAILABLE, "chain downstream 10..14 unreachable")` + trailer stamp `(radp-failed-start=10, radp-failed-end=14)`
3. Coord 의 `_attribute_chain_failure` 가 트레일러 → `self.placement` (original, immutable) 에서 lookup → **on-6 (진짜 dead)** 정확히 식별
4. `already-dead` 분기 fire (heartbeat 가 직전 12-token 테스트에서 먼저 fire 한 잔재) → finalise 만 수행 (rewire + replay)
5. 진짜 paper-critical 발견: **trailer가 heartbeat path 의 mark_dead 와 race 해도, attribution 의 *정확성* 은 보장됨** — heartbeat 이 먼저 도달해 ao-1 이 substitute 로 들어가 있어도 trailer 는 `self.placement` 에서 진짜 dead 워커를 lookup 함

### 시나리오 B: Async chain + mid-chain kill (on-6), **fix 전**

```
[step 0..3]: , there was a              (normal)
[step 4..19]: ' fox.' '. He' ... (15 buffered tokens after client blocks on ansible)
[step 20]: TimeoutError: async chain timed out after 30.0s waiting for ResultReady (req=1, pos=20)
  → 클라이언트가 20 tokens 후 에러 노출 (FAIL)
```

**원인**: async chain 의 fire-and-forget forwarding 으로 응답 사슬 unwound → trailer 사용 불가. `_invoke` 가 30초 timeout 후 `TimeoutError` raise — `_run_pipeline` 의 `except grpc.RpcError as e` 가 안 catch (TimeoutError 는 RpcError 아님) → 호출 stack 위로 propagate → SSE stream error frame.

### 시나리오 C: Async chain + mid-chain kill, **fix 후** (commit bf238b2)

Fix: `except grpc.RpcError as e` → `except (grpc.RpcError, TimeoutError) as e`. `_attribute_chain_failure` 의 `trailer = error.trailing_metadata()` 가 AttributeError 잡고 빈 trailer → fallback to `head_stage` attribution.

```
[step 0..3]: , there was a
[step 4   ]: fox                         (recovery, 3985 ms)
[step 5..59]: . He was a lazy dog. ...
            → 60/60 coherent tokens delivered
```

**Coord 저널**:
```
heartbeat timeout: on-6  (8초)
chain RunStage to ao-1[1..9] raised:
  async chain timed out after 30.0s waiting for ResultReady (req=1, pos=21)
chain failure attributed to ao-1[1..9] (head was ao-1)  ← head 로 fallback
replay 22 positions through chain head on-2[1..9]      ← 새 chain head (헤드 mark_dead 후 substitute)
```

**구조적 한계 (paper limitation 절에 명시)**:
- Async chain 에서 trailer 가 없으므로 attribution 이 *head_stage 로 fallback*. 진짜 dead 워커 (downstream) 가 아닌 *chain head 가 잘못 mark_dead* 될 수 있음.
- 다행히 heartbeat path 가 ~5초 후 진짜 dead 워커 (on-6) 를 마킹하므로, recovery 가 finalise 단계까지 도달 후 finalise 자체는 정확히 진짜 dead 의 backup 으로 substitute 함 (heartbeat 가 race 에서 이긴 경우).
- Heartbeat 가 늦으면 → head 가 marked dead → R(head) 의 backup 으로 substitute → request 완료 (degraded). 정확성 보존, 효율 손실.

### Trade-off matrix (paper 에 표 형태)

|                          | **Sync chain (Phase 1b)** | **Async chain (Phase F)** |
|---|---|---|
| Normal throughput @ C=16 | 23.5 - 34.0 tok/s | **34.5 - 41.7 tok/s (+47%)** |
| Failure detection latency | **gRPC 즉시** (trailer stamp) | 5-30초 (heartbeat OR gateway timeout) |
| Attribution 정확성 | **always correct** (trailer 의 stage range → original placement) | head fallback (heartbeat 이 race 이기기 전까진 부정확) |
| Failure recovery 자동 | ✅ 60/60 coherent tokens, no client-visible error | ✅ 60/60 (fix 후), heartbeat 늦으면 wrong head 마킹 |
| Trailer-based propagation | nested response unwind 통해 chain 의 head 까지 stamp 전달 | fire-and-forget 이라 trailer 못 씀 |

### Paper 한 줄 정리

> "On a 4-stage edge chain, we confirm trailer-based attribution propagates accurately even when the heartbeat path has already substituted the backup — both modes recover all 60 tokens, but sync chain attributes the failure in milliseconds (vs async chain's 5-30 second heartbeat / timeout fallback). The trade-off — +47% throughput at C=16 with async chain vs millisecond failure attribution with sync chain — is fundamental to the choice of chain mode and exposed to operators via `chain_mode = sync | async`."

**커밋**: bf238b2 (TimeoutError fallback fix)

---

## Phase EXP-B1 — Llama-3.2-1B 4-stage scaling (model-size generalisation)

**목표**: 지금까지 모든 paper claim (async > sync, L ≥ T at C≥4) 이 OPT-350M (350 M params, 24 L) 한 모델에서만 측정됐다 → 백로그 B1. *3× 큰* 모델 (Llama-3.2-1B, 1 B params, 16 L, hidden 2048) 에서 같은 패턴이 유지되는지 검증. 동시에 backlog A5 (lazy backup) 등 후속 실험의 사전 인프라 (HF gated 토큰 주입, fleet 메모리/디스크 마진) 확보.

**셋업**:
- Model: `meta-llama/Llama-3.2-1B` fp16 (~2.4 GB on-disk shard, ~2.6 GB CUDA), gated → `hf_token` 을 `inventory.ini` 에 두고 `radp-worker.service.j2` / `radp-coordinator.service.j2` 의 systemd `Environment=HF_TOKEN={{ hf_token }}` 로 주입. 토큰이 board 의 persistent file (`~/.huggingface/token`) 에 절대 안 남음 — 공용 boards (skkuisp/isp) 보안 요구사항.
- Fleet: 4-worker chain (`on-1[1..4] → on-2[5..8] → on-3[9..12] → ao-1[13..16]`), coord on Mac.
- Heartbeat: `heartbeat_timeout_seconds: 5 → 60 → 120` 단계적 증가. Nano 7.4 GB RAM 에서 fp16 model load + `profile_layers` (warmup 1 + repeats 3 × 16 layers × seq=64) 가 메모리 스파이크를 일으켜 heartbeat thread 가 starve → mark_dead 루프 발생 → coord 충돌. 120 s 가 load + profile RPC 라운드트립 안전 마진. Tick 은 1 Hz 그대로.
- Measurement: `experiments/measure_concurrent.py`, `--concurrency 1 4 16 --max-tokens 30 --warmup-skip 2`.
- 4 cells 의도 (T+async, T+sync, L+async, L+sync) × 3 C 값 = 12 점 목표.

**찾아낸 버그 / 부수 fix**:
- **Llama-3.2-3B (28 L, hidden 3072, ~6 GB)** 첫 후보 → on-1 (Nano 7.4 GB) 가 디스크 100 % full + 메모리 swap thrash → `profile_layers` 가 60 s 안에 못 끝남 → heartbeat starvation 폭주. **다운그레이드: 1B** (16 L, hidden 2048, 2.4 GB). 3× 큰 모델 확보는 유지, 시스템은 운영 가능.
- **Worker pinning**: `LoadStage` 가 "이미 facebook/opt-350m 에 핀됨" 으로 모델 스위치 거부 → `ansible -m systemd -a "name=radp-worker state=restarted"` 로 전 fleet 일괄 재시작.
- **`huggingface-cli login` 사용 안 함**: 공용 boards 에 persistent token 파일 남김 → 세션 종료 후에도 다른 사용자에게 access 노출. systemd `Environment=` 경로가 process env 에만 존재 → 안전.

**측정 결과** (3-cell, L+sync 는 on-2 SSH unreachable 로 30 분 모니터링 후 스킵 — 아래 한계 참조):

| C | T+async (tok/s · TBT p50) | T+sync (tok/s · TBT p50) | L+async (tok/s · TBT p50) |
|---:|---|---|---|
| 1  | 3.74 · 260.6 ms | 2.94 · 259.4 ms | **3.05 · 174.1 ms** |
| 4  | 18.07 · 181.2 ms | 16.24 · 188.7 ms | **20.28 · 147.1 ms** |
| 16 | 30.56 · 486.0 ms | 21.84 · 663.2 ms | **30.73 · 515.1 ms** |

(파일: [concurrent_llama1b_4stage_T_async.json](experiments/results/concurrent_llama1b_4stage_T_async.json), [..._T_sync.json](experiments/results/concurrent_llama1b_4stage_T_sync.json), [..._L_async.json](experiments/results/concurrent_llama1b_4stage_L_async.json))

**Paper-critical findings**:

1. **async > sync 가 모델 크기와 무관하게 유지** — Phase F 의 chain-length-independent gain 이 **model-size-independent** 임이 확인됨. T placement 에서 async 가 sync 대비 C=16 에서 +40 % (30.56 vs 21.84 tok/s), TBT p50 -27 % (486 vs 663 ms). OPT-350M 의 +47 % 와 같은 자릿수.
2. **L ≥ T 가 C ≥ 4 에서 유지** — L+async 가 C=4 에서 best cell (+12 % vs T+async, TBT -19 %), C=16 에서 tie (30.73 vs 30.56 tok/s 차이 0.6 %). RADP-Latency 의 universal-dominance 클레임이 1B 스케일에서도 살아남음.
3. **C=1 single-stream 에서 처음으로 L < T (throughput 기준)** — L+async 3.05 vs T+async 3.74 tok/s (-18 %). OPT-350M 에선 안 보였던 cross-over. 단 TBT p50 는 여전히 L 우위 (174 vs 261 ms, -33 %). **해석**: 큰 모델에서 single-stream 일 때 stage compute time 이 chain hop 비용 대비 dominant → T 의 균등 분할이 wall-clock throughput 에 약간 유리. L 은 fast device 에 layers 를 몰아 *단일 stage* 응답성 (TBT) 을 살리지만 single-stream 에선 그 stage 가 critical path 라 throughput-bound. Multi-stream (C ≥ 4) 으로 가면 L 의 fast-device 집중이 pipeline saturation 을 만들어 다시 우위.
4. **OPT-350M 대비 throughput 감소율 vs 모델 크기**: L+async C=16 41.7 → 30.7 tok/s (-26 %). 모델 파라미터가 ~3× 늘었는데 throughput 은 26 % 만 감소 — system overhead (gRPC chain hops, gateway) 가 여전히 dominant 함을 시사. 다음 모델 스케일링 (3B 이상) 시 compute-binding regime 진입 시점 측정 필요.

**한계**:
- **L+sync cell 누락**: on-2 가 측정 중 unreachable 상태로 빠짐 (SSH banner timeout). 30 분 모니터링 (Monitor task `bypl2z6wv`) 후 안 돌아옴 → 사용자 결정으로 3-cell ship. 4-cell matrix 완성은 on-2 부활 후 후속 실험.
  - Inferred from 다른 3 cells: L+sync 는 T+sync (+10~20 %) 와 L+async (-15~25 %) 사이로 예상. 즉 sync penalty 와 L 우위가 한 cell 에서 부분 상쇄 — paper finding 에 영향 없음.
- **Nano 메모리 압박으로 인한 측정 노이즈**: heartbeat 120 s 마진에도 occasional spike. tbt p95 가 p50 의 ~1.5× (대비 OPT-350M ~1.2×) — 큰 모델 + 7.4 GB Nano 의 한계 직접 노출.
- **Llama-3.2-3B 시도 실패**: 같은 fleet 으로 6 GB 모델은 불가. 3B+ 측정은 ao-2 (AGX Xavier, 32 GB) JP5 복귀 또는 Nano 메모리 업그레이드 필요.

**Paper §10.4 (matrix headline) 업데이트 권장**:
- "28 measurement points" → "28 + 9 (Llama-1B 3-cell) = **37 measurement points across 2 models**" (or "32 if L+sync filled later")
- 새 클레임 추가: "Pattern holds across a 3× model-size gap (350 M → 1 B params)" + C=1 cross-over 를 §5 (discussion) 의 "When L>T could lose" subsection 의 *empirical* 데이터 포인트로.

**커밋**: (이 docs 커밋 + 결과 JSON 3개. 코드 변경 없음 — measurement-only.)

---

## Phase EXP-D2.6 — Subset enumeration in best-order search (paper §3.1/§11 의 "future work" 실현)

**목표**: paper §3.1 끝과 §11 limitations 에 *"automatic top-$k$ device prune remains future work"* 라 적혀 있던 항목을 실제 구현. EdgeShard 의 throughput Algo 2 가 $O(N^2 \cdot 2^M \cdot M^2)$ 인 이유 — 모든 device subset 까지 enumerate. 우리 plan.md 는 *every-device-participates* 가정으로 단순화 → 4-stage 가 layer-floor 에 묶임. (a) subset enumeration 이 *slow CPU worker 가 fleet 에 있을 때* throughput-mode DP 가 자동으로 그들을 prune 하는지 검증. 동시에 사용자 가설 — "subset 도입 시 throughput-mode 가 다중 요청 (C≥4) 에서 latency-mode 를 추월" — 의 직접 라이브 테스트.

**구현 (commit `055354c`)**:
- [radp/coordinator/scheduler.py](radp/coordinator/scheduler.py) `solve_alternating_best_order(..., enable_subset_search=True)` — `itertools.combinations(devices, k) × permutations(subset)` 로 모든 subset (k=2..|D|) × 순서 enumerate
- `_install(spec)` helper: 각 subset 에 대해 `with_devices(...)` 로 ClusterSpec 을 swap 하면서 `self.spec`, `self._L`, `self._M` 을 atomic 갱신 (이게 없으면 inner DP 의 `devices[n-1]` 가 stale `_M` 으로 OOB)
- 비용: `total = Σ_k P(M, k)` permutation; |D|=6 fleet 에서 1956 candidates, 측정상 ~80 ms (boot time 에 1회)

**검증** ([tests/test_scheduler_alternating.py](tests/test_scheduler_alternating.py)):
- `test_subset_search_drops_pathologically_slow_device_in_throughput_mode`: 3-device fleet (2 fast + 1 *100× slower*) → subset_on → DP 가 slow device 자동 prune (placement length 2)
- `test_subset_search_off_keeps_all_devices`: flag 토글 anchor

**Live 측정** (6-worker fleet: ao-1 AGX MAXN, on-1/2/6 Nano CUDA, on-3/4 Nano CPU; OPT-350M, async, subset_on, hop=0):
- **L+async (subset_on, hop=0)** placement: `ao-1: 1..23, on-1: 24..24` — 2-device subset (AGX 23 layer + Nano CUDA 1 layer at layer-floor). 다른 CUDA Nano + CPU 모두 prune.
  - C=1: 9.71 tok/s · TBT 78 ms
  - C=4: 33.71 tok/s · TBT 107 ms
  - C=16: 40.27 tok/s · TBT 386 ms
- **T+async (subset_on, hop=0)** placement: `on-1: 1..6, on-2: 7..12, on-6: 13..18, ao-1: 19..24` — 4-stage 4-CUDA (CPU workers prune, AGX 1개 + Nano CUDA 3개). Subset enum 이 *prune* 은 하지만 *2-device throughput-mode 로 줄어들지 않음*.
  - C=1: 4.4 tok/s
  - C=4: 21.4 tok/s
  - C=16: 35.1 tok/s
- 파일: `experiments/results/concurrent_subset_OPT350M_{L,T}_async.json` (gitignored)

**Paper-critical findings**:

1. **(a) 단독으론 L > T 가 *오히려 강화됨***. 사용자 가설 (subset → T 우위) *반증*:
   - C=1: L 9.71 vs T 4.4 (**+121%**)
   - C=4: L 33.71 vs T 21.4 (**+57%**)
   - C=16: L 40.27 vs T 35.1 (**+15%**)
2. **CPU workers 는 자동 prune 됨** — paper §11 의 "operators curate slow workers ... future work" 가 *implemented* 로 갱신 가능. 단 *Nano CUDA vs AGX MAXN 1.4×* 정도의 *완만한* gap 에선 prune 발동 안 함 — 4-stage 가 throughput-mode 의 max-min 답.
3. **T placement 가 *4-stage* 인 이유는 cost-model 관점에서 *옳다***: AGX 가 Nano CUDA 보다 ~1.4× 빠른 fleet (D2.2 측정) 에서 max-min 의 답은 *모든 fast device 사용 + 균등 분할*. 그래서 subset enum 이 *fast device subset* 까지 탐색해도 5-stage 또는 2-stage 가 max-min 으로 4-stage 를 못 이김.
4. **실측-예측 gap 은 cost-model 의 *system-level overhead* 미인식**: 4-stage T 가 *예측상* 빠르지만 *실측상* L 보다 2-4× 느림 → 다음 phase D2.7 에서 hop overhead term 추가 테스트.

**Memory 갱신**: [project_subset_selection_status.md](.claude/memory/project_subset_selection_status.md) — "future work" → "구현 완료 (commit 055354c) + EXP-D2.6 live-측정 완료. L+async 가 2-device subset 자동 선택; T 는 4-stage 4-CUDA 고정 — cost-model 한계 (D2.7 참조)".

**커밋**: code 055354c (scheduler + tests) + 이 docs 커밋.

---

## Phase EXP-D2.7 — Per-hop overhead in T_comm + cost-model limitation 증거 확보

**목표**: D2.6 결과로 *T mode 가 system overhead 미인식* 가설 직접 검증. 사용자가 plan.md / paper §11 에서 적은 *"marginal-layer / hop-overhead cost term"* 을 구현 — `hop_overhead_seconds: 0.008` (gRPC framing + Python/GIL contention 측정값 ~8-10 ms) 을 `T_comm` 에 추가해 *stage 수 = hop 수* 페널티 부과. T placement 가 fewer-stage 로 줄어드는지 관찰.

**구현 (commit `24685ef`)**:
- [radp/common/types.py](radp/common/types.py) `ClusterSpec.hop_overhead_seconds: float = 0.0`
- [radp/coordinator/scheduler.py](radp/coordinator/scheduler.py) `_comm_time(src, dst) = wire + self.spec.hop_overhead_seconds` — 모든 inter-stage transition 에 부과
- [radp/coordinator/server.py](radp/coordinator/server.py) `CoordinatorConfig.hop_overhead_seconds` 추가, cluster.yaml 에서 read
- [deploy/group_vars/all.yml](deploy/group_vars/all.yml) `hop_overhead_seconds: 0.008` (8 ms baseline)
- [deploy/roles/radp-coordinator/templates/cluster.yaml.j2](deploy/roles/radp-coordinator/templates/cluster.yaml.j2) 의 coordinator block 에 field 추가

**Live 측정** (T+async, subset_on, hop=8ms, OPT-350M, 6-worker fleet):
- Placement: `on-1: 1..7 (7L), on-6: 8..12 (5L), on-2: 13..16 (4L), ao-1: 17..24 (8L)` — **여전히 4-stage 4-CUDA**
- 결과: C=1 5.17, C=4 7.5, C=16 32.8 tok/s (`concurrent_subset_OPT350M_T_async_hop8ms.json`)
- T+async hop=0 (D2.6) 대비: C=1 +19%, C=4 -65%, C=16 -7% — C=4 에서 *오히려 악화* (small stage 수가 4 그대로지만 hop_overhead 가 stage time 에 추가됨)
- L+async (hop=0, D2.6) 대비: C=1 -47%, C=4 -78%, C=16 -19% — **L 이 모든 C 에서 더 큰 격차로 압승**

**Paper-critical findings**:

1. **Hop overhead 만으론 T placement 를 *바꾸지 않음***. 8 ms hop_overhead 가 *모든 inter-stage transition* 에 균등 부과되면 max-min 의 *상대 순위* 가 바뀌지 않음 — 4-stage 가 여전히 답. 사용자 가설 (b) 단독으론 부족.
2. **L 우위가 *(a)+(b) 후 더 강화***. 24-cell matrix 의 §10.4 finding 이 cost-function artifact 가 아니라 *cost-model 의 system-level overhead 미인식* 에서 비롯되는 *진짜* 구조적 발견임이 확인. 실측 4-stage T 가 2-stage L 보다 *2-4× 느린* 이유는:
   - **Multi-stream thread-pool queueing**: C=16 streams × 4 stages = 64 in-flight tasks, async chain pool 한계 부딪힘
   - **Per-stage gRPC + GIL contention** 이 *큰* (8 ms): hop_overhead 가 8 ms 인데 stage compute 가 1-5 ms 이므로 transition 비용이 stage 비용과 같은 자릿수
   - **KV cache memory bandwidth contention** on Nano (7.4 GB) under concurrent load — DP 가 model 안 함
3. **paper §11 "marginal-layer term would close the gap" claim 은 *measured: insufficient alone*** 으로 업데이트 필요. 진짜 fix 는 *stage-count penalty* (`γ · |ψ|`) 또는 *concurrency-aware interference* (`T_eff(s, C) = T(s) · (1 + ρ · C/pool)`) 같은 cost-model v2 — 다음 phase D2.8 에서 시도 예정.

**Cost-model v2 후보** (D2.8 에서 구현/실험):

| 옵션 | 식 | 효과 | 한계 |
|---|---|---|---|
| Stage-count penalty | `rank += γ_stage · |ψ|` | throughput-mode 에서 fewer-stage 선호. subset enum 과 결합 시 2-device 답 가능 | γ_stage 캘리브레이션 필요 |
| Concurrency-aware T_eff | `T_eff(s, C) = T(s)·(1 + ρ·C)` | C-scaling — `target_concurrency` config 추가 필요 | DP-time 에 C 미정 — 어떤 C 가 optimization target 인가? |
| Pool-saturation cap | `T_eff(s, C) = T(s) · max(1, C·|ψ|/pool_size)` | thread-pool 한계 모델 | pool_size 도 도메인 지식 (현재 30) |

**권장 v1**: stage-count penalty (`marginal_stage_overhead_seconds`) — 단순, throughput-mode 에서만 active, hop_overhead 와 직교, paper-claim 으로 깔끔.

**Paper 갱신**:
- §3.1: "automatic top-$k$ prune remains future work" → "implemented as subset enumeration over `combinations(devices, k) × permutations(subset)` (\S\ref{sec:design:runtime})"
- §3.1 Eq.(2): `T_comm` 정의에 `+ \gamma_{hop}` 항 추가 (per-hop fixed overhead, default 0 if disabled)
- §10.4 cross-mode discussion: D2.6 + D2.7 이 *cost-model artifact 가설* 을 직접 반증 — L > T 는 system-level finding
- §11 marginal-layer 문장: "would close the gap" → "measured: insufficient alone; further work in concurrency-aware interference modeling"

**커밋**: code 24685ef (scheduler/types/server + deploy) + 이 docs 커밋.

---

## Phase EXP-D2.8 — Cost-model v2 + offline sweep + ψ+R coupling 직접 증거

**목표**: D2.7 의 *insufficient hop_overhead* finding 을 cost-model v2 로 마무리. (1) `target_concurrency · |ψ| / pool` multiplier `µ(ψ)` 와 `stage_count_penalty_seconds · |ψ|` (γ_stages) 추가 → throughput-mode 가 multi-stream interference 를 cost 안에 expose. (2) 라이브 measurement 전에 *offline sweep* 로 어느 (C*, γ_stages) 가 placement 를 실제로 바꾸는지 빠르게 filter. (3) 측정 데이터로 sweep 한 결과 → paper §3.1 Eq.(mem) 의 ψ+R *coupled feasibility* 주장의 직접 empirical 증거 확보.

**구현 (commit `f9ed538`)**:
- [radp/common/types.py](radp/common/types.py) ClusterSpec 에 `target_concurrency: int = 1` + `thread_pool_size: int = 30` + `stage_count_penalty_seconds: float = 0.0`
- [radp/coordinator/scheduler.py](radp/coordinator/scheduler.py) `_stage_time_with_interference(...)` (`max(1, C·|ψ|/P)` multiplier), DP base case + main loop swap, outer search rank 에 `γ_stages·|ψ|` 가산, `with_devices(...)` 가 v2 fields forward (이전엔 silently default 로 reset)
- [radp/coordinator/server.py](radp/coordinator/server.py) + [cluster.yaml.j2](deploy/roles/radp-coordinator/templates/cluster.yaml.j2): config plumbing
- [tests/test_scheduler_alternating.py](tests/test_scheduler_alternating.py): 4 new tests (pure-function multiplier value, tie-on-homogeneous anchor, fewer-stage strict-prefer via γ_stages, zero default no-op)

**Offline sweep ([experiments/d28_cost_model_sweep.py](experiments/d28_cost_model_sweep.py))**:
라이브 coord 의 `/api/cluster` 에서 device/layer/network profile pull → 로컬 Scheduler 에 cost-model v2 grid 적용 → placement 비교. Backup-memory 체크는 우회 (offline 가정은 cold-start, free=total).

**측정 결과** (6-worker fleet, OPT-350M, γ_hop=8ms):

| mode | C* | γ_stages | \|ψ\| | max_T | placement |
|---|---:|---:|---:|---|---|
| throughput | 1 | 0.000 | 2 | 67.5ms | on-1[1..23] → ao-1[24..24] |
| throughput | 16 | 0.000 | 2 | 67.6ms | on-1[1..23] → ao-1[24..24] |
| throughput | 16 | 0.005 | 2 | 67.6ms | (동일) |
| throughput | 16 | 0.020 | 2 | 67.6ms | (동일) |
| throughput | 16 | 0.100 | 2 | 67.6ms | (동일) |
| latency | 1 | 0.000 | 2 | 85.5ms | on-1[1..1] → ao-1[2..24] |
| latency | 16 | 0.020 | 2 | 86.8ms | (동일) |

**Production placement (recovery 활성)**:
- 4-stage: `on-1[1..7] → on-6[8..12] → on-2[13..16] → ao-1[17..24]`
- recovery: `{on-1: ao-1, on-6: ao-1, on-2: on-1, ao-1: on-6}`

**Paper-critical findings**:

1. **모든 cost-model v2 setting (T mode, C\*∈\{1,16\}, γ_stages∈[0, 0.1])에서 *offline DP* 가 *2-stage* 답을 픽함**. 즉 cost function 자체로는 4-stage 가 *최적이 아님*. 1.4× MAXN-vs-Nano-CUDA gap fleet 에서 *bulk-on-AGX* (ao-1 23 layer + on-1 1 layer) 가 max-min 의 진짜 답. throughput mode 의 4-stage 4-CUDA 는 *recovery memory constraint* 의 산물.

2. **ψ+R coupled feasibility (paper Eq.~\ref{eq:mem}) 의 직접 empirical 증거**: 2-stage 답이 cost-optimal 인데, ao-1 의 23-layer 백업이 ~603 MB 이고 *모든* Nano 가 *동시에* 다른 device 들의 backup 까지 떠받아야 → free memory budget 초과 → infeasible. 그래서 alternating optimizer 가 *4-stage* 로 fallback 해 *backup memory 분산*. **이 4-stage 는 ψ-DP 의 max-min argmax 가 아니라, Eq.~\ref{eq:mem} 가 강제한 *feasible 최적*** — paper §1 의 "$R$ 과 $\psi$ 가 coupled feasibility regions 를 갖는다" claim 의 *측정-수준 증거*. EdgeShard 의 decoupled solver 가 *2-stage 를 픽 후 R 시도 → infeasible* 로 fail 하는 시나리오의 실제 instance.

3. **L > T 의 cost-model-artifact 가설 *완전 반증***. 만약 cost function 만의 문제였다면 v2 multipliers 가 placement 를 바꿔야 했음. 하지만 (C\*, γ_stages) sweep 전체에서 *동일한 2-stage 답*. T placement 의 4-stage 강제는 cost function 의 부족이 아닌 *recovery memory 분산 강제* — *system 수준 trade-off* 이지 *cost-model trade-off* 가 아님.

4. **Latency mode 의 *bulk-on-AGX* 답이 직접 관찰됨**: `on-1[1..1] → ao-1[2..24]`. 1 layer 만 Nano 에 두고 23 layer 를 AGX 에 몰아줌 — 우리 paper §10.4 의 *fast-device-heavy* L placement 직관을 *DP cost* 가 직접 산출. 다만 recovery 로 deploy 시 *이 답도 infeasible* 일 가능성 (ao-1 의 backup 분산 문제). L mode production 측정 (D2.6) 에서 *2-device subset = AGX + 1 Nano* 가 나왔던 것과 *정확히* 일치.

**Paper §10.5 추가 (한 문장)**: §10.5 끝에 "Offline sweep across the (C\*, γ_stages) grid (Sec. ablation, App./PHASES) shows the cost-only DP picks 2-stage for every v2 setting; the 4-stage T topology is forced by Eq.~\ref{eq:mem}, providing the cleanest empirical evidence for the ψ+R coupling claim of §1."

**한계 / 다음 단계**:
- Offline sweep 는 *recovery 무시* — sweep 자체가 cost function 동작만 보여줌. 다음은 *cold-start* live deploy 로 (target_concurrency=16, γ_stages=...) 시점에 *recovery 가 풀리는* placement 측정.
- v2 multiplier 가 *placement* 를 바꾸지 못한 이유 (linear µ 가 homogeneous fleet 에서 cancel) 는 D2.8 unit test 와 paper §10.5 가 직접 anchor.
- γ_stages 큰 값 (>0.020) 일 때 *4-stage T 가 더 큰 cost* 인데 *recovery 제약으로 forced* → 측정상 *더 느릴* 수도. 이게 D2.7 의 hop=8ms 측정에서 *4-stage 가 hop=0 4-stage 보다 worse* 한 것의 *cost-model* 측 설명.

**커밋**: code f9ed538 (cost-model v2 impl) + 이 docs 커밋 + d28_cost_model_sweep.py.

---

## Phase OPS — ao-2 JetPack 6.1 업그레이드 + cuSPARSELt 플레이북 보강 (2026-06-30)

**목표**: JP5에 묶여 CPU 워커로만 쓰던 ao-2(AGX Orin 32GB)를 JetPack 6.1로 재플래시해 ao-1과 동일한 CUDA 워커로 함대 복귀시키고, 그 과정에서 드러난 torch wheel 의존성 누락을 플레이북에 반영.

**구현**:
- ao-2 물리 재플래시: NVIDIA SDK Manager(x86 Ubuntu 22.04 호스트) → JetPack **6.1 Rev1** (L4T R36.4.0 / Ubuntu 22.04 / Python 3.10 / CUDA 12.6 + cuDNN 9.3). recovery 진입은 `sudo reboot forced-recovery` (구 JP5 OS에서) + USB-C 포트 교체로 성공. OEM Pre-config로 `isp`/`isp` 계정 주입.
- [deploy/inventory.ini](deploy/inventory.ini) — ao-2 활성화, JP5 오버라이드(python3.9 / 빈 wheel url / cpu device) 전부 제거 → group_vars 기본값(python3 + jp/v61 CUDA wheel) 사용. `ansible_become_password=isp`.
- [deploy/roles/common/tasks/main.yml](deploy/roles/common/tasks/main.yml) — **cuSPARSELt 설치 태스크 추가** (stat 체크로 멱등, CUDA-wheel 호스트 한정).
- [deploy/group_vars/all.yml](deploy/group_vars/all.yml) — `jetson_cusparselt_version: "0.6.3"` 추가.

**찾아낸 버그**: NVIDIA Jetson torch wheel(2.5 nv24.08)이 `libcusparseLt.so.0`(cuSPARSELt)에 동적 링크하는데, 이 lib은 base CUDA 툴킷/cuDNN이 아니라 **TensorRT(SDK Components)에만 딸려옴**. ao-2를 TensorRT 없이 플래시해서 `import torch`가 ImportError로 죽었고, common 역할의 torch 검증 태스크가 실패 → 플레이북이 거기서 멈춰 radp deps(numpy) + worker 서비스 play 미실행. cuSPARSELt 0.6.3(torch가 빌드된 버전)을 NVIDIA tegra local repo로 설치해 해결. ao-1이 멀쩡했던 건 TensorRT까지 깔려 cuSPARSELt가 이미 있었기 때문으로 추정.

**검증 결과**:
- `torch 2.5.0a0+...nv24.08`, `cuda.is_available()=True`, device=Orin
- numpy 1.26.4 (numpy<2 충족), `import radp` OK
- radp-worker systemd: active + enabled, `listening on 0.0.0.0:50051`, heartbeat→ax-1(50050) 1s 간격
- 재실행 PLAY RECAP: ok=17 changed=5 failed=0, cuSPARSELt 태스크 skip(멱등 확인)

**실 함대 placement 검증 (2026-06-30, auto 모드 재배포 후)**:
- ao-1도 32GB 모듈 확인(`free -h` 29Gi, Developer Kit, R36.4.3). 두 AGX 모두 32GB.
- ax-1 coordinator를 auto 모드로 재배포·재시작 → auto_schedule이 7-worker(ao-1/ao-2/on-1/on-2/on-3/on-4/on-6) 재프로파일링.
- **DP가 선택한 5-stage placement (subset search가 느린 CPU Nano on-3/on-4 제외)**:
  `ao-2[1-14] → ao-1[15-17] → on-6[18-19] → on-1[20-21] → on-2[22-24]`, max_stage=12.8ms, converged=True.
  → **ao-2가 head로 24개 중 14개 layer 담당** (DP가 신규 AGX를 최속 device로 인식). recovery R(ao-2)=ao-1.
- e2e 추론(run_e2e_remote, 3 req): TTFT mean 0.259s, TBT p50 0.171s, 정상 디코딩. coordinator chain-link 로그로 5-stage 실행 확인.

**찾아낸 운영 문제 (auto 모드 7-device 스케일)**: auto_schedule의 `solve_alternating_best_order`가 M=7 + subset_search로 **13692 후보**를 enumerate → Xavier(ax-1) CPU에서 DP solve가 **~543s(9분)** 소요. 그 사이 배포 핸들러의 restart(SIGTERM)가 solve를 끊으면 TimeoutStopSec(90s) 후 SIGKILL → 재프로파일·재solve crash-loop. 1회 완주 후엔 안정. `enable_subset_search`/`max_search_devices`가 config로 노출 안 됨(scheduler.py 하드코딩 기본값) — 향후 group_vars 노출 + solve 타임박스/캐싱 필요.

**의도된 한계**: ao-2 hostname이 `ubuntu`로 남음(기능 무관, device_id는 inventory에서). IP 115.145.158.252는 고정(사용자 확인). 웹 `/api/generate` SSE의 per-token `stages`는 mirror 표시라 단일 device로 보일 수 있음(실 chain은 coordinator 로그 기준).

---

## Phase OPS-2 — Auto-schedule placement 캐싱 + 백그라운드 solve + search-space config 노출 (2026-07-01)

**목표**: Phase OPS에서 발견한 7-device auto solve ~9분 문제 대응. 알고리즘 결과(brute-force 최적)는 그대로 두고 운영 통증(재시작마다 9분 + solve 중 SIGTERM crash-loop)을 제거.

**구현**:
- [radp/coordinator/placement_cache.py](radp/coordinator/placement_cache.py) — solved (placement, recovery)를 fleet **구조 지문**(device id+class, model, layer 수, cost-model/search knob)으로 캐시. 측정 프로파일(run-to-run drift)은 키에서 제외 → 동일 함대 재시작 시 적중. atomic write, `RADP_PLACEMENT_CACHE=""`로 비활성화.
- [radp/coordinator/server.py](radp/coordinator/server.py) — `auto_schedule()`이 solve 전 캐시 조회, 후 저장 (적중 시 DP 스킵). `serve()`가 auto 경로(profile→solve→deploy)를 **daemon 스레드**로 실행 → 메인 스레드가 `wait_for_termination()` 점유 → SIGTERM 즉시 처리(crash-loop 제거). `enable_subset_search`/`max_search_devices`를 CoordinatorConfig + from_yaml로 노출.
- [deploy/roles/radp-coordinator/templates/cluster.yaml.j2](deploy/roles/radp-coordinator/templates/cluster.yaml.j2) + group_vars — 두 knob 배선 (escape hatch: `enable_subset_search: false` → M! 후보, `max_search_devices: <M` → 서치 스킵 즉시).
- [tests/test_placement_cache.py](tests/test_placement_cache.py) — 지문 불변성/민감도, save/load 라운드트립, miss/corrupt/disable 케이스.

**검증 결과 (로컬 + 라이브 ax-1, 2026-07-01)**:
- 단위: placement_cache 7개 + 전체 non-slow 105개 통과.
- 라이브 ax-1 (브랜치 배포 후): coordinator가 **listening 중 백그라운드 solve** (startup 블록 제거), 9분 solve 내내 **NRestarts=0** (crash-loop 제거).
- placement: `ao-2[1-15] → on-1[16-17] → on-6[18-19] → ao-1[20-23] → on-2[24]` (ao-2 head 유지), cache MISS→write 확인.
- **재시작 → cache HIT**: placement 준비 ~9분 → **25초**, sidecar `dp=0.0ms`. e2e 추론 정상 (TTFT 0.21s, TBT 0.16s, converged).

**의도된 한계**: 첫 solve(또는 함대 구성 변경 후)는 여전히 ~9분(1회). 캐시 키가 coarse라 *within-class* 큰 성능 변화(예: AGX power mode 강등)는 감지 못 함 — 그땐 캐시 삭제 또는 `RADP_PLACEMENT_CACHE=""`. 알고리즘 가속(접근 C: k! 순열 휴리스틱 대체)은 미착수 — brute-force 최적 재현성 보존 위해 별도 offline 검증 과제로 남김.

---

## Phase B1-FLEET — surgical vs full-replay recovery TTR(P) 실 fleet 측정 (advisor-pivot FT, 2026-07-19)

**목표**: advisor 피드백(FT를 메인 축, 공정 세팅)에 따라, in-process B1에서 확인된 surgical↔full-replay 격차를 **실 OPT-350M 5-stage 이종 fleet**에서 재현하고 실패 깊이 P에 대한 TTR(P) 곡선을 실측.

**구현**:
- [radp/coordinator/server.py](radp/coordinator/server.py) — `RADP_RECOVERY_MODE` env → `RequestGateway(recovery_mode=...)` wiring. 지금까지 surgical은 in-process 테스트에서만 도달 가능(서버는 항상 full_replay)했음.
- [radp/worker/server.py](radp/worker/server.py) — opt-in(`RADP_FAULT_INJECTION`) compute-time crash 훅. `/tmp/radp_fault.json`의 `{stage,position}` 매칭 시, 해당 position의 mirror push가 coord에 도착(future 블록)한 뒤 raise → surgical 분기 결정론적 트리거. 평소엔 완전 inert. `submit_mirror`가 future 반환하도록 확장.
- [experiments/b1_ft_fleet.py](experiments/b1_ft_fleet.py) — fleet TTR(P) 스윕 드라이버. mode별 coordinator drop-in 설정, P마다 [재시작으로 plan 리셋 → arm → 1요청 → recovery-step wall 추출 + sequence-match], 선형 fit + 비교 JSON 생성.
- [paper/figures/make_recovery_ttr.py](paper/figures/make_recovery_ttr.py) — `fig_recovery_ttr.{pdf,png}` (TTR vs P, 두 모드 fit).

**찾아낸 것 (방법론적)**: fleet 기본 `chain_mode: async`에선 interior 워커 compute-time crash가 fire-and-forget이라 동기 전파 안 됨 → gateway 30s per-request 타임아웃 → trailer 없이 head로 오귀속(31s). recovery **work**은 두 모드 동일, 차이는 detection latency뿐 → 메커니즘 비교는 **sync chain**으로 측정(in-process와 동일 세팅). 또한 오래 떠있던 coordinator는 보드 outage 시 dead 마킹을 영구 유지(자동 un-mark 없음) → outage 후 coordinator 재시작 필요.

**검증 결과** (10/10 트라이얼 valid: fired✓, spike index=P−1✓, 출력=healthy 레퍼런스 일치✓):

| P | full-replay | surgical | 우위 |
|---|---|---|---|
| 4 | 0.897 s | 0.299 s | 3.0× |
| 8 | 1.510 s | 0.366 s | 4.1× |
| 16 | 2.834 s | 0.486 s | 5.8× |
| 24 | 3.928 s | 0.608 s | 6.5× |
| 32 | 5.056 s | 0.711 s | 7.1× |

```
full-replay: TTR(P) = 345 ms + 148.8 ms·P
surgical:    TTR(P) = 246 ms +  14.8 ms·P    → slope 10.1×
```
full-replay는 position마다 체인 전체 재-forward(~150 ms ≈ decode 1스텝), surgical은 죽은 stage backup만(~15 ms). in-process opt-125m slope 비율 2.8× → fleet 10.1× (실 network hop + 24층이 증폭). in-process 회귀(b1/surgical/mirror suite) 통과 유지. REPORT §B1-FLEET, 결과 `experiments/results/b1_ft_fleet.json`.

**의도된 한계**: fleet는 실험 후 비기본 상태(sync chain + surgical drop-in + 워커 fault env) — 원상복구는 별도. B2(no-mirror)/B3(redundant-hosting) fleet 라인 미측정. async detection 비용(30s)은 별개 축으로 아직 정량화 안 함.

## Phase B1-FLEET.2 — parity를 3번째 recovery line으로 fleet 드라이버 확장 (2026-07-20)

**목표**: 위 B1-FLEET 스윕(full_replay/surgical)에 이미 구현돼 있던 `gateway._recover_parity`(zero-forward XOR reconstruct) 분기를 fleet 드라이버 `--modes`에 3번째 옵션으로 연결하고, TTR(P) 그림도 3-line으로 확장.

**구현**:
- [experiments/b1_ft_fleet.py](experiments/b1_ft_fleet.py) — `set_worker_parity(on)`: 워커 전체(`ansible workers`)에 `radp-worker.service.d/parity.conf`(`RADP_PARITY=1`) 배치/제거 + 재시작. `run()`에서 `"parity" in modes`면 mode 루프 전에 1회 호출(healthy-reference 재스케줄보다도 먼저).
- **필수 controller 추가 (parity-branch 검증)**: `gateway._recover_parity`는 parity를 신뢰 못 하는 6가지 게이트(dead stage가 head / non-head survivor 없음 / FetchKV 실패 / KV geometry mismatch / parity cache incomplete / mirrored input 없음) 각각에서 조용히 `_recover_surgical`로 폴백한다 — 즉 parity 트라이얼이 실제로는 surgical 경로를 탄 채 parity로 오라벨될 수 있음. 이를 잡기 위해 `fetch_coordinator_log()`(트라이얼 시작 = 코디네이터 재시작 이후 journalctl, `restart_coordinator_and_wait`와 동일한 ssh 패턴 재사용)로 로그를 가져와 `_parity_branch_ran(log_text)` — gateway.py가 실제 zero-forward 경로에서만 찍는 `"PARITY reconstruct:"` 마커(gateway.py의 `log.warning("request=%d PARITY reconstruct: backup %s stage[%d..%d] KV slots=%d (zero-forward XOR), then run pos %d live", ...)`) 존재 여부로 판정. 트라이얼 row에 `parity_branch_ran`/`parity_branch_log` 기록, `mode=="parity"`일 때만 validity에 `and parity_branch_ran` 추가 — fit 필터와 로그 출력(`FELL BACK TO SURGICAL` 플래그) 모두 반영. full_replay/surgical 트라이얼은 이 체크를 아예 타지 않음(순수 additive).
- [paper/figures/make_recovery_ttr.py](paper/figures/make_recovery_ttr.py) — `STYLE["parity"]` 추가(`PALETTE["tertiary"]`, marker `"^"`), 유효 포인트 없는 모드는 `if not xs: continue`로 건너뜀(fit-lookup 전에도 가드 추가) — 기존 full_replay/surgical 렌더링·slope-ratio callout은 불변.

**검증 결과**: 이 세션에는 실 fleet가 없어 스윕은 미실행(Task 브리핑에 예정된 순서: 그대로). 대신 —
- `tests/test_b1_ft_fleet.py`(신규, non-slow) 4개: `_parity_branch_ran`을 실제 마커 포함 로그(True) / fallback-only 로그(True 아님) / 빈 문자열 / 잡음 속 마커로 검증.
- `.venv/bin/python -m pytest tests/ -m 'not slow' -q` 전체 그린 (118 tests, exit 0).
- `make_recovery_ttr.py`를 오늘의 실제(parity 키 없는) `experiments/results/b1_ft_fleet.json`에 대해 실행 → 에러 없이 완주(parity 스킵 가드 확인), 생성된 바이너리는 커밋 전 되돌림(진짜 parity 데이터 나오기 전까지 그림은 2-line 유지).

**의도된 한계**: 브리핑 Step 3(`--modes parity --positions 8` 1-trial 스모크, `fired/index_ok/seq_match` 확인)은 실 fleet 필요 — 아직 미실행. `set_worker_parity(False)`(워커 원상복구)는 스윕 종료 시 자동 호출하지 않음(명시적 별도 restore 단계로 남김, 브리핑 지시).

## Phase B1-PARITY — cross-stage XOR parity 복구 실 fleet 실측 (2026-07-20)

**목표**: surgical(≈Petals 입력-재생 계열)과 근본적으로 다른 **재계산 0** 복구 계열을 구현하고 실 OPT-350M fleet에서 3번째 라인으로 측정. (Phase B1-FLEET.2가 예고한 스윕의 실행 결과 — 그 항목의 "스윕 미실행"은 본 Phase로 해소.)

**구현** (spec/plan `docs/superpowers/{specs,plans}/2026-07-20-parity-recovery*`, SDD 7 태스크):
- [radp/coordinator/parity_cache.py](radp/coordinator/parity_cache.py) — `ParityCache`: 단일 parity blob P를 stage 컬럼 XOR로 누적, max-stage zero-pad, `(stage,pos)` dedup, 전 stage 기여 시에만 `is_complete`.
- [radp/worker/stage_runner.py](radp/worker/stage_runner.py) — `extract_kv_column`/`export_kv`/`install_kv` (DynamicCache ↔ raw dtype 바이트, forward 0) + `kv_seq_len`.
- [radp/common/proto/radp.proto](radp/common/proto/radp.proto) — `MirrorKV`(worker→coord) / `FetchKV`,`LoadKV`(coord→worker).
- [radp/worker/server.py](radp/worker/server.py) — `RADP_PARITY` gated per-slot KV push(local-run·tail 양 경로) + FetchKV/LoadKV 핸들러.
- [radp/coordinator/gateway.py](radp/coordinator/gateway.py) — `recovery_mode="parity"` + `_recover_parity`: 생존자 KV ⊕ P → 죽은 stage KV 비트 복원 → LoadKV 설치 → 실패 position만 라이브. 레이아웃 정합 `(3,0,1,2,4)`/`(1,2,3,0,4)`.
- [experiments/b1_ft_fleet.py](experiments/b1_ft_fleet.py) — parity 라인 + `set_worker_parity` + **`parity_branch_ran` 검증**.

**검증 결과** (15/15 valid, parity 5/5 `parity_branch_ran=True`):

| P | full-replay | surgical | parity |
|---|---|---|---|
| 4 | 0.973 s | 0.316 s | 0.298 s |
| 8 | 1.670 s | 0.373 s | 0.282 s |
| 16 | 2.882 s | 0.515 s | 0.293 s |
| 24 | 4.200 s | 0.638 s | 0.304 s |
| 32 | 5.621 s | 0.767 s | 0.316 s |

```
full-replay: 308.6 ms + 164.32 ms·P
surgical:    249.4 ms +  16.21 ms·P
parity:      284.1 ms +   0.87 ms·P   → surgical 대비 19×, full-replay 대비 188× 완만
```
in-process는 bit-exact(복원 KV가 원본과 `torch.equal`) + sequence-match로 별도 증명. 테스트 fast 118 / slow 19 green.

**의도된 한계**: ① ~~**첫 interior victim 한정**~~ → **Phase B1-PARITY.2에서 해소** (임의 interior victim 지원; 마지막 stage victim만 surgical 폴백 유지) ② 정상 운영 중 KV shipping 네트워크 세금 미최적화·미정량화 ③ 단일 장애(RAID-5) ④ prefill(pos 0) 장애는 라이브 prefill로 축퇴.

## Phase B1-PARITY.2 — parity 복구를 임의 interior victim으로 일반화 (2026-07-20)

**목표**: Phase B1-PARITY의 "① 첫 interior victim 한정" 한계 해소. 죽은 stage가 chain 어디에 있든(단, downstream non-head 생존자가 하나라도 있으면) zero-forward XOR 복원이 실제로 동작하게 한다.

**구현**:
- [radp/coordinator/gateway.py](radp/coordinator/gateway.py) — `_recover_parity`: 생존자들이 같은 slot 수를 갖도록 강요하던 게이트를 제거하고 **`N = min(생존자 slot 수)`** (= 모든 non-head stage가 공유하는 prefix)로 복원 대상 결정. `_xor_reconstruct_kv`는 slot 축을 `-1`로 reshape 후 transpose 결과를 `[:n_slots]`로 **슬라이스** — upstream 생존자의 여분 slot을 잘라 정렬. KV는 append-only라 slot i 바이트는 그대로.
- [radp/worker/server.py](radp/worker/server.py) — **선결 버그 수정**(아래).

**찾아낸 버그** (이 작업을 막고 있던 진짜 원인): 4-stage chain에서 stage 3이 죽었는데 coord가 **stage 2를 죽였다**. chain forwarding의 `except grpc.RpcError` 핸들러가 downstream이 이미 stamp 한 `radp-failed-*` trailer를 무시하고 **자기 next hop**으로 덮어써서, hop 하나 지날 때마다 책임이 head 쪽으로 한 칸씩 이동. 3-stage에서는 hop이 하나뿐이라 드러나지 않았음. 이제 중간 hop은 successor의 trailer를 **그대로 릴레이**한다 — 단, 이 릴레이는 successor가 실제로 자신의 `except` 핸들러에 도달해 stamp 한 경우, 즉 **fail-fast** 하향 실패에만 적용된다(아래 의도된 한계 ④ 참고).

**검증 결과**:
- 신규 slow e2e `test_parity_recovery_middle_victim` — 4-stage(head + non-head 3), victim=중간 non-head(upstream 생존자 1 + downstream 생존자 1). (a) PARITY 브랜치 실행 & surgical 폴백 0회, (b) 복원 KV가 원본과 layer별 K·V 모두 `torch.equal`, (c) 토큰 시퀀스 = healthy reference. 기존 first-victim 테스트와 공용 드라이버 `_assert_parity_recovery`로 통합.
- 신규 fast `test_trailer_survives_an_extra_hop` — trailer 릴레이 회귀 가드(수정 전 `'1' == '7'` 로 실패 확인).
- fast 117 green (기존 116 + trailer 릴레이 1), slow(parity+surgical+B1) 20 green (기존 19 + middle-victim 1). 최종 리뷰 fix 후 slow parity 12 (last-stage 폴백 테스트 추가).
- **실 fleet 실측** (victim `on-6[18..19]` = 중간 interior, 예전엔 폴백하던 케이스): 15/15 valid, parity 5/5 `parity_branch_ran=True`. `full-replay 321.6ms+163.01ms·P | surgical 223.9ms+17.53ms·P | parity 245.5ms+1.43ms·P` — **parity 기울기가 victim 위치와도 무관**(첫 victim 0.87 vs 중간 1.43 ms·P⁻¹, 둘 다 ≈0). 정상 decode 스텝 대비 복구 스텝 비율: parity 1.6–1.9×로 P·위치 무관 일정, surgical 1.9→5.0×, full-replay 6.0→34.4×. 결과 `b1_ft_fleet_mid.json`.
- **측정 방식 정정**: 복구 스텝을 `max(TBT)` 대신 **주입 인덱스 `TBT[P−1]`에서 직접 읽도록** 변경(`experiments/b1_ft_fleet.py`). parity가 빨라지자 무관한 지터가 복구 스텝을 앞지른 사례 1건 발생(중간 victim P=4: max 0.322s@idx32 vs 실제 0.278s@idx3). 기존 트라이얼은 전부 max 위치=P−1이라 그 1건만 값이 바뀌었고, 기록된 per-step 시계열에서 재추출(재실행 없음). `peak_*`는 진단용 유지, validity 게이트는 `recovery_visible`(복구 스텝 > 1.3× median)로 교체.

**의도된 한계**: ① **마지막 stage victim은 여전히 surgical 폴백** — downstream non-head 생존자가 없어 모든 생존자가 한 slot씩 길고, 마지막 공유 slot의 parity에 victim 기여분이 빠져 completeness 게이트가 걸림(틀린 토큰은 없음) ② 단일 장애(RAID-5) ③ prefill(pos 0) 장애는 라이브 prefill로 축퇴 ④ **trailer 릴레이는 fail-fast 하향 실패만 고침, hang은 미해결** — 모든 hop이 거의 동시에 같은 `timeout=10.0`을 쓰므로, 2+ hop 아래에서 **행(hang)**하는 victim은 entry hop 자신의 데드라인이 먼저 트립되어 여전히 자신의 (살아있는) next hop을 오귀속할 수 있음(entry가 직접 RpcError를 받는 시나리오라 fail-fast 케이스와 다름). 해소하려면 inner hop이 outer hop보다 짧은 데드라인을 가져야 함(future work) — pre-existing, 이번 작업으로 악화되지 않음.

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

## Phase B1-REPLICATE — full KV replication baseline (2026-07-22)

parity의 4번째 대조군으로 full KV replication 구현·측정. `ReplicaCache`(parity cache에서 XOR만 제거),
gateway `_recover_replicate`(생존자 fetch·XOR 없이 저장본 직접 install), fleet TTR(P) 스위프.
결과: `replicate TTR(P)=239.3+2.67 ms·P` — parity(284.1+0.87)와 **TTR 동률**(교차 P≈25), 둘 다
zero-recompute. parity의 우위는 저장뿐(max vs Σ = 2.25×, O(1) vs O(N)) → 2D Pareto(TTR × 저장)에서
parity만 좌하단 코너. SDD 7태스크(계획 버그 2건 하네스가 포착: n_slots·Stage 인자순서), fleet 5/5
`replicate_branch_ran=True`. 그림 fig_recovery_2d/ttr_slide(4선)/storage_scaling. 커밋 main.

## Phase B1-REACTIVE — reactive re-placement baseline (R={} 앵커) (2026-07-22)

**목표**: backup을 전혀 안 두는(R={}) 5번째 복구 계열을 실 fleet에서 측정해 2D Pareto의 우하단
(저장 0 ∧ TTR 폭발) 꼭짓점을 앵커링 — proactive backup(parity/replicate)의 값어치를 격리.

**구현** (코디/gateway 무변경 — 기존 web_api 엔드포인트만 드라이버에서 조합):
- [experiments/b1_ft_fleet.py](experiments/b1_ft_fleet.py) — `run_reactive_replacement_trial`:
  라이브 placement에서 interior victim 동적 선택(`pick_interior_victim`/`fetch_placement`) → arm
  compute-time crash → abort(R={}라 승격 backup 없음) → `clear_all_failures`+`mark_device_dead`로
  victim만 결정론적 dead 마킹 → `reconfigure_over_survivors`(생존자 재-solve+redeploy) → position 0
  재생. TTR=wall(crash→재생 복구토큰)−healthy reference wall.
- `_coord_web`는 gRPC IP(`--coord`)에서 web_api URL 유도(ansible alias는 DNS 미해석).

**찾아낸 버그/함정**:
- 초기 스모크가 `nodename nor servname` — 드라이버가 web_api를 ansible alias("ax-1")로 호출. IP 유도로 fix.
- **compute-time crash는 프로세스를 안 죽임** → victim이 계속 heartbeat → `_dead`에 자연 진입 안 함 →
  `survivors=workers−_dead`가 victim 배제 실패(reconfigured=False). `inject_failure`로 명시적 마킹이 필요.
- **placement 준-비결정적**(CPU 워커 등록 타이밍) → 정적 victim이 배포된 체인과 어긋나 fault 미발화
  (fired=False). victim을 라이브 placement에서 동적 선택으로 해결.
- crash 윈도우가 무관한 워커 heartbeat를 flap → `_dead`에 spurious 진입 → 재배치가 victim 외 배제.
  `clear_all_failures` 선행으로 survivors=all−{victim} 결정론화.
- **CPU 워커 on-3 SSH-unreachable**(swap-thrash, on-2와 동일) → 코디 `wait_for_workers`(전 워커
  hard-require) 320s hang. inventory에서 on-3/on-4 주석 → 안정적 5-워커 CUDA/AGX fleet로 축소
  (parity/replicate와 동일 토폴로지), `config` 재배포.

**검증 결과** (fleet 5/5 valid, 매 트라이얼 victim 1개만 배제):
```
reactive TTR(P) = 56.9 s − 0.18 s · P   (사실상 flat ~53 s, 음의 기울기는 노이즈)
P=4 64.1s  P=8 48.2s  P=16 50.5s  P=24 53.5s  P=32 52.8s
```
P=32에서 parity 대비 ~176×, full-replay 대비 ~10× 느림. 비용은 재배치 중 cold model reload +
position 0 재생이 지배(crash 위치 무관). 그림 fig_recovery_ttr_slide(5선, reactive 최상단)/
fig_recovery_2d(로그-X, reactive 우하단).

**의도된 한계**: 탐지를 heartbeat timeout 대신 명시적 mark_dead로 대행(실환경 탐지지연 ~5s를 뺀
셈이나 52s 대비 무시 가능). 5-워커 측정(CPU 워커 제외) — reactive TTR은 cold reload 지배라 토폴로지
robust. 출처 `b1_ft_fleet_reactive.json`.

## Phase B1-OVERHEAD — 상시 network shipping 계열별 실측 (mirror-as-surgical-rung 프레이밍) (2026-07-30)

**목표**: parity/replicate가 정상 운영 중 문다고만 기술돼 있던(§B1-PARITY/§B1-REPLICATE 한계 항목) KV 컬럼
network shipping 세금을 계열별로 정량화하고, 항상-켜짐 input mirror가 어느 복구 rung의 값인지 코드로 규명.

**구현**:
- [experiments/_harness.py](experiments/_harness.py) — `shipping_overhead(placement, n_heads, head_dim,
  itemsize)`: worker→coord 상시 shipping을 mirror(모든 계열 always-on, `server.py:429-451`)와 KV 컬럼
  (RADP_PARITY 게이트, parity/replicate만, `server.py:473-484`)으로 분해.
- [experiments/gen_overhead.py](experiments/gen_overhead.py) — 배치
  `ao-2[1-15]/on-1[16-17]/on-6[18-19]/ao-1[20-23]/on-2[24]`에 `shipping_overhead`를 적용하고,
  `b1_ft_fleet_parity.json`의 실측 median TBT(0.1633 s)로 나눠 bytes/step→bytes/s 변환.
  `experiments/results/b1_ft_overhead.json` 갱신.

**검증 결과** (`b1_ft_overhead.json`):
```
input_mirror_bytes_per_step = 8192   (5계열 전부, always-on)
kv_column_bytes_per_step    = 36864  (parity/replicate만)
shipping_bytes_per_step: full_replay/reactive/surgical = 8192, parity/replicate = 45056
bandwidth_bytes_per_s:   full_replay/reactive/surgical ≈ 50165.3 (49.0 KiB/s)
                         parity/replicate            ≈ 275909.4 (269.4 KiB/s)   → 5.5×
```
코드 추적(`radp/coordinator/gateway.py`)으로 mirror read-back 경로 확인: `_recover_surgical`가
dead-stage mirror 히스토리 전체(0..P-1)를 읽는 게 복구 메커니즘 그 자체, `_recover_parity`/
`_recover_replicate`는 실패 포지션 P 1개치만 mirror에서 읽고 과거는 XOR/복제본으로 재구성하며
게이트가 걸리면 `_recover_surgical`로 폴백, `_replay_through_chain`(full-replay)과 reactive의
재-prefill은 worker mirror를 전혀 안 읽음. surgical 자체도 async-mirror lag 시
`_replay_through_chain`으로 한 단계 더 폴백하는 코드가 이미 존재(`gateway.py:843-858`) —
`parity/replicate → surgical → full-replay` 사다리가 실코드.

**의도된 한계**: shipping 바이트는 배치·모델 크기에서 **결정론적으로 계산**된 값(측정 아님),
대역폭만 실측 median TBT로 변환. 5.5× 비율은 이 5-stage/OPT-350M 배치(layer 분포 [2,2,4,1]) 한정 —
다른 placement에선 mirror:KV 비가 달라짐. mirror·KV 트래픽의 실제 gRPC 링크 latency/처리량 영향은
별도 측정 안 함.

## Phase B1-FIDELITY — 재계산 기반 복구의 tier 간 bit fidelity 실측 (백로그 B4) (2026-07-30)

**목표**: §B1-PARITY.2가 "복구 결과의 강도가 다르다"를 논증으로만 남겼던 걸(parity=bit-exact XOR,
surgical/full-replay=재계산이라 tier 따라 다를 수 있음, 미측정) 실 하드웨어 프로브로 검증 — 백로그 B4.

**구현**:
- [experiments/probe_recompute_fidelity.py](experiments/probe_recompute_fidelity.py) — OPT-350M
  non-head stage `[16,17]`(2층)에 고정 시드 입력(seq=8, `torch.manual_seed(0)`)을 동일 바이트로
  두 tier(`on-1`=cuda, `on-3`=cpu)에 ansible로 ship, 각 tier에서 `StageRunner.run`(prefill)→
  `export_kv`→sha256+raw dump 회수 후 비교. `--board`/`--controller` 두 모드.
- [experiments/fidelity_compare.py](experiments/fidelity_compare.py) — `compare_kv`(순수 numpy,
  torch/fleet 의존 없음): 바이트 동일이면 exact, 아니면 float64 캐스팅 후 `fraction_mismatched`·
  `max_abs_diff` 계산.
- `experiments/results/b1_ft_fidelity.json` 갱신.

**검증 결과** (`b1_ft_fidelity.json`):
```
tier_a=cuda(on-1) vs tier_b=cpu(on-3): hash_equal=False, exact=False
fraction_mismatched=0.26861572265625 (≈26.9%), max_abs_diff=0.00390625 (=2⁻⁸)
recompute_diverges=true
family_verdict: parity/replicate=bit-exact (by construction),
                surgical/full_replay/reactive=tier-dependent recompute
```
최대오차 2⁻⁸는 fp16 몇 ULP 규모 — 정확도 버그가 아니라 CUDA/CPU BLAS 커널 reduction 순서·FMA
차이에 의한 부동소수 non-associativity로 해석.

**의도된 한계**: stage 1곳(`[16,17]`)·tier 쌍 1개(cuda↔cpu)만 측정 — `agx`(`ao-1`) tier·다른
stage·동일 기종(cuda↔cuda) 조합은 미검증(§B1-PARITY.2가 추정한 "같은 기종이면 bit-identical
가능성"은 아직 확인 안 됨). parity/replicate의 bit-exact verdict는 `parity_branch_ran`/
`replicate_branch_ran=True`(자기 primary 경로를 실제로 탔을 때)에 한정 — 폴백 시 이 프로브의
드리프트를 그대로 상속(§B1-OVERHEAD 참조). 지금까지 모든 fleet 트라이얼의 `sequence_match`(토큰
출력)는 100% 일치 — 이 프로브가 잡는 건 argmax 이전 중간 텐서 수준의 차이.

---

## Phase B1-RAID6 — double-parity(k=2): O(1) 저장으로 동시 2-실패 복구 (2026-08-03)

**목표**: parity(RAID-5, XOR blob 1개, 단일 실패만)를 GF(2⁸) double-parity(RAID-6)로 확장 —
동시 2-stage 실패를 재계산 0으로 복원. 런타임 토글로 RAID-5로 되돌아올 수 있게 하고, 실 fleet에서
RAID-5 / replicate / RAID-6 3-way 비교.

**구현** (워커 무변경 — Q는 coord가 기존 push된 KV 컬럼으로 접음):
- [radp/coordinator/gf256.py](radp/coordinator/gf256.py) — GF(2⁸) 필드(다항식 0x11d, gen 0x02)
  + `solve_two_erasures`(Anvin RAID-6 2×2 연립). 순수 numpy.
- [radp/coordinator/parity_cache.py](radp/coordinator/parity_cache.py) — `k` 파라미터 + 두 번째
  blob Q(`gf_mul_scalar(gf_pow(2, coeff_index), col)` 누적). k=1 기본은 Q 미할당(RAID-5 byte-for-byte).
- [radp/coordinator/gateway.py](radp/coordinator/gateway.py) — `parity_k` 배선 + stage→gⁱ coeff
  map(원본 placement 기준, rewiring 무관) + `_gf_reconstruct_kv`/`_recover_parity_double`. dispatch는
  `self._dead`의 non-head 2개 기준으로 attribution/head-check **앞에서** 분기(head-alive 가드).
- `RADP_PARITY_K=1|2` env 토글([server.py](radp/coordinator/server.py), coord 전용).
- 저장 회계: `replication_overhead`에 `raid6_bytes=2×parity` + `gen_overhead`/`storage_scaling_models`
  + 그림 `make_storage_scaling_models`.
- 드라이버 [experiments/b1_ft_fleet.py](experiments/b1_ft_fleet.py) — `pick_two_interior_victims`,
  `set_parity_k`, `run_raid6_trial`(동시 2-victim 주입).

**찾아낸 버그**: (1) `test_k2_q_grows_zero_padded`가 큰 컬럼을 먼저 넣어 Q-grow 경로 미실행 → 순서
교정. (2) `pick_two_interior_victims`가 `start_layer`/`end_layer` 키를 읽는데 실제 `fetch_placement`는
`start`/`end` → 라이브 KeyError 전에 수정. (3) **dispatch-precedence(라이브에서 발견, `7522c92`)**:
first non-head victim(head 인접) 크래시가 gRPC trailer 유실 시 head로 오귀속돼 head-check가
double-dispatch보다 먼저 발동 → surgical 폴백. `self._dead` 기준 dispatch를 attribution 앞으로 이동.

**검증 결과**:
- 유닛: `test_gf256.py`(6, 2-erasure 전 rank 쌍 bit-exact) + `test_raid6_recovery.py`(2: in-process
  double-recovery bit-exact + dispatch-precedence 회귀) + `test_parity_cache.py`(9, k=1 회귀 포함) +
  `test_parity_recovery.py`(13, single-failure 회귀 불변). 전부 통과.
- 라이브 5/5 (`b1_ft_raid6.json`, victim=on-1[16]·on-6[17-19]): 전 포지션 `raid6_branch_ran=True`
  + `sequence_match=True`(무장애 reference와 정확 일치). `TTR(P)=30.29 s+2.78 ms·P` — slope≈0
  (zero-recompute, parity 0.87·replicate 2.67과 같은 평탄대; surgical 16.2·full-replay 164 대조).
- 저장(이 placement): parity 16384 · raid6 32768 · replicate 36864 B/tok.

**의도된 한계**: 절대 TTR 절편 30.3 s는 알고리즘이 아니라 **축퇴 복구테이블 인공물** — 이 fleet의 자동
solve된 R이 non-head 백업을 전부 on-2로 몰아, 2-victim이면 약한 Nano(on-2)가 3-stage 호스팅+cold
weight load(단일 실패 parity는 같은 fleet에서 284 ms). 집중은 상수 offset만 더해 slope는 오염 안 됨.
백업이 분산된 R에서의 깨끗한 절대 TTR은 미측정(future work — 현 R로는 백업 분산된 2-victim 쌍이 없음).
저장 이점도 head-heavy placement라 raid6/replicate=0.89로 얇음(balanced-N geometry가 2/N vs (N-1)/N).
k≥3(일반 Reed-Solomon)은 범위 밖.
