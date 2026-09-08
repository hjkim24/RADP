원문: ars_round5_decision_2026-09-08.md (영문). 본 문서는 한국어 번역본이며 판정의 효력은 원문 기준이다.

# 편집 판정 — Round 5 (4차 검증) — KV-CARE (IEEE IoT-J)

**일자:** 2026-09-08 · **R1 판정:** Major(대폭 수정) · **R2 판정:** Major · **R3 판정:** Minor(소폭 수정) · **R4 판정:** 편집자 확인 정오표 조건부 채택(Accept with editor-verified errata) (MUST 5건) · **R5 판정:** §6 참조
**근거:** Round-5 검증 재심사 5건(`R0/R1/R2/R3/DA_round5.md`)을 `EDITORIAL_DECISION_R4.md` §8, 정오표 1–27(MUST 1–5, SHOULD 6–16, OPTIONAL 17–27), 그리고 §4 L1–L9와 대조하여 확인하였다.
**유지되는 제약 조건:** 테스트베드는 폐쇄되었다 — 아래의 어떤 항목도 측정을 요구하지 않는다; 심사자가 저자에게 "read it off the board"(보드에서 읽어 오라)를 요구하는 곳(`ao-2`에 대한 R3)에서는 패널이 폐쇄 테스트베드 형태로 대체한다. 지면 예산은 해제되었다(11 pp.; 열한 번째 페이지는 참고문헌만 — R0 W11); 따라서 R4의 "선언된 지면 예산상의 포기" 보호는 저자가 그 페이지를 쓰기로 선택한 항목에는 더 이상 적용되지 않으며, 그 항목들은 내용으로 채점한다(R3 §0).
**이번 라운드의 범위:** Round-4 정오표 *및* 판정 이후의 추가분 — 환경 문단(§IV-A L44–50), 코디네이터 규모 산정 문단(§IV-C L244–251 + Limitations L82–85), IoT-J 참고문헌 다섯 편이 들어간 §II-B, 재구성된 서론, 문장 분할 약 20건, 다시 그린 Fig. 1, 그리고 초록의 네 문장 재구성.
**MUST-FIX 규칙, Round 3 이후 불변:** MUST가 되는 경우는 (a) 저자 자신의 파일·코드·로그에 대조하여 **검증된 사실 오류 또는 내적 일관성 오류**이거나, (b) **인용(upheld)된 DA CRITICAL**이거나, (c) **심사자 3인 이상이 차단 사유로 지목한 경우**에 한한다. Round-4의 명확화는 유지된다: 등재(docketed)된 절이 적용되지도 선언되지도 않으면 그 등급은 이월된다; 그리고 이번 라운드의 따름정리로서, 등재된 SHOULD가 적용되지도 선언되지도 않은 채 **새 본문에 의해 반박되면** 규칙 (a)에 따라 새 본문을 기준으로 채점한다.

---

## 1. 패널 표

| 심사자 | R4 권고 | **R5 권고** | 이번 라운드 집계 (A 해소 · P 부분 해소 · N 미해소 · D 선언 · W 악화) | 여전히 편집자에게 지목된 항목 | 점수 변동 (R1 → R2 → R3 → R4 → **R5**) |
|---|---|---|---|---|---|
| **R0** Journal-Fit | 채택, 편집자 확인 정정 조건부 | **채택(Accept)** — "Nothing blocks acceptance"; 교정 단계에서 라벨 하나(N18) | 추적한 정오표 26행: A 16 · P 5 · N 5 (선언 1, 선택-미주장 2, 미선언 SHOULD 1 [항목 14], **적용되었다고 주장 1 [항목 18]**). **MUST 1–5: 5/5 A.** 자신의 N14–N17: **4/4 A**. 재유도한 수치 17건; 실패 0건; 느슨함 1건("about 30"). DOI 여섯 건 확인, 초록 다섯 편 읽음. | N18 (JetPack 라벨), N19 ($N_{\mathrm{ctx}}$/단위/"about 30"), N20 (응답서 §2 a–f); nit N23–N28 | **Fit 6→6→6→6→7** (다섯 라운드 만의 첫 변동) · Originality 6→7→7→7→**7** · Significance 5→5→5→5→**5** · Clarity 6→7→8→9→**9** · **Claims-vs-evidence 4→6→8→8→9** |
| **R1** Methodology | 채택, 한 절짜리 정정 2건 조건부 | **채택** — "Nothing blocks acceptance … I do not need to see the manuscript again" | **R4 차단 항목 2건(NEW-13, NEW-14) 모두 종결.** MUST 5/5 A. SHOULD 11건: A 8 · HALF 2 (11, 12) · N-선언 1 (10) · **N-미선언 1 (14)**. 재계산한 수치 16건: **정확 14 · 느슨함 1 · 한정어 오류 1**("as built"). 환경 문단을 절 단위로 점검: 10개 절 중 8개가 저장소로 추적된다. | NEW-20 (JetPack), NEW-21 (256 MiB 상한), NEW-22 (여섯 벡터 "as built"), NEW-23 (응답서), NEW-24 (`ao-2`, LAN 속도), S-1 | Exp. design 5→6→6→6→**6** · Stat. validity 4→4→5→6→**6** · **Metric defs 6→7→8→8→9** · **Reproducibility 3→4→5→6→7** · Limitations 6→7→9→9→**9** |
| **R2** Domain | 채택, 편집자 확인 절 1건 조건부 | **채택** — 교정 단계 정오 1건(N5-1, 규칙 (a)); "no reviewer needs to be re-engaged" | N4-1…N4-5 **모두 A**. MUST 5/5, **각 문자열을 여섯 섹션 파일 전부에 걸쳐 grep — 살아남은 쌍둥이 없음**. SHOULD 6, 7, 8, 9, 11, 12(절반), 13, 15, 16 A; 10 선언에 의한 포기; **14 적용되지도 선언되지도 않음**. 치명 트리거 F1–F6: 발동 없음; GhostServe를 그 PDF에 대조하여 재확인. | N5-1 ("as built"), N5-2 (세 번째 "coordinator state" 지점), N5-3 (§II-B 두 단어), N5-4 (응답서), N5-5 (외양상) | **Literature 5→6→7→7→8** · Tech. soundness 5→6→7→8→**8** ("would be 9 with N5-1's one phrase") · Novelty 5→5→5→6→**6** · **Fairness 5→7→8→8→9** |
| **R3** IoT 실무자 | 채택, 편집자 확인 정오 1건 조건부 | **채택** — "Nothing blocks"; "I would deploy from this paper" | 채점 27행: **A 19 · P 3 · N 3 · D 3 · W 0.** R4 차단 항목 NEW-1 종결. Fig. 1 요청 세 건 모두 수용, 첫 번째는 더 강한 형태(재작도)로. `tectonic`으로 깨끗이 재빌드: 11 pp., overfull 0건, 미정의 인용 없음. | NEW-1 (256 MiB 상한), NEW-2 (여섯 벡터), NEW-3 (메모리 한정 한계), NEW-4 (`ao-2` 모드), NEW-5 (응답서), NEW-6 (§V-A L68) | **Deployability 4→5→6→6→7** · Motivation–eval 3→5→6→6→**6** · **Practical impact 5→6→6→7→8** · **Clarity for practitioners 6→6→6→7→8** |
| **DA** Devil's Advocate | "Nothing blocks acceptance" — 정오표 이후 채택 | **"Nothing blocks acceptance"** — 편집자 확인 정오표 이후 채택(5건 열거) | R4 errata 1, 2, 3, 5 해소; 4 선언. K1, K3, K6, K9, K10, K11, K15, S-4, S-10 반영. **신규 CRITICAL 0건.** 기존 파생 수치 전부 재현(499.6 ms; $P{=}32$ 평균들을 소수 셋째 자리까지; ±26.67; 9 864 090). 새 공격: §3.1(i)–(vi) 규모 산정, §3.2 환경, §3.3 §II-B, §3.4 서론. | Errata 1 ("as built"), 2 (30 GB free / "about 34" / 256 MB 상한), 3 (JetPack), 4 (Zhang "must"), 5 (응답서) | 루브릭 없음 |

**패널 산술: 5인 중 5인이 채택을 권고; 4인은 교정 단계에서 편집자가 처리할 항목을 붙여 "Accept"를 쓰고, 1인(DA)은 "accept after editor-verified errata"를 쓴다. 어떤 심사자도 추가 외부 라운드를 요구하지 않는다. 채점된 18개 차원 중 9개가 상승하고 하락은 없다** — 다섯 라운드 중 단일 라운드 최대 변동이다(R4: 7개 상승). 패널이 Round 1부터 지녀 온 상한 두 개가 처음으로 움직였다: §II-B와 재구성된 서론에 대한 **R0의 Fit 6→7**("earned … I checked the five characterisations against the abstracts"), 그리고 코디네이터 규모 산정 문단에 대한 **R3의 Deployability 6→7**("the one thing holding this at 6 for four rounds").

