원문: ars_round3_decision_2026-09-03.md (영문). 본 문서는 한국어 번역본이며 판정의 효력은 원문 기준이다.

# 편집 판정 — Round 3 (2차 검증) — KV-CARE (IEEE IoT-J)

**일자:** 2026-09-03 · **R1 판정:** Major(대폭 수정) (5/5) · **R2 판정:** Major (무조건 Minor 1건, Major로 귀결되는 조건부 Minor 2건, Major 2건)
**근거:** Round-3 검증 재심사 5건(`R0/R1/R2/R3/DA_round3.md`)을 `EDITORIAL_DECISION_R2.md` §7 및 로드맵 항목 1–42와 대조하여 확인하였다.
**유지되는 제약 조건:** 테스트베드는 폐쇄되었다 — 테스트베드에 종속된 항목은 범위 설정과 공개(disclosure) 여부만으로 평가한다. 저자는 논문을 **의도적으로 10 pp.로 유지**하고 있으며, *선언된* 지면 예산상의 포기는 오류가 아니라 공개된 부재로 채점한다(R3 §Context). 아래의 모든 MUST-FIX는 단어 또는 절 수준이며 지면을 소모하지 않는다.
**이번 라운드의 MUST-FIX 적용 규칙**(패널이 수렴하였으므로 R2보다 엄격하게 조정): 어떤 항목이 MUST-FIX가 되는 경우는 (a) 저자 자신의 파일·코드·로그에 대조하여 **검증된 사실 오류 또는 내적 일관성 오류**이거나, (b) **인용(upheld)된 Devil's Advocate CRITICAL**이거나, (c) **심사자 3인 이상이 각자의 권고에서 차단 사유로 지목한 경우**에 한한다. 그 외는 모두 SHOULD/OPTIONAL이다. 단순히 "심사자 2인 이상이 제기함"만으로는 더 이상 충분하지 않다 — 이 단계에서는 저자가 다듬기(polish)와 구분할 수 없는 목록을 만들어낼 뿐이다.

---

## 1. 패널 표

| 심사자 | R1 권고 | R2 권고 | **R3 권고** | A | P | N | W | 추적 항목 | 점수 변동 (R1 → R2 → **R3**) |
|---|---|---|---|---|---|---|---|---|---|
| **R0** Journal-Fit | Major | Minor *(조건부; 조건 미충족)* | **Minor — "그리고 이번에는 조건부가 아니다"** | 15 | 10 | 0 | **0** | 25 (17 R1 + 8 R2-new) + 로드맵 20행 | Fit 6→6→**6** · Originality 6→7→**7** · Significance 5→5→**5** · Clarity 6→7→**8** · **Claims-vs-evidence 4→6→8** |
| **R1** Methodology | Major | Minor ("1–8 반영 후 게재") | **경미한 편집상 수정을 조건으로 게재(Accept)** (명시된 조건 2건) | 13 | 13 | 4 | **1** | 31 (24 R1 + 7 R2-new) + 로드맵 15행 | Exp. design 5→6→**6** · Stat. validity 4→4→**5** · Metric defs 6→7→**8** · Reproducibility 3→4→**5** · **Limitations 6→7→9** |
| **R2** Domain | Major | Minor *(전파 점검을 조건으로)* | **Minor — "타인의 검증에 조건부가 아니다, 내가 직접 수행했기 때문이다"** | ~19 | ~11 | ~5 | 0 | 35 (C-1–C-4, M-1–M-11, m-1–m-12, NEW-1–NEW-8) + 로드맵 17행 | Literature 5→6→**7** · Tech. soundness 5→6→**7** · **Novelty 5→5→5** · Fairness 5→7→**8** |
| **R3** IoT 실무자 | Major | **Major** | **Minor — "정오(errata) 세 건만 고치면 게재하겠다"** | 17 | 9 | 7 *(6건은 선언된 미적용 목록상)* | **0** | 33 (25 R1 + 8 R2-new) + 로드맵 12행 | Deployability 4→5→**6** · Motivation–eval match 3→5→**6** · **Practical impact 5→6→6** · **Clarity for practitioners 6→6→6** |
| **DA** Devil's Advocate | Major | **Major** | **Minor — "이 원고에 대해 그렇게 쓴 것은 이번이 처음이다"**, NEW-3을 조건으로 | MUST 15건 중 12건 무결 | — | — | — | 21 (C1–C8, M1–M13) + 신규 9 | 루브릭 없음. **8개 항목 철회**(C3, C5의 차단 사유 절반, M1, M2, M10, N3, N4, N6-as-arithmetic); **신규 CRITICAL 1건**(NEW-3) |

**패널 산술: Minor 이상 5인, Major 0인, Major로 귀결되는 조건부 Minor 0인.** R2의 Minor는 R2 라운드에서 전파 점검을 조건으로 하였다. R2는 이번 라운드에 그 점검을 직접 수행하였고 "실질적으로 통과한다"고 보고한다. R0의 R2 Minor는 자신의 항목 1–2(결론; 163/183 + 갱신되지 않은 그림)를 조건으로 하였는데, R0는 응답서가 아니라 **파일, 그림 바이너리, 생성기, 결과 JSON으로부터** 둘 다 수정되었음을 검증하였다. R3와 DA는 모두 Major → Minor로 이동하였다.

**패널이 만장일치로, 각자 독립적으로 이행되었다고 기록하는 사항**(5인 전원): 결론이 실질적으로 재작성되었고 여섯 또는 일곱 개의 유보 문구를 담고 있다(DA는 7/7 검증); "regardless of the failure position"은 grep 결과가 0건이다; Fig. 2 판독 문장이 재작성되었고 Table I에 대해 *참*이다(R1이 확인); 163 ms와 183 ms는 진정으로 서로 다른 두 측정치이며, R0, R1, R2, DA가 원시 JSON으로부터 각각 독립적으로 재현하였다; 세 그림 모두 소스 편집 **이후**, 빌드 이전에 재생성되었다; 뒤바뀐 Reconfigure 짝짓기가 **저자 자신의 로그에 대조하여** 수정되었고(P=4→465.805 s, P=8→413.069 s) 심사자 4인이 검증하였다; 그리고 응답서의 Round-2 허위 진술 네 건이 *해당 위치에서 실명으로* 철회되었다. 심사자 4인은 이번 개정이 반복적으로 **저자 자신의 이익에 반하는 방향으로** 움직였음을 별도로 지적한다: 헤드의 12.4 GiB 전량을 부과한 점, n=3에서 "these figures bound the cost rather than rank the modes"를 게재한 점, DejaVu 베이스라인의 중앙집중성을 공개한 점, "four times the bytes" 서사를 폐기한 점, 그리고 초록에 3.7×와 나란히 2.7×를 실은 점이다.

---

## 2. 합의된 잔여 결함 (심사자 2인 이상)

