# 랩미팅 0805 — Claude for PowerPoint 프롬프트

`ppt/Progress Report_0805.pptx`(figure가 이미 심어진 복사본)를 열고 아래를 그대로 붙여넣는다.

---

**너(Claude for PowerPoint)는 열린 이 덱만 볼 수 있다** — 디스크의 `DESIGN_SYSTEM.md`나 그림
파일은 못 읽는다. 그래서 필요한 걸 전부 이 덱 안에 넣어뒀다:

- **서식 규격은 이 덱의 예시 슬라이드에 이미 구현돼 있다.** 새 레이아웃을 발명하지 말고 기존
  슬라이드의 패턴 — 섹션 밴드 / 워크스트림 제목(24pt) / 소제목(16pt **굵게**) / 표 스타일 /
  색 — 을 그대로 복제해라. 좌표·폰트·색을 새로 정하지 마라. 예시 슬라이드에서 복사해라.
- **그림 2종은 덱 끝의 "STASH" 슬라이드에 이미 얹혀 있다.** 파일에서 다시 불러오지 말고 그
  이미지를 해당 슬라이드로 **옮겨라**(각 STASH 슬라이드의 빨간 메모가 목적지를 지정). 다 옮긴
  뒤 STASH 슬라이드는 삭제. 배율은 건드리되 그림을 다시 그리거나 그림 안 글자를 고치지 마라.

**문체: 음슴체 또는 명사 종결.** 존댓말·서술체로 바꾸지 마라. 숫자 없는 형용사 새로 넣지 마라.
**영단어 뒤 한국어 조사는 붙여 써라** (`KV-RAID는`, `P=32에서`, `k=2로`, `on-1은`). "not X but
Y" 반전 쓰지 말고 사실을 직접 말해라.

**그림 안 글자는 영어다.** 슬라이드 본문은 한국어, 그림 안은 영어 — 손대지 마라.

**작업 전 처리:** 안 쓰는 예시 패턴 슬라이드는 삭제한다. 워크스트림 소제목은 **굵게**.

**정확성이 서식보다 우선한다.** 인테이크에 없는 숫자는 지어내지 말고 비워두고 물어봐라.

> **네이밍 바뀜(이번 주부터).** baseline은 reference 논문명으로 — full-replay→**Recompute**,
> surgical→**Petals**, replicate→**DejaVu**, reactive→**Reconfigure**. 우리 방식 parity→**KV-RAID**
> (단일 실패 = KV-RAID-5, 이번 주 추가한 이중 실패 = KV-RAID-6). **이 매핑을 맨 앞 slide(목차
> 다음)에서 먼저 소개**하고, 이후 덱 전체에서 새 이름만 쓴다.

> **이번 주는 새 기술(KV-RAID-6) 도입 주다.** 원리(작동) → 비용/상한 → 실측 순서. 숫자를 원리
> 앞에 두지 마라. Recompute/Petals/DejaVu/Reconfigure는 지난주(0730)에 이미 소개 — 반복하지 말고
> recap 1장으로 압축.

---

## 인테이크

**날짜:** 2026-08-05
**이번 주 헤드라인:** 동시 2-실패를 O(1) 저장(blob 2개)으로 복구 — 라이브 5/5 bit-correct

> **헤드라인이 들어가는 자리 = KV-RAID-6 실측 슬라이드의 소제목.** 표지·별도 제목 슬라이드가
> 아니라 **핵심 슬라이드의 소제목(=주장, 16pt 굵게)** 으로 간다. **표지는 원본 그대로 안 건드림.**
> 각 슬라이드 소제목은 라벨이 아니라 주장 — 아래에 미리 박아둔다.

### 네이밍 정리 (맨 앞 framing slide — 목차 다음)

> 덱 전체가 새 이름을 쓰므로 매핑을 먼저 박아둔다. 이 slide는 §1(Summary)의 리드.

- **소제목(주장):** 복구 계열 이름 정리 — baseline은 논문명, 우리 방식은 KV-RAID
- 시각물: **STASH의 fig_recovery_families** — Recompute/Petals/KV-RAID 복구 비용 사다리(같은 장애, 계열별 재계산량). 새 이름이 그림에서도 일관
- 네이밍 표:

  | 구 | 신(reference) | 역할 |
  |---|---|---|
  | full-replay | **Recompute** | strawman (DejaVu가 이기는 null baseline) |
  | surgical | **Petals** | input-replay (Petals, exact 매치) |
  | replicate | **DejaVu** | KV replication baseline |
  | reactive | **Reconfigure** | re-solve+cold restart (SpotServe) |
  | parity (우리) | **KV-RAID** | 우리 방식 (KV-RAID-5 단일 / KV-RAID-6 이중) |

