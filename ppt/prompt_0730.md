# 랩미팅 0730 — Claude for PowerPoint 프롬프트

`Progress Report_0721.pptx`(또는 템플릿 `ppt/template/radp-progress-template.pptx`) 복사본을
열고 아래를 그대로 붙여넣는다.

---

이 파일의 서식 규격은 `ppt/DESIGN_SYSTEM.md`에 있다. **§1~§8을 먼저 읽고 그대로 따라라.**
좌표·폰트·색·표/그림 규격을 여기서 다시 설명하지 않는 이유는 그 문서와 템플릿 안에 이미 있기
때문이다. 새 레이아웃을 발명하지 말고 §8 패턴에서 골라 복제해라.

**문체는 §8 「문체」 절을 그대로 지켜라.** 아래 인테이크 문구는 이미 그 규격으로 썼다. 문장을
다듬을 일이 생기면 **음슴체 또는 명사 종결**을 유지하고 존댓말·서술체로 바꾸지 마라. 숫자 없는
형용사를 새로 넣지 마라. **영단어 뒤 한국어 조사는 붙여 써라** (`parity는`, `P=32에서`, `on-1은`).

**그림 안 글자는 영어다.** 슬라이드 본문은 한국어, 그림 안은 영어 — 손대지 마라. 그림을 다시
그리지 말고 아래 경로 파일을 **배율 100%** 로 얹어라.

**작업 전 처리:** 안 쓰는 패턴 슬라이드는 삭제한다. 워크스트림 소제목은 **굵게**.

**§11 정확성 규칙이 서식보다 우선한다.** 인테이크에 없는 숫자는 지어내지 말고 비워두고 물어봐라.

> **이번 주는 follow-up이다.** parity·surgical·full-replay는 지난주(0721)에 이미 원리까지
> 소개했다. 그 세 개의 원리 슬라이드를 반복하지 마라 — recap 1장으로 압축하고, 이번 주 새
> 내용(replicate·reactive·2D Pareto)에 지면을 써라.

---

## 인테이크

**날짜:** 2026-07-30
**이번 주 헤드라인:** parity만 좌하단 — TTR 동률, 저장 **2.25× 적음**

> **헤드라인이 들어가는 자리 = 3번(2D Pareto) 슬라이드의 소제목.** 헤드라인은 표지나 별도
> 제목 슬라이드에 넣는 게 아니라 **핵심 슬라이드의 소제목(=주장, 16pt 굵게, 워크스트림 제목 바로
> 아래)** 으로 간다 (DESIGN_SYSTEM §「슬라이드 제목은 라벨이 아니라 주장」). **표지는 원본 그대로
> 안 건드림.** 각 슬라이드도 소제목이 라벨이 아니라 주장이어야 한다 — 아래 워크스트림마다 소제목을
> 미리 박아둔다.

### 지난주 계획 → 대응 (P1 표)

7/21은 진행 확인 — 별도 피드백 없었음. 지난주 「다음 1주」 계획 대비 대응만 싣는다.

| 지난주 계획 | 이번 주 대응 |
|---|---|
| 다른 baseline을 같은 fleet에서 비교 | zero-recompute 라이벌(replicate) + no-backup 극단(reactive) 측정 완료 |
| (그로써) parity 우위 격리 | 1D TTR → **2D Pareto(TTR × 저장)** 재프레이밍 — parity만 좌하단 |

### 워크스트림별 진행 (§2)

> **흐름 고정.** recap(0) → 새 baseline 2종(1, 2) → 종합 그림(3) → 한계 → 다음.
> 각 새 baseline은 **원리 한 줄 → 실측 → 한 줄 결론** 순서. 숫자를 원리 앞에 두지 마라.

**0. 지난주 요약 (recap, 1장)**
- **소제목(주장):** 지난주 — parity만 기울기 ≈ 0. 근데 그게 재계산 때문인가?
- 3계열 TTR(P): full-replay **164** / surgical **16** / parity **0.87** ms/pos — parity만 기울기 ≈ 0 (재계산 0)
- 이번 주 질문 한 줄: **parity의 우위가 정말 "재계산 0" 때문인가?** → 다른 zero-recompute 전략과 붙여봐야 격리됨
- 캡션: OPT-350M 24층 / 5-stage 이종 체인 / victim `on-1`