**패널이 만장일치로 이행되었다고 기록하는 사항**(5인 전원, 각자 독립적으로, 응답서가 아니라 파일에 대조): 모든 Round-4 MUST — 모든 섹션에서 사라진 "backup room"(K1; R0, R1, R2, R3, DA의 `grep` → 0), 삭제된 493 괄호 구와 게이트된 60행 위에 서 있는 500 ms(K2; R1과 DA가 499.6을 재유도), 결론의 "In an offline placement analysis"(K3; 초록과 바이트 단위로 동일), Round 3부터 심사자 4인이 요청해 온 끝점(endpoint) 절로 대체되고 Petals의 방향이 명시된 Pareto 부류(K4; 2.314 s, 교차점 $P{=}10.14$, 3.71×, 1.31 스텝을 R1과 DA가 재현), 그리고 Fig. 1 캡션의 "retains stage inputs"(K5). MUST 너머로: **비대칭 $R$로 재생성된 Fig. 1** — OPTIONAL의 더 강한 형태로, 5인 전원이 `make_architecture.py` L15–16과 PNG에 대조하여 검증; 두 지점의 "coordinator KV state"(K11); 명명되고 미측정으로 표시된 헤드 장애 경로(K9); 9.9 million(K10); 별개의 양으로 명명된 527 ms(S-4); ±27(K16); "whose recovery contract holds"(S-12); 캡션과 일치시킨 Fig. 3 생성기(S-10); 페이지가 붙은 `kosaian2019parity`(K15). **네 라운드에 걸친 전파 양상은 어떤 MUST 문자열에서도 재발하지 않았다** — R1, R2, R3가 각각 모든 정오 문자열을 여섯 파일 전부에 걸쳐 grep하였다(R1 §4: "`backup room` 0, `493` 0, `solely` 0, `least state` 0, `interrupted position's input` 0"). 그리고 저자가 산 페이지는, R0의 표현으로, "where four rounds of reviewers asked them to spend it"(네 라운드의 심사자들이 쓰라고 한 곳)에 쓰였다.

---

## 2. 합의된 잔여 결함 (심사자 2인 이상)

모든 항목은 Round-4 판정 시점에 **존재하지 않았던** 본문에 있거나, 미적용으로 남은 등재된 R4 항목이다; 어느 것도 측정 결과를 건드리지 않는다(R0, R1, R2, R3, DA 모두 그렇게 말한다).

### 2a. 코디네이터 규모 산정 문단 (`evaluation.tex` L244–251)

| # | 결함 | 인용된 위치 | 제기자 | 최소 수정 |
|---|---|---|---|---|
| **Q1** | **다섯 벡터 설계 미러에 "as built"가 붙어 있다; 프로토타입은 여섯을 보유한다.** R4 SHOULD 14(DA의 S-2)는 적용되지도 선언되지도 않았고, 새 문장은 이제 회계상의 개수를 구축물의 것으로 라벨한다. 심사자 4인이 독립적으로 `gateway.py:1729–1735`를 읽었다("prime the mirror cache locally for the chain-head stage … `self.cache.put(request_id, first_key, position, blob)`", 위치마다, 무조건). 8 kB 벡터 여섯 = 48 kB/tok = 2 048-토큰 요청당 **96 MiB**(R1 행 11, R2, R3); DA는 각 blob이 `int64` attention mask도 담고 있다고 덧붙이며 ≈200 MiB로 추정한다(단일 심사자, "torch was not available locally", 컨테이너는 미계산 — 충돌 **B1**). 두 한계는 어느 개수 아래서도 살아남는다(96 → "roughly 100"; 33 → "about 30"); §IV-C L230–231의 3.0×/42 %는 여섯 벡터에서 2.9×/41 %가 된다 | L246–247 "plus 80\,MB of mirror **as built**" | **R2-N5-1 (규칙 (a), "should not ship")** · **R1-NEW-22** ("undeclared and propagated") · **R3-NEW-2** · **DA §3.1(ii) / erratum 1** ("the words 'as built' make it false") · R0 항목 14 / N25 (미선언; 연성) — **5인 전원** | 80 MB를 유지하고 "as built"를 **"by Table I's five-vector accounting (the prototype also primes the head's input, 8 kB per token)"**로 교체 — R2의 두 번째 형태에 R1/R3의 괄호 구를 더한 것; 다섯이든 여섯이든 DA의 마스크 포함 개수든 정확. 그다음 L230–231의 3.0×/42 %를 "on the five shipped vectors"로 범위 한정하거나 2.9×/41 %로 재계산. 응답서: 항목 14를 등재. **MUST** — 규칙 (a), 코드 판독 4건, 그리고 R4 K2 유형(등재된 항목이 악화됨). |
| **Q2** | **"leaves room for roughly 100 such requests in flight"가 256 MiB 저장소 둘 옆에 있다.** `parity_cache.py:33`과 `activation_cache.py:32`는 기본값 256 MiB; `ParityCache`는 `gateway.py:163–165`에서 `max_bytes` **없이** 생성된다; `server.py`나 `deploy/`에 설정 키 없음; 축출은 요청 단위 LRU. 2 048-토큰 단일 패리티 열 하나가 224 MiB이므로, 실제 구축상 코디네이터는 축출 전까지 요청 약 하나의 패리티와 요청 셋의 미러를 보유한다(R1, R3, DA가 메커니즘에 동의). 이 문장은 메모리 산술로서는 참이다("leaves room"; 앞 문장은 "a derived projection from the measured layer shapes"로 끝난다 — DA 자신의 양보) | L249–251 | **R1-NEW-21** (경미, 누락) · **R3-NEW-1** (SHOULD; "the one that would page someone at 3 a.m.") · **DA §3.1(iii) / erratum 2** (요구) — 3인 | 한 절: "(a derived projection; the prototype's parity and mirror stores default to 256 MB each and evict whole requests, so the bound assumes they are raised)". **SHOULD, 최우선 순위** — 규칙 (a) 불충족(쓰인 대로 참이며, 한 문장 앞에서 projection으로 라벨됨), 규칙 (c) 불충족(차단 1인). 충돌 **B2**. |
| **Q3** | **"about 30 GB free"는 플릿 표의 RAM 열이지 여유 메모리 측정이 아니다.** `REPORT.md:41` "ax-1 … 30 GB"는 Nano 항목이 7.4 GB, Orin 항목이 29 GB로 읽히는 열에 있다 — `free`가 보고하는 `MemTotal`(R1 행 12: "the RAM column; total as `free` reports it; ~29 GB free"; DA §3.1(i)). 저장된 어떤 프로파일도 `ax-1`의 여유 메모리를 기록하지 않는다(DA: `d29_coupling_threshold_20260903.json`은 워커 여섯을 열거하며 `ax-1`은 없음). DA만이 공유 머신에 대한 2026-08-12 설계 노트 "Coordinator has only ~7 GB memory available"를 인용한다 — 위험 부기이지 측정이 아니며, 이제는 판가름할 수 없다 | L249 "has about 30\,GB free" | **DA §3.1(i) / erratum 2** · R1 행 12 ("total"을 보강; "acceptable"로 채점) · R0 항목 23 ✓ · R3 §2 ✓ — 1인 공격, 3인 수용, 1인은 열의 의미를 보강 | "is a 32\,GB board with about 30\,GB of RAM" (DA의 형태). 어떤 해석 아래서도 정확; 비용 없음; 누구도 판가름할 수 없는 ~7 GB 문제를 비켜 간다. **SHOULD.** 충돌 **B3**. |
| **Q4** | **replication에 대한 "about 30"은 33.7이다**(십진 GB 또는 여섯 벡터 아래서는 31.4–33); "roughly 100 … about 30" 쌍은 3.3×로 읽히는데 문단 자신의 전 계열 비율은 두 문장 앞에서 3.0×이다(L230). 반올림은 replication의 여유에 대해서는 저자에게 *불리하게*, 비교에 대해서는 *유리하게* 작용한다 | L250 | R0-N19 ("about 35" 또는 "a third as many") · R1 행 13 (느슨함) · R3 §2 (보수적; "34 would be closer") · **DA §3.1(iv)** ("rounds the wrong way") — 4인 | "about 34" 또는 "about a third as many". **SHOULD.** 선례: K10의 9.8→9.9는 SHOULD였다; 여기의 상대 간극(11 %)은 더 크다. |
| **Q5** | $N_{\mathrm{ctx}}$가 정의 없이 사용됨; "224/448/80/832 MB"는 논문의 kB = 1 024 관례 아래서는 MiB인데, Table I 주석은 이를 kB에 대해서만 선언한다 — J8의 네 번째 지점 | L245–248 | R0-N19 · R3 K14 행 ("the units are binary throughout and the numbers check") — 2인 | "$N_{\mathrm{ctx}}$, the context length in tokens"; J8은 선언된 채로 남는다. **OPTIONAL.** |

### 2b. 환경 문단 (`evaluation.tex` L44–50)

