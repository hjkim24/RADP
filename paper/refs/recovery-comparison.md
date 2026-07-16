# recovery-comparison.md — 엣지 분산 (LLM) 추론의 장애 복구 방식 비교

> **범위:** PAPERS.md 카탈로그 중 *실제 recovery 메커니즘을 가진* 엣지 계열 5편.
> **원칙:** 복구 방식 서술은 **각 논문에 명시된 사실만**. "RADP 대비" 항목만 해석(인용 시 구분).
> 관련 문서: [PAPERS.md](PAPERS.md)(상세·venue), [comparison.md](comparison.md)(왜-엣지 동기), 초안 [../draft/3-related.md](../draft/3-related.md) §B(fault tolerance).
>
> **선정 근거:** failure를 *인지만* 하고 복구 메커니즘이 없는 논문(PA-MDI, Distributed-MoA)은 하단 부록으로 분리. 데이터센터 recovery(SpotServe, DualMap)는 엣지 아님 → 제외.

---

## 요약 비교표

| 논문 | Venue | 도메인 / 스케일 | 장애 트리거 | 사전 이중화(redundancy) | 복구 단위 | 복구 메커니즘 | in-flight 상태 복원 | proactive? |
|---|---|---|---|---|---|---|---|---|
| **Petals** | NeurIPS 2023 | inference / 인터넷 consumer-GPU swarm | server(peer) 장애·이탈 | swarm 내 block **중복 보유** | 실패 stage의 **KV cache** | dual attention cache로 KV 복구 → 중복 보유 대체 peer로 reroute + greedy rebalancing | ✅ 실패 stage KV만 복구(전체 재시작 X) | reactive rebalance (redundancy는 상시 유지) |
| **JARVIS** ★ | MILCOM 2024 | inference / tactical SDR 18-node (wireless+wired) | node 장애 | **peer-level layer duplication** | layer(구간) | (a) backup peer가 이어받음, (b) **layer skipping**(다음 hop 재라우팅, 해당 layer 생략) | ⚠️ skip 시 해당 layer 연산 생략 → accuracy 저하 감수(측정) | 부분 proactive(duplication), 배치는 **수동 config** |
| **QEIL** | arXiv 2026 (preprint) | inference / **단일 edge 머신** 내 CPU·GPU·NPU | device(compute unit) fault·thermal | 없음(healthy unit로 재분배) | workload(layer assignment) | 100ms fault detection → healthy device redistribution → graceful degradation(50% capacity 점진 복귀), safety monitor override | ⚠️ workload 재분배, formal latency bound(τ_degraded ≤ τ_opt·D/D_healthy) | reactive + degradation 보장 |
| **Parallax** | arXiv 2025 (preprint) | inference / decentralized 볼런티어 GPU(지리 분산·공용망) | GPU join/leave(dynamic membership) | model **replica**(다중 복제) | layer(de-allocation) / pipeline stage | DHT live metric 기반 localized adjustment 또는 **CoV 기반 global rebalancing** + replica 간 **stage stitching**(request-time) | ❌ rebalance/re-stitch (KV 복원 명시 없음) | reactive rebalance |
| **FTPipeHD** | IEEE TMC 2024 | **training** / heterogeneous edge pipeline | device 장애 | **주기적 weight replication**(이웃 + central node) | model **weights** | 실패 시 survivor로 **re-partition** + missing weight refetch → resume | ⟂ training이라 in-flight KV 개념 없음; budget=training batch(초) | proactive checkpoint + reactive re-partition |

★ JARVIS = layer-level partition에 backup+recovery를 결합한, RADP에 가장 근접한 baseline.

---

## 논문별 상세

### Petals (NeurIPS 2023) — swarm redundancy + KV cache 복구
- 인터넷의 신뢰할 수 없는 consumer-GPU를 swarm으로 묶어 50B+ LLM을 pipeline-parallel 서빙.
- **복구:** 서버 장애 시 **dual attention cache**로 전체 generation을 재시작하지 않고 실패 stage의 **KV cache만 복구**, 같은 block을 **중복 보유한 대체 peer로 load 재할당**. 각 서버에 block을 배정하는 탈중앙 **greedy rebalancing**으로 커버리지·throughput 유지.
- **전제:** 복구가 성립하려면 예비 peer가 그 block을 **이미 중복 보유**해야 함 → spare-memory(consumer GPU, 실측 swarm ~11–24GB) 전제.
- bib: `borzunov2023petals`, `borzunov2023distributed` (등록됨).

