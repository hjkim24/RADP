# recovery-comparison.md — 엣지 분산 (LLM) 추론의 장애 복구 방식 비교

> **범위:** PAPERS.md 카탈로그 중 *실제 recovery 메커니즘을 가진* 엣지 계열 5편 + (2026-07-16 추가) 데이터센터 KV-보호 계열 4편(DejaVu/GhostServe/KevlarFlow/LUMEN, 하단 섹션).
> **원칙:** 복구 방식 서술은 **각 논문에 명시된 사실만**. "RADP 대비" 항목만 해석(인용 시 구분).
> 관련 문서: [PAPERS.md](PAPERS.md)(상세·venue), [comparison.md](comparison.md)(왜-엣지 동기), 초안 [../draft/3-related.md](../draft/3-related.md) §B(fault tolerance).
>
> **선정 근거:** failure를 *인지만* 하고 복구 메커니즘이 없는 논문(PA-MDI, Distributed-MoA)은 하단 부록으로 분리. 데이터센터 recovery(SpotServe, DualMap)는 엣지 아님 → 제외.

---

## 요약 비교표

| 논문 | Venue | 도메인 / 스케일 | 장애 트리거 | 사전 이중화(redundancy) | 복구 단위 | 복구 메커니즘 | in-flight 상태 복원 | proactive? |
|---|---|---|---|---|---|---|---|---|
| **Petals** | NeurIPS 2023 | inference / 인터넷 consumer-GPU swarm | server(peer) 장애·이탈 | swarm 내 block **중복 보유** | 실패 stage의 **KV cache** | client-side cache(각 stage로 보낸 입력)를 대체 peer에 재생해 그 stage state 복원 + greedy rebalancing | ✅ 실패 stage KV만 복구(전체 재시작 X) | reactive rebalance (redundancy는 상시 유지) |
| **JARVIS** ★ | MILCOM 2024 | inference / tactical SDR 18-node (wireless+wired) | node 장애 | **peer-level layer duplication** | layer(구간) | (a) backup peer가 이어받음, (b) **layer skipping**(다음 hop 재라우팅, 해당 layer 생략) | ⚠️ skip 시 해당 layer 연산 생략 → accuracy 저하 감수(측정) | 부분 proactive(duplication), 배치는 **수동 config** |
| **QEIL** | arXiv 2026 (preprint) | inference / **단일 edge 머신** 내 CPU·GPU·NPU | device(compute unit) fault·thermal | 없음(healthy unit로 재분배) | workload(layer assignment) | 100ms fault detection → healthy device redistribution → graceful degradation(50% capacity 점진 복귀), safety monitor override | ⚠️ workload 재분배, formal latency bound(τ_degraded ≤ τ_opt·D/D_healthy) | reactive + degradation 보장 |
| **Parallax** | arXiv 2025 (preprint) | inference / decentralized 볼런티어 GPU(지리 분산·공용망) | GPU join/leave(dynamic membership) | model **replica**(다중 복제) | layer(de-allocation) / pipeline stage | DHT live metric 기반 localized adjustment 또는 **CoV 기반 global rebalancing** + replica 간 **stage stitching**(request-time) | ❌ rebalance/re-stitch (KV 복원 명시 없음) | reactive rebalance |
| **FTPipeHD** | IEEE TMC 2024 | **training** / heterogeneous edge pipeline | device 장애 | **주기적 weight replication**(이웃 + central node) | model **weights** | 실패 시 survivor로 **re-partition** + missing weight refetch → resume | ⟂ training이라 in-flight KV 개념 없음; budget=training batch(초) | proactive checkpoint + reactive re-partition |

★ JARVIS = layer-level partition에 backup+recovery를 결합한, RADP에 가장 근접한 baseline.

---

## 논문별 상세

### Petals (NeurIPS 2023) — swarm redundancy + KV cache 복구
- 인터넷의 신뢰할 수 없는 consumer-GPU를 swarm으로 묶어 50B+ LLM을 pipeline-parallel 서빙.
- **복구:** 캐시 2종 유지 — *"server-side cache holds past attention keys and values for their layers... client-side cache holds past inputs sent to a given pipeline stage"* (§3.2). 서버 장애 시 클라이언트가 같은 stage를 든 다른 서버를 찾아 **client-side cache(그 stage로 보냈던 입력들)를 재생해 서버 state 복원** — *"compute only the stages held by the failed servers"* (실패 stage만 O(t) 재계산, 전체 재시작 X). ⚠️ 2026-07-16 정정: 종전 표기 'dual attention cache'는 오기. 각 서버에 block을 배정하는 탈중앙 **greedy rebalancing**으로 커버리지·throughput 유지.
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

