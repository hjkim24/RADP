# BRIEF — RADP Introduction 재작성 (IEEE IOTJ, fault-tolerance-first)

이 문서는 **작성 지시서**다. 최종 산출물이 아니다.
산출물은 `paper/draft/introduction-v4-iotj.md` 에 쓴다.

---

## 0. 산출물 규격

- **형식: 문단별 불렛 개요.** 완성된 산문 아님. 각 문단에 대해 (a) 그 문단이 세우는 주장 한 줄,
  (b) 그 주장을 지지하는 불렛 3~6개, (c) 다음 문단으로 넘어가는 논리적 연결고리 한 줄.
- **언어: 한국어 불렛 + 영어 기술용어 유지** (`paper/draft/2-introduction-v2-TII.md` 의 관례를 따른다).
  최종 논문은 영어지만 지금은 논리 설계 단계다.
- **분량:** 문단 8~12개 정도. 문단 수는 논리가 요구하는 대로. 4단 구성에 억지로 맞추지 말 것.
- **인용:** `[EdgeShard]`, `[Petals]`, `[DejaVu]` 처럼 대괄호 키로 표기. 번호 매기지 말 것(추후 .bib 대조).
  근거 없는 인용을 지어내지 말 것 — 아래 §5 목록에 있는 것만 쓴다.

## 1. 무엇이 바뀌었나 (이전 초안 대비)

이전 초안 두 개는 **폐기**한다. 읽어서 참고는 하되 그대로 따르지 말 것:
- `paper/draft/2-introduction-v2-TII.md` — TII 타깃, DP 중심
- `paper/draft/introduction-v3-recovery-first.md` — TII 타깃, 영어 산문

바뀐 점 세 가지:

1. **투고처: IEEE TII → IEEE IoT Journal (IOTJ).**
2. **주축 전환: DP(레이어 배치) 중심 → fault tolerance 중심.** DP는 종속 요소로 내려간다.
   이유: placement DP만으로는 선행 연구 대비 차별점이 약하다.
3. **네이밍에서 "RAID" 라는 단어를 완전히 제거** (§4 참조).

## 2. 요구되는 논리 흐름

큰 골격은 아래 4단이되, **문단은 더 잘게 쪼개도 된다.** 채점 기준은 4단 준수가 아니라
**주장 간 논리적 정합성과 각 주장의 정당화**다.

1. **분산 추론의 필요성** — 왜 엣지에서, 왜 여러 대로 나눠서.
2. **기존 엣지 분산추론과 그 한계** — 무엇이 이미 풀렸고 무엇이 안 풀렸나.
3. **우리의 접근 (RADP)** — fault tolerance 가 주축, placement DP 는 그것이 요구하는 것.
4. **기여 (Contributions)**.

### 2-1. 1단에서 반드시 지켜야 할 것 (IOTJ 프레이밍)

- **"클라우드가 선택지가 아니다"** 라는 오프라인 필연성 논거를 유지한다. 이게 가장 강한 전제다.
  privacy/API 비용을 주된 동기로 내세우지 말 것 — "클라우드로 보내도 되는 것 아니냐"에 취약해진다.
- 다만 **사례를 공장 OT 일변도에서 IoT 배치 전반으로 넓힌다**: air-gapped 산업망뿐 아니라
  원격 인프라 모니터링, 현장 로봇/드론, 오지·해상 설비 등. TII 용으로 모은 산업 인용은 대부분 재사용 가능.
- 그 다음 **capacity 벽**으로 연결: billion-param 모델은 weight + (길이에 따라 커지는) KV cache 를
  함께 적재해야 하고 이는 단일 엣지 디바이스 용량을 넘는다 → 이미 현장에 깔린 이기종 노드 여러 대에
  레이어를 나눠 싣는 분산 파이프라인이 필연.

### 2-2. 2단에서 반드시 지켜야 할 것

- **선행 연구를 부당하게 깎지 말 것.** EdgeShard/Jupiter 는 이기종성을 **이미 정면으로 다룬다**.
  "기존 연구는 이기종성을 가정하지 않는다" 같은 서술은 사실과 다르다(이전 초안의 알려진 오류).
- 진짜 공백은 **불신뢰성(unreliability) + memory-tightness** 다:
  - EdgeShard/Jupiter 계열: 각 레이어를 한 디바이스에만 두고 복구 경로가 없다 → 첫 워커 실패에 stream 전체 abort.
  - Petals: 예비 피어가 그 레이어를 이미 들고 있다고 전제 → consumer GPU 급 여유 메모리 필요, 4GB 엣지엔 없다.
