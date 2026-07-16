# 지도교수 피드백 분석 & 방향 재정비 (2026-07-16)

> **상태:** 논문 작성 **보류**. 아래 "필요한 실험(Part 3-B)" 먼저 수행 → 결과 확인 후 재작성.
> **한 줄 결론:** 세 피드백은 별개 지적이 아니라 한 방향 — *알고리즘 novelty로 승부 보지 말고, 장애복구(FT)를 논문 중심축으로 옮기고, 성능은 "복구를 넣고도 크게 안 뒤처진다"는 보조 근거로 재배치하라.* 타깃 venue가 **TII(Industrial Informatics, 신뢰성 1급 주제)**라는 점과도 정합.

받은 피드백 원문:
1. DP 알고리즘 차별성 부족 → Jupiter에서 가져온 것 그대로 + 메모리 제약조건 추가 정도? 이건 차별성이 안 됨.
2. 차라리 LB보다 FT를 메인으로. 이때 FT 없는 논문 대비 측정 지표가 무엇일지 고민 필요(Time-to-recovery 등).
3. Throughput/latency는 "복구도 구현했으면서 다른 논문 대비 많이 안 떨어진다" 정도로. 지금처럼 극단 환경으로 우리 모델에 유리하게 내는 건 옳지 않음 — **공정한(fair) 세팅 필요.**

---

## Part 1. 프로젝트의 현실적 한계

| # | 한계 | 근거 (코드/측정) |
|---|---|---|
| L1 | **inner DP는 Jupiter의 ψ-recurrence 그대로.** α-knob은 EdgeShard(α=0)/Jupiter(α=1) 두 기존 목적함수의 보간 | `introduction.tex`: "Jupiter … 우리 ψ-recurrence의 직접 조상" |
| L2 | **outer subset+permutation 탐색이 factorial (≈e·M!).** M=7 full search ~9분 — 스케일 불가, top-k heuristic은 future work(미구현) | `server.py` 복잡도 주석; subset selection 미구현 |
| L3 | **DP comm cost가 wire-only.** gRPC+GIL의 ~9ms hop overhead 누락 → 모델은 오히려 T(다단계)를 과대평가. live에서 L이 이기는 건 실측 hop cost가 T를 때리기 때문 | `project_dp_comm_cost_underestimate` 메모 |
| L4 | **L≻T는 regime-specific.** small model(≤1B)+launch-bound+C≥4 고동시성+76× 극단 이질성에서만 강함. compute-bound 대형 모델에선 좁혀지거나 뒤집힐 수 있음 | `introduction.tex` "larger models would expose more"; 76×는 CPU-only 보드 포함 시 |
| L5 | **복구 baseline이 "복구 없음"뿐.** placement-only가 abort하는 건 자명 — recovery *품질*을 비교할 실제 FT baseline 부재 | `experiments/_harness.dp_placement_no_recovery` |
| L6 | **chain 복구 live 수치가 오염됨.** 3292ms 중 ~3000ms가 ansible/kill orchestration overhead → intrinsic TTR 아님 | `experiments/REPORT.md` §9.2 |
| L7 | **failure model 단순.** 단일 mid-stream SIGKILL만. 동시/연쇄 장애, partition 지속시간, 반복 장애 없음 | `run_failure.py` 단일 victim |
| L8 | **backup 예약이 가용 메모리를 실제로 깎음** — "4GB가 빠듯하다"는 동기와 정면 긴장. 명시 안 하면 리뷰어가 찌름 | `Eq.mem`, `recovery_table.determine_recovery_table` 자유메모리 근사 |

### 이미 가진 강점 자산 (FT 축의 근거)
- **복구 latency**: star topology **mean 617 ms / p95 670 ms (N=5, EXP-A2)** — bounded, CDF 그림(`paper/figures/make_recovery_cdf.py`) 존재
- **장애 하 정합성**: mid-stream SIGKILL에도 **60 token 전부 정합** vs placement-only는 **17–20 token 후 abort** (강한 binary 결과)
- **chain-aware attribution**: trailer(sync) vs heartbeat(async) race에서도 진짜 죽은 worker 식별 (테스트 검증)
- **ψ+R coupling 직접 증거**: D2.8 offline sweep — cost-only DP는 2-stage, backup memory 제약이 production을 4-stage로 강제 (`project_psi_r_coupling_empirical_evidence`)
- **정상운영 mirror overhead 실측**: 8 token당 16 push / 72,064 bytes (`REPORT.md` §9.1)

---

## Part 2. 피드백별 타당성

### ① "DP 차별성 부족" → 타당 (~75%). 결론은 '버려라'가 아니라 **'팔지 마라'**
- inner DP는 Jupiter 것, "메모리 제약 추가"를 novelty로 내세우면 그대로 깨짐 — 맞는 지적.
- **하지만 진짜 델타는 "메모리 제약"이 아니라 coupling**: backup 예약(Eq.mem)이 *feasible placement 집합 자체를 바꿔* ψ·R을 독립적으로 못 풀게 함. D2.8이 실증.
- **처방:** DP를 "새 알고리즘"으로 팔지 말고 **"ψ·R이 memory-tight edge에서 coupled라는 발견 + 함께 푸는 formulation"**이라는 systems/feasibility 기여로 재포지셔닝. α-knob 통합은 헤드라인에서 강등(convenience 수준).