### 지난주 계획 → 대응 (P1 표)

7/30 미팅의 「다음 1주」계획 대비 대응 + 이번 주 새 방향.

| 7/30 계획 | 이번 주 대응 |
|---|---|
| KV shipping 상시 네트워크 비용 정량화 | 계열별 분해 완료(mirror 8192 B always-on + KV 컬럼). 단 교수님 #4로 **논문에선 제외**, 코드만 유지 |
| 재계산 복구 KV의 tier 간 정합성(백로그 B4) | 실측 완료 — DejaVu/KV-RAID는 bit-exact 보장, 재계산 계열(Recompute/Petals)은 cuda↔cpu 26.9% 불일치(무보장) |
| (새 방향) KV-RAID를 동시 2-실패로 확장 | **KV-RAID-6(double-parity)** 구현·라이브 측정 5/5 완료 |

### 워크스트림별 진행 (§2)

> **흐름 고정.** (recap 슬라이드 없음 — 지도교수가 지난 미팅에 있었음. 네이밍은 맨 앞 §1 리드, 계획↔대응은 그다음) KV-RAID-6 작동(1) → 비용·상한(2) → 실측(3, 헤드라인) → DejaVu 검증(4). KV-RAID-6가 왜 필요한지(단일 실패만 됨)는 작동 슬라이드의 「기존 한계」 한 줄로 흡수.

**1. KV-RAID-6 — 작동 (원리)**
- **소제목(주장):** 패리티 blob 2개(P·Q)로 동시 2-stage 복원 — RAID-6 = k=2 Reed-Solomon
- a. 기존 한계: KV-RAID-5는 XOR blob P 1개 → 방정식 1개로 미지수 2개 못 풂 → 2개 죽으면 Petals로 폴백(비쌈)
- b. 작동: 두 번째 blob **Q(GF(2⁸) 가중합)** 추가. 2개 죽으면 P·Q로 **2×2 GF 연립** 풀어 둘 다 재계산 0으로 복원. 토글 `RADP_PARITY_K=1|2` — **k=1은 KV-RAID-5 그대로**, k=2도 단일 실패는 P만 써서 RAID-5 포함
- b2. 선행: **RAID-6 = k=2 Reed-Solomon 소거부호**(Anvin). store-KV 데이터센터(DejaVu 복제 / GhostServe erasure-coding)를 이종 엣지 다중실패 레짐으로 옮긴 것 — GhostServe가 cross-node pipeline parity를 future work로 남긴 자리
- 워커 무변경: Q는 coordinator가 기존 push된 컬럼으로 계산

**2. KV-RAID-6 — 비용과 상한**
- **소제목(주장):** 저장 blob 2개 — k≥3(일반 RS)은 DejaVu에 짐, 그래서 k=2가 상한
- 시각물: **STASH의 fig_storage_tolerance** — 저장 × 실패내성. KV-RAID-5(1 blob, f=1)·KV-RAID-6(2 blob, f=2)이 DejaVu 선 아래, f≥3은 crossover 위로
- c. 트레이드오프: 저장 = KV-RAID-5 **16384** / KV-RAID-6 **32768** / DejaVu **36864** B/tok. 단일 실패는 여전히 P만 → RAID-5 비용 그대로. 워커 무변경
- d. 상한: **정확히 2개까지**. k-parity가 DejaVu 이기려면 `k < Σ/max` (balanced면 non-head 개수). 우리 fleet `Σ/max=2.25` → k=1,2만 이기고 **k=3부터 저장이 DejaVu 초과(1.33×)+내성 약함 = dominated**. 일반 RS는 balanced 큰 파이프라인 future work

