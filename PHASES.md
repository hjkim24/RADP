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