## (추가 2026-07-16) 데이터센터 KV-보호 계열 — 복구 설계 공간의 반대편

> Petals/RADP의 **입력-재생**(평시 비용↓, 복구 시 재계산 지불)과 달리, 2024–26 데이터센터 serving 계열은 **KV 자체를 보호**(평시 메모리·대역폭 지불, 복구 시 재계산 회피). 4편 전부 원문 검증(PAPERS.md 상세 참조).

| 시스템 | 보호 대상 | 보호 위치 | 평시 비용 | 복구 | **전제 headroom** |
|---|---|---|---|---|---|
| **DejaVu** (ICML'24) | KV 자체(per-token 스트림) | ring 이웃 워커 | <2% @32–40Gbps | replica 반송+마지막 복제 이후만 재계산 (1.91×→1.24×) | 노드당 KV ~2× 메모리 + 수십Gbps 링크 |
| **KevlarFlow** ('26 preprint) | KV block | spare 파이프라인 peer GPU | 2.3–4.0% | 대체 노드 재개, MTTR 29–35s | **웜 여분 파이프라인 2–4개** + GPU 헤드룸(50–60% util) |
| **GhostServe** (MLSys'26) | KV parity (8:2 erasure) | **1TB 호스트 RAM** | <5–10% | parity+생존 shard 디코드+부분 재계산, <5s | intra-node TP + NVLink + 대용량 호스트 RAM |
| **LUMEN** ('26 preprint) | 요청별 KV checkpoint | full-replica 워커 호스트 RAM (80–160GB) | TTFT/TPOT ≈0 | checkpoint 접두사 재사용+부분 re-prefill, 29.9s | **모든 워커 = 모델 전체 사본** + 대용량 DRAM |

**축별 판정 (원문 근거):**
- **공통 전제 = 메모리 headroom.** 4편 모두 KV 사본/parity를 둘 "어딘가"(이웃 GPU 2×, 여분 파이프라인, 1TB/80–160GB 호스트 RAM)를 전제. **한 모델을 겨우 나눠 싣는 4GB 엣지(headroom 0) 레짐은 4편 모두 미대응.**
- **GhostServe가 명시적으로 남긴 공백:** *"primarily designed for intra-node serving, particularly for tensor parallelism"* — cross-node/pipeline-parallel + inter-node 대역폭이 future work. = 정확히 RADP의 레짐(노드 간 pipeline + 저속 LAN).
- **LUMEN ≠ RADP placement coupling (novelty 비충돌 확인):** LUMEN의 "checkpoint placement"는 full-replica들 사이 **요청별 KV checkpoint 보관자 선택**(*"a worker is a complete copy of the model weights"*). layer×backup 공동 배치가 아님 — 모든 워커가 전 layer를 들어서 결합할 대상 자체가 없음.
- **입력-재생 대비 열위 인정할 것:** KV-보호 계열은 복구 시 재계산을 (거의) 안 함 — headroom이 있는 환경에선 입력-재생보다 우월. related work에서 정면 대응 필요.

**RADP 포지셔닝 업데이트 (해석 — 인용 시 구분):**
1. **검증된 novelty**: 메모리 상한 하 **layer placement × backup placement 공동 최적화**(ψ+R) — Petals(기회주의 중복)·LUMEN(요청별 checkpoint 보관자)·나머지(배치 최적화 없음) 누구도 안 함.
2. **검증된 레짐 공백**: headroom-0(4GB, 모델 단일 사본 분할) + 저속 LAN — 4편 전부 전제 불충족.
3. **메커니즘 개척 여지**(future/next): GhostServe가 남긴 cross-node pipeline parity 보호를 저속 링크·coordinator mirror 채널 위에 재설계 — "재계산 vs parity-디코드"를 링크 대역폭 제약 하에 최적화하는 문제.

## (부록) failure-aware이지만 recovery 메커니즘은 없음

| 논문 | Venue | 다루는 방식 |
|---|---|---|
| PA-MDI | arXiv 2024 | objective에 worker 이탈·packet loss 실패확률 ∏(1−P)를 페널티로 반영 — backup·recovery-time 보장 없음 |
| Distributed-MoA | IEEE PIMRC 2025 | 중앙 SPOF 회피 + diverse connection robustness — 명시적 recovery mechanism 없음 |

---

## 유지 메모
- bib 미등록: **JARVIS**(MILCOM'24), **QEIL**(arXiv:2602.06057), **Parallax**(arXiv:2509.26182). related work에서 인용 확정 시 references.bib에 추가.
- 초안 `../draft/3-related.md` §B는 현재 Petals·FTPipeHD만 인용 → 이 문서 기준 **JARVIS·QEIL·Parallax 추가** 시 "recovery gap" 논증 강화.