**3. KV-RAID-6 — 라이브 실측 (이번 주 핵심)**
- **소제목(주장) = 이번 주 헤드라인:** 동시 2-실패 라이브 복구 5/5 bit-correct, 복구시간 실패위치 무관
- 실측(라이브 fleet, victim `on-1`+`on-6` 동시): 5개 포지션(P=4·8·16·24·32) 전부 **출력이 무장애 reference와 정확 일치(5/5)** + GF double-reconstruct 분기 발화 확인
- `TTR(P) = 30.29 s + 2.78 ms·P` → **slope ≈ 0**(재계산 0 시그니처). 단일 실패 KV-RAID(0.87)·DejaVu(2.67)와 같은 평탄대, Petals(16.2)·Recompute(164) 대조

  | 복구 방식 | slope (ms/pos) | shape |
  |---|---|---|
  | Recompute (full-replay) | 164 | P에 비례↑ |
  | Petals (surgical) | 16.2 | P에 비례↑ |
  | KV-RAID (단일, k=1) | 0.87 | 평탄 |
  | DejaVu (replicate) | 2.67 | 평탄 |
  | **KV-RAID-6 (2-실패)** | **2.78** | **평탄** |

- **정직 캐비엇(반드시 슬라이드에):** 절편 **30.3 s = 축퇴 복구테이블 인공물** — 알고리즘 비용 아님. 이 fleet 자동 R이 non-head 백업을 전부 `on-2`로 몰아, 2-victim이면 약한 Nano `on-2`가 3-stage 호스팅+cold-load(같은 fleet 단일 실패 KV-RAID는 284 ms). 집중은 상수 offset만 더해 **slope는 안 오염**. 깨끗한 절대 TTR은 백업 분산 R 필요(future work)
- 라이브 버그 발견·수정: `on-1`이 head 바로 뒤라 크래시가 head로 오귀속 → double-dispatch보다 head-check가 먼저 발화해 폴백하던 것. dispatch를 dead-set 기준으로 앞당겨 수정, 5/5 정상

**4. DejaVu 인용 검증**
- **소제목(주장):** 우리 DejaVu baseline은 원 논문 알고리즘을 충실히 대표 — 차이는 replica 위치뿐
- DejaVu(replicate) baseline이 원 논문 알고리즘과 **핵심 동일**: KV state 비동기 복제 → 죽은 stage 재계산 대신 복원, 미복제 tail만 재계산
- 차이는 **replica 위치** — DejaVu는 ring 이웃 워커(분산), 우리는 coordinator(중앙집중). 저장 O(N)·복구 프로파일은 동일 → baseline으로서 cost/recovery 충실히 대표
- 인용: "DejaVu-style KV replication, adapted to our coordinator-centric architecture" — verbatim 재구현 아님(ring-neighbor·DejaVuLib·disaggregation은 미구현)

### 한계 (반드시 슬라이드에 올릴 것)

- **KV-RAID-6 깨끗한 절대 TTR 미측정** — 이 fleet 축퇴 R로 절편 30 s(slope는 무관). 백업 분산 R에서의 측정이 future work
- **동시 2개까지만**(k=2). k≥3(일반 RS)은 이 fleet에서 DejaVu에 dominated
- **DejaVu baseline은 replica 위치가 다름**(coordinator vs ring 이웃) — 알고리즘 핵심은 동일하나 verbatim 재구현 아님
- 측정은 5-워커 CUDA/AGX fleet, 인접 2-victim(`on-1`+`on-6`). 비인접 쌍은 구조적으로 맞으나 미측정

### 다음 1주 (P5, 3줄)

- TII 원고 FT 절을 **KV-RAID 네이밍 + 저장×내성 프레이밍**으로 작성(intro는 recovery-first 초안 완료)
- 백업 분산 R로 KV-RAID-6 깨끗한 절대 TTR 재측정 검토
- 비인접 2-victim 커버리지 테스트 추가

---

## 예상 구성 (참고 — 내용이 정하되 대략 이 정도)

1 표지 / 2 목차 / **3 네이밍 정리(맨 앞 framing, 매핑 표 + fig_recovery_families)** /
4 지난 계획↔이번 주 대응(P1) / 5 KV-RAID-6 작동 / 6 KV-RAID-6 비용·상한(storage×tolerance) /
7 KV-RAID-6 실측(**헤드라인 소제목**, 표+캐비엇) / 8 DejaVu 인용 검증 / 9 한계 / 10 P5 계획 → 10장

recap 슬라이드 없음(2026-08-05 skill 변경). 네이밍 framing 1장 + 계획↔대응 1장 + 작동·비용·실측 3장 + DejaVu 검증 1장.