| # | 결함 | 위치 | 제기자 | 최소 수정 |
|---|---|---|---|---|
| **Q6** | **"The workers run JetPack 6.1"은 적어도 워커 하나에 대해 저자 자신의 로그와 모순된다.** `PHASES.md:1995`는 `ao-1`을 **L4T R36.4.3**으로 기록하는데, NVIDIA는 이를 **JetPack 6.2**로 출하한다; `PHASES.md:1981`은 `ao-2`가 "JetPack 6.1 Rev1 (L4T R36.4.0 …)"으로 재플래시되었다고 기록한다. 같은 문단은 Nano에 대해 "MAXN SUPER"를 인쇄하는데, R1과 DA는 이를 JetPack 6.2의 기능으로 식별한다(R1은 이것이 저장소 사실이 아닌 NVIDIA 릴리스 노트 지식임을 표시한다; 패널은 `PHASES.md:1995`만으로 판정한다). CUDA 12.6 / cuDNN 9.3 / Python 3.10 / Ubuntu 22.04는 두 릴리스에 공통이며 유지된다(R0, R1, DA). R3는 같은 줄을 읽고 "R36.4 covers both"로 수용하였다; R2는 쌍 일관성만 점검하였다 | L44–45 "JetPack 6.1 (L4T R36.4, …)" | **R0-N18** (규칙 (a) 아래 "the only candidate"; "correct at proof") · **R1-NEW-20** ("factual, contradicted by the authors' own log") · **DA §3.2 / erratum 3** ("WRONG for five of six workers"; 요구) — 3인 검증; R3, R2는 다투지 않음 | "JetPack 6.1–6.2 (L4T R36.4.0–36.4.3, …)" 또는 보드별로. **MUST** — `PHASES.md:1995`에 대한 독립적 판독 3건으로 규칙 (a)가 충족된다; 버전 라벨에는 이를 덮어 줄 "about"이 없다. 충돌 **B6**. |
| **Q7** | **"`ao-2` as flashed"는 전력 모드를 명명하지 않는다** — 측정된 7B 배치에서 일곱 레이어(19–25)를 보유하는 보드에 대해; 2026-06-30 재플래시 이후 `ao-2`의 모드 기록은 저장소 어디에도 없다; 저자 자신의 노트(`PHASES.md:1122`)는 AGX Orin 공장 기본값을 MODE_30W로 기록하는데, 이는 `ao-1`이 레이어당 Nano보다 느렸던 모드이다. "As flashed"는 정직하다(R0: "the disclosure itself runs against the authors — the two AGX were not configured alike") | L48–49 | R0-N18 ("the mode name would be better") · **R1-NEW-24a** ("asserted without a source … say the mode or say 'not recorded'") · **R3-NEW-4** ("read it and print it") · **DA §3.2** ("unverifiable and underspecified") — 4인 | 테스트베드가 폐쇄되었으므로 R3의 "read it"은 가용하지 않다. "`ao-2` at its flashed default (power mode not recorded; the factory default is 30\,W)" — 또는 저자가 로그를 보유하고 있다면 그 모드. **SHOULD.** 충돌 **B9**. |
| **Q8** | **LAN 속도 없음** — 세 라운드 연속의 K20 절. R3: 저장소에는 초기 애플리케이션 수준 "~10 MB/s gRPC" 수치만 있으며, "not a link rate — nothing to print". DA: 스케줄러 자신의 프로브가 *저장되어 있다* — `b1_steady_r2_protection_off_20260830.json` `scheduler/network_profile/bandwidth_bps`(`on-1->on-6` 22 295 123, `on-2->on-6` 23 602 725, `on-2->on-1` 16 445 263; 1 MiB 페이로드 × 10 라운드, `all.yml:179–180`), 즉 배치가 본 대로의 쌍별 16–24 Mbit/s | L50 "one wired campus LAN" | R0 §4 · **R1-NEW-24b** · R3 §3 · **DA §3.2** — 4인 요청; R3는 인쇄할 것이 없다고, DA는 수치를 찾아낸다 | 있는 것을 있는 그대로 라벨하여 인쇄: "one wired campus LAN (the scheduler's gRPC probe measured 16–24\,Mbit/s between worker pairs)"; 또는 저자가 보유하고 있다면 공칭 링크 속도. **SHOULD.** 충돌 **B5**. |
| **Q9** | **아티팩트 / 코드 가용성 진술 없음** — K20의 마지막 절; "the repo, the result JSONs and the figure generators … are the thing every number in this paper was verified against for four rounds"(R3) | §IV-A | R0 §4 · R1 §2 · R3 §3(e) · DA §3.2 — 4인 | 코드, 결과 JSON, 그림 생성기가 어디에 기탁될지를 명시한 한 문장. **SHOULD.** |
| **Q10** | R3만 열거하는 재현성 세부: 설치된 대로의 grpcio/protobuf(논문은 핀 "1.60+"을 정직하게 인쇄한다 — R1, DA); Xavier의 JetPack 5 마이너 버전(`PHASES.md:324`에 따르면 5.0) | L46–47 | R3 §3(b)(c) (R1과 DA는 "1.60+"을 정직하게 진술된 하한으로 수용) | **OPTIONAL.** |

### 2c. §II-B (`related.tex` L23–40)와 재구성된 서론

| # | 결함 | 위치 | 제기자 | 최소 수정 |
|---|---|---|---|---|
| **Q11** | **Sun et al. "migrate tasks away from failed nodes"** — 인용된 초록은 *선제적(proactive)* 프레임워크이다: 손실에 앞선 "fault identification and task migration decisions"; "failed"는 사후 대응으로 읽힌다. 메커니즘의 오기술이 아니라 "a mis-description of when"(시점의 오기술)(DA) | L27–28 | **R0 §3.2** ("loses the paper's operative word"; "migrate tasks proactively, ahead of predicted node failures"를 제안) · **R2-N5-3** ("nodes predicted to fail") · **DA §3.3** ("failed" → "failing") · R3 §4 ("✓ fair") — 3인 지적 | "migrate tasks away from nodes identified as failing". **SHOULD.** 한 단어. |
| **Q12** | **"the substitute node is chosen after the service it replaces has been placed"는 Ma et al.에 대해 과잉 일반화이다** — 그들의 신뢰성 인지 스케줄러에는 대체 노드가 없다: 가용성은 스케줄링 결정 *안에서* 학습되며 — 이 문장이 인정하는 것보다 KV-CARE 자신의 결합(coupling)에 더 가깝다. Mudassar, Sun, Zhang (fog)에 대해서는 참 | L32–34 | R0 §3.2 (연성; "fits Ma least") · **R2 §3 / N5-3** · R3 §4 ("fits Ma least … still true of what Ma protects") · **DA §3.3** ("fits two or three") — 4인 | R2의 절: "These mechanisms protect a task's completion; **where a substitute node exists,** it is chosen after the service it replaces has been placed." **SHOULD.** |
| **Q13** | **Zhang et al. (joint) "show that coupled placement decisions must be solved together"** — 초록은 둘이 "coupling issues in practice … a complete process combining edge server and service placement"이며 "a two-step method"(클러스터링 + 비선형 계획법)를 통한다고 말한다. "Must"는 인용 논문의 입을 빌린 저자의 논지이며; 그 방법은 §IV-E가 "cost-first"라 부르는 순차적 종류이다 | L34–36 | R0 §3.2 ("a shade stronger … acceptable") · R2 §3 ("'must' is the authors' inference … 'benefit from being solved together' is the safer verb") · **DA §3.3 / erratum 4** ("Overclaims"; 요구) — 3인 | "argue that the two placement decisions are coupled and solve them in one combined process" (R2의 동사, R0의 초록 인용; DA의 "one formulation"은 DA 자신의 two-step 판독이 이를 약화시키므로 피한다). **SHOULD** — 저자 자신의 파일이 아니므로 규칙 (a)가 아니다. 충돌 **B4**. |
| **Q14** | "assistants in homes and buildings"는 새 서두에서 유일하게 인용이 없는 예시이며, 뒤따르는 격리(isolation) 논변이 다루지 않는 유일한 것이다 | `introduction.tex` L4 | R0 §3.2 (nit) · R3 §4 ("the one clause I would cut") · DA §3.4(2) — 3인 | 인용하거나 삭제. **OPTIONAL.** |
| **Q15** | "Zhang et al."이 아홉 줄 간격으로 두 그룹을 가리킨다; IEEE 번호는 구분하지만 산문은 구분하지 않는다 | `related.tex` L29, L34 | R0 §3.2 / N26 · (R2와 DA는 자신들의 표에서 "(fog)" / "(joint)"로 구분) | "P. Zhang et al." / "X. Zhang et al.", 또는 "(fog)"/"(joint)". **OPTIONAL.** |
| — | **검증되었다고 기록, 조치 없음:** 다섯 특성화는 주장된 입도(granularity)에서 정확하다(R0, R2, R3, DA — Mudassar "nearly verbatim"; Zhang (fog)는 R0와 DA가 초록에서 확인하여 R3의 제목 수준 의문을 종결; Ma "exact"); 마무리 델타는 다섯 모두에 대해 성립한다(DA: "a real difference from all five, including Zhang (joint), whose solver is two-step"); 이 문단은 "not padding"이며(R0 §3.3), 올바르게 배치되었다(R2, R3); 서론의 재구성은 주장이 아니라 범위 단어를 옮긴다(DA §3.4, R3 §4: "still honest to the industrial motivation"); 삭제된 `zhang2026finetuning`은 어디에도 인용되지 않는다(R0 §1.3); GhostServe를 그 PDF에 대조하여 재확인(R2 §3). | | | |

### 2d. 이월 및 전파된 잔여 결함