- 엣지 노드가 실제로 흔히 죽는다는 근거를 붙일 것 (energy depletion, hardware malfunction; 노드 하나
  실패가 data loss/degradation 으로 연쇄). 우리 fleet 에서도 crash·OOM·network partition 을 직접 관측.
- **데이터센터 machinery 를 그대로 못 빌리는 이유**도 짧게: 노드 신뢰성·넉넉한 메모리·고속 interconnect 를
  전제하는데 엣지엔 셋 다 없다.

### 2-3. 3단에서 반드시 지켜야 할 것 — 이 논문의 핵심 논증

**순서가 중요하다. fault tolerance 를 먼저 세우고, 그것이 placement DP 를 요구하게 만든다.**

(a) **복구 전략 자체가 이 레짐에서 미검증이라는 점을 먼저 세운다.**
   - 재계산 계열: 전체 파이프라인 재실행(full replay) 또는 죽은 stage 를 mirror 된 입력으로 재생(Petals 계열).
     비용이 **실패 시점까지 얼마나 진행했는가에 비례해 자란다.**
   - KV 상태를 저장하면 재계산이 사라진다 (데이터센터에서 replication [DejaVu] 또는 erasure coding [GhostServe]으로 하는 것).
     그러나 full replication 은 모든 stage 에 걸쳐 상시 저장이 곱해진다.
   - 백업 없이 생존자로 재배치(re-solve)하면 cold weight reload 가 걸려 interactive latency 에 치명적.
     실제로 이 계열을 채택한 유일한 서빙 시스템도 순진한 버전을 피하도록 설계돼 있다 [SpotServe].
   - → **어느 복구 전략이 이기종·메모리 빠듯한 엣지에 맞는지가 정립돼 있지 않다.** 이게 우리가 여는 문제.

(b) **cross-stage parity 를 답으로 제시한다** (메커니즘, §4 네이밍 규칙 준수):
   - 살아있는 non-head stage 들이 자기 KV 컬럼을 coordinator 로 흘리고, coordinator 가 이를 하나의
     parity 컬럼으로 누적한다. 실패 시 죽은 stage 의 KV 를 생존자 + parity 로 **바이트 단위 동일하게** 복원.
     **model forward pass 가 한 번도 없다.**
   - 두 축에서 동시에 싸다: 복구 시간이 실패 위치에 사실상 무관(flat-in-P), 상시 저장이 파이프라인
     깊이에 대해 O(1) (max stage 하나) — replication 의 O(N) (stage 합) 과 대비.
   - **저장 이점은 per-token 으로 보면 작아 보인다(16 KB vs 37 KB). 반드시 스케일 논증을 붙일 것**:
     KV 백업은 시퀀스 길이에 따라 누적되고 모델 크기에 따라 커지므로, 현실적 context·모델에서는
     수백 MB~GB 로 벌어진다. per-token 숫자만 제시하고 끝내지 말 것.

(c) **여기서 placement DP 를 끌어온다 — "FT 를 감당하려면 불가피하다"는 논증으로.**
   이 부분이 이 초안에서 가장 공들여야 할 논증이다. 세 갈래 근거가 있고, **가급적 셋 다 엮되
   (i) 을 주력으로** 세운다:

   - **(i) 백업 예약이 실제로 배치 답을 바꾼다 — 측정된 사실, 가정이 아님.**
     offline sweep 에서 backup-memory 항이 없는 cost-only DP 는 모든 세팅에서 2-stage 배치를 골랐고,
     backup 항을 넣은 production DP 는 4-stage 를 골랐다. 즉 배치를 먼저 고정하고 FT 를 나중에 얹으면
     그 배치가 백업을 담지 못해 **infeasible** 해진다. (출처: `experiments/REPORT.md` D2.8)
   - **(ii) 배치가 복구 비용을 직접 결정한다.** parity 컬럼 크기 = max(non-head stage KV) 이므로
     레이어를 어떻게 자르느냐가 복구 저장을 그대로 정한다. 배치를 먼저 고정하면 복구 저장이 따라
     결정돼 되돌릴 수 없다.
   - **(iii) 복구 테이블 R 의 질도 배치가 좌우한다.** 배치와 무관하게 R 을 풀면 백업이 약한 노드
     한 대에 몰리는 축퇴가 구조적으로 발생한다(우리 fleet 에서 실제로 관측).
   - → 따라서 RADP 는 ψ(배치)와 R(복구 라우팅)을 **하나의 alternating DP 로 함께 푼다**:
     백업 메모리 예약량이 placement feasibility 검사로 되먹임된다.
   - 부수적으로, cost knob 하나로 latency-optimal 레짐 [EdgeShard] 과 throughput-optimal 레짐 [Jupiter] 을
     한 정식화 안에 담는다. **이건 곁가지로만 언급하고 헤드라인으로 쓰지 말 것.**

