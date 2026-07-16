# Related Work — 초안 (틀, Phase 1) · TII

> 타깃 **TII**. Phase 1 = 주제별 문단 프레임(줄글+약간의 불렛). 기술 용어 영문 유지.
> 인용: RADP-경쟁계열=PAPERS.md, 산업계열=TII-industrial-refs.md(전부 DOI 검증). 수치 `[확인]`.
>
> **역할 경계 (redundancy 방지):**
> - Intro §2/§3 = "gap이 있다"를 **논증**(Petals/EdgeShard/Jupiter/데이터센터 name-drop).
> - Background = "왜 순진한 조합이 안 되나"를 **메커니즘**으로(spare-memory·coupled feasibility, Eq.mem).
> - **여기(Related) = 선행 시스템을 주제별로 catalog + RADP delta 정밀 명시.** 메커니즘 재유도 금지 → §Background 참조로 넘김.
> - 3개 묶음(A placement[데이터센터 흡수] / B fault tolerance / C 산업정보학) + 마무리 positioning 한 문단.

---

## A. 분산 LLM 추론의 layer placement

- **다루는 것:** placement 알고리즘 계열.
  - **Petals** — greedy placement + swarm-redundancy [borzunov2023petals].
  - **EdgeShard** — latency용/throughput용 **DP 2개를 분리** 제시, 각자 자기 목적함수로만 평가 [zhang2024edgeshard].
  - **Jupiter** — max-min throughput DP + TBT-SLO; 우리 ψ-recurrence의 **직접 조상**(α=1, recovery·γ_hop 없는 형태) [ye2025jupiter].
  - **Helix** — max-flow로 greedy placement의 이기종 fleet 2.38× 손해 실측 → DP 정당화 [mei2025helix].
  - **Dai et al.** — 이기종 엣지에서 device placement + model partition **joint**, 단 one-shot DNN(per-token TBT·KV·recovery 없음) [dai2025joint].
- **데이터센터 대응물(흡수):** 대규모 이기종 serving은 성숙 — HexGen/HexGen-2/Hetis/LLM-PQ/SpotServe. 그러나 reliability·넉넉한 memory(24–80GB)·고속 interconnect(NVLink급)를 **가정**해 4GB·비신뢰·저속망(수십 Kbps–1000Mbps [zhang2024edgeshard]) 엣지로 직접 전이 안 됨. SpotServe preemption조차 **예고된 graceful** 종료(무통보 crash 아님). [PAPERS.md]
- **RADP delta:** ① EdgeShard(α=0)·Jupiter(α=1) 두 mode를 **하나의 DP + α rank function**으로 통합, ② per-hop γ_hop 추가, ③ **결정적 차이는 recovery를 placement와 co-optimize**(위 전부 recovery 부재; 데이터센터 계열이 가정으로 배제하는 4GB frontier 타깃). mode cross-evaluation 부재 = §Eval 매트릭스가 메움.

## B. 분산 추론·학습의 fault tolerance

- **다루는 것:** recovery unit·budget이 서로 다른 선행 FT.
  - **Petals swarm redundancy** — "예비 peer가 그 layer를 이미 보유"를 전제(consumer GPU, ~11–24GB) → spare-memory 가정 [borzunov2023petals].
  - **FTPipeHD** — **training-side**. weight를 주기적 복제, 실패 시 재파티션+weight refetch 후 재개. recovery unit=weight, budget=training batch(초 단위) [chen2024ftpipehd].
  - (데이터센터 checkpoint/restart·SpotServe preemption은 §A 데이터센터 대응물과 연결.)
- **RADP delta:** recovery unit = **in-flight KV+activation chain**, budget = **per-token TBT**, 그리고 backup 메모리를 **placement DP 안(Eq.mem)에서 예약** — spare-peer 가정 없이. training/coarse-grained recovery는 decode로 전이 안 됨(TBT 안에 KV 복원 필요). *메커니즘 상세는 §Background/§Design-B.*

## C. 산업정보학(TII)에서의 분산 추론·장애복구

- **왜 이 묶음:** TII 리뷰어에게 "분산 추론 + fault tolerance가 이미 산업정보학의 1급 주제"임을 보이고, 그럼에도 **LLM decode의 placement+recovery joint는 공백**임을 못박음.
- **분산/협업 추론 계열:** cloud–edge–end DNN layer partition [Lin'20 TII], IIoT 협업 DNN 추론 [Wu'21 TII], end-edge-cloud joint inference [Fan'23 TII], 산업 엣지 on-device 추론 [Fang'21 EdgeKE TII]. → 단 **one-shot DNN 수준**(autoregressive KV·TBT 없음).
- **fault tolerance 계열 ★:** WSN-IIoT의 노드가 "energy depletion·hardware malfunctioning"으로 실패 [Kaur'23 TII], 노드 fail 시 "data loss·performance degradation" 연쇄 [Xu'20 TII], 분산 임베디드는 "reliable, hard real-time" 필수·공유망이 SPOF [Gessner'19 TII], 안전필수 real-time에서 FT를 hard constraint로 [Devaraj'21 TII]. → 단 **data routing·task scheduling·network 수준**.
- **RADP delta:** 기존 산업 FT가 다루지 않는 **LLM 분산추론의 placement+recovery joint**를 산업 엣지 fleet에 가져옴.

## 마무리 — positioning 한 문단

- RADP는 (A) EdgeShard·Jupiter mode를 α 하나로 일반화하고 데이터센터 serving이 가정으로 배제한 4GB·비신뢰 frontier를 타깃하며, (B) recovery를 placement와 **Eq.mem로 co-optimize**하고, (C) 이를 산업정보학이 요구하는 **fault-tolerant LLM 분산추론**으로 구체화 — **세 계열 어디도 동시에 하지 않는 지점**을 메움.

---

## (메모) TODO / 확인
- **bib 등록 완료** (references.bib, 2026-07-08): 데이터센터 5편 `jiang2024hexgen` `jiang2025hexgen2` `mo2025hetis` `zhao2024llmpq` `miao2024spotserve` + TII 12편 `zhang2026finetuning` `liu2024joint` `wang2024largescale` `chamotra2026advancing` `kaur2023intelligent` `xu2020dynamic` `gessner2019faulttolerant` `devaraj2021resourceoptimal` `lin2020costdriven` `wu2021accuracyguaranteed` `fan2023dnn` `fang2021edgeke`. 전부 Crossref/arXiv 검증.
- 확인 필요: HexGen(ICML'24)/HexGen-2(ICLR'25) venue는 dblp/PAPERS.md 기반 inference(arXiv eprint 병기). LLM-PQ는 PPoPP'24 **poster**(full은 arXiv:2403.01136, note로 병기).
- 수치 `[확인]`: Helix 2.38×(원문 확인됨, related.tex 기재), 76×·수십Kbps–1000Mbps는 §Background/EdgeShard 원문.
- role C 문구는 **인용 전 원문 재확인**(초록 기반 요약 포함, TII-industrial-refs.md 주의사항).
- 기존 `sections/related.tex`(영문, TII 이전 작성본)에 A·B는 이미 있음 → Phase 2에서 이 프레임(데이터센터 흡수·C 신설)으로 갱신.
- 분량: 주제 A~C가 각 3–5문장이면 related work 적정(½–¾ 컬럼). C가 너무 길어지면 분산추론 계열은 1–2편으로 압축.