| # | 결함 | 위치 | 제기자 | 최소 수정 |
|---|---|---|---|---|
| **Q16** | **K9의 수정이 겨냥한 문장에서 열아홉 줄 하류에 안착하였다.** L68–69 "the head stage and the coordinator are unprotected"는 불변이다; 새 L87–88 "A head failure falls to full-prefix replay on its preloaded backup, a path we did not measure"가 거기까지 도달한 독자에게 이를 명확화한다. 전파 양상의 온건한 형태 | `discussion.tex` L68–69 | R0-N24 · R2-N5-5 (외양상) · **R3-NEW-6** (권고 5) — 3인 | "the head stage is outside the parity guarantee and the coordinator is unprotected". **SHOULD.** 한 절. |
| **Q17** | **여덟 디바이스 탐색 상한이 "unverified"로 포기되었다 — 저자 자신의 파일에 있는 리터럴이다.** `scheduler.py:289` `max_search_devices: int = 8`, L322 `if max_search_devices < M:`은 스펙 순서로 폴백한다; `server.py:129, 205`; `deploy/group_vars/all.yml.example:79` / `all.yml:143`. 새로 인쇄된 "about 9.9 million at ten devices" 옆에 있는데, 이는 프로토타입이 결코 열거하지 않을 수치이다($\sum_{k=2}^{8}P(8,k)$ = 여덟에서 109 592) | `design.tex` L225; 응답서 "(unverified)" | R0-N27 / §2(e) · **R1 S-1 / 행 12** · **R2-L-c** ("not a defensible ground") · **R3 S-1** ("the reason given for not applying it is not a reason") · DA — **5인 전원** | R1의 절: "the prototype searches up to eight devices (109 592 orderings) and falls back to heartbeat order above that." 응답서: "unverified"를 적용됨 또는 "by choice"로 교체. **SHOULD.** |
| **Q18** | K13의 나머지 절반: replication에 대한 "tolerate **any number** of simultaneous protected-stage failures" — `_recover_replicate`는 피해자 하나를 귀속하고 하나가 측정되었다 | `evaluation.tex` L232 | R3 §1a / 권고 6 · **DA K13 행** ("should-fix, unchanged") · R2 SHOULD 11 행 — 3인 | "any number" 뒤에 "(one was measured)". **SHOULD** (R4 항목 11에서 이월). |
| **Q19** | "At $P{=}32$"가 문법적으로 "recovers faster than \sys{} only below $P\approx10$"를 지배하는데, 이는 $P$ 전 구간의 fit 속성이다 | L211–213 | R0-N23 · R1-NEW-25a · R2 MUST-4 행 (외양상) — 3인 | "Petals is the low-state endpoint (40\,kB per token; 2.3\,s at $P{=}32$) and recovers faster …". **OPTIONAL.** |
| **Q20** | "42\% for two"에는 그 병렬구 "46 % less than replication"이 지닌 "less"가 여전히 없다 | L231 | R0 · R2 · R3 · DA — 4인 | 한 단어. **OPTIONAL** (이월). |
| **Q21** | 저장소의 `main.log`/`.bbl`/`.aux`가 낡았다(Aug 27–28, 9 pp., 미정의 `sec:discussion`); Sep 8 PDF는 다른 곳에서 빌드되었다. R3는 깨끗이 재빌드: 11 pp., overfull 0건, 미정의 인용 없음 | `paper/main.log` | R0-N28 · R1 §6 · R3 (자료) — 3인 | 저장소에서 한 번 빌드하고 로그를 커밋한다. **OPTIONAL**, 제작. |
| **Q22** | `background.tex` 고아 파일; 지면 예산 사유는 더 이상 적용되지 않는다 | `main.tex` L93–97 | R0 · R2 · R3 (선언됨, 항목 34) — 3인 | 삭제. **OPTIONAL**, 선언됨. |
| **Q23** | §II-B의 PDF 다섯 편이 `paper/refs/`에 없고 `PAPERS.md`가 이를 목록화하지 않는다 — 저장소 자신의 관례; `PHASES.md` L2604는 Crossref 확인을 기록하지, 읽었음을 기록하지 않는다 | `paper/refs/` | R1 §6 · R3 §4 — 2인 | 정리 작업; 원고 결함은 아니다(R0와 DA가 초록을 읽고 절들이 정확함을 확인). **OPTIONAL.** |
| — | **선언에 의한 포기, 기록하되 밀어붙이지 않음:** Table I 주석 (a) Reconfigure 폐기 사유(K12/항목 10) — "by choice"; 쓰인 대로 참; 저자에게 불리하게 작용한다(R0, R1, R2, R3, DA 모두 기록). | | | |

---

## 3. 단일 심사자 제기이나 조치할 가치가 있는 잔여 결함

| # | 결함 | 위치 | 심사자 | 최소 수정 |
|---|---|---|---|---|
| **S-1** | **실제 구축상 ≈200 MiB 미러** — 위치당 blob 여섯, 각각 길이 `past_len+1`의 `int64` attention mask를 담음(`gateway.py:606`; `stage_runner.py:341–344`; `worker/server.py:439–451`은 blob을 그대로 미러; `tensor_io.py:16–20` `torch.save` 컨테이너): hidden 96 MiB + 마스크 ≈96 MiB + 컨테이너 | `evaluation.tex` L247 | **DA §3.1(ii)** — 보강되지 않음(R1, R2, R3는 hidden 벡터만으로 96 MiB를 계산; DA: 컨테이너는 "unmeasured here") | **수치로는 채택하지 않음.** Q1의 재라벨은 구축물이 96이든 200 MiB든 정확하다; 패널은 게이트하지 않은 수치를 제공하지 않을 것이다(R4 B7의 교훈). 저자가 요청당 RSS 델타를 보유하고 있다면 인쇄하라; 아니면 재라벨로 충분하다. |
| **S-2** | **복구 시 작업 메모리는 한계 밖에 있다**: 패리티 복구는 XOR 전에 살아남은 열 넷((416−112) kB/tok × 2 048 = 608 MiB)을 가져오고, 여기에 재구축된 224 MiB 열이 더해진다 — 요청의 정상 상태 footprint의 ≈3.7×, 일시적; replication은 열 하나를 설치하고 아무것도 가져오지 않는다 | `evaluation.tex` L249–251; `gateway.py:1097–1155`; L173–174 | **DA §3.1(v)** | 저자가 그 문단을 손댄다면 한 절: "a recovery additionally holds the surviving columns transiently (about 0.8\,GB at 7B)". **OPTIONAL.** 저자에게 불리하게 작용한다; R3의 Q24 절이 더 저렴한 사촌이다. |
| **S-3** | 한계는 메모리 한정이다; 동시 폴딩 아래의 코디네이터 연산(여덟 Carmel 코어에서 요청당 토큰당 보호 열당 XOR 하나, 그리고 $k{=}2$에서 GF($2^8$) 곱셈-누산 하나)은 측정되지 않았다; Limitations L104–106은 수치를 읽는 곳에서 스무 줄 떨어져 그렇게 말한다 | L249–251 | **R3-NEW-3** | 그 자리에 다섯 단어: "a memory bound; coordinator compute under concurrency was not measured". Q2의 절에 통합. **SHOULD** (Q2의 일부로). |
| **S-4** | K11의 두 지점 목록에 없는 세 번째 "3.7× less coordinator state" 지점; 3.0×를 인쇄하는 섹션을 가리킨다 | `evaluation.tex` L177–178 | **R2-N5-2** | "coordinator **KV** state". 한 단어. **OPTIONAL.** |
| **S-5** | 서론의 지배 구절 "deployments that run on site"가 CASIT에 대해 단언되는데, 그 초록은 LLM-agent IoT 시스템을 기술하며 LLM이 디바이스에서 실행된다고 말하지 않는다 | `introduction.tex` L3–4 | **DA §3.4(1)** — R0 §3.2는 "collective agents over IoT devices" 절을 제목에 대조하여 정확함을 확인 | "run on site" 결속 없이 "LLM agents over IoT devices~\cite{zhong2024casit}", 또는 CASIT를 콜론의 두 번째 항목 뒤로 옮긴다. **OPTIONAL.** |
| **S-6** | "so …, and reconfiguration grows from 24.25 to 439.4 s"가 reconfiguration의 증가를 recomputation의 "so"에 매단다 | `evaluation.tex` L402–403 | **R1-NEW-25b** (사소) | "Reconfiguration grows" 앞에 마침표. **OPTIONAL.** |
| **S-7** | Mudassar의 핵심어 "adaptive"(지연 요구에 따라 checkpoint/restart 대 replication을 선택)가 압축되어 사라졌다 | `related.tex` L26–27 | **R2 §3** (연성; "not wrong") | 조치 불필요; 기록. |
| **S-8** | Fig. 1의 회색 백업 라벨(인쇄 ≈7 pt)은 더 진할 수 있다; 스테이지 $n$의 열이 패리티로 복구될 수 없음에도 스테이지 2의 것처럼 그려져 있다 | Fig. 1 | R0 S-11 · DA S-8 (둘 다 이월, 둘 다 R4에서 OPTIONAL) | **OPTIONAL**, 변경 없음. |

---

## 4. 응답서 대 파일 대조 결과

**대표적 결과: Round 2 이후 첫 허위 변경 서술 — OPTIONAL 항목에 대한 것 — 에 더해 허위 사유 하나, 오집계 하나, 누락된 포인터 하나, 공개되지 않은 편집 패스 둘. 필수 변경에 대한 허위 서술은 없음.** 5인 전원이 Round-4 헤더, 표 여섯 행 전부, "Applied after the Round-4 synthesis" 문단의 모든 절(13–14개 절)과 "Post-decision additions" 문단(5개 절), 그리고 R4 §4가 요청한 Round-3 정정들을 확인하였다. **5인 전원에 대해 참으로 검증:** 행 1–3, 5, 6; 파일이 쓰는 표현 그대로의 MUST 서술 여섯 건; K3, "coordinator KV state", 헤드 장애 경로, "whose recovery contract holds", "parity falls to replay beyond $k$", 527 ms, ±27, 9.9 million, Fig. 1 코디네이터 캡션, Fig. 3 mean(생성기 검증), `kosaian` 페이지; Fig. 1 행("the best row in the section" — R2); 목록으로서의 판정 이후 추가분 셋; 34 → 39; 갱신된 Round-3 "spread" 행(R4 L1 ✓); J8 등재 및 J10 인정(R4 L3 ✓); Fig. 1과 +1 번호 재부여 공개(R4 L6 ✓); "one numeric clause … was false"(R4 L7 ✓ — 3인; 충돌 **B7**).