### ② "FT를 메인으로" → 매우 타당. 강력 추천
- 진짜 차별점이 여기: recovery-comparison.md 기준 **in-flight KV 복원은 Petals뿐, backup을 placement DP 안에서 예약 + per-token TBT budget 복구는 RADP뿐.** TII venue-fit 완벽.
- **측정 지표** — 있음 ✅ / 필요 ⬜:
  - ✅ TTR: 617 ms mean / 670 ms p95
  - ✅ token loss/정합성: 0 loss vs 17–20 abort
  - ✅ 정상운영 mirror overhead: 8 tok당 16 push / 72 KB
  - ✅ attribution 정확도: trailer vs heartbeat
  - ⬜ goodput under failure (재계산 손실 반영 tok/s)
  - ⬜ failure 다양성: crash/OOM/partition, 연쇄·반복 장애 성공률
  - ⬜ intrinsic TTR (orchestration overhead 제거)
- ⚠️ **함정(교수님이 정확히 찌른 부분):** "우리는 복구, 쟤넨 abort"는 **자명한 비교 → 논문 안 됨.** 반드시 **실제 복구 baseline**(cold-restart / full-prefix-replay / 메모리 되는 데선 Petals식 redundancy) 대비 TTR·overhead·goodput 우위를 보여야 함. → **현재 가장 크게 빈 실험(L5).**

### ③ "throughput/latency 공정 세팅 + '복구 넣고도 안 뒤처짐'으로" → 타당. 내부 취약점(L3·L4)과 일치
- L≻T를 "topology·runtime·model 무관 structural property"로 파는 현재 클레임은 **과함.** small model+launch-bound+고동시성+극단 이질성에서 hop 적은 L이 이기는 특정 레짐 현상. 76×는 CPU-only 보드로 만든 극단값.
- **처방:** throughput/latency를 헤드라인 승리가 아니라 **cost-of-FT("복구 준비 대가가 작다")**로 재배치 + **공정한 중립 세팅** 측정 + **sensitivity sweep으로 L이 이기는/지는 경계 정직하게 지도화.**
- 부분 방어: cost-model ablation(subset enum+γ_hop 켜도 격차 *넓어짐*)은 유효 → finding 유지, "universal" 수식어만 제거.

**세 피드백의 일관성:** ①(알고리즘 novelty 약함)·②(FT 메인)·③(성능은 보조)은 모두 같은 pivot을 가리킴 — 신뢰성 중심 재편.

---

## Part 3. 개선 방향

### A. 재프레이밍 (코드 0줄, 즉시 — 단 실험 후 실행)
1. 중심축을 **"신뢰성 있는 산업 엣지 LLM 추론을 위한 recovery-aware placement"**로. FT 헤드라인, placement/throughput 보조.
2. Contributions 재작성: ① **ψ+R coupled feasibility 발견+formulation**(알고리즘 novelty 주장 삭제) ② **in-flight KV chain 복구 + trailer attribution**(핵심) ③ cost-of-FT ④ 정직한 regime boundary.
3. **Limitations 섹션 신설** — L2·L3·L4·L8 자진 명시. 특히 backup 예약의 메모리 대가.

### B. 필요한 실험 (우선순위순) — **← 지금 여기부터**
1. **[최우선] 실제 FT baseline 1~2종** → TTR·goodput·overhead 비교. 최소 cold-restart + full-prefix-replay. (②함정 해소, L5)
2. **공정 세팅 + sensitivity sweep**: 이질성 수준·모델 크기·동시성 축으로 L≻T 경계 지도. 76× 극단 대신 중립 config를 메인으로. (③, L4)
3. **intrinsic TTR 재측정**: ansible/kill overhead 분리, 순수 replay 비용만. (L6)
4. **정상운영 overhead 표**: mirror 대역폭·메모리·backup 예약 비용 정량화. (L8)
5. **failure 다양성**: crash/OOM/partition + 연쇄·반복 장애 성공률. (L7)

### C. 버리지 말 것
D2.8 coupling 증거(①핵심 근거), attribution 정확성, 장애 하 token 정합성(강한 binary 결과), cost-model ablation(범위만 좁혀 유지).

---

## 리스크 (정직하게)
1. 공정 세팅에서 **L≻T 마진이 줄 수 있음** — 헤드라인 아니게 되므로 OK.
2. 실제 FT baseline 대비 RADP TTR가 **극적으로 우월하진 않을 수도** 있음(617 ms는 빠르지만 cold-restart 대비 얼마나 이기는지는 미측정). → **B1 먼저 돌려 확인.** 측정이 클레임과 어긋나면 해석으로 합리화하지 말 것(`feedback_question_unexpected_results` 교훈).