**1. replicate — full KV replication (parity의 TTR 라이벌)**
- **소제목(주장):** replicate도 재계산 0 — TTR로는 parity와 안 갈림
- b. 원리 (한 줄): parity에서 **XOR만 뺀 것** — stage별 KV를 통째로 coordinator에 저장했다 그대로 install. 재계산 0, **저장하는 것만 다름**(N벌 vs XOR 1장)
- e. 실측 (P4 표에 한 행 추가하거나 recap 표에 병기):

  | 복구 방식 | TTR(P) | P=32 |
  |---|---|---|
  | parity | 284.1 ms + 0.87 ms·P | 0.32 s |
  | **replicate** | **239.3 ms + 2.67 ms·P** | **0.33 s** |

- → 결론 한 줄: **TTR로는 parity가 replicate를 못 이김** (둘 다 재계산 0, 교차 P≈25). 차이는 오직 저장.

**2. reactive re-placement — backup 없음 (R={})**
- **소제목(주장):** backup 없으면 복구 167배 — cold reload + position 0 재생
- b. 원리 (한 줄): backup을 **아예 안 둠**. 장애 시 코디네이터가 생존자 위에서 재배치 → 재배치받은 워커가 레이어 가중치 **cold-reload** → 요청을 **position 0부터 재생**
- e. 실측: **56.9 s − 0.18 s·P** → P에 사실상 flat **~53 s** (replay가 항상 0부터라 crash 위치 무관, 비용은 cold reload가 지배). P=32에서 **parity 167×, full-replay 9.4× 느림**
- → 결론 한 줄: **backup 없으면 복구가 두 자릿수 초** — proactive backup(parity/replicate)의 존재 이유

**3. 2D Pareto — parity만 좌하단 (이번 주 핵심 그림)**
- **소제목(주장) = 이번 주 헤드라인:** parity만 좌하단 — TTR 동률, 저장 2.25× 적음
- 시각물: `paper/figures/fig_recovery_2d.png` — **전폭 그림**(log-X). 저장(y) × P=32 복구시간(x)
- 라벨 3줄:
  - full-replay·reactive: 저장 0이나 TTR가 각각 P를 타고(5.6 s)·폭발(53 s)
  - replicate: TTR 낮으나 저장 N배; surgical: 저장 ~0이나 TTR가 깊이 선형
  - **parity만 낮은 TTR ∧ 낮은 저장** — 좌하단 코너 유일
- 저장 숫자: parity **16384 B**(max) vs replicate **36864 B**(Σ) = **2.25×**, 스케일링 O(1) vs O(N)
- 함께 얹을 그림: `paper/figures/fig_recovery_ttr_slide.png` — **5-선 로그축**, reactive가 최상단 ~53 s
- 캡션: 1D TTR 그래프론 parity 우위가 안 보임 → 2D가 필요한 이유

### 한계 (반드시 슬라이드에 올릴 것)

- **reactive**: 탐지를 heartbeat timeout 대신 명시적 mark_dead로 대행 — 실환경 탐지지연(~5 s)을 뺀 셈이나 52 s 대비 무시 가능. victim은 재시작이 아니라 배제(= reactive re-placement 정의 그대로)
- **replicate·parity**: 정상 운영 중 KV shipping 네트워크 세금은 **동일** — parity의 변별점은 오직 coordinator 저장 바이트 (아직 정량화 안 함)
- 측정은 **5-워커 CUDA/AGX fleet** (CPU 워커 on-3 swap-thrash 제외, parity/replicate와 동일 토폴로지). reactive TTR은 cold reload가 지배해 토폴로지에 robust
- 단일 장애만 (parity RAID-5). tail victim·prefill 장애는 지난주 한계 그대로

### 다음 1주 (P5, 3줄)

- KV shipping의 정상 운영 네트워크 비용 **정량화** (parity/replicate 공통 세금)
- surgical 복구 KV를 원본과 바이트 비교 (백로그 B4)
- TII 원고 FT 절을 **2D Pareto 프레이밍**으로 재작성

---

## 예상 구성 (참고 — 내용이 정하되 대략 이 정도)

1 표지 / 2 목차 / 3 지난주 계획↔대응 /
4 recap(3계열, 이번 주 질문) / 5 replicate 원리+실측 / 6 reactive 원리+실측 /
7 2D Pareto (핵심, **헤드라인 소제목**) + 5선 그래프 / 8 한계 / 9 P5 계획 → 9장

지난주보다 짧다 — 새 원리 슬라이드가 2개(replicate·reactive)뿐이고 각각 압축본이라
(follow-up이므로 a-c 전체 흐름 반복 안 함).