| # | 결함 (한 줄) | 심사자가 인용한 위치 | 제기자 | 최소 수정 |
|---|---|---|---|---|
| **J1** | MUST-FIX 4 / K10 / DA-C6이 초록, §I, §III-E에는 도달했으나 **결론에서 멈추었다** — 결론은 §III-E가 명시적으로 부정하는 바를 주장하고 있다 | `discussion.tex` L128–129: "so that **the recovered state has a device to run on**", 이는 `abstract.tex` L11–13 "the failed stage's **weights** have a device to **load** on" 및 `design.tex` L198–200 "Eq. (mem) charges weights only"와 상충 | **R0-N9 (MAJOR)** · **R1-NEW-11 (차단 사유)** · **R2-N3-2 (차단 사유 #2)** · **R3-NEW-B (차단 사유 #3)** · DA-NEW-4/C6 ("세 번째로 요청함") | 다섯 단어: 초록 자신의 표현을 붙여넣으면 된다. 같은 김에 결론의 실현 가능성 절에 "in an offline placement analysis"를 추가한다(R2-N3-2, R3-MAJOR-6). |
| **J2** | K17 수정은 모순을 §IV-A의 산문에서 §III-A의 **표기법**으로 옮겼을 뿐이다: R의 선언된 정의역이, 같은 문장이 포함한다고 말하는 스테이지를 배제한다 | `design.tex` L8 "$R:\mathcal{S}\to\mathcal{D}$ … **every stage $s$, the head included**" 대 L31 "Let $\mathcal{S}$ denote the **protected non-head stages**"; $\mathcal{S}$는 Eqs. (1)–(3), $\ell_{\max}$ 패딩 규칙, 완전성 규칙, Alg. 1의 가드 $F\nsubseteq\mathcal{S}$에서 그 좁은 의미를 그대로 지닌다 | **R0-N10 (MAJOR)** · **R1-NEW-12 (차단 사유)** · **R2-N3-1 (차단 사유 #1)** · **R3-NEW-A (차단 사유 #1)** · DA-NEW-2 (MAJOR) | 기호 하나: $\mathcal{S}^{+}=\mathcal{S}\cup\{\text{head}\}$로 두고 $R:\mathcal{S}^{+}\!\to\mathcal{D}$. 그다음 근거 한 절 — 충돌 **A3** 참조. |
| **J3** | K8을 위해 추가한 유보 문구가 원고의 **유일한 허위 파생 진술**이다 | `evaluation.tex` L160–161 "$-6\pm3$ ms per position, **within two standard errors of zero**". 두 심사자 모두 `b1_ft_fleet_7b_rep3.json → fits.replicate`로부터 재계산: $0.0060417/0.0029646=\mathbf{2.038}$ SE — 범위 밖이다. 반올림된 표 값 $6.0/3.0$으로는 정확히 2.0, 즉 within이 아니라 *at*이다 | **DA-NEW-1 (MAJOR)** · R1-NEW-8 (minor; 독립적으로 2.04 산출) | "about two standard errors"라고 쓰거나 비율을 제시한다. DA 자신의 문장이 그대로 쓸 만하다: "2.0 standard errors from zero, in the one family that does no per-position work, which we read as an unmodelled systematic." |
| **J4** | Table I의 새 각주 (b)가 정반대의 것을 측정한 프로브를 근거로 인용한다 | `evaluation.tex` L134–135 "byte identity **verified in the fidelity probe** (§IV-D)". 그 프로브는 Table II이며 교차 계층 *replay* 경로에서 **KV 원소의 26.9 %가 상이함**을 보고한다; §IV-D는 바이트 동일성을 "the **unit tests** assert layer-wise identity"(L261–262)에 귀속시킨다 | **R0-N11** · **R2-N3-5** | 세 단어: "byte identity **asserted in unit tests** (§IV-D)". R0의 지적이 유효하다: 이렇게 하면 주석이 오히려 *더 강해진다* — "by construction, unit-tested"는 충분한 근거이며, 잘못된 것은 프로브의 권위를 빌려온 점이다. |
| **J5** | 항목 18/K12는 "growth stated"로 보고되었으나 원고는 상한이 아니라 방향만 진술하고 있다 — 게다가 solve 시간은 저자 자신의 보고서에 존재한다 | `design.tex` L206–209 "ten iterations", "1 950 on the six-worker fleet", "so the search grows with the number of ordered subsets". **DA가 누락된 숫자를 찾아냈다: `experiments/REPORT.md:812`에 "solve 122 s (1950 후보 중 1454 feasible / 496 infeasible)"이 기록되어 있다** | R0-W8/M2 · R1-item 18 · R2-item 18 · R3-MAJOR-10 · DA-M9 (5인 전원) | 숫자 둘: "the solve takes 122 s on this fleet and enumerates $\sum_{k=2}^{|\mathcal{D}|}P(|\mathcal{D}|,k)$ ordered subsets — 1 950 at six devices, ≈9.8 M at ten." 테스트베드 불필요; 지면 불필요. |
| **J6** | Table II는 여전히 상대 오차나 스케일 없이 절대 차이만 보고한다 | `evaluation.tex` Table II: 26.9 %, $2^{-8}$, 변경 없음 | R1-M8 · R2-M-5 · R3-MAJOR-9 · DA-M6 (4인) | 열 하나 또는 절 하나: $2^{-8}$ 절대값 옆에 상대 오차. R1은 이 하위 항목이 적용되지도, 미적용 목록에 오르지도 않았음을 지적한다. |
| **J7** | Pareto 문장의 자격 부여 기준이, 더 적은 상태를 보유한 유일한 경쟁자를 배제하는 바로 그 임계값에서 그어져 있다 | `evaluation.tex` L204–205 "among the families that recover **within two seconds**, \sys{} retains the least state" — Petals는 2.31 s / 40 kB/tok, 즉 **상태가 2.8× 적음**에도 0.31 s 차이로 배제된다; 해당 문단은 그 부등호의 방향을 결코 밝히지 않는다 | R0-N13 · R2-N3-4 · R3-NEW-C · DA-C5 잔여 (4인) | 저자의 기존 문체로 한 절: "Petals is the low-state endpoint at 40 kB/tok and 2.3 s." 4인 모두 현재 문장이 *참*이라고 평가하면서도, 4인 모두 그 경계가 눈에 띈다고 지적한다. |
| **J8** | 세 가지 단위 관례가 공존하는데 새로 추가된 선언은 그중 하나에만 미친다 | Table I 주석 L132 "kB denotes 1 024 bytes"(선언됨, 표 범위) 대 §IV-C L223–224 "832 MB / 224 MB"(이진, 미선언), "12.4 GiB"(L25, L88), Table III "4.8 GB / 23 GB", §IV-A "3.1–5.8 GB" | R0-W14 · R1-m18 · R2-m-3 · R3-MINOR-7 (4인) | 선언을 §IV-A로 옮기고 MB/MiB까지 확장하거나, 값을 변환한다. |
| **J9** | 환경 문단은 심사자 2인의 최우선 비차단 요청이며 테스트베드에 **종속되지 않는다** | `sections/` 전체에 대해 jetpack/l4t/nvpmodel/jetson_clocks/tegrastats/Gb·s⁻¹ grep → **0건**; `design.tex` L218 "Python with PyTorch and gRPC"; 아티팩트 진술 없음 | R1-m22 ("the single most consequential missing environment fact") · R3-MINOR-1/-2 ("if a page becomes available at proof, I would spend it here first") | 두 줄: JetPack/L4T, PyTorch/CUDA/gRPC 버전, `nvpmodel`/`jetson_clocks` 전력 모드, LAN 속도, 아티팩트 진술. 두 심사자 모두 전력 모드는 측정치가 아니라 **저자가 여전히 보유한 설정 사실**임을 강조한다. |
| **J10** | Eqs. (1)–(2)가 구체화하는 RAID-5/6 계보가 여전히 명시되지 않았고, 정정으로 열린 신규성 절도 여전히 작성되지 않았다 | `sections/`에 대한 `grep -niE "raid\|evenodd\|rdp"`는 GhostServe 서술에서만 걸린다; §II-E는 여전히 "\sys{} applies the same idea to the KV state of a pipeline"으로 끝난다 | R2-C-2 · R3-MAJOR-7 · DA-N8 (3인) | 절 두 개. R2는 두 번째 절을 세 라운드 동안 5에 묶여 있는 "the cheapest available raise to my Novelty score"라고 부른다: 저장된 KV 바이트는 **정확한(exact)** 선형 부호를 허용하는 반면, 예측 서빙은 학습된 근사만을 허용하였다. |
| **J11** | "two to three decode steps"가 논문 자신의 2.1–3.9×에 반하여 유보 없이 살아남았다 | `abstract.tex` L15–16, `discussion.tex` L142, 이에 반해 `evaluation.tex` L185–187 "$2.1$–$3.9\times$ for every $P$ and **both victims**" (3.9×는 네 스텝) | R1-M14(c) · R2-N3-6/m-5 · R3-NEW-D · DA-NEW-5 · R0-item 39 (*밀어붙이지 않음*) | "two to four"로 쓰거나 1차 피해자 스윕으로 범위를 한정한다. 충돌 **A2** 참조 — 미적용 목록에서 조용히 누락된 점이 더 큰 과실이다. |
| **J12** | `rashmi2016eccache`에는 DOI도 페이지도 없는데 응답서는 "DOIs added"라고 보고한다 | `references.bib` L338–343 | R0-M3 · R3-item 22 · DA-N8 · R2 (OSDI 항목은 흔히 DOI가 없음을 지적) | 한 줄, 또는 응답서의 한 단어("three of four"). |
| **J13** | 40-cap 그리드는 비균일한데 산문은 규칙적 스윕처럼 읽힌다 | `evaluation.tex` L300–302 "over 40 caps from 0.2 to 23 GB"; 실제 사다리는 상단에서 4 000 MB 간격, **보고된 4.6/4.8 경계에서는 정확히 200 MB 간격**, 하단에서는 50 MB 간격이다 | R1-M10 · R0-W5 잔여 · DA-NEW-6 (3인) | 여섯 단어: "a non-uniform ladder densened to 0.2 GB near the threshold". 구간 설정 자체는 정당하다; 정당하지 않은 것은 그것을 어떻게 찾았는지에 대한 서술이다. |
| **J14** | §I ¶1의 용량 전제가 §IV-A의 양보와 끝내 조정되지 않았다 | `introduction.tex` L15 "KV cache **can exceed the memory of a single edge device**" 대 `evaluation.tex` L27–29 "either AGX Orin could, so on this fleet the pipeline is the scheduler's throughput choice" | R3-NEW-6 · DA-C8 (2인) | §I에 한 절. 로드맵 27은 두 지점을 모두 지목했으나 평가 쪽만 작성되었다. |
| **J15** | 수정된 163/183 분리의 7B 대응 쌍은 모호한 채로 남았고, 500 ms는 493.4를 반올림한 값이다 | `evaluation.tex` L41 "500 ms at 7B" (유효 60 시행에 대해 493.4–499.65 ms로 재계산) 대 L353 "527 ms" protection-off; §IV-G의 파생값 "0.89 steps/position"이 그 반올림을 물려받는다(참값 0.91) | R0-N12 · DA-NEW-8 (2인; R2-m-5는 *정합적*이라고 봄, **A4** 참조) | 7B에도 동일한 두-값 명명을 적용하고, 493 ms 또는 "about 500 ms"로 인쇄한다. 두 심사자 모두 이 반올림이 저자에게 **불리하게** 작용함을 지적한다. |

---

## 3. 단일 심사자 제기이나 조치할 가치가 있는 잔여 결함

| # | 결함 | 위치 | 심사자 | 최소 수정 |
|---|---|---|---|---|
| **S1** | **"496 rejected *solely* because no peer could reserve the backup weights"**는 계측이 뒷받침할 수 없는 귀속이다. `scheduler.py:403-416`은 `NoFeasibleSolutionError`와 `NoRecoveryError`를 하나의 핸들러에서 잡고, 세 번째의 조용한 `continue`에서 비유한(non-finite) 목적값을 버리며, `feasible_count`만을 센다; 496 = 1950 − 1454는 세 원인의 잔여값이다. **최소 12건은 다른 원인임이 증명 가능하다**: `per_layer_bytes` = 406 953 984 → 32 layers = 12.13 GiB이고 가장 큰 Nano 쌍(`on-1`+`on-6`)은 11.32 GiB를 보유하므로, $P(4,2)=12$개의 순서 있는 두-Nano 부분집합 전부가 백업을 고려하기도 전에 **활성(active)** 용량에서 실패한다 | `evaluation.tex` L296–299 — **§IV-E의 유일한 실측 데이터** | **DA-NEW-3 (CRITICAL)** | "solely"를 삭제한다: "496 were rejected as infeasible, the backup reservation among the causes." 선택적으로 원인별 카운터를 복원하여 재유도한다 — 이는 저장된 프로파일에 대한 **오프라인** 솔버 재실행이므로 폐쇄된 테스트베드는 변명이 되지 않는다. §5 참조. |
| **S2** | 새로 추가된 트래픽 양보가 범위 한정 없이 서술되어, 두 소절 앞의 §IV-B와 모순된다 | `evaluation.tex` L217–218 "Parity and replication ship the same KV columns from the workers, so their difference is coordinator memory, not traffic" 대 L163–164 "\sys{} first fetches the four surviving columns from their workers, **four RPC round trips**" — DejaVu가 지불하지 않는 트래픽이며, 장애 경로에서 프리픽스에 비례해 증가한다 | **R2-N3-3 (차단 사유 #3)** | 네 단어: "…ship the same KV columns **during failure-free decoding**, so their steady-state difference is coordinator memory, not traffic; the parity path additionally fetches the surviving columns at recovery." |
| **S3** | KV-CARE 자신의 **보유 입력(retained-input) 회계**가 두 가지로 진술되어 있으며, 대표 수치 3.7×가 그중 어느 쪽이 참인지에 의존한다. 이 지표는 Petals에 위치별 스테이지 입력 40 kB/tok을 부과한다; §III-B는 KV-CARE의 사다리가 "from **the retained stage inputs**"로부터 replay한다고 말한다; §III-A는 코디네이터가 "**the current position**"(단수)의 입력 활성값을 보유한다고 말한다 | `design.tex` §III-A/§III-B, 변경 없음; `evaluation.tex` Table I | **R3-NEW-4** — R2에서 제기되었으나 **패널이 한 번도 접수(docket)하지 않았다** | 어느 방향으로든 한 문장. R3는 이를 K4와 정확히 구분한다: K4의 2.7×는 $(\Sigma\ell-\ell_{\text{tail}})/\ell_{\max}=304/112$로 스테이지 커버리지 보정이다; 이 경로는 $416/152$를 주는데 — 다른 유도로 같은 수가 나오기에 혼동이 쉬웠다. 패널은 나쁜 쪽 분기를 가정해서는 안 된다: **저자에게 명시하도록 요청한다.** |
| **S4** | Table I의 주석은 어떤 지점이 "**not measured**"라고 말하지만, 저자 자신의 로그는 시도되었다가 폐기되었다고 기록한다 | Table I 주석 "not measured at $P{=}32$"; `b1_ft_fleet_7b_reactive_log_20260901.json`은 `n_valid: 2`와 `invalid: {"16": "survivor worker socket closed mid re-solve", "24": "boot not ready…", "32": "boot not ready…"}`를 기록한다 — **다섯 Reconfigure 지점 중 셋이 사유와 함께 시도·폐기되었으며**, 그 베이스라인의 439 s는 "minutes"로 인용되고 있다 | **DA-M7** (R1-M11은 일반적 회계를 요구하고, DA는 그 사례를 지목함) | "not measured"를 로그 자신의 표현으로 대체한다. 이것만으로 제외 회계 요구(로드맵 21)의 가장 값싼 절반이 한 절로 해소된다. |
| **S5** | "a per-position **spread** of 0.03–0.23 s"는 사실 위치별 **표준편차**이다 | `evaluation.tex` L156–157. R1이 유효한 parity 시행 15건으로부터 재계산: spread(max−min) = $P=8,16,24,32,4$에서 각각 0.053, 0.223, 0.154, 0.173, **0.443** s; SD = 0.027, 0.126, 0.077, 0.088, 0.231 s. 인쇄된 범위는 $P{=}4$에서 시행 간 범위를 약 2× 축소해 말한다 | **R1-NEW-9** | "standard deviation"으로 라벨을 고치거나 0.05–0.44 s를 인용한다. |
| **S6** | 복원된 교차 스케일 쌍 "1.6–1.9"가 재현되지 않는다 | `evaluation.tex` L376. R1: 유효한 350M parity 시행 5건은 0.282–0.316 s → 논문 자신의 163 ms 스텝 기준 **1.73–1.93**(183 ms 기준 1.54–1.73). 이 쌍은 Round-1 이전 본문에서 복원되었을 뿐, 이번 라운드가 도입한 decode-step 정의 아래에서 재계산되지 않았다 | **R1-NEW-10** | 1.7–1.9로 인쇄한다. |
| **S7** | ±11 %가 인용되었으나, 비보호 베이스라인 자신의 라운드 간 SD가 파일에 있으며 2.6 %이다 | abstract L22–24 / `discussion.tex` L134–135; `protection_off.throughput_tokens_per_sec_sample_std` $=0.0492/1.9249=2.6\%$ | **DA-N7** | 한 절, 또는 비교 자체를 삭제. "Quoting 11 % where the measured baseline spread is 2.6 % still flatters the null." |
| **S8** | 보호 비용 결과에 대한 MDE가 없다 | `evaluation.tex` §IV-F. $n=3$에서 95 % 구간은 $\pm t_2\cdot10.7/\sqrt3=\pm26\%$이며, 20 % 보호 비용은 배제 불가능하다 | **R1-M4** | 한 절. 저자가 더 어려운 절반("these figures bound the cost rather than rank the modes")을 *자발적으로* 내놓았고 심사자 4인이 이를 인정함을 부기한다. |
| **S9** | 중재 **C2**가 삭제된 `fig_storage_tolerance`의 대가로 대체하도록 한 $k$의 이득 행이 끝내 추가되지 않았다 | Table I은 State 열(416 / 112 / 224 kB/tok)만 담고 있다; 내성(tolerance) 행이나 열이 없고, replication 자신의 내성도 전혀 진술되지 않는다 | **R3-MAJOR-7** | Table I에 인접한 한 행: 보유 바이트 대비 허용 가능한 동시 장애 수. 중재는 그 그림의 삭제를 **이것과 교환하여** 허용하였다; 거래의 절반이 미지급 상태이다. |
| **S10** | 저널 적합성: **34편 중 IEEE IoT-J 항목 1편**, TII 항목 5편은 §I 동기 부여에만 사용, 해당 저널의 엣지 신뢰성/중복 배치 문헌에 대한 §II의 관여 없음 | `references.bib`; §II | **R0** — "I would make that a condition of acceptance … the difference between a paper that belongs here and a systems paper that happened to be submitted here" | §II 문단 2–3개. 세 라운드에 걸친 성실한 개정이 **아무런 변화도 만들지 못한** 유일한 차원이다(C1이 6, 6, 6으로 고정). 지면을 어디서 확보할지는 충돌 **A5** 참조. |
| **S11** | §IV-F의 두 번째 범위 외 선언이, 자신의 비용이 곧 네트워크 트래픽인 바로 그 소절에 살아남아 있다 | `evaluation.tex` L365–366 "Network traffic itself is not an evaluation axis in this paper" | **R3-CRITICAL-1 잔여** | 해당 문장을 삭제한다; §V-A의 "Network traffic and per-token energy were not measured"가 이제 이를 포괄한다. |
| **S12** | §IV-E는 지표 절이 약속한 12.4 GiB를 끝내 전달받지 못한다 | `evaluation.tex` 지표 절 "…are accounted in Recovery Feasibility, not here", 이에 반해 §IV-E L331–334 | **DA-C1 잔여** | §IV-E에 한 문장: 그 바이트 총량을 수령하고 DejaVu도 동일한 예약을 지불함을 진술한다. |
| **S13** | 승격 이후 rank($s$) 상속이 여전히 정의되지 않아, 장애 이전 $Q$ 항목의 유효성이 미결이다 | `design.tex` §III-D; L77의 $a_s=g^{\operatorname{rank}(s)}$ — 재랭킹은 기존 $Q$ 전체를 조용히 무효화한다 | **R2-M-8** (미적용으로 선언됨, 항목 30) | 한 문장. 테스트베드도 지면도 필요 없다. |

---

## 4. 응답서 대 파일 대조 결과

**대표적 결과는 명확하며 패널이 만장일치로 기록한다: 어떤 심사자도 Round-2 유형의 허위 진술을 발견하지 못했다.** R0는 15개 MUST-FIX 행 전부와 두 종결 목록, 마무리 문장을 절 단위로 확인하였다; R1은 §§1–8과 새 Round-2 블록을 확인하였다; R2는 신규 15행과 미적용 목록을 확인하였다; R3는 MUST 15행과 SHOULD 16절을 확인하였다; DA는 모든 절을 파일과 대조하였다. Round-2의 허위 진술 네 건(L1–L4)은 **해당 위치에서 실명으로 철회되었다** — §1은 이제 "Conclusion: not changed in Round 1 (the panel caught this); rewritten in Round 2"라고 적고, §8은 코디네이터 관련 문장이 "was already in the submitted version and is unchanged"임을 인정한다. R2: "the letter is now a document an editor can read alongside the files without being misled." R3: "the letter is now a usable verification instrument. That is a material change in how I read this submission." **이를 판정서에 기록한다.**

남은 사항은 다음과 같다:

| # | 응답서 문구 | 검증 결과 | 발견자 |
|---|---|---|---|
| **L1** | 항목 14: "'within two standard errors of zero'" | **이번 라운드의 유일한 허위 문구.** k=2 절반은 정직하다(1.07 SE, R1과 DA가 검증); DejaVu 절반은 저자 자신의 피팅이 반박하는 바를 진술한다(2.038 SE). | **DA §4 ("HALF FALSE")** · R1-NEW-8 |
| **L2** | 서두: "**All fifteen MUST-FIX items** … are applied below" | **참이나 완전성을 과장한다.** 항목 1은 7 중 6이고(J1), 항목 7은 절반이며(5-worker 주석 부재), 항목 13은 모순을 도입한다(J2). R0: "it is fourteen and a half … the completeness claim should be accurate, because that is precisely what this round was convened to check." | **R0-M1** · R2 §2 · DA §4 |
| **L3** | 적용 목록 18: "**growth stated**" | **방향에 대해서는 참이나 상한에 대해서는 아니다.** "grows with the number of ordered subsets"는 재진술일 뿐이며, 로드맵은 증가를 수치로, 그리고 측정된 solve 시간을 요구했다. 둘 다 논문에 없다 — 게다가 DA가 저자 자신의 `REPORT.md`에서 solve 시간(122 s)을 찾아냈다. | **R0-M2** · R3 §2 · DA-M9 |
| **L4** | SHOULD-22: "**DOIs added**" | **넷 중 셋.** `rashmi2016eccache`에는 DOI도 페이지도 없고, `kosaian2019parity`에는 페이지가 없다. R2의 독립적 필드 감사는 다섯 항목 어디에서도 **잘못된 필드를 찾지 못했으며**, DOI는 제작 부서가 기계적으로 해결할 것을 권고한다. | **R0-M3** · R3 §2 · DA-N8 · R2 bib 감사 |
| **L5** | 13행: "R defined over every stage, the head included" | **구현에 대해서는 참이나 파일에 대해서는 거짓.** `recovery_table.py:97-102`(주 스테이지가 없는 장치만 건너뜀), 실측 7B 표(`REPORT.md:818`, head `on-6` 백업됨), `build_execution_plan`에서 검증되었다. 원고는 `design.tex` L31에서 이를 반박한다. 응답서 자신의 괄호 안 근거가 바로 원고에 필요하지만 빠져 있는 문장이다. | **R1 §2** · **R2 13행** · DA §4 |
| **L6** | SHOULD-19: fidelity | **건너뛴 하위 항목이 적용됨으로 기재되었다.** 상대 오차 절반은 적용되지 않았고 **미적용 목록에도 없다**. | **R1 §2** |
| **L7** | 미적용 목록 (17, 20, 21, 25, 30, 31, 34, 38, 41) | **MUST/SHOULD에 대해서는 정확하고 완전하다** — R1, R2, R3, DA가 각각 파일과 대조 검증하였다. **다만 3–4개 항목이 빠져 있다**: 로드맵 39("two to four"), 42(삭제된 유보 문구 복원), K22의 RAID 계보, K5의 5-worker 주석. 이 목록은 망라적이어야 한다. | R3 §2 · DA §4 · R1 §2 |
| **L8** | 제시된 사유: "no data without the testbed, or out of page budget" | **최소 네 항목에 대해서는 무리한 주장이다.** 항목 20(전력 모드/버전)과 21(제외 회계)은 저자가 보유한 사실과 로그에 대한 책상 작업이고; 30(rank 상속)은 설계 문제이며; 41(분해된 시행의 명명)은 R1과 DA가 둘 다 읽은 로그 안에 있다. R1: "no data"가 아니라 "**deferred for space**"라고 쓰라. | **R1 §2** · **R0 §2** |

**편집 부기.** 응답서에 남은 과실은 Round 2와는 다른, 훨씬 작은 종류이다: *변경 서술*이 아니라 *범위 주장*의 문제이다. 응답서가 서술하는 모든 변경은, 응답서가 사용한 그 표현 그대로 파일 안에 있다(R0). 저자는 L1–L4를 정정하고 L7을 완성해야 한다 — 이 패널은 이제 두 편의 응답서를 절 단위로 감사했으며, 이 작업의 가치가 범위 주장이 변경 서술만큼 정확한지에 달려 있다는 R0의 지적은 옳다.

---

## 5. Devil's Advocate CRITICAL 판정

모든 DA CRITICAL을 가시적으로 판정한다. C4는 R2에서 해소되었으며 재개하지 않는다.

| DA 항목 | DA의 R3 상태 | 보강 / 반박 | **판정** |
|---|---|---|---|
| **C1** — 풋프린트가 12.4 GiB 백업 가중치를 제외함 | PARTIAL; **DA가 자신의 Round-2 산술 이의를 철회한다**: "the implementation does back up the head and the number was right", `recovery_table.py`와 실측 표에서 검증됨 | R1-NEW-7, R2, R3-MAJOR-2 모두 12.4 GiB가 전체 모델이며 올바른 분기가 선택되었음을 확인 | **수치에 관해서는 해소.** 지표 수정과 헤드 비용 부과는 5인 전원이 수용하며, 그 부과는 저자에게 *불리하게* 작용한다(Eq. (mem)을 엄격하게 하고 Table III의 대역을 이동시킨다). 두 잔여 사항은 다른 곳에 재접수되었다: 표기법 모순은 **J2 (MUST)**, §IV-E가 바이트 총량을 수령하지 못하는 문제는 **S12 (SHOULD)**. DA의 자기 정정을 기록한다. |
| **C2** — Θ(N) 루프에 대한 "flat in P" | 결론 절반은 **해소**; **노이즈 절반은 악화** | R0, R1, R2, R3 모두 결론 절반을 해소로 채점하고 k=2 격차를 1.07 SE(정직함)로 독립 재현. R1은 DejaVu 기울기를 2.04 SE로 독립 계산 | **노이즈 절반을 MUST-FIX로 인용(J3); 결론 절반은 해소.** k=2 절편에 대해 이행된 수정은 정확하며, 차이의 SE가 인쇄되지 않았다는 점에서만 미흡하다. DejaVu 절은 원고의 유일한 허위 파생 수치이며, 두 문단 위의 *정확한* 12 ms 2-SE 상한을 훼손한다 — DA: "a reader who checks one 2-SE claim and finds it false has no reason to trust the other." |
| **C3** — 계약 게이트에 조건부인 지연시간 | **DA가 철회**: "exactly the six-word fix asked for" | R1-M7, R2 5행, R3-CRITICAL-3 모두 `abstract.tex` L24를 검증 | **해소.** 잔여는 표면적이고 단일 심사자 사안이다: 초록에는 있는 계약 유보가 §V-B의 마무리 문장에는 없다(R3-CRITICAL-3, 여섯 단어) — 같은 문단이므로 J1의 편집에 함께 접는다. |
| **C5** — Petals에 0 kB/tok을 부여한 점; 지배(domination) 주장 | **해소**, 임계값 잔여 있음 | R0-item 2, R1-C2("a better sentence than the one the editorial asked for"; Table I에 대해 참임을 검증), R2-C-1, R3-MINOR-10 모두 해소로 채점; 4인 모두 2초 경계를 지적 | **차단 항목으로서는 해소; 잔여는 SHOULD-FIX로 하향(J7).** 이는 R2의 MUST-FIX #1이었고 이행되었다. 심사자 4인이 재작성된 문장이 단지 모순되지 않는 데 그치지 않고 Table I에 대해 *참*임을 독립적으로 확인했으며, 생성기 docstring도 함께 수정되었다. 남은 것은 Petals를 저상태(low-state) 종단점으로 명명하는 한 절이며, 이는 정확성 요구가 아니라 프레이밍 요구이고 숨겨진 것은 없다(40 kB는 두 문단 뒤에 인쇄되어 있다). |
| **C6** — Eq. (mem)은 가중치를 예약하는데 초록은 상태를 약속함 | 초록과 §III-E에서는 해소; **결론에서는 아니며 — 이제 자기모순이다** | **다른 심사자 4인 전원이 지목하고 그중 3인이 차단 사유로 든다**: R0-N9, R1-NEW-11, R2-N3-2, R3-NEW-B | **인용, MUST-FIX(J1).** 세 번째로 요청하는 것이며, 다섯 단어이고, 저자가 이번 라운드에 그 외 부분은 재작성한 문단 안에 있다. 패널에서 가장 많이 인용된 단일 항목이다. |
| **C7** — 실현 가능성: 순차 베이스라인, 오프라인 라벨, 이동된 대역 | PARTIAL; 잔여 4건 | 초록의 "offline placement analysis" 라벨은 R0, R1, R2, DA가 검증(로드맵 37 ✓). cap 규칙, 40-cap 그리드, 6-worker 풀은 R0, R1, R2, DA가 각각 독립적으로 `d29_coupling_threshold_20260903.json`과 대조 검증; Table III의 대역은 정확히 재현됨 | **MAJOR 유지; 잔여는 분할된다.** **"solely" 귀속은 이번 라운드 유일의 CRITICAL로 승격된다(아래).** 5-worker 대역 주석은 종결한다(충돌 **A1**). 비균일 그리드는 **J13 (SHOULD)**. 특정 세 절차에 대한 "sequential procedures fail" 프레이밍과 *재시도(retrying)* 베이스라인의 부재(R2-M-7)는 MAJOR이되 차단 사유는 아닌 상태로 남는다: 이제 어떤 테스트베드로도 해결할 수 없다. |
| **C8** — 단일 AGX가 모델 전체를 수용할 수 있었다는 점 | 이전과 같이 PARTIAL; 조정은 평가 쪽에만 작성됨 | R3-NEW-6가 독립적으로: §IV-A의 양보 옆에서 §I ¶1은 변경되지 않음 | **기존 MAJOR를 수용; 잔여는 SHOULD-FIX(J14).** §IV-A의 "either AGX Orin could, so on this fleet the pipeline is the scheduler's throughput choice and capacity binds on the Nanos"는 자발적이고 오히려 강화된 양보이다. §I의 한 절이 로드맵 27을 완결한다. |
| **NEW-3 (신규 CRITICAL)** — "496 rejected **solely** because no peer could reserve the backup weights" | **유일하게 남은 CRITICAL; DA는 자신의 Minor를 이에 조건부로 건다** | **어떤 심사자도 반박하지 않았고, 어떤 심사자도 점검하지 않았다.** R0, R1, R2, R3는 각각 *1 950* 열거와 그에 관한 응답서의 주장을 검증했으나, 496 카운터를 감사한 심사자는 없다. DA의 증거는 코드 수준이자 산술적이다: `NoFeasibleSolutionError` **와** `NoRecoveryError`를 함께 처리하는 하나의 `except` 핸들러, 비유한 목적값에 대한 세 번째의 조용한 `continue`, 유일한 카운터인 `feasible_count`, 496 = 1950 − 1454; 그리고 496 중 12건은 활성 용량에서 실패함이 증명 가능하다(최대 Nano 쌍 11.32 GiB < 레이어 가중치 12.13 GiB). R1-M9(ii)는 인접하나 — *순차적* 절차에 관한 증거로 496이라는 수치가 제시된 점에 이의를 제기하는 것이어서 — 다른 논점이다 | **MUST-FIX #1로 인용.** 두 독립 근거로 자격을 충족한다: 인용된 DA CRITICAL(규칙 b), 그리고 저자 자신의 소스에 대조하여 검증된 사실 오류(규칙 a). 이는 패널이 세 라운드에 걸쳐 철회시켜 온 과잉 귀속의 전형이며, **§IV-E의 유일한 실측 데이터** 위에 놓여 있다 — "the difference between 'we observed the coupling on a live fleet' and 'we simulated it'"라는 DA의 말이 옳다. **두 가지 귀결이 있고, 서로 반대 방향으로 작용한다.** (i) 폐쇄된 테스트베드는 **변명이 되지 않는다**: 원인별 카운터는 저자가 이미 두 번 실행한 *오프라인* 솔버를 저장된 프로파일에 재실행하면 복원된다. (ii) 그 정정은 주장의 강도를 낮추는 **단어 하나의 삭제**이므로, 이를 인용한다고 해서 논문이 Major로 되돌아가지는 **않는다** — §6 참조. 저자는 어느 분기를 택해도 되며, 패널은 재유도를 요구하지 않는다. |

**요약.** 최초 8개 DA CRITICAL 중: **C4는 해소(R2), C1·C3·C5는 잔여를 재접수한 채 해소, C6은 인용되어 MUST-FIX, C2는 노이즈 절반만 인용, C7과 C8은 MAJOR 유지.** 신규 CRITICAL 1건(NEW-3) 인용. DA는 추가로 NEW-1과 NEW-2를 MAJOR로 채점하였고, 둘 다 다른 근거로 여기서 MUST-FIX이다(J3, J2). **DA는 이번 라운드에 8개 항목을 철회하고 자신의 Round-2 오류 하나를 공식적으로 정정하였다** — 패널은 이를 검증이 실제로 수행되었다는 표지로 기록한다.

---

## 6. 판정

### **MINOR REVISION(소폭 수정)** — 1라운드, 편집자 검증. 추가 외부 심사 없음; 정정 사항은 단어 수준이며 각각 grep 한 번과 산술 재계산 한 번으로 확인 가능하다.

**근거.**

*패널이 수렴하였다.* R2의 2 Minor / 2 Major / 1 조건부에 반해, 5인 중 5인이 Minor 이상을 권고한다. Round-2의 Major를 낳았던 두 조건은 해소되었으며, **모든 심사자가 응답서가 아니라 파일에 대조하여 각자 독립적으로 검증하였다**: R0의 항목 1–2(결론, 163/183 충돌, 갱신되지 않은 그림)는 수정되었고 163.3 ms와 183.17 ms는 심사자 4인이 각각 원시 JSON에서 재현하였다; R2는 자신이 조건으로 걸었던 전파 점검을 직접 수행하고 "실질적으로 통과한다"고 보고한다; R3의, 조용히 답변되지 않았던 테스트베드 불요 항목 4건은 이제 수정 1건(MAJOR-8, "the most serious untouched item", 두 절로 종결)과, 명시된 10페이지 결정에 귀속된 명시적이고 정직한 미적용 목록상의 3건으로 정리되었다 — R3는 이를 "a legitimate editorial trade openly made, and categorically different from silence"라고 정당하게 평한다.

*응답서는 더 이상 문제가 아니다.* Round 2의 판정은 원고 못지않게 네 건의 허위 응답서 진술에 좌우되었다. 네 건 모두 해당 위치에서 실명으로 철회되었다. 심사자 5인이 새 응답서를 절 단위로 확인하여 허위 문구 1건(L1, DejaVu 2-SE 절반), 완전성 과장 3건, 미적용 목록 누락 3–4건을 찾아냈다. 이는 종류가 다르고 훨씬 작은 과실이다.

*게재(Accept)를 가로막는 것은 작고 구체적이며 검증된 사항들이다.* 원고의 네 진술이 저자 자신의 파일·코드·로그에 의해 반박된다: DejaVu 기울기의 "within two standard errors"(2.038 SE — J3), 거부된 496개 부분집합에 대한 "solely" 귀속(S1), 세 지점이 시도·폐기되었다고 기록한 로그에 반하는 Table I의 "not measured at P=32"(S4), 그리고 재현되지 않는 작은 통계량 두 건(S5, S6). 여기에 Round-2 편집 자체가 만들어낸 내적 모순 두 건이 더해진다: R의 정의역(J2, 심사자 4인이 차단 사유로 지목)과 결론의 전파되지 않은 weights/state 절(J1, 차단 사유 4인 + DA). 대표 수치 3.7×에 관한 일관성 질문 하나는 두 번 제기되었으나 한 번도 접수되지 않았다(S3). 이런 것들이 남아 있는 원고를 그대로 게재할 수는 없다; 그러나 그 모두가 단어 하나, 절 하나, 기호 하나인 원고에 또 한 번의 Major 라운드는 필요하지 않다.

*반면.* 이 목록의 어느 것도 폐쇄된 테스트베드를 필요로 하지 않고, 어느 것도 지면을 필요로 하지 않는다 — 아래의 모든 MUST-FIX 항목은 기존 문장 내부의 치환이다. 지적 작업은 계속해서 저자 자신의 이익에 반하는 방향으로 진행되었다: 헤드에 12.4 GiB 전량을 부과한 점, $n=3$의 비분리를 자발적으로 밝힌 점("these figures bound the cost rather than rank the modes" — 어떤 심사자도 그런 형태로 요구하지 않은 양보), DejaVu 베이스라인의 중앙집중성을 공개한 점, "four times the bytes" 인과 서사를 방어하지 않고 폐기한 점, 초록에 3.7×와 나란히 2.7×를 실은 점, 뒤바뀐 Reconfigure 짝짓기를 자신의 로그에 대조해 수정한 점이다. DA는 원고의 **모든** 파생 수치를 재계산하여 정확히 하나가 틀렸음을 찾아냈고, R0와 R1도 독립적으로 같은 작업을 수행하여 같은 결과를 얻었다.

**다음 라운드를 위한 검증 지침.** 편집자는 로드맵 항목 1–9를 소스에 직접 대조하여 확인하고, 항목 1, 4, 6에 대해서는 `b1_ft_fleet_7b_rep3.json`, `b1_ft_fleet_7b_reactive_log_20260901.json`, `radp/coordinator/scheduler.py`에 대조하여 확인해야 한다. 어떤 심사자도 재위촉할 필요가 없다.

**의의(Significance) 상한 (기록용, 차단 사유 아님; 세 라운드 동안 불변).** R0는 Significance를 5로, R2는 Novelty를 5로 유지하며, 둘 다 의도적이고 둘 다 변화를 기대하지 않는다고 밝힌다: replication 대비 이득은 예측일 뿐 replication이 감당할 수 없는 구성에서 실증된 적이 없고, 이를 판가름할 실험은 더 이상 수행할 수 없다. R2는 Novelty를 움직일 수 있는 유일한 것을 덧붙이는데 이는 한 절이면 된다 — J10의 정확성(exactness) 논변이다. 두 심사자 모두 그 결과인 상한을 IoT-J로서는 게재 가능한 결과라고 평한다. 세 라운드의 개정이 대신 얻어낸 것은 R2가 명명한 속성이다: "every remaining claim in the paper is one a reader can check against a printed number."

---

## 7. 개정 로드맵 R3

번호를 붙이고 중복을 제거하였으며, 그대로 적용하면 된다. **모든 항목은 저자가 이미 보유한 텍스트, 기호, 숫자이다. 어느 것도 테스트베드를 필요로 하지 않는다. 어느 것도 지면을 필요로 하지 않는다** — MUST-FIX 항목 1–9는 기존 문장 내부의 치환이다.

### MUST-FIX (게재 차단)

1. **`evaluation.tex` L296–299 — "solely"를 삭제.** "496 were rejected as infeasible, **the backup reservation among the causes**"; 카운터는 세 개의 실패 경로에 걸친 `1950 − feasible_count`이다. *(S1 / DA-NEW-3, 인용된 CRITICAL. 선택적 강화 수정: 원인별 카운터를 복원하고 오프라인 솔버를 재실행한다.)*
2. **`discussion.tex` L128–129 — MUST-FIX 4를 전파.** "the recovered **state** has a device to **run** on" → "the failed stage's **weights** have a device to **load** on"; 같은 문단의 실현 가능성 절에 "in an offline placement analysis"를 추가한다. *(J1 — R0-N9, R1-NEW-11, R2-N3-2, R3-NEW-B, DA-C6)*
3. **`design.tex` L8 — R에 고유한 정의역을 부여.** $\mathcal{S}^{+}=\mathcal{S}\cup\{\text{head}\}$로 두고 $R:\mathcal{S}^{+}\!\to\mathcal{D}$로 하되, Eqs. (1)–(3), 패딩 규칙, Alg. 1의 $F\nsubseteq\mathcal{S}$에서 사용되는 패리티 보호 대상 비헤드 스테이지에는 $\mathcal{S}$를 그대로 둔다. *(J2 — R0-N10, R1-NEW-12, R2-N3-1, R3-NEW-A, DA-NEW-2)*
4. **`evaluation.tex` L160–161 — DejaVu 기울기는 2.038 SE이지 "within two"가 아니다.** "about two standard errors from zero, in the one family that does no per-position work, which we read as an unmodelled systematic"라고 쓴다. *(J3 — DA-NEW-1, R1-NEW-8; 원고의 유일한 허위 파생 수치)*
5. **`evaluation.tex` L217–218 — 트래픽 양보의 범위를 한정.** "…ship the same KV columns **during failure-free decoding**, so their steady-state difference is coordinator memory, not traffic; the parity path additionally fetches the surviving columns at recovery." *(S2 — R2-N3-3; 그렇지 않으면 L163–164와 모순된다)*
6. **`evaluation.tex` Table I 주석 — "not measured at $P{=}32$"는 로그와 모순된다.** 로그 자신의 표현을 사용한다: $P=16, 24, 32$에서 시도되었고 폐기됨(survivor socket closed mid re-solve; boot not ready). *(S4 — DA-M7; 로드맵 21의 가장 값싼 절반도 함께 해소된다)*
7. **`design.tex` §III-A/§III-B — KV-CARE의 보유 입력 회계를 확정**하되, 어느 방향이든 무방하다: 위치별 스테이지 입력을 보유하는 쪽(Table I의 해당 행은 152 kB/tok이 된다)이거나, 한 위치만 보유하는 쪽(그리고 §III-B의 폴백 사다리 표현을 정정한다). 초록의 3.7×가 그 답에 의존한다. *(S3 — R3-NEW-4, 두 번 제기되었으나 한 번도 접수되지 않음)*
8. **`evaluation.tex` L134–135 — 각주 (b)가 잘못된 산출물을 근거로 든다.** "byte identity **asserted in unit tests** (§IV-D)" — fidelity 프로브는 replay 경로에서 26.9 % 불일치를 측정하였다. *(J4 — R0-N11, R2-N3-5; 이 변경은 주석을 약화시키는 것이 아니라 강화한다)*
9. **`evaluation.tex` L156–157 및 L376 — 재현되지 않는 통계량 두 건.** "per-position spread 0.03–0.23 s"는 SD이다(spread는 0.05–0.44 s); 복원된 "1.6–1.9"는 이번 라운드 자신의 decode-step 정의 아래에서 **1.7–1.9**로 재계산된다. *(S5, S6 — R1-NEW-9, R1-NEW-10)*

### SHOULD-FIX

10. **`docs/paper/response_to_reviewers_*.md`** — L1(항목 14의 DejaVu 절은 거짓), L2("fourteen and a half of fifteen"), L3("growth stated" → 방향에 불과), L4("three of four DOIs")를 정정한다; 미적용 목록에 로드맵 39, 42, RAID 계보, K5 주석을 추가한다; 항목 20, 21, 30, 41에 대해 "no data without the testbed"를 "deferred for space"로 바꾼다. *(§4 — 5인 전원)*
11. **`design.tex` §III-E + `evaluation.tex` §IV-E** — solve는 **122 s**(`experiments/REPORT.md:812`)이고 열거는 $\sum_{k=2}^{|\mathcal{D}|}P(|\mathcal{D}|,k)$이다: 6개 장치에서 1 950, 10개에서 ≈9.8 M. *(J5 — 5인 전원; DA가 숫자를 찾아냄)*
12. **`evaluation.tex` §IV-C + §IV-A** — 한 절: "Petals is the low-state endpoint at 40 kB/tok and 2.3 s", 그리하여 프론티어가 이기기 위해 선택된 경계가 아니라 자신감으로 읽히게 한다. *(J7 — R0-N13, R2-N3-4, R3-NEW-C, DA-C5)*
13. **`design.tex` §III-F / `evaluation.tex` §IV-A — 환경 문단.** JetPack/L4T, PyTorch/CUDA/gRPC 버전, `nvpmodel`/`jetson_clocks` 전력 모드, LAN 속도, 아티팩트 진술. 두 줄이며, 모두 저자가 여전히 보유한 설정 사실이다. *(J9 — R1-m22와 R3-MINOR-1이 각각 자신의 최우선 비차단 요청으로 지목)*
14. **`related.tex` §II-E** — Eqs. (1)–(2)가 구체화하는 RAID-5/RAID-6(EVENODD/RDP) 계보를 명시하고, 정정된 Parity Models 표현이 열어준 신규성 절을 추가한다: 저장된 KV 바이트는 **정확한** 선형 부호를 허용하는 반면 예측 서빙은 학습된 근사만을 허용하였다. *(J10 — R2-C-2, R3-MAJOR-7, DA-N8; R2는 두 번째 절을 Novelty를 올릴 가장 값싼 수단이라 부른다)*
15. **`evaluation.tex` Table II** — $2^{-8}$ 절대값 옆에 상대 오차를 넣거나, 미적용 목록에 한 줄을 추가한다. *(J6 — R1-M8, R2-M-5, R3-MAJOR-9, DA-M6)*
16. **`evaluation.tex` §IV-C, §IV-A, Table III** — "kB denotes 1 024 bytes" 선언을 Table I 주석 밖으로 옮기고 MB/MiB 값까지 확장한다; 현재 세 가지 관례가 공존한다. *(J8 — R0-W14, R1-m18, R2-m-3, R3-MINOR-7)*
17. **`evaluation.tex` L300–302** — 40-cap 사다리가 **비균일**하며 보고된 경계 부근에서 0.2 GB로 조밀해진다고 밝힌다. *(J13 — R1-M10, R0-W5, DA-NEW-6)*
18. **`abstract.tex` L15–16 + `discussion.tex` L142** — "two to three decode steps" → "two to **four**", 또는 1차 피해자 스윕으로 범위를 한정한다. *(J11 — R1, R2, R3, DA; 충돌 **A2**)*
19. **`introduction.tex` ¶1** — 용량 전제를 §IV-A의 "either AGX Orin could"와 조정하는 한 절. *(J14 — R3-NEW-6, DA-C8; 로드맵 27을 완결)*
20. **`evaluation.tex` L41 / L353** — 163/183의 두-값 명명을 7B 대응 쌍(500 대 527 ms)에 적용하고 **493 ms** 또는 "about 500 ms"로 인쇄한다. *(J15 — R0-N12, DA-NEW-8; 충돌 **A4**)*
21. **`references.bib`** — `rashmi2016eccache`에 DOI와 페이지; `kosaian2019parity`에 페이지. R2의 필드 감사는 잘못된 필드를 찾지 못했다; 다섯 항목 전부를 제작 부서가 기계적으로 해결하도록 한다. *(J12 — R0-M3, R2, R3, DA-N8)*
22. **`evaluation.tex` Table I (인접 행)** — $k$의 이득: 보유 바이트(416 / 112 / 224 kB/tok) 대비 허용 가능한 동시 장애 수, 그리고 replication 자신의 내성. 이는 `fig_storage_tolerance` 삭제와 교환된 중재 **C2**의 절반이며 미지급 상태로 남아 있다. *(S9 — R3-MAJOR-7)*
23. **`evaluation.tex` §IV-F** — 살아남은 "Network traffic itself is not an evaluation axis in this paper"를 삭제한다; 이제 §V-A의 한계 진술이 이를 포괄한다. *(S11 — R3-CRITICAL-1)*
24. **`related.tex` §II + `references.bib`** — 교차 스테이지 패리티를 IoT-J가 직접 게재하는 엣지 서비스 내결함성 및 중복 배치 문헌 속에 위치시키는 문단 2–3개. 34편 중 IoT-J 항목 1편은 편집자가 제기할 수 있는 유일하게 남은 범위상의 이의이다. *(S10 — R0, "a condition of acceptance"; 충돌 **A5**)*
25. **`design.tex` §III-D** — 승격된 백업이 rank($s$)를 상속하는지, 그리고 장애 이전 $Q$ 항목은 어떻게 되는지에 대한 한 문장. 설계 문제이며 테스트베드도 지면도 필요 없다. *(S13 — R2-M-8)*
26. **`evaluation.tex` §IV-E** — 지표 절이 약속한 12.4 GiB를 수령하고 DejaVu도 동일한 예약을 지불함을 진술하는 한 문장. *(S12 — DA-C1 잔여)*

### OPTIONAL

27. `evaluation.tex` §IV-F — MDE: $n=3$에서 95 % 구간은 ±26 %이므로 20 % 보호 비용은 배제 불가능하다. *(S8 — R1-M4)*
28. `abstract.tex` / `discussion.tex` — 인용된 ±11 %에 비해 비보호 베이스라인 자신의 라운드 간 SD가 2.6 %임을 부기한다. *(S7 — DA-N7)*
29. `evaluation.tex` §IV-A — 완전한 제외 회계: 셀별 시도 대비 보고된 시행 수, 게이트별 폐기 수. 위 로드맵 항목 6이 구체적 사례를 다루며, 이것은 그 일반형이다. *(R1-M11, DA-M7)*
30. `evaluation.tex` §IV-A — "one injection mechanism" 주장이 제기되는 지점(L54–55)에서 주입 예외를 진술한다. 24줄 뒤가 아니다. *(R1-C3(c))*
31. `evaluation.tex` §IV-E — 7B "whole fleet"의 구성원을 정의하고 `on-3`/`on-4`를 명시한다. *(R1-M10, R0-item 26)*
32. `discussion.tex` — 삭제된 유보 문구 "the case the recovery contract is designed for"를 복원한다(로드맵 42, 조용히 누락됨); §V-B의 마무리 문장이 초록의 계약 유보를 받도록 한다. *(R1-M7, R3-CRITICAL-3)*
33. `evaluation.tex` §IV-B — ~1.2 s 절편의 freeze/fetch/decode/install/promote 분해와, 그로부터 함의되는 왕복당 ~70 ms. 측정이 아니라 로깅 변경이다. *(R2-M-6, R3-MAJOR-3, DA-M11)*
34. `main.tex` — `background.tex`에서 다듬은 동작 범위(operating-envelope) 표를 `\input`하거나, **고아 파일을 삭제**한다. 심사자 3인이 그 파일이 여전히 디스크에 있고 `\input`되지 않았음을 지적한다. *(R2-m-1, R3-MINOR-5, DA-N9)*
35. `abstract.tex` — 258–260 단어를 250 미만으로 줄인다(로드맵 36, 미적용); 확보된 줄은 항목 13 또는 24에 쓴다. *(R0-W17, R1-item 36)*
36. `evaluation.tex` §IV-C / `discussion.tex` — GQA/INT4 일반성 산술; `design.tex` §III-E — $\rho$에 $\ell_{\max}$ 항; `evaluation.tex` §IV-A — 코디네이터 용량 및 가용성 산술. 세 가지 모두 **선언된** 지면 예산상의 포기이다(항목 31, 34, 17); R0와 R3 모두 이들을 Significance와 Practical impact를 움직일 항목으로 기록한다. *(R3-MAJOR-4/-11/-1, R0-C3)*

---

## 심사자 간 충돌 중재

**A1 — 5-worker 6.5 GB의 출처(로드맵 7의 두 번째 절): "여전히 미해소" 대 "이제는 정오표를 낼 가치가 없음".**
R2-NEW-7은 이를 미해소로 채점하고("item 7's second clause unfilled"), DA-NEW-7은 심사자 4인이 요청했으나 여전히 응답서에만 있음을 지적한다. 반면 R0-M1은 밀어붙이기를 거부한다 — "an unpublished draft's superseded number needs no erratum, and the printed band is the one the six-worker artifact supports"; R1-NEW-6은 "since the 6.5 GB band was never published"를 이유로 해소로 채점하고; R3-NEW-7은 풀과 그리드가 이제 완전히 명세되었다는 이유로 이를 "from a verification concern to a nit"로 명시적으로 하향한다. **결정: 종결한다.** Round 2에서 이를 제기한 4인 중 3인이 동일한 논거로 철회 또는 하향하였고, 그 수치는 독자에게 도달한 적이 없다. 남는 것은 원고의 과실이 아니라 *응답서*의 과실이다: 응답서는 항목 7이 완전히 적용된 것처럼 시사하기를 멈춰야 한다(로드맵 항목 10). MUST와 SHOULD에서 완전히 제외한다.

**A2 — "two to three decode steps": 밀어붙일 것인가 말 것인가.**
R0는 항목 39를 미해소로 채점한 뒤 "Optional in the roadmap; I do not press it"이라 말하며, §IV-B가 조정하는 범위 문장을 추가했음을 지적한다. R3-NEW-D는 다른 여섯 유보가 들어온 지금 이것을 "the only place where the summary sentences round in the paper's favour"라고 부른다. R1-M14(c), R2-N3-6, DA-NEW-5는 모두 미해결로 열거한다. **결정: SHOULD-FIX(항목 18), 그리고 실제 과실은 절차적인 것이다.** 실질적 간극은 단어 하나이다. 그러나 R3와 DA 모두 이것이 *적용되지도, 포기로 목록에 오르지도 않았음*을 지적하며 — 로드맵 42도 마찬가지이다. 미적용 목록은 망라적일 때에만 검증 도구가 되며, 그렇기에 응답서 정정(항목 10)이 여기서는 본문 편집만큼의 무게를 지닌다.

**A3 — R의 정의역: 기호를 넓힐 것인가, 숫자를 줄일 것인가.**
R0, R1, R2, DA는 모두 넓히자고 한다($\mathcal{S}^{+}$ / $\mathcal{S}_{\mathrm{all}}$). R3-NEW-A는 대안을 제시한다: "drop 'the head included' and use ~10.1 GiB in §IV-A". **결정: 기호를 넓힌다.** R2와 DA는 각각 구현에 대조하여(`recovery_table.py:97-102`는 주 스테이지가 없는 장치만 건너뛴다; 실측 7B 표는 head `on-6`을 백업한다; 헤드 제외는 `gateway.py:971`의 KV 패리티에만 존재한다) 시스템이 헤드를 **실제로** 백업함을 검증하였으므로, 12.4 GiB가 코드가 뒷받침하는 수치이며 R3의 대안은 코드와 모순되는 수치를 인쇄하게 된다. 같은 편집에서 R2의 보완도 함께 반영한다 — 응답서 자신의 근거를 논문에 넣는 것이다: 헤드의 가중치는 사전 적재되어 있어 헤드 장애가 요청 상실이 아니라 생존 워커에서의 전체 프리픽스 replay로 저하되지만, 그 KV는 패리티로 보호되지 않는다. 이는 DA-NEW-2의 이차적 논점(§III-B가 보장 밖에 두는 스테이지에 왜 ~2.3 GiB가 예약되는가)도 함께 해소하며, 그렇지 않으면 이 점은 설명되지 않은 채 남는다.

**A4 — 7B에서의 500 대 527 ms: 결함인가, 이미 정합적인가.**
R2-m-5는 7B 쪽이 "now coherent by the same construction"이라고 본다 — L38–39가 decode step을 스윕의 중앙값으로 정의하고 L353의 527 ms는 protection-off 실행이므로 오류는 없다는 것이다. DA-NEW-8과 R0-N12는 둘 다, 163 ≠ 183을 방금 배운 독자는 500 대 527에 대해 물을 것이고 답을 찾지 못한다고 말하며, R0는 500이 493.4의 반올림이고 그 1.3 % 편차가 §IV-G의 0.89로 전파된다고 덧붙인다. **결정: MUST가 아니라 SHOULD-FIX(항목 20).** *틀린* 것은 없다는 R2가 옳고, 저자가 350M에 방금 적용한 수정을 그 쌍둥이에 적용하지 않았다는 나머지 둘도 옳다 — J1, J2와 동일한 실패 양상이 한 단계 아래에서 반복된 것이다. 그 반올림이 저자에게 **불리하게** 작용함을(0.91이 저자 자신의 "about one decode step" 주장에 더 가깝다) 부기한다. 따라서 이는 부풀리기가 아니라 정밀도 공개의 문제이다.

**A5 — 지면이 생긴다면 어디에 쓸 것인가.**
R0는 IoT-J 자신의 엣지 신뢰성 문헌에 관한 §II 문단 2–3개를 "a condition of acceptance"로 삼는다 — 세 라운드 동안 아무런 변화도 없었던 유일한 차원이다. R3는 "if a page becomes available at proof, I would spend it on item 20's environment paragraph before anything else"라고 말한다. **결정: 실질적 충돌 없음 — 둘 다 수용 가능하다.** 환경 문단은 두 줄이고(항목 13), §II 문단들은 대략 지면의 3분의 2이다(항목 24). 로드맵 항목 35는 저자가 이미 동의한 공간을 회수하며(초록 258–260 → 250 미만, 로드맵 36 미적용), 항목 23과 34는 죽은 구절 두 개를 제거한다. 둘 다 SHOULD-FIX이며, 저자가 선언한 10페이지 트레이드에 반하여 패널이 어느 쪽도 요구하지는 않는다. 다만 R0의 논점은 그 자체로 유효하다: 이는 편집자가 범위를 이유로 게재를 거절할 수 있는 유일하게 남은 근거이며, 비용은 반나절이다.

---

*편집 종합자(Editorial Synthesizer) 작성. 위의 모든 항목은 명시된 심사자 보고서와 항목 id로 추적된다. 이 판정을 작성하는 과정에서 원고를 읽거나 수정하지 않았다.*
