# Introduction — v2 (시나리오 2 하이브리드, TII 산업 프레이밍) · 간략본

> 타깃 IEEE **TII**. 문체: 논리 흐름용 ~임 체 + 불렛. 기술 용어 영문 유지.
> 인용: [저자'년 TII]=TII-industrial-refs.md, 그 외 comparison.md/PAPERS.md. 수치 `[확인]`.
> 뼈대: **엣지-first → 기존 엣지 한계 → 데이터센터는 왜 못 빌리나 → RADP**. "왜 엣지"는 privacy/cost 아니라 **capacity + 산업 offline + reliability**.

---

## 1. 분산 추론의 필요성 (산업 엣지)

- LLM이 클라우드 데모를 넘어 **산업 현장 워크로드로 진입** — 배터리(BMS) 상태추정에 3B LLM [Zhang'26 TII], 공장 조립 fault diagnosis [Liu'24 TII], 품질/defect 검사 [Wang'24 TII], ICS 보안 [Chamotra'26 TII] 등.
- 문제는 "**어디서 돌리나**". 산업 현장은 **클라우드가 선택지가 아닌** 경우가 많음:
  1. **air-gapped 공장 OT 망** — 보안상 클라우드 offload 자체가 정책적으로 금지됨
  2. **off-grid 설비**(해상 플랫폼·광산·원격 변전소) — 안정적 클라우드 링크가 물리적으로 부재
  3. **이동 로봇·AGV** — real-time 폐루프라 매 token 왕복 latency 불가
  → privacy·API 비용 이전에, 이런 현장은 **추론이 로컬 엣지에 남는 것이 전제**임.
- 그런데 곧바로 **capacity 벽** — billion-param LLM은 weight + (길수록 커지는) KV cache를 함께 적재해야 하고, 이는 단일 엣지 디바이스 용량을 초과함 (Llama2-7B FP16 ≈14–28GB > Jetson류 8–16GB `[확인]`). [Zhang'26 TII]조차 3B를 임베디드에 겨우 얹음.

→ **한 대로는 못 올림 → 이미 현장에 깔린 이기종 엣지 여러 대를 묶어 layer를 나눠 싣는 분산 추론이 필연.**

## 2. 기존 엣지 분산추론과 그 한계

- 엣지 분산추론은 산업에서 **이미 활발**:
  - **Petals** — consumer GPU swarm으로 billion-param 서빙
  - **EdgeShard** — DP 기반 latency-optimal layer placement (edge-cloud)
  - **Jupiter** — TBT-SLO throughput-optimal placement
  - (산업 DNN 계열: cloud–edge–end layer partition [Lin'20 TII], IIoT 협업 DNN 추론 [Wu'21 TII])
- 산업 엣지의 **given 운영환경** (시스템이 물려받는 *가정*이 아니라 조건 자체):
  - **이기종성** — GPU tier(AGX Orin·Nano) + CPU-only 혼재, fleet 내 격차 ~76× `[확인]`
  - **비신뢰성** — 노드가 흔히 죽음: "energy depletion and hardware malfunctioning"으로 실패 [Kaur'23 TII], 노드 하나 fail 시 "data loss, performance degradation" 연쇄 [Xu'20 TII]; 우리도 crash·OOM·partition 실측 `[확인]`
- 기존 엣지 시스템은 **이기종성은 이미 정면으로 다룸**. 못 감당하는 건 **비신뢰성 + memory-tightness**:
  - **recovery 부재** — EdgeShard/Jupiter는 각 layer를 한 device에만 두고 recovery 없음 → 첫 worker 실패에 **stream 전체 abort** = 산업선 생산중단·안전 문제
  - **spare-memory 전제** — Petals swarm redundancy는 "예비 노드가 그 layer를 이미 맡고 있음"을 전제(consumer GPU, 실측 swarm ~11–24GB) → 엣지엔 그런 여유 없음, 4GB Nano 미대응
- **더 근본**: 기존 연구는 layer placement(ψ)와 recovery routing(R)을 **별개 문제로** 다룸. memory-tight 엣지에선 ψ·R의 feasibility가 **coupled**(backup 예약이 placement 가능영역을 바꿈) → 분리하면 feasibility 아니면 performance를 반드시 잃음. **이 coupling이 기존 연구가 비운 지점.**

## 3. 데이터센터 분산추론은 왜 그대로 못 빌리나

- 대규모 이기종 GPU serving은 성숙 — Helix, HexGen/HexGen-2, Hetis, LLM-PQ, SpotServe.
- 그러나 이 machinery는 산업 엣지로 **직접 전이 안 됨** — 다음을 **가정**하기 때문 (엣진 이게 없음):
  - **노드 신뢰성** — 기존 분산추론은 "unreliable devices or high-latency networks"용이 아님 [Petals]; datacenter serving은 mid-inference crash recovery 없음(SpotServe의 preemption은 예고된 graceful 종료)
  - **넉넉한 메모리** — 이기종이라도 24–80GB GPU; backup 예약이 feasibility를 뒤집는 4GB 레짐은 엣지 고유
  - **고속 interconnect** — NVLink 최대 600GB/s vs 엣지 간 수십 Kbps–1000Mbps [EdgeShard]

→ **산업 엣지가 별도 연구를 요구하는 이유는 privacy/cost가 아니라, 데이터센터가 전제하는 신뢰성·메모리·네트워크가 현장에서 성립 안 하기 때문임.**

## 4. 우리 접근 — RADP (Recovery-Aware DP)

- **ψ와 R을 하나의 alternating DP로 joint 최적화** — backup-memory 예약량이 placement feasibility로 되먹임됨. α knob 하나로 EdgeShard latency mode(α=0)와 Jupiter throughput mode(α=1)를 한 프레임에 통합.
- 이를 실 fleet에서 돌리는 **런타임 둘**:
  - **mirror-cache 기반 chain-aware recovery** — activation out-of-band mirror + trailer 기반 failure attribution + chain replay
  - **asynchronous chain forwarding** (+ ResultReady reverse channel)
- **산업 명분(TII)** — fault tolerance는 산업 분산 시스템의 **hard constraint**로 다뤄져 옴 (real-time task는 processor fault에도 deadline 유지 [Devaraj'21 TII]; 분산 임베디드는 "reliable, hard real-time" 필수 [Gessner'19 TII]). 단 기존 산업 FT는 **data routing·task scheduling·network** 수준이지, **LLM 분산추론의 placement+recovery joint**는 공백 → RADP가 메움.

## 5. 기여 (Contributions)

- **ψ+R alternating DP** — 고정 device order에서 inner DP O(L²·|D|) 다항, alternation ≤3 iter 수렴 (전역최적 위한 outer subset+perm 탐색은 |D|에 지수적 → top-k heuristic future work). EdgeShard L-mode·Jupiter T-mode를 α rank function 하나로 일반화. (§Design-A)
- **mirror cache + chain-aware failure attribution** — gRPC trailer로 heartbeat race 속에서도 진짜 죽은 worker 식별. (§Design-B)
- **asynchronous chain forwarding** — per-request locking + ResultReady로 chain 길이 무관 C=16에서 17–47% throughput↑ `[확인]`. (§Design-C)
- **실측 평가** — 6-worker Jetson fleet에서 OPT-350M 24 operating point + Llama-3.2-1B 9-cell. C≥4 전 지점 L≻T; mid-stream SIGKILL에 RADP는 60 token 전부 정합, placement-only baseline은 17–20 token 뒤 abort `[확인]`. (§Eval)
- **cost-model ablation** — subset enum + γ_hop 켜도 L≻T 격차 넓어짐 → 남은 격차가 wire-cost 아니라 multi-stream system-level 효과. (§Eval)

---

## (메모) TODO
- 수치 확정: Llama2-7B 28GB, 76×, 17–47%, 60 vs 17–20 token → REPORT.md/PHASES.md 대조.
- 산업 시나리오는 "such as" 동기 예시로만 — 실 배포 주장 금지.
- role A 인용 2–3편으로 압축(Zhang'26 + Liu'24 권장). role D 문구 원문 재확인.
- main.tex/main_kor.tex 서론의 "두 가정" 문장도 §2 논리로 정정 필요(EdgeShard/Jupiter는 동질성 가정 안 함).