### JARVIS (MILCOM 2024) — layer duplication(backup) + layer skipping
- LLM decoder layer를 wireless/wired 혼재 edge node의 **token ring**에 분산(각 token이 ring 한 바퀴).
- **복구 2종:** (1) **peer-level layer duplication** — 다른 peer가 같은 layer 사본 보유 → 장애 시 이어받음. (2) **layer skipping** — 장애 layer를 건너뛰고 다음 hop으로 재라우팅. MMLU로 layer 1~2개 제거 시 accuracy degradation heatmap을 측정해 **skip 가능 layer**(초반·일부 중간 critical, 후반 강건)를 실증.
- **한계:** placement를 최적화로 풀지 않고 **수동 config**; skip은 accuracy 저하를 감수하는 **degraded operation**.
- bib: **미등록** (registration 필요 시 MILCOM'24, doi 10.1109/MILCOM61039.2024.10773726).

### QEIL (arXiv 2026, preprint) — 단일 머신 fault redistribution + graceful degradation
- edge 이기종 하드웨어(CPU/GPU/NPU) inference-time scaling 정량화 + **safety-first** 오케스트레이션.
- **복구:** **100ms 내 fault detection** → healthy device로 **workload redistribution** → **graceful degradation**(50% capacity 점진 복귀). **safety monitor가 optimization engine보다 override 우선권**. formal degradation guarantee(τ_degraded ≤ τ_optimal·D/D_healthy), 실측 100% fault recovery·zero thermal throttling.
- **스코프 주의:** 다중 네트워크 노드가 아니라 **한 머신 내부** CPU/GPU/NPU 재분배 → 다른 4편과 층위가 다름.
- bib: 미등록 (arXiv:2602.06057).

### Parallax (arXiv 2025, preprint) — dynamic-membership reactive rebalancing
- 이기종·저대역 볼런티어 GPU 풀에 model replica를 placement하고 request-time에 pipeline chain을 선택.
- **복구:** DHT의 **live per-layer latency/RTT**로 GPU join/leave에 적응 — **localized adjustment** 또는 **coefficient-of-variation 기반 global rebalancing**; GPU leave 시 layer **de-allocation**, replica 간 **stage stitching**으로 요청을 다른 replica 경로로 재봉합.
- **성격:** 사전 backup을 심는 게 아니라 **사후 reactive rebalancing/re-stitching**. HexGen을 이긴 최신 비교 대상.
- bib: 미등록 (arXiv:2509.26182).

### FTPipeHD (IEEE TMC 2024) — training-side weight replication + re-partition
- 이기종 edge에서 **pipeline-parallel training**을 지속.
- **복구:** weight를 **주기적으로 복제**(이웃 + central node) → 장애 시 survivor로 **재파티션** + 누락 weight **refetch** 후 재개.
- **차이:** recovery unit = **model weights**, budget = **training batch(초 단위)**. inference decode의 per-token TBT·in-flight KV 복원과는 층위가 다름.
- bib: `chen2024ftpipehd` (등록됨).

---

## 비교 분석 (축별)

- **복구 단위:** KV cache(Petals) · layer(JARVIS) · workload(QEIL) · layer/stage(Parallax) · weights(FTPipeHD). → **in-flight KV state를 복원하는 건 Petals뿐**(나머지는 layer/workload/weight 재배치나 skip).
- **redundancy 위치:** 상시 중복 보유(Petals swarm, JARVIS duplication, Parallax replica, FTPipeHD weight replica) vs 없음(QEIL은 healthy unit로 재분배만).
- **proactive vs reactive:** 전부 **장애 발생 후** rebalance/재파티션/skip. 사전 이중화가 있어도 그것을 **placement 최적화에 반영**하진 않음(수동/greedy/heuristic).
- **품질·비용 trade-off:** JARVIS는 accuracy 저하(skip), QEIL은 capacity 저하(graceful degradation), Petals/Parallax는 spare peer 필요, FTPipeHD는 초 단위 budget.
- **스코프 이질성:** 인터넷 swarm(Petals) / tactical SDR(JARVIS) / 단일 머신(QEIL) / 볼런티어 GPU(Parallax) / training(FTPipeHD) — "엣지"의 정의가 논문마다 다름에 유의.

---

## RADP 포지셔닝 (해석 — 인용 시 구분)

- **공통 gap:** 다섯 편 모두 recovery가 **reactive(사후 rebalance/재파티션)·degraded(skip)·수동 config** 중 하나이며, **backup memory를 placement 최적화의 제약으로 사전 통합**하지 않음.
- **RADP 차별점:** recovery unit = **in-flight KV+activation chain**, budget = **per-token TBT**, backup 메모리를 **placement DP(Eq.mem) 안에서 예약** → ψ·R **coupled feasibility**를 사전에 함께 해결(proactive).
- **가장 강한 대조 baseline = JARVIS**(backup duplication을 하지만 최적화 없이 수동 배치 + skip 허용)와 **Petals**(swarm redundancy는 spare-memory 전제라 4GB 엣지 부적용).

---

## (부록) failure-aware이지만 recovery 메커니즘은 없음

| 논문 | Venue | 다루는 방식 |
|---|---|---|
| PA-MDI | arXiv 2024 | objective에 worker 이탈·packet loss 실패확률 ∏(1−P)를 페널티로 반영 — backup·recovery-time 보장 없음 |
| Distributed-MoA | IEEE PIMRC 2025 | 중앙 SPOF 회피 + diverse connection robustness — 명시적 recovery mechanism 없음 |

---

## 유지 메모
- bib 미등록: **JARVIS**(MILCOM'24), **QEIL**(arXiv:2602.06057), **Parallax**(arXiv:2509.26182). related work에서 인용 확정 시 references.bib에 추가.
- 초안 `../draft/3-related.md` §B는 현재 Petals·FTPipeHD만 인용 → 이 문서 기준 **JARVIS·QEIL·Parallax 추가** 시 "recovery gap" 논증 강화.
