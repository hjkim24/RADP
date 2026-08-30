# FT baseline references (related-work mapping, 2026-07-30)

교수님 피드백 #2 대응 — 복구 baseline별 reference 논문. 각 논문이 **실제로 하는 것**과 우리 baseline 정의와의 **매치 강도**를 표기. 미검증 preprint는 명시.

## surgical ← Petals (정확 매치, 원문 검증)

- **Petals: Collaborative Inference and Fine-tuning of Large Models** — Borzunov et al., **ACL 2023 (System Demonstrations)**, arXiv:2209.01188.
- 확장판(fault-tolerance 상세): **Distributed Inference and Fine-tuning of LLMs Over The Internet** — Borzunov et al., **NeurIPS 2023**, arXiv:2312.08361.
- 원문 인용(§2.1): *"Clients store past inputs to each server so that if any server fails ... another one can quickly take its place ... the client sends all previous inputs to the replacement server, so that it has the same attention keys and values."*
- **매치: exact.** 클라이언트가 stage 입력(활성화)을 캐시했다가 stage 죽으면 교체 서버에 재생 → 그 stage KV만 로컬 재계산. 우리 surgical과 동일 기제. 교수님의 "surgical=Petals"가 맞음.
- 같은 input-replay 서브패밀리의 다른 top-venue 논문은 못 찾음 — Petals가 이 기제의 유일·깔끔한 선례.

## reactive re-placement ← 학습 쪽 선례 + 서빙 쪽 SpotServe

전용 spare 없이 생존자로 재구성. 선례는 대부분 **분산 학습**:

| 논문 | Venue/Year | 하는 것 | 매치 |
|---|---|---|---|
| **Varuna** — Athlur et al. | EuroSys 2022 (Best Paper) | spot VM 선점 시 남은 머신셋으로 파이프라인/DP 재구성, 체크포인트에서 재개. spare 없음. | **close** (재개가 체크포인트, 우리는 cold full-replay — 같은 계열) |
| **ReCycle** — Gandhi et al. | SOSP 2024 | 명시적 "without spare servers" — 실패 시 microbatch를 DP peer 파이프라인으로 재라우팅. | **close** (spare-free, 단 live 재라우팅) |
| **TorchElastic** (`torch.distributed.elastic`) | 논문 없음 (GitHub design doc만) | 멤버십 변경 시 rendezvous → world size 축소 → 생존자로 체크포인트 재시작. | 기제 close, **canonical 인용 없음**(엔지니어링 아티팩트) |
| Oobleck — Jang et al. | SOSP 2023 | pipeline template + **f+1 복제 인스턴스** 사전 유지 → 재슬롯. | **adjacent** (redundancy 기반, spare-free 아님 — 순수 reactive로 인용 금지) |
| Bamboo — Thorpe et al. | NSDI 2023 | **redundant computation**으로 선점 견딤. | **adjacent** (redundancy 기반) |
| Parcae | NSDI 2024 | proactive 재구성(liveput). | adjacent (proactive) |

- **서빙 쪽 결정적 인용: SpotServe — Miao et al., ASPLOS 2024 (Distinguished Artifact).** spot 인스턴스 서빙에서 인스턴스 마이그레이션을 bipartite matching + "stateful inference recovery"로 풀어 **naive cold 재배치를 일부러 회피** — 이유는 full re-solve+cold-restart가 P99를 망치기 때문. → **"reactive 재배치는 추론 서빙엔 부적합, 무겁게 엔지니어링해야 함"이라는 우리 주장을 직접 뒷받침.** 우리 corrected client-observed reactive baseline은 median 24.25초(18.62–39.35초); 과거 약 53초는 다른 wall-time 정의라 폐기했다.
- 엣지: KubeEdge/K3s 재스케줄은 표준 K8s 동작이라 LLM-specific 논문 없음(Borg/K8s 계보 = Burns et al., CACM 2016). generic 엣지-오케스트레이션 선례로만.
- **정직한 gap: reactive 선례는 전부 학습 쪽.** 서빙은 SpotServe가 유일하고 그마저 naive를 피함 → "추론엔 안 쓰는 이유"로 프레이밍.

## full-replay ← canonical 인용 없음 (naive strawman)

- 아무도 "제안"한 시스템이 아니라 fault-tolerant 서빙 논문들이 **정의하고 이기는 null baseline**.
- **DéjàVu — Strati et al., ICML 2024** (peer-reviewed): "recompute the lost KV cache from scratch"를 자기가 대체하는 기본 경로로 명시. ← full-replay를 strawman으로 쓰는 **가장 단단한 근거**.
- LUMEN (arXiv:2606.17787, **preprint**): "Stop-and-Restart"로 명명(생존 워커가 요청을 처음부터 재실행). FailSafe (arXiv:2511.14116, **preprint**): "costly KVCache recomputation"을 표준으로 언급.
- **권장 인용법**: "보편적 naive baseline"으로 쓰고 근거 = DéjàVu(peer-reviewed). 자체 provenance 있는 척 안 함.

## 보너스 — store-KV(replicate/parity) 서빙 선행연구 클러스터

우리 hero 쪽(KV를 저장/코딩)의 데이터센터 선례:
- **DéjàVu (ICML 2024)** — KV-cache **streaming/replication** 으로 fault-tolerant 서빙. → **replicate의 데이터센터 원조.** (PDF 이미 `paper/refs/DejaVu_...pdf`)
- **GhostServe** (이미 인용) — parity/erasure-coding checkpointing. → **parity 원조.** (PDF 이미 있음)
- 주의: DéjàVu/FailSafe는 **KV 상태 자체를 복제(state-replication)** 라 surgical(input-replay)과 **다른 서브패밀리** — surgical 인용에 섞지 말 것.
- **RADP 각도**: 이 store-KV 계열(GhostServe parity + DéjàVu replication)을 **이종 엣지 + parity의 O(1) 저장 + 5-way 공정비교**로 옮긴 것.

## 요약 (인용 우선순위)
- surgical → **Petals (ACL'23 / NeurIPS'23)** — exact, 안전.
- reactive → **Varuna (EuroSys'22)** + **ReCycle (SOSP'24)** (학습) + **SpotServe (ASPLOS'24)** (서빙, "왜 추론엔 부적합" 근거). Oobleck/Bamboo는 adjacent 주의.
- full-replay → 인용 없음, **DéjàVu (ICML'24)** 로 "표준 strawman"임을 근거.
- replicate/parity(우리 것) → **DéjàVu (ICML'24)** + **GhostServe** = 서빙 store-KV 선례.
- preprint(LUMEN/FailSafe)는 보조로만.