(d) **다중 실패 확장은 한 절로만** (§3 "노출 수위" 참조).

### 2-4. 4단 (Contributions)

4~5개. **1번은 반드시 fault tolerance 축**이어야 한다. placement DP 는 뒤로.
각 항목은 "무엇을 했다"가 아니라 "무엇을 보였다/무엇이 새롭다"로 쓸 것.

## 3. 노출 수위 — 반드시 지킬 것 (정직성 게이트)

이 절을 어기면 리뷰에서 반려된다.

- **다중(2개 동시) 실패 확장은 "한 절 + 기여 항목 하나" 로만 다룬다.**
  핵심 주장(재계산 0, O(1) 저장)은 **깨끗한 단일 실패 실측**으로 세운다.
  확장은 *"구성이 k개 parity 컬럼으로 일반화되어 동시 k개 실패를 견디며, k=2 로 구현·라이브 검증했다"*
  정도의 한 문장.
- **동시 2-실패 복구의 절대 TTR(30.3 초)을 서론에 절대 쓰지 말 것.** 이 절편은 알고리즘 비용이 아니라
  우리 fleet 의 축퇴된 복구 테이블에서 온 아티팩트다(백업이 약한 노드 한 대에 몰려 cold weight load 를 문다).
  기울기(≈0)는 깨끗하므로 "재계산 0" 성질만 인용 가능.
- **k≥3 일반화는 하지 않았다.** 하지 않은 이유를 정직하게 쓸 수 있으면 강점이 된다:
  k-parity 저장 = k×max(non-head), replication 저장 = Σ(non-head) 이므로 parity 가 이기려면 `k < Σ/max`.
  우리 배치는 Σ/max = 2.25 라 k=3 부터는 저장이 더 크면서 내성은 더 약한 **완전 열등**이 된다.
  (서론에 넣을지는 재량 — 넣는다면 한 절.)
- **network overhead 를 우리 강점으로 주장하지 말 것.** 지도교수 지시로 이 축은 논문에서 제외한다.
  parity/replicate 는 오히려 KV 를 흘리므로 대역폭을 더 쓴다.
- **fidelity 는 "보장(guarantee)" 으로만 서술.** 저장된 바이트를 복원하므로 복구된 KV 가 원본과
  bit-identical 이다 — 재계산 계열이 tier 간에 줄 수 없는 보장. 단 **"출력 오류가 줄어든다"고 쓰지 말 것**:
  실측에서 토큰 출력은 100% 일치했다(출력이 갈린 적 없음).
- **subset selection 은 미구현(future work).** 자동 노드 선별을 했다고 쓰지 말 것.
- 숫자는 아래 §5 에 있는 것만 쓴다. **없는 숫자를 지어내지 말 것.** 필요한데 없으면 `[확인]` 으로 표시.

## 4. 네이밍 규칙 — "RAID" 금지

**논문 산문과 figure 어디에도 "RAID" 라는 단어를 쓰지 않는다.** (GhostServe 도 erasure-coding
어휘로만 서술한다.) 대신:

| 쓸 것 | 쓰지 말 것 |
|---|---|
| **cross-stage parity** (메커니즘 이름) | KV-RAID, RAID-5, RAID-6 |
| **single-parity (f=1)** / **double-parity (f=2)** / k-parity | RAID-5 방식 / RAID-6 방식 |
| erasure coding, parity column, Reed–Solomon, GF(2⁸) | RAID 계열 표현 전반 |

- 계보는 **Reed–Solomon 소거부호**로 인용한다. RAID 는 필요하면 각주 한 번 정도지 이름에는 안 넣는다.
- 베이스라인은 원 시스템 이름으로 부른다: **Petals**(입력 재생 복구), **DejaVu**(전체 KV 복제),
  **SpotServe**(생존자 재구성), 그리고 recompute-from-scratch 계열.
