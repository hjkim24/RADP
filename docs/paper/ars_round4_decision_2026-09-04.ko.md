원문: ars_round4_decision_2026-09-04.md (영문). 본 문서는 한국어 번역본이며 판정의 효력은 원문 기준이다.

# 편집 판정 — Round 4 (3차 검증) — KV-CARE (IEEE IoT-J)

**일자:** 2026-09-04 · **R1 판정:** Major(대폭 수정) (5/5) · **R2 판정:** Major · **R3 판정:** Minor(소폭 수정) (5/5 Minor 이상, 1라운드, 편집자 검증)
**근거:** Round-4 검증 재심사 5건(`R0/R1/R2/R3/DA_round4.md`)을 `EDITORIAL_DECISION_R3.md` §7 및 로드맵 항목 1–36(MUST 1–9, SHOULD 10–26, OPTIONAL 27–36)과 대조하여 확인하였다.
**유지되는 제약 조건:** 테스트베드는 폐쇄되었다 — 아래의 어떤 항목도 측정을 요구하지 않는다. 저자는 논문을 **의도적으로 10 pp.로 유지**하고 있으며, 선언된 지면 예산상의 포기는 공개된 부재로 채점한다. 로드맵 커밋 이후 새 **Fig. 1**(아키텍처)이 §III-A에 추가되었으며, 이는 §5에서 평가한다.
**이번 라운드의 MUST-FIX 규칙** — Round-3의 규칙을 그대로 유지한다: 어떤 항목이 MUST-FIX가 되는 경우는 (a) 저자 자신의 파일·코드·로그에 대조하여 **검증된 사실 오류 또는 내적 일관성 오류**이거나, (b) **인용(upheld)된 Devil's Advocate CRITICAL**이거나, (c) **심사자 3인 이상이 차단 사유로 지목한 경우**에 한한다. 이번 라운드에 필요했던 명확화 한 가지: **적용되지도 선언되지도 않은 R3 MUST-FIX 절은 그대로 이월된다**(이미 MUST였으므로); 적용된 절반으로 그 *목적*이 이행되었다고 패널이 판단하는 절은 명시적으로 종결한다(충돌 **B9** 참조).

---

## 1. 패널 표

| 심사자 | R3 권고 | **R4 권고** | 이번 라운드 집계 (A 해소 · P 부분 해소 · N 미해소 · W 악화 · D 선언) | 여전히 차단 사유로 지목된 항목 | 점수 변동 (R1 → R2 → R3 → **R4**) |
|---|---|---|---|---|---|
| **R0** Journal-Fit | Minor, 무조건 | **채택(Accept), 편집자 확인 정정 조건부 — 추가 심사 라운드 없음** | R0를 인용한 로드맵 13행: A 6 · P 4 · N 2 (선언/선택) · W 1 (*R0 자신의 수치*). 자신의 R3 항목 N9–N13/M1–M3: A 6 · N 1 · **철회 1 (N12)**. 패널 MUST 1–9 독립 점검: A 6 · P 2 (항목 2, 5의 두 번째 절) · 공개에 의한 A 1 (항목 7). 재유도한 수치 14건; 1건 실패(자신의 것). | N14 (493 ms), N16 (offline 절), N15 (Pareto 경계), 응답서 §2a–d | Fit 6→6→6→**6** · Originality 6→7→7→**7** · Significance 5→5→5→**5** · **Clarity 6→7→8→9** · Claims-vs-evidence 4→6→8→**8** |
| **R1** Methodology | 경미한 편집상 수정을 조건으로 채택 (조건 2건) | **채택, 한 절짜리 정정 2건 조건부 — 추가 외부 심사 없음** | 로드맵 26행: A 15 · P 3 · N 7 (6건 선언, **J8 미선언**) · W 1 (J15). **R3 조건 2건(NEW-11, NEW-12) 모두 해소.** 파생 수치 16건 재계산: 14 ✓ · 자신의 반올림 1건 (±26) · ✗ 1건 (493). | NEW-13 (§V-A "backup room"), NEW-14 (493 ms) | Exp. design 5→6→6→**6** · **Stat. validity 4→4→5→6** · Metric defs 6→7→8→**8** · **Reproducibility 3→4→5→6** · Limitations 6→7→9→**9** |
| **R2** Domain | Minor, 무조건 ("I performed the check") | **채택, 편집자 확인 절 1건 조건부** | R3 차단 항목 3건(N3-1, N3-2, N3-3) 모두 해소; N3-4/5/6 종결; **C-2는 잔여 항목으로서 철회**; 치명 트리거 F1–F6 발동 없음; 신규 N4-1…N4-5. | N4-1 (§V-A "backup room") | Literature 5→6→7→**7** · **Tech. soundness 5→6→7→8** · **Novelty 5→5→5→6** (4라운드 만의 첫 변동) · Fairness 5→7→8→**8** |
| **R3** IoT 실무자 | Minor ("정오 세 건만 고치면 게재하겠다") | **채택, 편집자 확인 정오 1건 조건부 — 추가 심사 라운드 없음** | 채점 20행: A 12 · P 4 (J7, J10, J12, S4) · N 2 (J8 오분류; 항목 32 선택) · D 5 · **W 0**. R3 차단 정오 3건(NEW-A, NEW-4, NEW-B) 모두 해소. | NEW-1 (§V-A "backup room") | Deployability 4→5→6→**6** · Motivation–eval 3→5→6→**6** · **Practical impact 5→6→6→7** · **Clarity for practitioners 6→6→6→7** |
| **DA** Devil's Advocate | Minor, NEW-3 조건부 | **"Nothing blocks acceptance" — 편집자 확인 정오표 이후 채택** | **NEW-3 CRITICAL 철회**("solely" 삭제됨; 대체 표현은 뒷받침 가능). NEW-1/2/4/5/6 A · NEW-7 종결 (A1) · **NEW-8 악화** (493) · NEW-9 사소한 N. C1 잔여, C8, N7, M9 해소 및 철회. **신규 CRITICAL 0건.** 493을 제외한 모든 파생 수치가 재현됨. | errata 1 (493), 2 (Pareto), 3 (Fig. 1 캡션 + 회색 채움), 4 (Table I 사유); 응답서 | 루브릭 없음 |

**패널 산술: 5인 중 5인이 편집자 확인 정정 조건부 채택을 권고; Minor 0인; Major 0인; 조건부 0인. 어떤 심사자도 추가 외부 라운드를 요구하지 않는다.** 채점된 18개 차원 중 **7개가 상승하고 하락은 없다**; R2의 Novelty가 처음으로 움직인 것(5→6)은 저자가 쓰고도 공을 주장하지 않은 문장에서 비롯되었다(`related.tex` L69–71; R2 §2, R1 항목 14, DA §2).

**패널이 만장일치로 이행되었다고 기록하는 사항**(5인 전원, 각자 독립적으로 파일에 대조): 심사자 4인 이상이 차단 사유로 들었던 R3 항목 3건 — 결론의 *weights/load* 절(J1 첫 번째 절; `discussion.tex` L129–130이 초록과 문자 그대로 동일), R의 정의역(J2; 타이핑된 `R:S→D` 삭제, A3의 근거 "the head's backup serves replay" 존재, **R2와 DA가 `gateway.py` L1183–1186에 대해 참임을 검증**), 그리고 이제 "about two standard errors"가 된 DejaVu 기울기(J3; 2.038 SE를 R0, R1, DA가 재현) — 에 더해, §IV-E에서 삭제된 DA CRITICAL "solely"(S1; R1은 추가로 SLO 상한이 7B에서 구속하지 않았음을 검증하였으므로, 병합된 두 원인 모두 Eq. (mem)이다), 재귀속된 각주 (b)(J4), 재현되지 않던 통계량 두 건의 수정(S5/S6; R1이 0.027–0.231 s SD와 1.73–1.94를 재현), 인쇄된 solve 시간과 열거 공식(J5; `REPORT.md:812`의 122 s, 여섯 디바이스에서 $\sum P(|\mathcal D|,k)$ = 1 950), 명시된 비균일 사다리(J13), "two to four"(J11), §I의 처리량 전제(J14), 자발적으로 제시된 MDE ±26 %(S8), §IV-E에 부과된 12.4 GiB(S12), 삭제된 범위 외 문장(S11), 그리고 **두 비율을 모두 명시하여 3.7×/46 % 옆에 3.0×/42 %를 인쇄한** 보유 입력(retained-input) 회계(S3; R1이 `worker/server.py:439–451`에서 동작 주장을 검증). 심사자 4인은 이번에도 개정이 중요한 지점에서 **저자 자신의 이익에 반하는 방향으로** 움직였음을 지적한다(R0 §6, R1 §6, R2 §6, R3 §6). 정확한 아키텍처 그림이 지면 소모 없이 추가되었다(§5).

---

## 2. 합의된 잔여 결함 (심사자 2인 이상)