| # | 응답서 문구 | 검증 결과 | 발견자 |
|---|---|---|---|
| **L1** | 적용 ¶: "the tolerance sentence says parity falls to replay beyond k **and fetches surviving columns at recovery**" | **두 번째 절에 대해 허위.** L232–237에도 새 본문 어디에도 그런 표현이 없다(`grep "at recovery"` → L10뿐; "surviving columns" → 기존의 L173–174). OPTIONAL 항목 18은 R4 B9에서 MUST로서 종결되었는데 적용되었다고 보고되어 있다. 원고는 아무것도 잃지 않는다; "described the intended edit rather than the one made"(만든 편집이 아니라 의도한 편집을 서술)(R0) | R0 §2(a) · R1-L5/NEW-23a · R2-L-b · R3-L8 · DA §2 — **5인 전원** |
| **L2** | 행 4: "§III-A now notes … **pointing to §IV-C's accounting**" | **절반만 참.** 괄호 구는 `design.tex` L34–35에 있다; `design.tex`에서 `grep "ref{sec:eval"` → 없음 | R0 §2(b) · R2-L-a · R3-L4 · DA §2 — 4인 |
| **L3** | "Not applied: … the eight-device search bound (**unverified**)" | **사유가 저자 자신의 코드에 대해 허위이다** — `scheduler.py:289`, `server.py:129, 205`, `all.yml.example:79` / `all.yml:143` (Q17) | R0 §2(e) · R1-L8 · R2-L-c · R3-L10 · DA §2 — **5인 전원** |
| **L4** | 판정 이후 ¶: "IoT-J entries 1 → **6**" | **7**: `zhang2024edgeshard` + §II-B 다섯 편 + `zhong2024casit`, 모두 `journal = {IEEE Internet of Things Journal}`, 모두 인용됨. R2는 6으로 집계(서론을 통해 들어오는 CASIT 누락). 저자 자신에게 불리한 과소 주장 | R0 §2(c) · R1-L10 · R3-L11 · DA §2 (7) 대 R2-L-h (6) — 충돌 **B8** |
| **L5** | 행 6: "J10's exactness novelty clause was applied (**§II-E**)" | **하나만큼 낡음.** 판정 이후의 §II-B가 Parity를 **§II-F**로 밀어냈다(pdftotext: A Distributed, B Fault Tolerance in Edge and IoT, C Recomputation, D Replication, E Reconfiguration, F Parity) | R0 §2(d) · R2-L-e · R3-L7 — 3인 |
| **L6** | 판정 이후 ¶는 추가분 셋만 열거 | **미공개:** CASIT가 들어간 서론의 재구성된 서두(커밋 `8777dc0`, `0644c81`), **삭제된** `zhang2026finetuning`(참고문헌의 유일한 삭제 — "34 → 39"는 하나가 삭제되고 여섯이 추가되었기에만 옳다), 초록의 네 문장 재구성, 여섯 파일에 걸친 문장 분할 약 20건(`dfb0520`, `91af728`, `0c064a6`), microscopy 문단의 재구성. R4의 미공개 Fig. 1과 같은 유형(R2) | R0 §2(f) · R2-L-d · DA (커밋 목록) — 3인 |
| **L7** | 미적용 목록 | **여전히 망라적이지 않음**(네 번째 라운드 — R3): 항목 14(여섯 벡터)는 어느 목록에도 없음; 항목 21의 "42 % less"; 항목 24; K13의 "(one was measured)"; 항목 18은 열거 대신 주장됨 | R0-N25 · R1-L13/NEW-23d · R2 · R3-L12 · DA — 항목 14에 대해 **5인 전원** |
| **L8** | Round-3 서두 "No false statement was found in the Round-2 letter" | **종결.** R0, R2, DA는 수정된 L85를 그대로 인용한다: "No false change description was found in the Round-2 letter; one numeric clause ('within two standard errors') was false and is corrected". R1-L12는 미수정으로 읽는다; 축자 인용 세 건이 이를 결정한다(**B7**) | R1-L12 대 R0 항목 16 · R2-N4-5 · DA errata 5 행 |
| **L9** | Round-2 마무리 "Abstract 258 words; 10 pages" | 과거 기록; 이제 255 / 11. 무해함, 세 번째 라운드 낡음 | R0 §2(g) · R2-L-f · DA §2 |

**편집 부기.** Round 2: 허위 변경 서술 네 건. Round 3: 허위 절 하나, 과장 셋. Round 4: 낡은 행 하나, 누락 하나, 과소 주장 하나, 미공개 그림 하나. **Round 5: OPTIONAL 항목에 대한 허위 변경 서술 하나, 허위 사유 하나, 오집계 하나, 누락된 포인터 하나, 미공개 패스 둘.** R3: "the letter remains a usable instrument"; R0: "both a grep away from detection, neither touching a number". 어떤 심사자도 재위촉되지 않으므로 응답서의 역할은 기록이다: L1–L7은 정오표와 함께 한 문단짜리 부록에 담는다(아래 SHOULD 12). 패널은 그 유형 — "described the intended edit rather than the one made" — 이 원고의 "as built"를 낳은 것과 같은 유형이며(Q1), 둘의 수정도 같음을 부기한다: 계획이 아니라 파일을 서술하라.

---

## 5. Devil's Advocate 판정

DA는 **새 CRITICAL을 제기하지 않았으며**, "Nothing blocks acceptance"로 시작하고, 자신의 R4 errata 다섯 건 중 넷을 해소하고 다섯 번째를 선언됨으로 기록한다. DA가 편집자에게 요구하도록 요청한 모든 항목과 모든 should-fix를 가시적으로 판정한다.