- **코드 식별자는 이 규칙의 대상이 아니다.** `parity`, `replicate`, `RADP_PARITY_K` 등은 그대로 둔다.

## 5. 사용 가능한 숫자 (전부 실측·검증됨)

출처는 `experiments/REPORT.md`. 이 값들만 쓴다.

**복구 시간 (5-stage OPT-350M Jetson fleet, P = 실패 시점의 토큰 위치):**
- cross-stage parity: `TTR(P) = 284.1 ms + 0.87 ms·P` — 기울기 사실상 0
- Petals 계열(입력 재생): 기울기 `16.21 ms/pos` → parity 대비 **19× 가파름**
- recompute-from-scratch: 기울기 `164.32 ms/pos` → parity 대비 **188× 가파름**
- DejaVu(전체 복제): `239.3 ms + 2.67 ms·P` — parity 와 사실상 **동률** (둘 다 zero-recompute)
- 생존자 재구성(백업 없음): 약 **53 초** 중앙값, P 에 무관 (cold weight reload + position 0 재생 지배).
  P=32 에서 parity 대비 약 **176×** 느림

**상시 저장 (이 배치, non-head stage 가 1/3/4/1 레이어, KV 토큰당):**
- cross-stage parity: **16,384 B** = max(non-head stage)
- DejaVu: **36,864 B** = Σ(non-head stages) → parity 가 **2.25× 적음**
- 스케일링: parity O(1) (파이프라인 깊이 무관) vs replication O(N)
- double-parity(f=2): 32,768 B
- **주의:** 우리 배치는 head-heavy(head 가 15/24 레이어)라 2.25 는 **보수적인 끝**이다.
  균등 배치면 비율 = non-head stage 개수. 이 점을 밝히면 "유리하게 뽑은 숫자" 반박을 미리 막는다.

**저장 격차의 스케일 (모델 기하로 계산, 라이브 아님):**
- OPT-350M 우리 fleet 실측: KV 토큰 1개당 약 20 KB → 2048 토큰에서 약 **40 MB**
- 균등 파이프라인 기준: OPT-350M @4096 토큰 약 **230 MB**, OPT-13B @4096 토큰 약 **1.9 GB**

**기타:**
- fleet 내 노드 간 처리량 격차 최대 **76×** (GPU tier ↔ CPU-only)
- double-parity 라이브: **5/5 시퀀스 완전 일치** (bit-correct), 기울기 `2.78 ms/pos`
- fidelity: 같은 stage 를 cuda 와 cpu 에서 재계산하면 KV 원소의 **26.9%** 가 불일치,
  최대 절대오차 `2⁻⁸` (BLAS reduction 순서 차이). 단 **토큰 출력은 3156 회 결정 전부 일치**.

## 6. 읽을 것

- `experiments/REPORT.md` — §B1-* 전부(복구 계열 실측), D2.8(ψ+R coupling sweep). **1차 사료.**
- `paper/draft/2-introduction-v2-TII.md`, `paper/draft/introduction-v3-recovery-first.md` — 폐기된 이전 초안(참고용)
- `paper/draft/0-advisor-feedback-2026-07-30.md` — 지도교수 지시(network overhead 제외 등)
- `paper/refs/PAPERS.md` — 선행 연구 카탈로그
- `paper/refs/TII-industrial-refs.md` — 산업 인용(IOTJ 로 재사용 가능)
- `paper/refs/recovery-comparison.md`, `paper/refs/baseline-references-2026-07-30.md` — 복구 계열 선행 연구 대조
- `AGENTS.md` — 프로젝트 컨텍스트

## 7. 문체 (지킬 것)

- **"not X but Y" 반전 구문 금지.** "복구가 아니라 저장이 문제다" 같은 재프레이밍은 요점이 없을 때
  나오는 문장이다. 그냥 주장을 직접 쓴다.
- 숫자·이름·메커니즘이 없는 형용사를 쓰지 않는다. "혁신적", "핵심적", "크게 향상" 금지.
- "~를 통해", "극대화", "seamless", "robust", "leverage" 류의 인플레이션 어휘 금지.
- 문단 첫 문장에서 목청 가다듬지 말 것("최근 들어 ~가 주목받고 있다" 류).
- 근거 없는 significance 부여 금지. 사실을 쓰고 독자가 무게를 재게 한다.