| # | 결함 (한 줄) | 심사자가 인용한 위치 | 제기자 | 최소 수정 |
|---|---|---|---|---|
| **K1** | **MUST-FIX 1이 §IV-E에는 전파되었으나 Discussion의 쌍둥이에는 전파되지 않았다** — 패널이 CRITICAL로 인용한 단일 원인 귀속이 다른 표현으로 살아남아 있다 | `discussion.tex` L56–57 "the live solve rejected a quarter of its candidate placements **for want of backup room**" — **Round-3 이전 스냅샷과 바이트 단위로 동일**(R2). §IV-E L308–310은 이제 "rejected as infeasible under Eq. (mem)"으로 읽힌다. R1, R2, R3가 각각 `scheduler.py:403–416`을 다시 읽음: 하나의 `except (NoFeasibleSolutionError, NoRecoveryError)`, 비유한(non-finite) 목적값에 대한 조용한 `continue`, 하나의 `feasible_count`; 핸들러 자신의 주석이 병합을 인정한다(R2) | **R1-NEW-13 (차단 사유)** · **R2-N4-1 (차단 사유)** · **R3-NEW-1 (차단 사유)** | 여섯 단어: "as infeasible under Eq.~\ref{eq:mem}, the backup reservation among the causes" (R3의 형태; 어떤 해석 아래서도 정확 — 충돌 **B1**). 인용된 줄에는 수정이 이루어지고 그 쌍둥이에는 이루어지지 않은 네 번째 연속 라운드이다(R1). |
| **K2** | **유일한 새 허위 수치이며, 패널이 제공한 것이다.** J15를 위해 추가된 괄호 구가 죽은 $k{=}2$ 스텁 행 15개를 병합한다 | `evaluation.tex` L40–41 "500 ms at 7B (**493 ms pooled over the repeated trials**)". 493.4 = `b1_ft_fleet_7b_rep3.json`의 **전체 75행**에 대한 중앙값으로, `fired:false, sequence_match:false`, 75–91 ms/token인 `raid6` 행 15개를 포함한다. 논문 자신의 게이트를 통과하는 60행에 대해서는 **499.6 ms**(R0 499.65 · R1 499.6 · DA 499.6/499.1/498.0). 그림 생성기는 게이트된 중앙값을 사용하여 500을 인쇄한다(`make_recovery_latency.py:61–63`, R1). 출처: R0-N12 / 로드맵 20이 "493.4–499.65"를 인쇄함; **R0는 N12를 자신의 오류로 철회한다** | **R0-N14 (차단 사유; "mine")** · **R1-NEW-14 (차단 사유)** · **DA §3 ✗ / errata 1** (NEW-8 악화) | 여덟 단어를 삭제하거나(3인 모두), "(499.6 ms over the 60 gated trials)"로 쓴다(R1, DA). 하류에서 493을 사용하는 곳은 없다 — R0와 R1이 모두 확인(31 steps, 2.1–3.2×, 0.89 모두 500을 사용). 충돌 **B7**. |
| **K3** | **R3 MUST-FIX 2의 두 번째 절이 적용되지도 선언되지도 않았다** — 초록에는 있는 증거 등급 라벨이 결론의 실현 가능성 문장에는 없다 | `discussion.tex` L138–141 "with backups confined to pipeline devices, joint placement remains feasible at every per-device memory cap at which the model fits"; `grep -n offline discussion.tex` → 0건(R0, R2, DA); 초록 L20에는 "in an offline placement analysis"가 있다. 어떤 미적용 목록에도 없음(R0-2c, R1, R2-L-c, R3-L14) | **R0-N16 (차단 사유)** · R1-NEW-19 · R2 MUST-2 행 · R3-NEW-4 ("my MAJOR-6 second ask, third round") · DA NEW-4 행 (5인 전원) | 네 단어, 초록 자신의 표현. 명확화된 규칙에 따라 MUST로 이월된다. R2의 "misleads no one"을 부기한다(충돌 **B9**). |
| **K4** | **J7이 절을 추가하는 대신 임계값을 옮기는 방식으로 적용되었다** — Pareto 부류가 이제 KV-CARE 자신의 점보다 0.08 s 위에, 그리고 자신이 인쇄한 범위 *안쪽*에 그어져 있다 | `evaluation.tex` L206–207 "among the families that recover **within three decode steps**, \sys{} retains the least state" (이전에는 "within two seconds"). 3 × 500 ms = 1.50 s; $P{=}32$에서 KV-CARE $k{=}1$ = 1.42 s (0.08 s 차이로 안쪽); Petals 2.31 s = 4.6 스텝. 그러나 논문은 L157에 "2.1–3.2×", L188에 "2.1–3.9× … both victims"를 인쇄한다; $P{=}4$ 최악 시행은 3.17 스텝, 2차 피해자는 3.92이다(R1, DA가 `rep3.json` / `7b_mid.json`에서). 요청된 절("Petals is the low-state endpoint at 40 kB/tok and 2.3 s")은 나타나지 않는다; Petals 부등호의 방향은 여전히 한 번도 진술되지 않는다(R2, R3) | **R0-N15 (차단 사유)** · R1-NEW-15 · R2 SHOULD-12 행 (부분 해소) · R3-NEW-2 · **DA errata 2** ("the second time this boundary has been redrawn to admit exactly one family") (5인 전원) | 지난 라운드에 심사자 4인이 요청한 절을 추가한다; 부류를 유지한다면 "at $P{=}32$"로 범위를 한정하거나(DA), 자신의 결과에서 0.08 s 떨어진 곳이 아닌 딱 떨어지는 수에서 긋는다(R0). 충돌 **B2**. |
| **K5** | **Fig. 1의 캡션은 설계상의 필요를 진술하는데 §IV-C는 이제 프로토타입의 동작을 진술한다** — §IV-C에서 해소된 S3의 두 가지 진술 문제가, 독자가 가장 먼저 보는 그림에서 다시 나타난다 | 캡션(`design.tex` L8–11) "retains **the interrupted position's** input" 대 `evaluation.tex` L219 "the prototype retains this per-position input mirror **for every family**"; 코드는 스테이지당 `dict[position, bytes]`, 256 MB, 요청 단위 축출을 유지한다(DA, `activation_cache.py:15–43`; R1, `worker/server.py:439–451`). `design.tex` L31–32 "the current position"에도 같은 긴장(R0, R3) | R0 §3(i) · **R1-NEW-18** · R2 §3 (외양상) · R3 §3(4)/§1c · **DA §4(1) / errata 3** (5인 전원) | 캡션: "retains the stage inputs by position (the interrupted position's suffices for the parity path)" (R1/DA의 표현). §III-A L31–32에 상호 참조 절 하나(R3 §1c)를 두면 상류의 같은 긴장이 종결된다. |
| **K6** | Fig. 1은 $R$을 순열 — 워커당 백업 하나 — 로 그리는데, 측정된 7B 매핑은 백업이 집중되어 있다 | `make_architecture.py` L15–16 `STAGES`: head→[stage n], 2→[3], 3→[head], n→[2]. 라이브 7B 매핑(`REPORT.md:818`): `on-5`와 `on-1`이 각각 **두 개**의 백업을 호스팅하고, `on-2`, `ao-2`는 **없음** — 보고서 자신의 표현으로 "backup이 on-5·on-1에 몰림". 그 집중이 §IV-E의 결합(coupling) 결과와 350M 30.3 s 절편 뒤의 메커니즘이다(R3, DA). §IV-A L29–30은 배포가 "of the form in Fig. 1"이라고 말한다 | R1 §3(1) (경미; 캡션 수준) · **R3 §3(1) ("the one change that would most improve it")** · DA §4(2) ("false of the prototype as measured") | 캡션 절 "(one backup per worker as drawn; the scheduler may assign several or none)" — 최소이며 편집자가 확인 가능. `STAGES` 리터럴을 통한 재작도가 더 나은 수정이며 생성기는 이미 리스트를 지원한다(R3 L70–73) — OPTIONAL. 충돌 **B3**. |
| **K7** | Fig. 1의 헤드는 회색으로 채워져 있으나, 그 이유를 말하는 범례 항목이나 캡션 절이 없다 | `make_architecture.py` `fc="#F2F2F2" if head`; 범례의 다섯 항목은 이를 다루지 않는다; 독자는 빠져 있는 빨간 화살표로부터 "unprotected"를 추론하거나 "or does not"(R3) | R0 §3(ii) · R2 §3 ("head: no parity") · R3 §3(2) · DA §4(3) / errata 3 (4인) | 범례 또는 캡션 한 마디: "shaded: outside the parity domain (the head's backup serves replay)". |
| **K8** | 코디네이터 — 백업도 replay도 없는 유일한 구성 요소 — 가 유일하게 표시되지 않은 상자이다 | `design.tex` L25–26 "is outside the protection domain"; 그림은 이것에 가장 굵은 테두리를 주면서 아무 표시도 하지 않는다; 백업이 *있는* 헤드가 오히려 음영 처리된 쪽이다(R3) | R3 §3(3) · DA §4(5) (2인) | 코디네이터에 음영을 넣고 K7의 범례 항목이 둘 다 포괄하게 하거나(R3의 통합 수정), 캡션 다섯 단어 "coordinator: outside the protection domain". |
| **K9** | "Unprotected"가 이제 두 가지 의미를 지닌다 — 그리고 새 §III-A 절이 단언하는 헤드 장애 replay 경로는 한 번도 실행된 적이 없다 | `design.tex` L21 (신규) "the head's backup serves replay" 대 `discussion.tex` L69–70 "the head stage and the coordinator are unprotected"; 코디네이터는 *상실*되고 헤드는 *replay*된다; 헤드에 장애를 내는 시행은 없다(R2는 `gateway.py` L1186에 경로가 존재함을 검증; R3는 배포자가 "unprotected"를 "lost"로 읽는다고 지적) | R2-N4-3 · R3-NEW-3 (2인) | §V-A: "the head stage is outside the parity guarantee (a head failure falls to full-prefix replay on its preloaded backup, a path we did not measure) and the coordinator is unprotected". |
| **K10** | "about 9.8 million at ten devices"는 9 864 090이다 — 편집 판정서 자신의 절사가 그대로 옮겨졌다 | `design.tex` L223; $\sum_{k=2}^{10}P(10,k)=9\,864\,090$ (R0, R1, R2, DA, 그리고 `scheduler.py:339–343`의 공식) | R0 nit · R1 행 7 · R2-N4-4 · DA M9 행 (4인) | "about 9.9 million". |
| **K11** | 대표 수치 "3.7× less coordinator state"는 설계상 필요 수치이며; 논문 자신의 새 공개에 따르면 코디네이터 상주 총량은 3.0×이다 | `abstract.tex` L17, `discussion.tex` L134 "3.7× less coordinator state"; `evaluation.tex` L219–224 "Charged to every family, the ratios become 3.0× … 42 %"; Table I 주석은 "coordinator **KV** state"라고 말한다. R0: 지표(L86–89)는 경로별 부과를 뒷받침하므로, 이는 **공개된** 회계상의 선택이다 | R0-N17 (연성) · R1 항목 7 잔여 · **R2-N4-2** · R3 §1c ("the word 'coordinator' points at the box whose memory is actually 3.0× smaller") (4인) | 두 지점에 한 단어: "3.7× less coordinator **KV** state" (R2). 어느 미러 개수 아래서도 정확하며 DA의 6-벡터 잔여(아래 S-2)를 비켜 간다. 충돌 **B4**. |
| **K12** | Table I 주석 (a)는 이제 참이지만 논문에 *유리한* 증거인 사유를 숨긴다 — 폐기된 Reconfigure 시도 셋 중 둘은 재구성된 파이프라인의 부팅 실패였다 | `evaluation.tex` L135 "no valid trial at $P{=}16$, 24, 32". 로그 `b1_ft_fleet_7b_reactive_log_20260901.json`의 `invalid`: 16 "survivor worker socket closed mid re-solve", 24 "**boot not ready** (… load_head died)", 32 "**boot not ready** (same regime instability)" — R0, R1, R3, DA가 검증. `discussion.tex` L67–68 "Reconfigure was measured at two positions"는 여전히 선택이었던 것처럼 읽힌다(R1) | R0 항목 6 (정직한 축약형) · R1 행 9/항목 6 · R2 MUST-6 행 (부분 해소) · R3 §1c (P) · **DA M7 행 / errata 4** ("hidden by its own conservatism") (5인 전원) | 주석 또는 §V-A에 한 절: "three further positions were attempted; two were discarded because the reconfigured pipeline did not come up". 저자에게 유리하게 작용한다. 충돌 **B6**. |
| **K13** | "tolerated failures" 문장(S9의 대체물)이 한 방향으로는 과장하고 다른 방향으로는 축소한다 | `evaluation.tex` L225–226 "Replication and the replay families tolerate **any number** of simultaneous protected-stage failures that backups can host; parity tolerates $k$." R3: "parity tolerates $k$"는 $(k{+}1)$번째 장애가 요청을 잃는 것처럼 읽히는데, §III-B L50–53/L61–63은 이를 부정한다(replay로 넘어감). DA: "any number"는 replication에 대해 검증되지 않았다 — `_recover_replicate`(L946ff)는 죽은 스테이지 **하나**를 귀속하며; `parity_k == 2`만이 다중 피해자 디스패치를 가진다 | R3 §1c · DA S9 행 (2인) | 둘을 모두 담은 한 문장: "By construction, replication and replay tolerate any number of simultaneous protected-stage failures that backups can host (one was measured); parity restores up to $k$ without recomputation and falls to replay beyond." |
| **K14** | J8(단위 관례)은 적용되지도 어떤 미적용 목록에도 오르지 않았는데, 응답서는 올라 있다고 말한다 | Table I 주석 L134 "kB denotes 1 024 bytes"가 유일한 선언으로 남아 있다; "832 MB / 224 MB"(L234–235), "12.4 GiB"(L25, L90), Table III "4.8 GB / 23 GB"가 공존한다. 응답서 부록 ¶: "J8 … remain on the not-applied lists above" — **세 목록 중 어디에도 없다** | R0 항목 16/§2b · R1 항목 16/L3 · R2-L-c · R3 항목 16/L13 (4인) | 원고: 외양상, OPTIONAL. **응답서: 목록에 올린다**(SHOULD). |
| **K15** | `kosaian2019parity`에는 여전히 페이지가 없다(SOSP '19, 30–46); `rashmi2016eccache`는 이제 페이지가 있고, DOI가 없는 것은 옳다 | `references.bib` L330–336 | R0 항목 21 · R1 행 16 · R2 SHOULD-21 행 · R3 항목 21 · DA N8 행 (5인) | 필드 하나; 제작 부서. |
| **K16** | "about ±26 %"는 26.6–26.7로 재계산된다 — R1 자신의 Round-3 반올림이 그대로 옮겨졌다 | `evaluation.tex` L373–374; $t_{0.975,2}\cdot10.737/\sqrt3=26.67$ | R0 · R1-NEW-17 ("mine") · R2 · DA (4인; 모두 "about"이 이를 포괄한다고 말함) | Nit; ±27로 쓰거나 그대로 둔다. |
| **K17** | R3 MUST-FIX 5의 두 번째 절(복구 경로 fetch)이 추가되지 않았다 — 그러나 그것이 겨냥한 모순은 범위 한정으로 해소되었다 | `evaluation.tex` L227–229 "During failure-free decoding, …" ✓; L165–166 "four RPC round trips"가 이미 복구 경로 트래픽을 담고 있다 | R0 항목 5 (P; "worth doing") · R1 항목 5 (모순 남지 않음) · R2 N3-3 (없음) · R3-L10 (4인) | **MUST로서는 종결** — 4인 중 3인이 목적이 이행되었다고 말한다(충돌 **B9**). OPTIONAL. |
| **K18** | `background.tex`가 여전히 디스크에 있고 `\input`되지 않았다 | `main.tex` L93–97 | R0-W11 · R3 항목 34 (D, 선언됨) (2인) | 고아 파일을 삭제한다; 지면 소모 없음. 선언됨; OPTIONAL. |
| **K19** | 7B "whole fleet"의 구성원이 정의된 적 없다; `on-3`/`on-4`는 이름이 없다 | `evaluation.tex` L317–318 "the six CUDA workers" | R0 항목 31 · R1 항목 17 잔여 (2인; 둘 다 선택) | OPTIONAL. |
| **K20** | 환경 문단(J9) — "deferred desk work"로 선언되었으나, 같은 두 심사자의 최우선 비차단 요청으로 남아 있다 | jetpack/l4t/nvpmodel/jetson_clocks grep → 0건; `design.tex` L237 "Python with PyTorch and gRPC" | R1 항목 13 ("still my top non-blocking ask") · R3 항목 13 ("if a page appears at proof, item 20 first") (2인) | 선언됨; 기록하되 밀어붙이지 않는다. 두 심사자 모두 전력 모드는 저자가 보유한 설정 사실임을 재차 강조한다. |

---

## 3. 단일 심사자 제기이나 조치할 가치가 있는 잔여 결함

| # | 결함 | 위치 | 심사자 | 최소 수정 |
|---|---|---|---|---|
| **S-1** | 프로토타입은 **탐색을 여덟 디바이스로 제한한다**; 열 디바이스에서는 아무것도 열거하지 않는다 — "≈9.8 million at ten devices"를 인쇄하는 문장 바로 옆에서 | `scheduler.py:289` `max_search_devices: int = 8`; `server.py:26`; `group_vars/all.yml.example:79` "<M → skip the search, use heartbeat order" | **R1-NEW-16** | `design.tex` L223 뒤에 한 절: "the prototype searches up to eight devices (109 592 orderings) and falls back to heartbeat order above that." 인쇄된 수치에 인접한 사실 간극; 테스트베드 불필요. |
| **S-2** | 프로토타입의 미러는 토큰당 다섯이 아니라 **여섯** 벡터이다: 코디네이터가 모든 위치에서 *헤드의* 입력을 프라이밍하고, 전체 replay가 이를 소비한다 | `gateway.py:1735` `self.cache.put(request_id, first_key, position, blob)`; `_replay_through_chain` L1642–1668. 48 kB/tok에서 전 계열(family) 비율은 3.0× / 42 %가 아니라 **2.9× / 41 %**이다 | **DA S3 행** (MINOR; "the paragraph's words cover it, its numbers do not") | §IV-C의 전 계열 비율을 여섯 벡터로 재계산하거나, "five non-head vectors (the head's primed input adds 8 kB/tok)"라고 쓴다. K11의 "KV" 수정은 어느 쪽이든 대표 수치를 정확하게 유지한다. |
| **S-3** | §IV-E의 대체 표현 "infeasible under Eq. (mem)"은 *대체로* 옳다 — `NoFeasibleSolutionError`는 `scheduler.py:279`에서 열 번 반복 비수렴 시에도 발생하며, 비유한 `continue`는 세 번째 출구이다 | `evaluation.tex` L308–310 | **DA NEW-3 행** (MINOR) · R0 항목 1 연성 잔여 (비유한 continue) — R1 행 14는 이를 "precise"로 본다 | 3인 모두 차단 사유 아님. 손댄다면: "rejected as infeasible (Eq. (mem) is the binding constraint)" (DA). K1의 §V-A 표현은 이미 정확한 형태를 사용한다. 충돌 **B8**. |
| **S-4** | J15의 나머지 절반 — 527 ms protection-off 간격이, 350M에서 183 ms가 그러했듯 별개의 양으로 명명되지 않은 채 남아 있다 | `evaluation.tex` L367–368 "median token interval of 527 ms" | **DA errata 1 (두 번째 문장)** · R0 항목 20 (외양상) · R3-L9 (주장되지도 적용되지도 않음) | "these runs' median token interval of 527 ms" — 350M에 적용한 것과 같은 두-값 명명. |
| **S-5** | 응답서가 **Fig. 1을 언급하지 않는다** — 검증 라운드 중에 도입되어 다른 모든 그림의 번호를 바꾼 새 그림 | 로드맵 커밋 `6a4da75` 이후의 커밋 `57324dd`; Round-2 행들이 이제 엉뚱한 그림을 가리킨다 | **R2-L-d** ("the one an editor should ask about") | 응답서에 한 줄: 그림 추가, 모든 그림 번호 +1 재부여. |
| **S-6** | 응답서의 Round-3 서두 "No false statement was found in the Round-2 letter"가 스무 줄 앞의 응답서 자신의 행 14("Round 2 had written 'within two', which was false")와 모순된다 | `response_to_reviewers_2026-09-03.md` | **R1-L1** | "One false clause (row 14) and three completeness overstatements are corrected above." |
| **S-7** | §III/Fig. 1로부터 코디네이터 용량을 산정하는 배포자는 요청당 40 kB/tok을 과소 산정한다; 배포자에게 필요한 절대값(152 / 264 / 456 kB/tok; 2 048-토큰 요청당 +80 MiB 미러)이 인쇄되어 있지 않다 | `evaluation.tex` §IV-C L234–236은 설계 수치 "224 MB"만 제시한다 | **R3 §1c** | $k{=}1$에서의 실제 구축(as-built) 절대값 괄호 하나. OPTIONAL. |
| **S-8** | 스테이지 $n$의 열이 스테이지 2의 열과 동일하게 보호되는 것으로 그려져 있다; 꼬리 피해자는 하류 생존자가 없어 replay로 넘어간다 | Fig. 1의 빨간 화살표가 $n-1$개 스테이지에 걸쳐 균일; §IV-C "retain the tail stage's column, whose recovery falls back to replay"; `gateway.py` L1119–1121 | **DA §4(4)** | OPTIONAL 캡션 절; §IV-C가 이미 진술한다. |
| **S-9** | "42 % for two"에는 그 짝인 "46 % less than replication"이 지닌 "less"라는 단어가 없다 | `evaluation.tex` L224 대 L214 | **R0 nit** | 한 단어. |
| **S-10** | Pareto 캡션 "the mean of its two measured positions" 대 `make_recovery_pareto.py:6,52`의 `median` — $n{=}2$에서는 동일 | Fig. 3 캡션 | **DA-NEW-9** (사소) | OPTIONAL. |
| **S-11** | Fig. 1의 흰 바탕 위 회색 백업 라벨(소스 5.6 pt, 인쇄 ≈7 pt)이 R0가 진하게 하겠다는 유일한 요소이다 | 200 dpi로 렌더링한 p. 3 | **R0 §3** | OPTIONAL; 제작. |
| **S-12** | 계약 한정어 "whose recovery contract holds"가 §V-B의 마무리 문장에 없다(R3의 C3 잔여, 중재 C3에 의해 로드맵 2에 통합됨) | `discussion.tex` L141–143 | **R0-N16 (차단 사유 #2의 일부)** — R1 항목 32는 이를 **선택에 의한 선언**으로 채점; R3 항목 32 "optional; I do not press it" | 선언된 포기에 관한 상시 규칙에 따라 OPTIONAL. 충돌 **B5**. |

---

## 4. 응답서 대 파일 대조 결과

**대표적 결과, 두 라운드 연속 만장일치: 허위 변경 서술 없음.** R0는 Round-3 헤더, 11개 행 전부, 부록 문단의 모든 절(참조 17건)을 확인하였다; R1은 11개 행과 16개 절; R2는 같은 것에 더해 Round-2 정정들; R3는 15개 절; DA는 모든 절. **로드맵 10이 요청한 Round-2 정정 네 건 모두 해당 위치에서 이루어졌다**: "Fourteen of the fifteen MUST-FIX items"(L2), 행 14 "(2.04 SE; Round 2 had written 'within two', which was false)"(L1), "growth formula … and the 122 s solve time stated (Round 3)"(L3, 그리고 이제 *파일에 대해 참*), "DOIs added to three of the four"(L4); 미적용 목록은 42, K22, 7의 주석을 담고 있다(L7); "no data"는 "deferred desk work (facts or logs we hold but did not write up this round)"가 되었다(L8 — R1: "the wording I asked for"). R3: "the letter remains a usable verification instrument; its remaining faults are bookkeeping."

남은 사항 — 모두 범위 수준이며, Round-2 유형은 없다:

| # | 응답서 문구 | 검증 결과 | 발견자 |
|---|---|---|---|
| **L1** | 행 "'spread' is a sample SD → 'round-to-round standard deviation' **in the abstract, §Cost and the conclusion**" | **낡음(stale).** §IV-F L368–369에 대해서만 참이다; 초록(L23)과 결론(L135–136)은 같은 날 S7에 따라 "+0.6 % (±11 % across three rounds)"로 재편집되어 "standard deviation"을 담고 있지 않다. 부록 문단은 그 후속 편집을 기록하고 있으나 행은 갱신되지 않았다. | R0-2a · R1-L2 · R2-L-b · R3-L5 · DA §2 (5인 전원) |
| **L2** | 행 "7B decode step … '500 ms (493 ms pooled over the repeated trials)'" | **변경 서술로서는 참; 수치는 허위**(K2). 응답서는 파일에 충실하고; 파일은 로드맵의 잘못된 쪽 끝을 옮겨 적었다. | R0 · R1 · DA |
| **L3** | 부록 ¶: "J6, J8, J9, J10, S10, S13 remain on the not-applied lists above" | **여섯 중 다섯; 그리고 과소 주장 하나.** J8은 어떤 목록에도 없다(K14). J10의 두 번째 절 — 정확성(exactness) 문장 — 은 **적용되었는데**(`related.tex` L69–71) 미적용으로 보고되어 있다. | R0-2b · R1-L3 · R2-L-c/§2 · R3-L13 · DA §2 (5인 전원) |
| **L4** | 헤더: "**All Round-3 residuals** are sentence-scale and applied" | **둘 또는 셋만큼 과장**: MUST-2의 offline 절(K3), MUST-1의 Discussion 쌍둥이(K1), MUST-6의 사유(K12). Round 3의 "all fifteen"과 같은 종류가 한 라운드 뒤에 반복된 것이다. | R0-2c · R2-L-a |
| **L5** | Round-2 행: "Fig. 1 regenerated … Fig. 2 caption … Fig. 4 y-axis"; Round-1 "Fig. 2 (Pareto)" | **하나씩 어긋남.** 아키텍처 그림이 이제 Fig. 1이고; 지연은 2, Pareto는 3, 비용은 4이다. 과거 행들이므로; 대괄호 주석 하나로 고쳐진다. | R0-2d · R1-L4 · R2-L-d · R3-L15 (4인) |
| **L6** | **Fig. 1이 응답서 어디에도 언급되지 않는다.** | 로드맵 커밋 이후, 검증 라운드 중에 도입된 새 그림. 그림은 정확하다(§5); 침묵이 과실이다. | **R2-L-d** |
| **L7** | Round-3 서두: "No false statement was found in the Round-2 letter" | 스무 줄 앞의 행 14 및 R3 판정의 L1과 모순된다. 허위 절 하나가 *실제로* 발견되었다; 그렇게 말해야 한다. | **R1-L1** |
| **L8** | 미적용 목록이 망라적이지 않다 | 누락: MUST-2의 두 번째 절, MUST-5의 두 번째 절, `kosaian2019parity` 페이지, J8. R2: "the third round I have written that sentence." | R0 · R1 · R2 · R3 |
| **L9** | Round-2 마무리 "Abstract 258 words" | S7 편집 이후 이제 253이다(R0의 집계 253; DA `wc -w` 253). 무해하다. | R0 항목 35 · DA §2 |

**편집 부기.** 응답서의 과실은 다시 줄어들었다: Round 2에는 허위 변경 서술 네 건; Round 3에는 허위 절 하나와 완전성 과장 셋; Round 4에는 낡은 행 하나, 목록 누락 하나, 과소 주장 하나, 공개되지 않은 그림 하나. 이 판정이 *편집자 확인 정오표 조건부 채택*이고 어떤 심사자도 재위촉되지 않으므로, 응답서에 남은 역할은 기록이다: 저자는 파일이 응답서와 마지막으로 한 번 더 일치하도록 L1, L3, L6, L7을 정오표와 함께 한 문단짜리 부록으로 제출해야 한다.

---

## 5. Fig. 1 (시스템 아키텍처, §III-A) — 통합 평가

**출처와 빌드**(R0, R2, R3): `make_architecture.py` 21:53:16 → `fig_architecture.{pdf,png}` 21:53:17 → `main.pdf` 21:56:41, 마지막 섹션 편집 이후; 폰트는 임베드·서브셋(Times + STIX)되어 본문과 일치; 10페이지 유지(`pdfinfo`), **overfull box 0건**(`main.log`, R2); §III-A와 §IV-A L29–30에서 참조("a six-stage pipeline **of the form in** Fig. 1" — R1과 R2 모두 이를 일반적 $n$-스테이지 도면에 대한 올바른 유보라고 평한다).

**정확성 — 5인 전원이 생성기와 §III에 대조하여, R0, R1, R2, DA는 코드에 대조하여 검증.** 모든 심사자가 독립적으로 동일한 일곱 요소를 확인한다: (1) 코디네이터의 네 역할 = §III-A의 네 동사; (2) 워커당 스테이지 하나, 그 아래 점선의 프리로드된 백업 = `design.tex` L23–25 및 `memory_check.py:60` `eager_backup=True`(DA); (3) **헤드는 백업을 가지며 하나를 호스팅한다 — J2 수정이 그려진 것**; 모든 백업이 자신의 1차 디바이스가 아닌 디바이스에 있음, 즉 Eq. (mem)이 요구하는 완전순열(derangement)(R2); (4) **빨간 "KV + input" 화살표는 비헤드 스테이지에서만 나오고 헤드에서는 나오지 않음** — `gateway.py:1183` "Head is coord-sourced and never ships KV"(R0, R2, DA) 및 `worker/server.py:441`의 `start_layer > 1` 가드(R1, DA); (5) 모든 워커로 향하는 점선 제어 버스 $(\psi,R)$; (6) 요청 경로 client → coordinator → head, stage $n$ → coordinator = §III-F의 RPC-trailer 검출; (7) 헤드의 KV가 비보호임은 생략으로 표시. R1과 R2 모두 헤드가 스테이지 $n$의 백업을 호스팅하는 것이 라이브 표(`on-6`은 `on-5`가 백업하고, `ao-1`의 것을 호스팅)를 반영한다고 지적한다. **그림의 어느 것도 설계 본문과 모순되지 않는다**(R0, R1, R2, R3, DA — 5인 중 5인). 공격이 임무였던 DA: "honest about more than most architecture figures"; "nothing in the figure is false of the *design*."

**가독성**(R0): 가장 작은 라벨은 소스 5.5 pt → 1.3× 배율 후 인쇄 ≈7 pt로 IEEE의 6 pt 하한 이상; 선 굵기 유지; 단의 ≈40 %; 지면 비용 없음.

**점수에 미친 영향.** R0 Clarity 8→9("the figure is the reason"; Round 1부터 이월된 W11 종결). R3 Clarity-for-practitioners 6→7("the largest single move toward that bar in four rounds") 및 Practical impact 6→7의 기여 요인. R2: "technically accurate against §III on every point I checked." R0: "the cheapest improvement the paper has received in four rounds" — 이 그림은 논문이 IoT-J 독자에게 시스템으로 *읽히게* 만든다; 서지적 적합성 이의는 별개의 문제이며 움직이지 않는다.

**캡션**(`design.tex` L8–11): "KV-CARE architecture. The coordinator places layers and backups ($\psi$, $R$), folds the protected stages' KV columns into parity, retains the interrupted position's input, and detects failures; each worker serves one stage and preloads the backup weights $R$ assigns to it (dashed)." 적절하다(R0, R2); 그려진 모든 역할과 범례에 없는 인코딩 하나를 명명한다. 유일한 결함은 모든 심사자가 발견한 것이다: "retains the interrupted position's input"은 설계상의 *필요*이고, 같은 개정에서 작성된 §IV-C는 프로토타입이 모든 위치를 보유한다고 말한다(K5).

**패널이 다섯 보고서로부터 통합한 세 가지 변경**(모두 캡션/범례 수준, 편집자가 확인 가능, 앞의 둘은 재생성 불필요):

1. **캡션, 미러**(K5; R0, R1, R2, R3, DA): "retains the stage inputs by position (the interrupted position's suffices for the parity path)". MUST-FIX — 캡션과 §IV-C L219 사이의 내적 불일치.
2. **범례, 표시되지 않은 두 영역**(K7 + K8; R0, R2, R3, DA): 헤드의 회색 채움에 대한 항목 하나("outside the parity domain; backup serves replay")와 코디네이터에 대한 표시("outside the protection domain"). R3의 통합 형태 — 코디네이터에도 음영을 넣고 "shaded: outside the parity/protection domain"을 추가 — 는 범례 한 줄로 둘을 종결한다. SHOULD-FIX.
3. **실제 배정된 $R$**(K6; R1, R3, DA): 도면은 순열이다; 측정된 7B 매핑은 `on-5`와 `on-1`에 백업 두 개를, `on-2`/`ao-2`에는 없음을 두며, 그 집중이 §IV-E의 결합 결과와 350M 30.3 s 절편 뒤의 메커니즘이다. 최소: 캡션 "(one backup per worker as drawn; the scheduler may assign several or none)". 어차피 다시 빌드한다면 더 나은 것: `STAGES` 리터럴 변경 — 생성기의 `for k, l in enumerate(hosted)` 루프가 이미 리스트를 렌더링한다(R3). SHOULD(캡션) / OPTIONAL(재작도).

부기하되 요구하지 않음: 클라이언트로의 반환 화살표 없음(R2); Eq. (mem)의 주제인 메모리가 도면 어디에도 나타나지 않음(R3); 스테이지 $n$의 열이 패리티로 복구될 수 없음에도 스테이지 2의 열과 동일하게 그려짐(DA §4(4), S-8); 회색 백업 라벨은 더 진해도 됨(R0, S-11); 응답서는 그림과 번호 재부여를 공개해야 함(L6).

---

## 6. Devil's Advocate 판정

모든 DA CRITICAL과 DA가 편집자에게 요구하도록 요청한 모든 항목을 가시적으로 판정한다. **DA는 이번 라운드에 새 CRITICAL을 제기하지 않았으며** "Nothing blocks acceptance."로 평결을 시작한다.

| DA 항목 | DA의 R4 상태 | 보강 / 반박 | **판정** |
|---|---|---|---|
| **NEW-3 (R3의 유일한 CRITICAL)** — "496 rejected *solely* because no peer could reserve the backup weights" | **해소 — CRITICAL 철회.** §IV-E는 이제 "rejected as infeasible under Eq. (mem), which charges backup reservations beside each device's own stage"; 핸들러에 대한 응답서의 설명은 "is exactly what `scheduler.py:405` does". 잔여 MINOR: L279의 비수렴은 집계되지 않은 원인이므로 "under Eq. (mem)"은 "*mostly* right rather than *provably* wrong" | R0 항목 1 A(핸들러를 읽음; 비유한 `continue`를 연성의 세 번째 원인으로 지적); **R1 행 14 A, 더 강하게** — throughput 모드의 SLO 상한이 7B에서 구속하지 않았음을 검증(`slo_tbt_seconds: 1.0` 대 최대 스테이지 72 ms)하여, 병합된 두 원인 모두 Eq. (mem)의 두 항임; R2 A; R3-L3 참. **그러나 R1-NEW-13, R2-N4-1, R3-NEW-1은 각각 같은 귀속이 `discussion.tex` L56–57 "for want of backup room"에 살아남아 있음을 발견 — DA가 점검하지 않은 지점** | **§IV-E에서는 해소; Discussion의 쌍둥이는 MUST-FIX로 인용(K1)** — 규칙 (a): 저자가 여전히 보유한 스케줄러가 반박하는 명시된 원인이며, 심사자 3인이 독립적으로 다시 읽음 — 및 규칙 (c): 심사자 3인이 차단 사유로 지목. DA 자신의 §IV-E 잔여와 R0의 잔여는 둘 다 MINOR로 채점되어 OPTIONAL로 남는다(S-3); K1의 표현("the backup reservation among the causes")은 어떤 해석 아래서도 정확하므로 §V-A 편집은 그 의문을 물려받지 않는다. |
| **Errata 1** — "(493 ms pooled over the repeated trials)"는 발동되지 않은 $k{=}2$ 스텁 행 15개를 포함한다; 500이 옳았다(NEW-8 악화) | 요구: 삭제하거나 499를 인쇄; 그다음 527 ms를 보호 비용 실행의 간격으로 명명 | **R0-N14와 R1-NEW-14가 `rep3.json`에서 독립적으로 재현**(게이트된 60행 → 499.65 / 499.6 ms); R1은 그림 생성기가 같은 방식으로 게이트하여 500을 인쇄한다고 덧붙임. R2 "did not recompute"; R3는 이의 없이 493을 사용. **R0는 출처인 자신의 Round-3 N12를 철회** | **MUST-FIX로 인용(K2)** — 규칙 (a), 심사자 3인이 원시 파일로부터 검증. 패널은 이 수치가 자신의 로드맵(항목 20이 "493 ms or 'about 500 ms'"를 인쇄)에서 나왔음을 기록한다; 수정은 저자가 원래 가지고 있던 것을 복원하는 삭제이다. 527 ms 명명은 SHOULD(S-4): R0는 외양상으로 채점하고, 로드맵 자신의 항목 20이 이미 한 번 요청하였다. |
| **Errata 2** — "within three decode steps"가 KV-CARE 자신의 2.1–3.9×에 걸쳐 있다 | 요구: "at $P{=}32$" 또는 로드맵의 Petals 절 | R0-N15 차단 사유; R1-NEW-15 경미, 비차단; R2 부분 해소, 교정 단계에서 should-fix; R3-NEW-2 경미, "strongly recommended". 5인 모두 이 문장이 *Fig. 2의 $P{=}32$ 평균에 대해 참*이라고 말한다; R1과 DA는 같은 섹션의 L157("2.1–3.2×")과 L188("2.1–3.9×")에 대한 불일치를 지목 | **MUST-FIX로 인용(K4), 다섯 중 가장 약한 것** — 규칙 (a)에 따른 내적 일관성 결함(부류 경계가 두 문단 앞에 논문 자신이 인쇄한 최대값 아래에 놓임)이며, 동일한 한 절짜리 요청이 채택되지 않고 변경이 반대 방향으로 간 두 번째 라운드이기 때문이다(R0: "does that more visibly than the old"). 2인 차단, 3인 비차단 — 규칙 (c)만으로는 성립하지 않으나; (a)로 성립한다. 충돌 **B2**. |
| **Errata 3** — Fig. 1 캡션 "the interrupted position's input"이 §IV-C와 모순; 헤드의 회색 채움에 범례 항목 없음 | 둘 다 요구 | 캡션: R0 §3(i), R1-NEW-18, R2 §3, R3 §3(4) — 5인 중 5인(K5). 회색 채움: R0, R2, R3(K7) | **캡션은 MUST-FIX로 인용(K5)** — 같은 개정에서 작성된 두 구절 사이의 내적 불일치로, `worker/server.py`와 `activation_cache.py`에 대조하여 검증됨. **회색 채움은 SHOULD-FIX(K7)** — 오류가 아니라 누락; R2는 외양상이라고 부른다. |
| **Errata 4** — "no valid trial"이 폐기 셋 중 둘이 재구성된 파이프라인의 부팅 실패였음을 숨긴다 | 한 절 요구 | R0 "the honest short form"; R1 "true; reasons unpublished"; R2 부분 해소; R3 "P; not blocking; the reasons matter more than the count". 5인 모두 주석이 로그에 대해 **참**임을 확인 | **SHOULD-FIX로 하향(K12).** 주석은 참이며 허위였던 것을 철회한다; DA의 논점은 그 누락이 저자에게 *불리하게* 작용한다는 것인데 — 이는 권고할 이유이지 차단할 이유가 아니다. 규칙 (a)는 충족되지 않는다; 다른 어떤 심사자도 차단하지 않는다. 충돌 **B6**. |
| **Errata 5** — 응답서: 낡은 "spread" 행, J10 과소 주장, 초록 253 | 요구 | 5인 모두 L1을 발견; R1, R2, DA는 L3; R0와 DA는 단어 수 | **SHOULD-FIX(§4).** 후속 심사 라운드가 없으므로; 응답서는 기록이다. |
| **C7 잔여** — 세 절차에 대한 "sequential procedures fail"; 재시도 베이스라인 없음 | 미해소; "stays MAJOR-not-blocking, as adjudicated" | R2-M-7 인접; R3 이후 변경 없음 | **기존 MAJOR, 비차단, 변경 없음.** 어떤 테스트베드도 이를 판가름할 수 없다; DA는 재개하지 않는다. |
| **NEW-8 (J15)** | 악화 | = Errata 1 | K2 / S-4에 통합. |
| **S3 잔여** — 미러는 여섯 벡터(헤드 프라이밍)이므로 3.0×/42 %는 실제 구축상 2.9×/41 %이다 | MINOR | 단일 심사자, 코드 수준(`gateway.py:1735`); 반박되지 않음 — R1은 워커가 보내는 다섯 벡터를 검증했고, DA는 코디네이터가 프라이밍하는 여섯 번째를 덧붙인다 | **SHOULD-FIX(S-2)**; K11의 "KV"가 어느 개수 아래서도 대표 수치를 정확하게 유지한다. |
| **S9 잔여** — "tolerate any number"는 replication에 대해 검증되지 않음; `_recover_replicate`는 피해자 하나를 귀속 | should-fix | R3 §1c가 같은 문장의 나머지 절반을 제기 | **SHOULD-FIX(K13)**, 병합. |
| **§5 "strongest remaining counter-argument"** — "when a reviewer supplies a number, it is transcribed rather than recomputed"(493; Pareto 경계) | — | R1: "the one number in the manuscript a reader following the stated protocol cannot reproduce, and it arrived by copying the roadmap's 493.4 without re-deriving it"; R0는 출처를 자인 | **이번 라운드 잔여의 성격 규정으로 수용**, 다만 패널이 공동 책임을 진다는 수정과 함께(B7). 9.8(K10)과 ±26(K16)을 낳은 것과 같은 실패 유형이며, 둘 다 역시 패널의 수치이다. |

**요약.** DA의 Round-3 CRITICAL은 DA가 지목한 지점에서 해소되었고 DA가 점검하지 않은 지점에서 인용되었다. DA의 errata 다섯 건: MUST로 인용 2건(K2, K5), 다른 근거로 MUST 인용 1건(K4), SHOULD로 하향 1건(K12), SHOULD 1건(응답서). 신규 CRITICAL 없음. **DA는 이번 라운드에 9개 항목을 철회 또는 종결하였으며**(NEW-3 CRITICAL, NEW-1, -2, -4, -5, -6, -7, C1 잔여, C8, N7), 이는 그 검증이 실제로 수행된다는 R3 부기를 뒷받침한다.

---

## 7. 판정

### **ACCEPT WITH EDITOR-VERIFIED ERRATA(편집자 확인 정오표 조건부 채택)** — MUST-FIX 5건, 각각 단어 하나, 절 하나 또는 삭제 하나; 추가 심사자 라운드 없음.

**근거.**

*패널은 Minor를 지나 수렴하였다.* 5인 중 5인이 편집자 확인 정정을 조건으로 채택을 권고한다; 어떤 심사자도 추가 외부 심사를 요구하지 않는다; DA는 "Nothing blocks acceptance."로 시작한다. 모든 R3 MUST-FIX 항목이 적용되었거나(1, 3, 4, 6, 7, 8, 9), 적용된 절반이 정확한 채로 절반 적용되었으며(2, 5), **응답서에서 취한 것이 아니라 모든 심사자가 각자 독립적으로 파일·코드·결과 JSON에 대조하여 검증하였다**. R1의 조건 2건, R2의 차단 항목 3건, R3의 errata 3건, DA CRITICAL이 모두 해소되었다. 채점된 18개 차원 중 7개가 상승하고 하락은 없다; R2의 Novelty가 4라운드 만에 처음으로, 저자가 주장하지 않고 쓴 문장에서 움직였다.

*무조건 채택에 미치지 못하게 하는 것은 다섯 항목이며, 각각 검증되었고 각각 한 줄이다.* 둘은 패널이 이제 매 라운드 정정해 온 유형의 전파 실패이다 — Discussion에 살아남은 단일 원인 귀속(K1; 심사자 3인 차단, `scheduler.py`의 독립적 판독 3건)과 결론에 여전히 없는 "offline placement analysis" 라벨(K3; R3 MUST-FIX 2의 미적용 절반, 적용되지도 선언되지도 않음). 하나는 **패널 자신이 제공한** 허위 파생 수치이다(K2; R0는 자신의 Round-3 N12를 철회; 정정은 여덟 단어를 삭제하고 저자가 인쇄했던 500 ms를 복원하는 것이다). 하나는 그림 캡션과 같은 개정에서 작성된 §IV-C 문단 사이의 내적 불일치이다(K5; 5인 중 5인). 하나는 심사자 4인이 요청한 절 대신 다시 그어진 부류 경계로, 이제 논문 자신이 인쇄한 범위 안에 놓여 있다(K4; 2인 차단, 5인 제기). 어느 것도 폐쇄된 테스트베드를 필요로 하지 않고; 어느 것도 지면을 필요로 하지 않으며; 각각 grep으로, 그리고 K2의 경우 `b1_ft_fleet_7b_rep3.json`의 게이트된 60행에 대한 중앙값 한 번으로 검증 가능하다.

*왜 Minor Revision이 아닌가.* Round-3 판정이 기준을 세웠다: "four statements … are contradicted by the authors' own files"에 더해 스스로 만든 모순 두 건과 접수되지 않은 일관성 질문 하나일 때 Minor였다. 이번 라운드의 집계는 반박된 진술 하나(K1, 이미 수정된 것의 쌍둥이), 패널이 쓴 허위 수치 하나, 내적 불일치 두 건이며 — 편집자가 아닌 심사자가 다시 보아야 할 항목은 없다. R2: "It is six words and a grep; I would not convene the panel for it." R1: "What remains is two clauses and a caption." R3: "An editor can check it by grep; it does not need a reviewer."

*반면, 기록해 둔다.* 전파 양상은 실재하며 "the fix is trivial, the pattern is not"이라는 R1이 옳다 — 네 라운드, 네 번의 쌍둥이 누락(R2 결론; R3 결론 + $R$; R4 Discussion + 결론의 두 번째 절). 편집자는 각 MUST-FIX 문자열을 인용된 파일만이 아니라 **모든** 섹션 파일에서 grep해야 한다. 그리고 패널 자신의 전사 오류(493, 9.8, ±26)가 아래 MUST-FIX 2가 치환이 아닌 삭제인 이유이다: 저자에게는 심사자가 제공하는 어떤 수치든 복사하지 말고 재유도하도록 요청해야 한다.

**편집자를 위한 검증 지침.** MUST 1–5를 `sections/discussion.tex`, `sections/evaluation.tex`, `sections/design.tex`에 대해 grep으로 확인한다; MUST 2에 대해서는 괄호 구가 사라졌음을 확인하거나, 인쇄된 값이 있다면 `b1_ft_fleet_7b_rep3.json`에서 `fired`, `recovery_visible`, `sequence_match`가 모두 true인 행들의 `median_tbt_seconds` 중앙값(≈499.6 ms)에 대조하여 확인한다. MUST 1에 대해서는 추가로 `sections/` 전체에 `backup room`을 grep하여 0건을 기대한다. 어떤 심사자도 재위촉할 필요가 없다.

**상한(기록용, 차단 사유 아님; 네 라운드 동안 불변).** Fit 6(R0)과 Significance 5(R0): 34편 중 IoT-J 항목 1편, §II 문단들은 선언된 지면 예산상의 포기(A5), replication 대비 이득은 여전히 "a derived projection". R0는 이번 라운드에 **§II 문단들을 조건에서 철회한다** — "an associate editor should not re-impose a condition the panel has weighed and set aside" — 그리고 그림을 표현상 적합성의 실질적 진전으로 기록한다. R3의 Deployability는 항목 17 하나로 6에 묶여 있으며, "an absence, not an error"이다. 두 심사자 모두 그 결과인 상한을 IoT-J로서는 게재 가능한 결과라고 평한다.

---

## 8. 정오표 R4

번호를 붙이고 중복을 제거하였으며 충돌을 해결하였다. 모든 항목은 저자가 이미 보유한 텍스트, 기호 또는 숫자이다; 어느 것도 테스트베드나 지면을 필요로 하지 않는다.

### MUST-FIX (확정본(version of record) 이전 편집자 검증)

1. **`discussion.tex` L56–57** — "for want of backup room" → "as infeasible under Eq.~\ref{eq:mem}, the backup reservation among the causes". 그다음 `grep "backup room" sections/` → 0. *(K1 — R1-NEW-13, R2-N4-1, R3-NEW-1)*
2. **`evaluation.tex` L40–41** — "(493\,ms pooled over the repeated trials)" 삭제; "500 ms" 유지. 값을 남긴다면: "(499.6 ms over the 60 gated trials)". *(K2 — R0-N14, R1-NEW-14, DA errata 1; 패널이 제공한 수치)*
3. **`discussion.tex` L138–141** — "with backups confined to pipeline devices" 앞에 "in an offline placement analysis"를 삽입. 초록 자신의 표현(L20). *(K3 — R0-N16, R1-NEW-19, R2, R3-NEW-4, DA; R3 MUST-FIX 2 이월)*
4. **`evaluation.tex` L206–207** — "Petals is the low-state endpoint at 40 kB/tok and 2.3 s"를 추가; 유지하는 부류는 "at $P{=}32$"로 범위를 한정하거나 삭제. *(K4 — R0-N15, R1-NEW-15, R2, R3-NEW-2, DA errata 2)*
5. **`design.tex` L8–11, Fig. 1 캡션** — "retains the interrupted position's input" → "retains the stage inputs by position (the interrupted position's suffices for the parity path)". *(K5 — R0 §3, R1-NEW-18, R2 §3, R3 §3, DA errata 3)*

### SHOULD-FIX (같은 작업에서; 지면 불필요)

6. **`abstract.tex` L17, `discussion.tex` L134** — "3.7× less coordinator state" → "3.7× less coordinator **KV** state"; 선택적으로 "(3.0× as built)". *(K11 — R2-N4-2, R0-N17, R1, R3 §1c; 충돌 B4)*
7. **Fig. 1 범례/캡션** — 헤드의 회색 채움에 대한 항목 하나와 코디네이터에 대한 표시: "shaded: outside the parity domain (head: backup serves replay; coordinator: unprotected)". *(K7+K8 — R0, R2, R3 §3(2)(3), DA §4(3)(5))*
8. **Fig. 1 캡션** — "(one backup per worker as drawn; the scheduler may assign several or none)". *(K6 — R1 §3(1), R3 §3(1), DA §4(2); 충돌 B3)*
9. **`discussion.tex` L69–70** — "the head stage is outside the parity guarantee (a head failure falls to full-prefix replay on its preloaded backup, a path we did not measure) and the coordinator is unprotected". *(K9 — R2-N4-3, R3-NEW-3)*
10. **`evaluation.tex` L135 Table I 주석 (a) 또는 §V-A L67–68** — "three further positions were attempted; two were discarded because the reconfigured pipeline did not come up". *(K12 — DA errata 4, R3 §1c, R1, R0, R2; 충돌 B6)*
11. **`evaluation.tex` L225–226** — "By construction, replication and replay tolerate any number … (one was measured); parity restores up to $k$ without recomputation and falls to replay beyond." *(K13 — R3 §1c, DA S9 행)*
12. **`design.tex` L223** — "about 9.8 million" → "about 9.9 million"; "the prototype searches up to eight devices (109 592 orderings) and falls back to heartbeat order above that"를 추가. *(K10 — R0, R1, R2, DA; S-1 — R1-NEW-16)*
13. **`evaluation.tex` L367–368** — protection-off 간격을 별개의 양으로 명명: "these runs' median token interval of 527 ms", 350M에서 183 ms에 그리하였듯. *(S-4 — DA errata 1, R0, R3-L9)*
14. **`evaluation.tex` L219–224** — 프로토타입이 보유하는 여섯 벡터로 전 계열 비율을 재계산(2.9×, 41 %)하거나, "five non-head vectors; the head's primed input adds 8 kB/tok"라고 쓴다. *(S-2 — DA S3 행)*
15. **`design.tex` L31–32** — "(the prototype keeps every position's input for the replay ladder; Section IV-C charges it)". *(K5 상류 — R3 §1c, R0, R1)*
16. **응답서 부록** — "spread" 행 갱신; J8 등재; J10의 적용된 절 인정; Fig. 1과 +1 번호 재부여 공개; "No false statement was found"를 "one false clause"로 정정; 미적용 목록을 망라적으로; 초록 253. *(§4 L1–L9 — 5인 전원; R2-L-d; R1-L1)*

### OPTIONAL

17. `evaluation.tex` L308–310 — 비수렴 출구까지 포괄하려면 "rejected as infeasible (Eq. (mem) is the binding constraint)". *(S-3 — DA NEW-3 행, R0 항목 1; 충돌 B8)*
18. `evaluation.tex` L227–229 — "the parity path additionally fetches the surviving columns at recovery"를 덧붙인다. *(K17 — R0; MUST로서는 종결, 충돌 B9)*
19. `discussion.tex` L141–143 — 마무리 문장에 "whose recovery contract holds". *(S-12 — R0-N16; R1 항목 32에 따라 선택에 의한 선언; 충돌 B5)*
20. `make_architecture.py` L15–16 — 한 워커가 백업 둘을, 한 워커는 없음을 호스팅하도록 `STAGES` 리터럴을 변경; 재생성. *(K6 강한 형태 — R3 §3)*
21. `evaluation.tex` L224 — "42 % less"; L373–374 — "±27 %" 또는 "about" 유지. *(S-9 — R0; K16 — R1-NEW-17, R0, R2, DA)*
22. `references.bib` L330–336 — `kosaian2019parity`에 `pages = {30--46}`; 제작 부서. *(K15 — 5인 전원)*
23. `evaluation.tex` §IV-C — $k{=}1$에서의 실제 구축 절대값(152 kB/tok; 2 048-토큰 요청당 ≈80 MiB 미러). *(S-7 — R3 §1c)*
24. `evaluation.tex` L317–318 — 7B "whole fleet"를 명명(`on-3`/`on-4`). *(K19 — R0 항목 31, R1 항목 17)*
25. `main.tex` / `background.tex` — 고아 파일을 삭제하거나 `\input`한다. *(K18 — R0-W11, R3 항목 34; 선언됨)*
26. Fig. 3 캡션 "mean" → "median"으로 `make_recovery_pareto.py`와 일치; Fig. 1 회색 백업 라벨을 더 진하게; 스테이지 $n$의 열이 replay로 넘어간다는 캡션 한 마디. *(S-10 — DA-NEW-9; S-11 — R0; S-8 — DA §4(4))*
27. `design.tex` §III-F / `evaluation.tex` §IV-A — 환경 문단(JetPack/L4T, 버전, `nvpmodel`/`jetson_clocks`, LAN 속도, 아티팩트 진술). 선언됨; 교정 단계에서 지면이 생기면 두 심사자 모두 가장 먼저 쓰겠다는 곳. *(K20 — R1 항목 13, R3 항목 13)*

---

## 9. 네 라운드의 궤적

Round 1은 만장일치 Major였다: Devil's Advocate CRITICAL 8건, 경쟁자에게 0 kB/tok을 부여한 Pareto 문장, 백업 가중치를 누락한 footprint, 그리고 시스템 그림의 부재. Round 2는 다른 이유로 Major에 머물렀다 — 원고는 개선되었으나 응답서가 허위 변경 서술 네 건을 담고 있었고, 그림 둘이 낡았으며, 163 ms와 183 ms가 섹션을 넘나들며 서로 싸웠다; 패널의 판정은 논문 못지않게 응답서에 좌우되었다. Round 3는 Minor에 도달했는데, 응답서가 허위 진술을 해당 위치에서 실명으로 철회하였고, MUST-FIX 15건이 단어 수준의 9건이 되었으며, DA가 모든 파생 수치를 재계산하여 정확히 하나의 오류(2.038 SE)와 하나의 과잉 귀속("solely")을 찾아냈기 때문이다. 이번 라운드에 그 9건은 적용되거나 절반 적용되었고, CRITICAL은 지목된 지점에서 해소되었으며, 응답서에는 허위 변경 서술이 없고, Round 1부터 논문에 없던 그림이 지면 소모 없이 추가되어 심사자 4인이 코드에 대조하여 검증하였으며, 잔여는 다섯 줄 — 그중 하나는 패널이 쓴 것이다. 남은 것의 종류는 라운드마다 줄어들었다: 허위 응답서 진술, 다음은 허위 범위 주장, 다음은 낡은 행; 허위 대표 주장, 다음은 허위 파생 수치 하나, 다음은 심사자로부터 옮겨 적은 허위 괄호 구 하나. 줄어들지 않은 것은 R1이 명명한 양상 — 인용된 줄에는 수정이 이루어지고 그 쌍둥이에는 이루어지지 않는 것, 네 라운드 연속 — 과, 게이트하지 않은 수치를 제공하고 저자가 그것을 복사하게 만든 패널 자신의 습관이다. 둘 다 절차적이고, 둘 다 grep 한 번이면 종결되며, 어느 것도 측정에 닿지 않는다. 네 라운드가 얻어낸 것은, Round 3에서 R2가 한 말이자 이번 라운드에 모든 심사자가 되풀이한 말로, "every remaining claim … is one a reader can check against a printed number, a printed log or the authors' code — and I have checked them."인 논문이다. 상한 — Fit 6, Significance 5, Novelty 6 — 은 Round 1에서 도달한 것으로 논문의 정직한 크기이며; 개정은 거기에 도달하기 위해 일관되게 저자 자신의 이익에 반하는 방향으로 움직였다. **편집자 확인 정오표 조건부 채택.**

---

## 심사자 간 충돌 중재

**B1 — §V-A 표현: "under Eq. (mem)"(R1, R2) 대 "…, the backup reservation among the causes"(R3) 대 Eq. (mem)은 "mostly"만 원인이라는 DA의 지적.** DA-NEW-3 행: `NoFeasibleSolutionError`는 `scheduler.py:279`에서 열 번 반복 비수렴 시에도 발생한다; R0 항목 1: 비유한 목적값의 `continue`는 세 번째 출구이다. R1 행 14는 SLO 상한이 구속하지 않았음을 검증하고 §IV-E를 "precise"라고 부른다. **결정: §V-A에는 R3의 형태를 사용한다.** 이는 어떤 해석 아래서도 정확하고(비수렴이 기여했든 아니든 Eq. (mem)이 원인들 *가운데* 있다는 것은 참이다), R3 로드맵 항목 1 자체가 제시한 구절이다. §IV-E의 "under Eq. (mem)"은 그대로 둔다 — 심사자 3인이 수용하고 DA는 그 잔여를 MINOR로 채점한다(S-3, OPTIONAL).

**B2 — Pareto 경계: MUST인가 SHOULD인가.** R0(차단 사유 #3)와 DA(errata 2)는 요구한다; R1, R2, R3는 경미·비차단으로 채점한다. 5인 모두 이 문장이 $P{=}32$ 평균에 대해 참이라는 데 동의한다. **결정: 규칙 (a)에 따라 MUST-FIX** — R1과 DA 모두 같은 섹션에 인쇄된 "2.1–3.2×"(L157)와 "2.1–3.9×"(L188)에 대한 내적 불일치를 지목한다: "within three decode steps"로 정의된 부류는 논문이 보고하는 모든 KV-CARE 시행을 포함하지 않으므로, 이 문장의 주어 자신이 도시된 점에서만 부류 안에 있다. 규칙 (c)만으로는 성립하지 않으나(차단 2인, 3인 아님); (a)로 성립한다. 패널은 또한 동일한 한 절짜리 수정이 요청되고도 편집이 반대 방향으로 간 두 번째 라운드라는 점을 고려한다. 다섯 MUST 중 가장 약한 것이며, 편집자는 "at $P{=}32$"만을 최소로 수용해도 된다.

**B3 — Fig. 1의 $R$: 캡션 절(R1) 대 재작도(R3) 대 "false of the prototype as measured"(DA).** R0와 R2는 지적하지 않았다. **결정: 캡션 절은 SHOULD-FIX; 재작도는 OPTIONAL.** 캡션 절은 편집자가 grep으로 확인 가능하고 재빌드가 필요 없다; 재작도가 더 나은 수정이고 생성기가 이를 지원하지만(R3가 `hosted` 루프를 검증), 정오표 단계에서 재생성된 그림은 편집자가 텍스트로부터 검증할 수 없는 것이다. 저자가 다른 이유로 재생성한다면 R3의 형태를 취한다.

**B4 — 3.7× 대표 수치: "(3.0× as built)" 괄호(R0-N17) 대 "coordinator KV state" 한 단어(R2-N4-2) 대 DA의 6-벡터 2.9×.** **결정: R2의 한 단어.** "3.7× less coordinator KV state"는 정확히 Table I 자신의 행 라벨이고, 미러가 다섯 벡터든 여섯 벡터든 참이며, DA의 단일 심사자 코드 판독에 의존하지 않는다. R0의 괄호는 선택 사항이며; DA의 6-벡터 집계는 3.0×/42 % 수치가 있는 §IV-C를 위해 S-2로 별도 접수한다.

**B5 — §V-B 마무리 문장의 계약 한정어.** R0는 이를 차단 사유 #2에 통합한다(R3의 중재 C3에 따라); R1 항목 32는 "declared by choice"로 채점하고; R3 항목 32는 "optional; I do not press it". **결정: OPTIONAL.** 저자의 선언 목록에 있으며 상시 규칙은 선언된 포기를 보호한다. 그것이 초록 자신의 표현이라는 R0의 논점은 기록한다.

**B6 — Table I의 Reconfigure 사유: DA는 요구하고, 심사자 4인은 차단하지 않는다.** 5인 모두 "no valid trial"이 로그에 대해 참임을 확인한다. **결정: SHOULD-FIX.** 부팅 실패 두 건이 논지에 *유리한* 증거라는 DA의 논변은 옳고 그 절을 권고하는 이유이지만, 저자 자신에게 유리한 증거를 생략한 참인 진술은 규칙 (a) 아래의 오류가 아니다. R3의 "the reasons matter more than the count"는 같은 권고의 실무자 판본이다.

**B7 — 493의 책임 소재.** R0: "my error"; R1: "on the panel as much as the authors"; DA: "adopted from a Round-3 reviewer remark without a check" — 전사 양상. **결정: 수치는 패널의 책임이고 전사는 저자의 책임이며, 수정은 삭제이다.** R3 로드맵 항목 20은 "493 ms or 'about 500 ms'"를 인쇄했고; 저자는 패널이 보증한 쪽을 취했다. 이는 판정서에 패널의 오류로 기록되며, 같은 유형(9.8 M, ±26 %)이 항목 12가 복사가 아닌 재유도를 요청하는 이유이다. R1과 DA가 제시한 두 분기(삭제; 또는 게이트된 60 시행에 대한 499.6 인쇄) 모두 수용 가능하다.

**B8 — §IV-E의 "under Eq. (mem)"은 정확한가?** R1: 그렇다(SLO 상한이 구속하지 않았다). DA: 대체로(비수렴이 집계되지 않음). R0: 세 번째 원인의 가능성(비유한 `continue`), 정량화되지 않음. **결정: 차단 사유 아님 — 3인 모두 그렇게 말한다.** OPTIONAL 표현(항목 17). 원인별 카운터를 둔 오프라인 솔버 재실행이면 판가름되고 테스트베드가 필요 없음은 A6이 확립한 바이나; 패널은 이를 요구하지 않는다.

**B9 — 미적용 두 번째 절 중 어느 것이 MUST로 이월되는가.** R3 MUST-FIX 2의 두 번째 절(offline 라벨)과 MUST-FIX 5의 두 번째 절(복구 경로 fetch)은 둘 다 적용되지도 선언되지도 않은 채 남았다. **결정: 2는 이월(K3, MUST); 5는 종결(K17, OPTIONAL).** 규칙: R3 MUST 절은 적용된 절반으로 그 목적이 이행되었다고 패널이 판단하지 않는 한 이월된다. 5에 대해서는 R1, R2, R3가 각각 "during failure-free decoding" 범위 한정만으로도 이미 복구 경로 트래픽을 진술하는 L165–166과의 모순이 제거되었음을 검증한다 — 절의 목적이 충족되었다. 2에 대해서는 어떤 심사자도 결론의 실현 가능성 문장이 다른 무엇으로든 라벨되어 있다고 보지 않는다; R2의 "misleads no one"("per-device memory cap"이 상한을 둔 분석을 함의하므로)이 종결을 위한 가장 강한 논거이나, 패널은 초록, §IV-E, §V-A가 모두 라벨을 지니고 있고 결론이 훑어 읽는 독자가 도달하는 곳이라는 이유로(R1-NEW-19) 이를 기각한다 — K1과 같은 쌍둥이 전파 결함이다.

---

*편집 종합자(Editorial Synthesizer) 작성. 위의 모든 항목은 명시된 Round-4 심사자 보고서와 항목 id로 추적된다. 이 판정을 작성하는 과정에서 원고, 그 소스, 코드, 결과 파일을 읽거나 수정하지 않았다; 모든 인용은 다섯 심사자 보고서에서 취하였다.*