| DA 항목 | DA의 R5 상태 | 보강 / 반박 | **판정** |
|---|---|---|---|
| **Erratum 1** — 80 MB 미러의 "as built"; 구축물은 `int64` 마스크가 붙은 여섯 번째 blob을 프라이밍, ≈200 MiB | 요구: "as built" 삭제 또는 ≈200 MB 인쇄 | **여섯 벡터는 R1(행 11), R2(N5-1, 규칙 (a)), R3(NEW-2)가 보강 — 각자 독립적으로 `gateway.py:1735`를 읽음.** 마스크/컨테이너 개수는 DA 단독이며 미계산("torch was not available locally"); R1, R2, R3는 96 MiB를 계산. R0는 이 항목을 미선언으로 기록(N25) | **MUST-FIX로 인용(Q1)** — 규칙 (a): 저자 자신의 코드와 모순되는 실제 구축 수치 진술, 독립적 판독 4건, 그리고 적용되지도 선언되지도 않은 채 악화된 R4 등재 항목(K2 유형). **DA의 200 MB는 채택하지 않는다**(S-1): 패널은 어떤 개수 아래서도 정확한 재라벨을 처방하며 게이트하지 않은 수치를 제공하지 않을 것이다. 충돌 **B1**. |
| **Erratum 2 (a)** — "about 30 GB free"는 RAM 총량; 저자 자신의 노트는 ~7 GB라고 했다 | 요구: "32 GB board (about 30 GB of RAM)" | R1 행 12는 그 열이 총량임을 보강("~29 GB free; acceptable"); R0와 R3는 `REPORT.md:41`을 출처로 수용. ~7 GB 설계 노트는 단일 심사자, 2026-08-12자 위험 부기이지 측정이 아니며, 판가름할 수 없다 | **SHOULD-FIX로 하향(Q3)** — DA가 제안한 단어 교체는 정확하고 무비용이므로 채택한다; 실제 기준값이 ~7 GB였다는 주장은 기록하되 인용하지 않는다. 충돌 **B3**. |
| **Erratum 2 (b)** — "about 30"은 33.7; 논문의 3.0× 대비 암묵적 3.3× | 요구: "about 34" | R0(nit), R1(느슨함), R3(보수적 ✓) — 4인 모두 33.7을 본다 | **SHOULD-FIX(Q4).** "About"은 패널 자신의 선례에서 26.67→27과 9.86→9.9를 포괄한다; 33.7→30은 더 넓고 비교가 논문 자신의 비율보다 10 % 좋게 읽히므로, 권고하되 요구하지는 않는다. |
| **Erratum 2 (c)** — "room for roughly 100"이 요청 단위 축출의 256 MiB 저장소 셋 옆에 있다 | 요구: "(a derived projection; the prototype caps each store at 256 MB)" | R1-NEW-21(경미), R3-NEW-1(SHOULD, "would page someone at 3 a.m.") — 같은 메커니즘, 같은 코드 줄; 둘 다 문장이 허위는 아니라고 말한다 | **SHOULD-FIX로 하향, 최우선 순위(Q2).** 규칙 (a) 불충족 — 이 문장은 한 문장 앞에서 "a derived projection"으로 라벨된 메모리 산술이다(DA 자신의 양보) — 그리고 규칙 (c) 불충족(3인 중 1인 차단). 패널이 R4에서 SHOULD로 채점한 S-1 유형이며 R3도 동일하게 채점한다. 충돌 **B2**. |
| **Erratum 3** — `ao-1`이 R36.4.3이고 Nano가 MAXN SUPER인 플릿에 대한 "JetPack 6.1" | 요구: "6.1/6.2 (L4T R36.4.0–36.4.3)" | **R0-N18과 R1-NEW-20이 `PHASES.md:1995`에서 독립적으로 검증**; R0는 규칙 (a) 아래 "the only candidate"로 명명. R3는 "R36.4 covers both"로 수용; R2는 로그를 점검하지 않음. MAXN-SUPER ⇒ 6.2 추론은 릴리스 노트 지식(R1의 단서)이며 판정에 불필요 | **MUST-FIX로 인용(Q6)** — 저장소 사실만으로 규칙 (a). "of the size the panel has been grading SHOULD"라는 R1의 논변은 검토 후 기각: 9.8과 ±26은 "about"으로 덮인 패널 제공 수치였다; 이것은 헤지 없는 저자 제공 버전 라벨이며, 규칙은 크기로 등급을 매기지 않는다. 충돌 **B6**. |
| **Erratum 4** — Zhang (joint) "show … must be solved together"는 과잉 주장; 방법은 two-step | 요구: "argue … coupled … one formulation" | R0: "a shade stronger … acceptable"; R2: "'must' is the authors' inference … safer verb"; R3는 제목 수준에서만 확인 | **SHOULD-FIX로 하향(Q13).** 인용 논문의 특성화는 "the authors' own files, code or logs"가 아니다; 규칙 (a)는 거기에 미치지 않는다. DA의 "one formulation"(DA 자신의 two-step 판독이 이를 약화시킨다) 대신 R2의 동사와 R0의 초록 인용으로 채택. 충돌 **B4**. |
| **Erratum 5** — 응답서: "fetches …" 삭제; IoT-J 7; "unverified"; §III-A 포인터 | 요구 | 5인 전원이 L1과 L3를 발견; 4인이 L2와 L4를 발견 | **SHOULD-FIX(§4, SHOULD 12).** 후속 심사 라운드가 없으므로; 응답서는 기록이다. |
| **Should-fix: 복구 시 일시적 메모리(608 + 224 MiB)** | should | 단일 심사자; 반박되지 않음; R3의 연산 단서(S-3)가 인접한 요청 | **OPTIONAL(S-2).** 저자에게 불리하게 작용한다; 문단을 손댄다면 권고. |
| **Should-fix: `network_profile.bandwidth_bps`의 LAN 속도; `ao-2` 모드; 아티팩트 진술** | should | R1-NEW-24a/b, R3 §3, R0 §4가 셋 모두를 요청; R3는 프로브가 "not a link rate"라고 주장 | **SHOULD(Q7, Q8, Q9)** — 프로브는 *프로브로서* 인쇄할 수 있다; `ao-2`는 폐쇄 테스트베드 형태로. 충돌 **B5**, **B9**. |
| **Should-fix: CASIT "run on site"; "homes and buildings" 미인용** | should | R0 §3.2는 CASIT 절을 확인하여 정확함을 발견; R0와 R3는 미인용 예시도 지적 | **OPTIONAL(S-5, Q14).** |
| **Should-fix: Sun "failed" → "failing"; "after placement" 일반화의 축소** | should | R0 §3.2, R2-N5-3(둘 다); R3 §4(Ma) | **SHOULD(Q11, Q12).** |
| **Should-fix: K13의 "(one was measured)"; S-1의 여덟 디바이스 한계; "42 % less"** | should | R3 권고 6 / R2(K13); 5인 전원(S-1); 4인(42 %) | **SHOULD(Q18), SHOULD(Q17), OPTIONAL(Q20).** |
| **C7 잔여** — 세 순차 절차; 재시도 베이스라인 없음 | 미해소(UNCHANGED); 기존 MAJOR-비차단 | R2 Fairness 행: "the single-shot cost-first baseline (standing MAJOR-not-blocking, unrunnable)" | **기존 MAJOR, 비차단, 변경 없음.** 어떤 테스트베드도 이를 판가름할 수 없다; DA는 재개하지 않는다. |
| **§5 "strongest remaining counter-argument"** — "every number in [the sizing paragraph] that is not a multiplication is unsupported or wrong in the paper's own terms"; 유도하지 않고 옮겨 적는 양상이 "has moved from reviewer-supplied numbers to author-supplied ones" | — | R1: 16개 중 14개 수치가 정확히 재현, 느슨함 1, 한정어 오류 1; R0: 17건 재유도, 실패 없음; R3: "every arithmetic in §IV-C reproduces" | **부분 수용.** "As built"는 오류이고(4인) "free"는 총량에 붙은 라벨이며(R1 보강); "about 30"은 느슨하고; 상한은 누락이다. 그러나 ~7 GB 기준값과 ≈200 MB 미러는 DA 단독이며 미측정이므로 "unsupported or wrong"은 둘만큼 과장이다; 모든 곱셈과 두 한계는 어떤 해석 아래서도 재현된다. 패널은 DA의 *지침* — 수치를 담은 새 문단은 조판 전에 그것이 인용하는 파일에서 재유도한다 — 을 채택하며, 이 문단이 그 사례 연구임을 기록한다. |

**요약.** DA errata 두 건이 MUST로 인용(1, 3), 둘 다 규칙 (a)에 따라 저자의 코드와 로그로부터 두세 건의 독립적 보강과 함께; erratum 2는 SHOULD 셋으로 분할; erratum 4는 규칙 (a)의 범위 밖으로 SHOULD로 하향; erratum 5는 SHOULD(응답서). CRITICAL 제기 없음. DA의 R4 errata 다섯 건은 해소 또는 선언되어, 그 검증이 실제로 수행된다는 R3/R4 부기를 뒷받침한다 — 이번 라운드에는 모든 $P{=}32$ 평균을 소수 셋째 자리까지 재유도한 것을 포함한다.

---

## 6. 판정

### **ACCEPT WITH EDITOR-VERIFIED ERRATA(편집자 확인 정오표 조건부 채택)** — MUST-FIX 2건, 각각 구절 하나, 둘 다 Round-4 판정 시점에 존재하지 않았던 문단에; 추가 심사자 라운드 없음.

**근거.**

*패널은 수렴하였다.* 5인 중 5인이 채택을 권고한다; 4인은 교정 단계 항목을 붙여 곧바로 "Accept"를 쓰고 다섯 번째는 "accept after editor-verified errata"를 쓴다; 어떤 심사자도 추가 외부 심사를 요구하지 않는다; DA는 "Nothing blocks acceptance."로 시작한다. **모든 Round-4 MUST-FIX가 적용되었고 모든 심사자가 각자 독립적으로 파일에서 검증하였다** — 그리고 다섯 라운드 만에 처음으로 *모든 지점에서* 검증되었다: R1, R2, R3가 각각 모든 정오 문자열을 여섯 섹션 파일 전부에 걸쳐 grep하여 살아남은 쌍둥이를 찾지 못했다. R1의 조건 둘, R2의 절, R3의 정오, 그리고 Round 4의 DA errata 다섯 건 모두가 해소되거나 선언되었다. 채점된 18개 차원 중 9개가 상승하고 하락은 없다; 패널이 Round 1부터 책상 작업만으로 움직일 수 있다고 명명해 온 상한 둘 — R0의 Fit과 R3의 Deployability — 이 해제된 지면이 산 문단들에서 움직였고, R0는 네 라운드 동안 이월된 서지적 적합성 반론을 "answered on the merits"로 기록한다.

*무조건 채택에 미치지 못하게 하는 것은 새 본문의 검증된 사실 오류 둘과 패널 자신의 규칙이다.* 규칙 (a) — 지난 라운드에 정확히 이 크기의 결함에 대해 MUST-FIX K1과 K2를 낳은 규칙 — 아래에서, 저자 자신의 코드와 모순되는 수치 진술과 저자 자신의 로그와 모순되는 버전 라벨은 결과와 무관하게 MUST이다. **MUST 1**(Q1): "80 MB of mirror **as built**"는 다섯 벡터 회계이다; 코디네이터는 위치마다 여섯 번째 벡터를 프라이밍한다(`gateway.py:1735`, R1, R2, R3, DA가 독립적으로 읽음). 적용되지도 선언되지도 않은 채 새 문장에 의해 반박된 R4 SHOULD 14 — K2의 "악화" 유형 — 이며, R2는 이에 대해 규칙 (a)를 실명으로 원용한다. **MUST 2**(Q6): "The workers run JetPack 6.1" — `PHASES.md:1995`는 `ao-1`을 L4T R36.4.3(JetPack 6.2)으로 기록한다 — R0, R1, DA가 같은 줄에서; R0는 규칙 (a) 아래 "the only candidate"라 부른다. 어느 것도 측정, 파생 한계, 대표 수치를 건드리지 않는다; 각각 편집자가 저장소 한 줄에 대조하여 검증 가능하다; 각각 구절 하나이다.

*왜 무조건 채택이 아닌가.* R0와 R2는 각각 규칙 (a) 항목 하나를 교정 단계용으로 명명하면서 "Accept"를 권고한다; R1은 두 실수가 "of the size the panel has been grading SHOULD"라고 논변한다. 패널은 자신의 규칙을 크기로 등급 매기기를 거부한다: K1은 여섯 단어였고 K2는 삭제였으며, 둘 다 *저자 자신의 파일에 대조하여 허위로 검증되었기에* MUST였다. 그런 항목 둘을 검증되지 않은 제작 단계 정정으로 흘려보내는 것은 패널 자신의 네 라운드 관행과 일관되지 않으며, 편집자의 확인 비용은 각각 grep 한 번과 로그 한 줄이다.

*왜 Minor Revision이 아닌가.* Round-3의 기준: 저자 자신의 파일과 모순되는 진술 넷에 더해 스스로 만든 모순들일 때 Minor. 이번 라운드: 반박된 구절 둘, 둘 다 판정 이후 추가된 문단과 문장에 있으며, 편집자가 아닌 심사자가 보아야 할 것은 없다. R2: "I would apply it at proof … it does not need a reviewer." R1: "I do not need to see the manuscript again." R3: "I would not convene a panel for any of them." R0: "I would not hold a paper for it; I ask that it be corrected at proof."

*반면, 기록해 둔다.* 잔여는 이동하였다(DA §5): 측정된 주장은 Round 2 이후 안정적이고 재현 가능하며, 남은 것은 마지막 판정 이후에 쓰인 산문이다. 두 양상이 축소된 형태로 살아남아 있다. R1이 Round 4에 명명한 전파 양상은 어떤 MUST 문자열에서도 재발하지 않았으나, K9의 수정은 그 표적에서 열아홉 줄 하류에 안착하였고(Q16) SHOULD 14는 건너뛰어지고 미선언인 채 새 본문에 의해 반박되었다(Q1). 그리고 응답서의 유형 — "described the intended edit rather than the one made"(R0) — 은 두 라운드 만의 첫 허위 변경 서술(L1)을 낳았으며 "as built"를 낳은 것과 같은 습관이다. 편집자는 MUST 둘과 SHOULD 12에 대해 저자가 계획이 아니라 파일을 서술하도록 요청해야 한다.

**편집자를 위한 검증 지침.** MUST 1: `grep -n "as built" sections/evaluation.tex` → 이 구절이 80 MB 미러를 한정해서는 안 된다; 재라벨이 Table I의 다섯 벡터 회계를 명명하는지 확인한다; 코드 사실은 `radp/coordinator/gateway.py:1729–1735`(chain-head 스테이지에 대한 `self.cache.put(request_id, first_key, position, blob)`). MUST 2: `grep -n "JetPack 6.1" sections/evaluation.tex` → "L4T R36.4.0–36.4.3"과 함께 "6.1–6.2"(또는 보드별)로 읽혀야 한다; 로그 사실은 `PHASES.md:1981`(`ao-2` R36.4.0) 옆의 `PHASES.md:1995`(`ao-1` R36.4.3). 어느 것도 테스트베드가 필요 없다. 어떤 심사자도 재위촉될 필요가 없다.

**상한(기록용, 차단 사유 아님).** Significance 5(R0) — 규모 산정 문단은 "the first place the paper says *when* its advantage binds"이나 여전히 파생 projection이며, W4는 유지된다; Novelty 6(R2) — §II-B는 위치를 잡을 뿐 메커니즘을 더하지 않는다; Motivation–evaluation 6(R3) — 링크 가변 실험, 구조상 도달 불가; Experimental design 6과 Statistical validity 6(R1) — "nothing measured, nothing could be". Fit 7(R0), 19-토큰 유선 LAN 워크로드와 트래픽·에너지 부재로 8 아래에 머무름 — 테스트베드에 묶임. 5인 모두 결과적 규모가 IoT-J에 게재 가능하다고 본다.

---

## 7. 정오표 R5

번호 부여, 중복 제거, 충돌 해소. 모든 항목은 저자가 이미 보유한 구절이다; 어느 것도 테스트베드나 지면을 필요로 하지 않는다.

### MUST-FIX (확정본(version of record) 이전 편집자 검증)

1. **`evaluation.tex` L246–247** — "80\,MB of mirror as built" → "80\,MB of mirror by Table~I's five-vector accounting (the prototype also primes the head's input, 8\,kB per token)"; L230–231의 3.0×/42 %를 출하된 다섯 벡터로 범위 한정하거나 2.9×/41 %로 재계산. *(Q1 — R2-N5-1, R1-NEW-22, R3-NEW-2, DA erratum 1, R0-N25; 충돌 B1)*
2. **`evaluation.tex` L44–45** — "JetPack 6.1 (L4T R36.4," → "JetPack 6.1–6.2 (L4T R36.4.0–36.4.3," 또는 보드별로, `PHASES.md:1981, 1995`에 따라. *(Q6 — R0-N18, R1-NEW-20, DA erratum 3; 충돌 B6)*

### SHOULD-FIX (같은 작업에서; 지면 불필요)

3. **`evaluation.tex` L249–251** — "(a derived projection and a memory bound: the prototype's parity and mirror stores default to 256\,MB each and evict whole requests, so the bound assumes they are raised; coordinator compute under concurrency was not measured)"를 덧붙인다. *(Q2 + S-3 — R1-NEW-21, R3-NEW-1/NEW-3, DA erratum 2c; 충돌 B2)*
4. **`evaluation.tex` L249** — "has about 30\,GB free" → "is a 32\,GB board with about 30\,GB of RAM". *(Q3 — DA erratum 2a, R1 행 12; 충돌 B3)*
5. **`evaluation.tex` L250** — "about 30" → "about 34" (또는 "about a third as many"). *(Q4 — R0-N19, R1 행 13, R3 §2, DA erratum 2b)*
6. **`evaluation.tex` L48–49** — "`ao-2` as flashed" → 저자가 로그를 보유하고 있다면 그 모드, 아니면 "`ao-2` at its flashed default (power mode not recorded; the factory default is 30\,W)". *(Q7 — R1-NEW-24a, R3-NEW-4, DA §3.2, R0-N18; 충돌 B9)*
7. **`evaluation.tex` L50** — 프로브로 라벨한 "(the scheduler's gRPC probe measured 16–24\,Mbit/s between worker pairs)", 또는 보유하고 있다면 공칭 링크 속도; 여기에 아티팩트/코드 가용성 문장 하나. *(Q8, Q9 — R1-NEW-24b, R3 §3, DA §3.2, R0 §4; 충돌 B5)*
8. **`related.tex` L27–28, L32–34, L34–36** — Sun: "away from nodes identified as failing"; "where a substitute node exists, it is chosen after…"; Zhang (joint): "argue that the two placement decisions are coupled and solve them in one combined process". *(Q11–Q13 — R0 §3.2, R2-N5-3, R3 §4, DA erratum 4; 충돌 B4)*
9. **`discussion.tex` L68–69** — "the head stage is outside the parity guarantee and the coordinator is unprotected". *(Q16 — R0-N24, R2-N5-5, R3-NEW-6; K9의 쌍둥이)*
10. **`design.tex` L225** — "the prototype searches up to eight devices (109\,592 orderings) and falls back to heartbeat order above that". *(Q17 — R1 S-1, R2-L-c, R3 S-1, R0-N27, DA; 5인 전원)*
11. **`evaluation.tex` L232** — "any number" 뒤에 "(one was measured)". *(Q18 — R3 권고 6, DA K13 행, R2)*
12. **응답서 부록** — "and fetches surviving columns at recovery" 삭제; "pointing to §IV-C's accounting"을 삭제하거나 `\ref` 추가; "unverified" → 적용됨 또는 "by choice"; "IoT-J entries 1 → 7"; "§II-E" → "§II-F"; 서론 재구성, 삭제된 `zhang2026finetuning`, 초록 재구성, 문장 분할 패스를 공개; 항목 14와 그 밖의 미적용 항목을 열거. *(§4 L1–L7 — 5인 전원; 충돌 B7, B8)*

### OPTIONAL

13. `evaluation.tex` L211–213 — "at $P{=}32$"가 더 이상 $P<10$ 절을 지배하지 않도록 "(40\,kB per token; 2.3\,s at $P{=}32$)". *(Q19 — R0-N23, R1-NEW-25a, R2)*
14. `introduction.tex` L3–4 — "assistants in homes and buildings"를 인용하거나 삭제; CASIT를 "run on site"에 결속하지 않는 "LLM agents over IoT devices". *(Q14, S-5 — R0, R3, DA §3.4)*
15. `evaluation.tex` L231 "42\% less"; L245 $N_{\mathrm{ctx}}$ 정의; L177–178 "coordinator KV state"; `related.tex` "P. Zhang" / "X. Zhang". *(Q20 — R0, R2, R3, DA; Q5 — R0-N19; S-4 — R2-N5-2; Q15 — R0-N26)*
16. `evaluation.tex` §IV-C — "a recovery additionally holds the surviving columns transiently (about 0.8\,GB at 7B)". *(S-2 — DA §3.1(v))*
17. `evaluation.tex` L46–47 — 설치된 대로의 grpcio/protobuf; Xavier의 JetPack 5 마이너 버전. *(Q10 — R3 §3)*
18. `evaluation.tex` L402–403 — "Reconfiguration grows" 앞에 마침표. *(S-6 — R1-NEW-25b)*
19. 저장소 — `background.tex` 삭제; 저장소에서 한 번 빌드하고 `main.log` 커밋; 저장소 자신의 관례에 따라 §II-B의 PDF 다섯 편을 `paper/refs/`에 목록화. *(Q22 — R0, R2, R3; Q21 — R0-N28, R1, R3; Q23 — R1, R3)*
20. Fig. 1 — 백업 라벨을 더 진하게; 스테이지 $n$의 열이 replay로 넘어간다는 캡션 한 마디. *(S-8 — R0 S-11, DA S-8; 이월)*

---

## 8. 다섯 라운드의 궤적

Round 1은 만장일치 Major였다: DA CRITICAL 8건, 경쟁자에게 0 kB/tok을 부여한 Pareto 문장, 백업 가중치를 누락한 footprint, 그리고 시스템 그림의 부재. Round 2는 논문 못지않게 응답서 때문에 Major에 머물렀다 — 허위 변경 서술 네 건, 낡은 그림 둘, 섹션을 넘나들며 서로 싸우는 163 ms와 183 ms. Round 3는 Minor에 도달했는데, 응답서가 허위 진술을 실명으로 철회하였고, MUST 15건이 단어 수준의 9건이 되었으며, DA가 모든 파생 수치를 재계산하여 하나의 오류를 찾아냈기 때문이다. Round 4는 그 9건이 적용되고, CRITICAL이 해소되며, Round 1부터 논문에 없던 그림이 추가되어 코드에 대조 검증되고, 잔여가 다섯 줄 — 그중 하나는 패널이 쓴 것 — 이 되었을 때 정오표 조건부 채택에 도달했다. 이번 라운드에 그 다섯은 모든 지점에서 적용되었고, 저자가 산 페이지는 네 라운드의 심사자들이 요청해 온 세 문단에 쓰였으며, 그림은 요구된 것 이상으로 다시 그려졌고, 아홉 차원이 움직이고 어느 것도 떨어지지 않았으며, 책상 작업으로 움직일 수 있었던 상한 둘 — 저널 적합성과 배포 가능성 — 이 움직였다. 잔여는 새 본문의 구절 둘이며, 둘 다 저자 자신의 저장소에 대조하여 검증되었고, 둘 다 편집자에게는 grep 한 번이다. 다섯 라운드가 보여 주는 것은 단조롭게 줄어드는 결함의 종류 — 허위 응답서 진술, 다음은 허위 범위 주장, 다음은 낡은 행, 다음은 옮겨 적은 괄호 구 하나, 이제는 잘못 라벨된 수치 하나와 버전 문자열 하나 — 와, 그 내내 변함없이, 중요한 곳마다 저자의 이익에 반하는 방향으로 움직인 개정이다: 부과된 백업 가중치, 인쇄된 두 비율, 저자 자신에게 불리하게 남겨 둔 Reconfigure 부팅 실패, 첫 번째와 같이 구성되지 않았다고 공개된 두 번째 AGX. DA의 마무리 관찰이 옳으며 패널은 이를 이 판정에서 살아남는 유일한 지침으로 채택한다: 측정된 주장은 Round 2 이후 안정적이고 재현 가능하며, 마지막 측정 이후에 쓰인 모든 수치는 조판 전에 그것이 인용하는 파일에서 재유도되어야 한다. **MUST 1과 MUST 2가 적용되고 편집자가 검증하면, 패널은 이 논문이 확정본(version of record)에 준비되었다고 본다.**

---

## 심사자 간 충돌 중재

**B1 — Q1의 수정: 96 MB(R1, R3) 대 재라벨-80 유지(R2의 두 번째 형태) 대 "as built" 삭제 또는 ≈200 MB 인쇄(DA).** 심사자 4인이 `gateway.py:1735`에서 여섯 벡터를 검증한다; DA만이 `int64` 마스크와 컨테이너를 더하며, DA는 컨테이너를 미계산으로 보고한다. **결정: 재라벨.** "By Table I's five-vector accounting (the prototype also primes the head's input, 8 kB per token)"은 구축물이 96이든 200 MiB든 참이며, 패널은 — 이전 라운드들에서 493, 9.8, ±26을 제공한 바 있으므로 — 게이트하지 않은 수치를 인쇄하지 않을 것이다. 저자가 요청당 RSS 델타를 보유하고 있다면 인쇄해도 좋다; 패널은 요청하지 않는다.

**B2 — Q2(256 MiB 상한): MUST(DA) 대 SHOULD(R1, R3).** 3인 모두 같은 코드 줄을 읽고 메커니즘에 동의한다; R1과 R3는 둘 다 문장이 허위가 아니라고 말한다; DA 자신도 앞 문장이 그 수치를 "a derived projection"으로 라벨함을 부기한다. **결정: SHOULD, 최우선 순위.** 규칙 (a)는 허위이거나 내적으로 불일치하는 진술을 요구한다; 인접한 projection 라벨이 붙은 참인 메모리 한계는 누락이다 — Round 4에서 SHOULD로 채점되었고 이번 라운드 R3가 "the same"으로 채점한 S-1 유형. 규칙 (c)는 차단 3인이 필요하다; 1인이 차단한다. R3의 "would page someone at 3 a.m."이 SHOULD 가운데 최우선으로 두고 S-3와 같은 절에 통합하는 이유이다.

**B3 — Q3("about 30 GB free"): DA 대 R0, R1, R3.** R1 자신의 판독이 `REPORT.md:41`의 열이 `MemTotal`임을 보강하고("total as `free` reports it") 그럼에도 ~29 GB free로 acceptable로 채점한다; R0와 R3는 출처를 수용한다. DA의 ~7 GB는 측정이 아니라 설계 노트의 위험 부기에서 온 것이며, 저장된 어떤 프로파일도 `ax-1`을 다루지 않는다. **결정: SHOULD, DA의 표현.** "A 32 GB board with about 30 GB of RAM"은 어떤 해석 아래서도 정확하고 무비용이다; ~7 GB 주장은 검증할 수 없고 테스트베드가 폐쇄되었으므로 기록하되 인용하지 않는다.

**B4 — Q13(Zhang "show … must"): 요구(DA) 대 acceptable(R0) 대 더 안전한 동사(R2).** **결정: SHOULD.** 규칙 (a)는 "the authors' own files, code or logs"에 미친다; 인용 초록의 특성화는 그 밖이며, 초록을 읽은 R0는 "must"를 a shade strong이나 acceptable로 채점한다. 수정은 R2의 동사와 R0의 초록 인용("a complete process combining")을 쓴다; DA의 "in one formulation"은 DA 자신의 판독이 방법을 two-step이라 말하므로 피한다.

**B5 — Q8(LAN 속도): "nothing to print"(R3) 대 "the rate was measured"(DA).** 둘 다 옳다: 저장된 `network_profile.bandwidth_bps`는 애플리케이션 수준 gRPC 프로브(1 MiB 페이로드)이지 링크 속도가 아니다. **결정: SHOULD, 라벨 명기.** 프로브를 *스케줄러의 프로브로서* 인쇄하거나, 저자가 보유하고 있다면 공칭 링크 속도를 인쇄한다; 프로브를 링크 속도로 인쇄하지는 않는다.

**B6 — Q6(JetPack): MUST(DA; R0 "the only rule-(a) candidate") 대 "SHOULD-sized"(R1) 대 수용(R3, R2).** R3는 `PHASES.md:1995`를 읽고 "R36.4"가 두 패치 레벨을 모두 포괄한다고 수용하였다 — L4T 절에 대해서는 참이나 JetPack 절에 대해서는 침묵이다; R2는 릴리스 쌍 일관성만 점검하였다. **결정: MUST.** 심사자 3인이 저장소 줄로부터 모순을 검증한다; R1의 크기 논변은, 패널이 R4에서 SHOULD로 채점한 수치(9.8, ±26)는 패널이 제공하고 "about"으로 헤지된 것인 반면 이것은 헤지 없는 저자 제공 라벨이므로 기각한다. MAXN-SUPER ⇒ 6.2 추론은 릴리스 노트 지식(R1의 단서)으로 기록하며 판정의 일부가 아니다.

**B7 — L8(Round-3 서두): "still uncorrected"(R1-L12) 대 수정됨(R0 항목 16, R2-N4-5, DA errata-5 행).** 심사자 3인이 수정된 형태의 L85를 그대로 인용한다("… one numeric clause ('within two standard errors') was false and is corrected"). **결정: 종결.** R1의 L12는 그 인용에 의해 추월된다.

**B8 — L4(IoT-J 집계): 7(R0, R1, R3, DA) 대 6(R2).** R2는 EdgeShard와 §II-B 다섯 편을 세고 서론을 통해 들어오는 `zhong2024casit`을 누락하였다; R0는 일곱 편 모두를 키로 열거한다. **결정: 7.** 응답서는 저자 자신에게 불리하게 과소 주장한다.

**B9 — Q7(`ao-2` 모드): "read it and print it"(R3) 대 폐쇄된 테스트베드.** `nvpmodel -q`는 실행할 수 없다. **결정:** 폐쇄 테스트베드 형태 — "power mode not recorded; the factory default is 30 W" — 단, 패널이 찾지 못한 로그 줄을 저자가 보유하고 있다면 예외; R1의 "say the mode or say 'not recorded'"가 채택된 형태이다.

**B10 — 채택(R0, R1, R2, R3) 대 정오표 이후 채택(DA).** 5인 모두 편집자를 위한 항목을 적어도 하나 명명한다; 2인(R0, R2)은 "Accept"를 쓰면서 각각 한 항목에 대해 규칙 (a)를 원용한다. **결정: 편집자 확인 정오표 조건부 채택**, 패널 자신의 Round-4 관행(§6)과의 일관성을 위해: 라벨은 크기가 아니라 규칙을 따른다.

---

*편집 종합자(Editorial Synthesizer) 작성. 위의 모든 항목은 명시된 Round-5 심사자 보고서와 항목 id로 추적된다. 이 판정을 작성하는 과정에서 원고, 그 소스, 코드, 로그, 결과 파일을 읽거나 수정하지 않았다; 모든 인용, 줄 번호, 파일 참조는 다섯 심사자 보고서와 Round-4 판정에서 취하였다.*
