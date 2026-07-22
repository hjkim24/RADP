# 엣지 장애복구 관련연구 정리 — RADP 대비 (2026-07-22)

검색 방법: WebSearch(arxiv/ieee/acm/usenix) 2쿼리 + 후보 2편 전문 확인(WebFetch).
literature-review 스킬의 방법론(다중검색 → 주제별 종합 → **논문이 실제로 말한 것만 인용**)만 차용.
**여기 수치·기법은 모두 원문/초록에서 확인한 것.** 미확인 항목은 그렇게 표기함.

우리가 이미 보유(카탈로그): QEIL·JARVIS(엣지 FT), Petals·DejaVu·GhostServe·KevlarFlow·LUMEN·SpotServe(데이터센터 FT).

---

## 1. 한 줄 지형

**LLM용 장애복구는 거의 전부 데이터센터 GPU 클러스터를 가정한다.** 엣지-네이티브 LLM
FT는 사실상 비어 있고, 엣지 FT 문헌의 다수는 여전히 CNN 이미지 분류 대상이다.
이 공백이 RADP의 위치다.

| 계열 | 대표 | 무대 | 상태 재구성 대상 |
|---|---|---|---|
| 데이터센터 KV 보호 | DejaVu, GhostServe, KevlarFlow, LUMEN, SpotServe | GPU 클러스터, 빠른 interconnect | KV cache |
| 데이터센터 신규(이번 검색) | Tarragon, AnchorTP, PipeBoost, ReviveMoE | GPU 클러스터 | KV/TP state |
| **엣지 FT (CNN)** | **RoCoIn** | 이종 IoT 엣지 | 없음 (stateless) |
| 엣지 FT (LLM) | JARVIS, QEIL, **RADP** | 이종 엣지 | KV cache |
| 엣지 파이프라인(비-FT) | LOIP | Jetson | — (FT 아님) |

---

## 2. 신규 발견 — 우리 카탈로그에 없던 것

### 2.1 RoCoIn (Robust Cooperative Inference) — arXiv:2406.14185

**엣지 FT 문헌 중 우리와 가장 가까운 무대, 가장 먼 기법.**

- **문제**: 장애가 잦은 이종 엣지 IoT에서 분산 DNN 추론을 견디게 하기
- **기법**: **중복 그룹 + 지식 복제.** 같은 그룹의 여러 디바이스가 **같은 파티션을
  동일한 student 모델로 동시에 실행.** 소스는 모든 디바이스를 기다리지 않고
  *필요한 수의 서로소 조각*만 오면 진행 → 일부가 죽어도 결과가 나옴
- **하드웨어**: 8 디바이스(5–30M FLOPS, 0.5–1 kbps), MobileNet-v2 / WideResNet, CIFAR-10/100
- **비용**: 상시 중복. baseline(NoNN 0.18M)보다 더 촘촘한 student(0.28M) 필요
- **정확도(장애 하)**: CIFAR-10 91.62% vs teacher 91.86% — **정확 복구가 아니라
  우아한 열화(graceful degradation)**
- **복구 시간**: 명시 없음

### 2.2 LOIP — arXiv:2512.21835 (참고: FT 아님)

Jetson Xavier NX에서 offloading 기반 interleaved pipeline parallelism으로 LLM을 돌리는
엣지 시스템. **"lossless"는 수치 무손실이지 장애복구가 아님** — 전문 확인 결과 node crash /
checkpoint / 복구 기제가 **전혀 없음.** 우리 §placement·KV pressure 관련 related work로만
유효하고, FT 비교 대상은 아님.

### 2.3 데이터센터 신규(엣지 아님, 참고)

- **Tarragon** (arXiv:2601.01310) — MoE serving, worker 단위 self-healing
- **AnchorTP** (arXiv:2511.11617) — elastic TP, **intra-node GPU 장애만** 견딤 + KV 재계산 필요
- **PipeBoost** (arXiv:2503.17707) — serverless pipeline 빠른 스케일업
- **ReviveMoE** (arXiv:2602.21140) — 대규모 MoE 하드웨어 장애 빠른 복구

전부 GPU 클러스터·빠른 interconnect·여분 용량 가정. 우리 레짐과 무대가 다름.

---

## 3. RADP와의 차이 — RoCoIn 정면 대조

RoCoIn이 "엣지 + 이종 + 장애복원"으로 무대가 겹치므로 가장 날카로운 대조군이다.

| 축 | RoCoIn | RADP |
|---|---|---|
| 모델 | CNN 이미지 분류 | LLM (autoregressive transformer) |
| **상태** | **없음** — 입력마다 독립, 재구성할 것이 없음 | **KV cache** — position마다 누적되는 상태 |
| 중복 방식 | **공간 중복** — N대가 같은 파티션을 **상시** 실행 | backup 배치 + **on-demand 재구성** (상시 중복 forward 없음) |
| 상시 비용 | 중복 연산(더 촘촘한 student N벌) | 입력 미러 + (parity 시) KV 컬럼 전송 |
| 정확성 | **근사** — 정확도 우아하게 열화 | **정확** — 토큰 일치(surgical), 비트 동일(parity) |
| 동시 장애 | 그룹 크기만큼 | 1대 (XOR parity) |

**핵심 통찰**: RoCoIn이 상태 재구성을 아예 안 하는 이유는 **CNN이 stateless라서**다.
입력 하나가 독립이므로 "복구 = 중복으로 미리 돌려두기"면 충분하다. RADP의 문제 전체가
**KV cache가 stateful하고 자라난다**는 데서 나온다 — 그래서 replay(surgical)나 대수적
잉여(parity)가 필요하다. RoCoIn의 무대는 같지만, LLM의 상태성이 왜 더 정교한 기제를
요구하는지를 오히려 선명하게 보여주는 대조군이다.

---

## 4. 우리 프로젝트 적용 가능성

### 4.1 직접 적용 — RoCoIn의 중복 그룹 → 우리 B3 라인

RoCoIn의 "같은 파티션을 여러 디바이스가 상시 실행"은 우리 백로그 **B3 redundant-hosting**
(같은 stage를 워커 2대에 얹기)과 **정확히 같은 아이디어**다. 즉 RoCoIn은 우리가
비교군으로 세우려는 그 브랜치의 엣지 선행연구다. 다만 LLM에 그대로 옮기면
**KV cache가 2배**로 들어 메모리 상한(우리 ao-2 32GB, Nano 8GB) 레짐에서 비싸다 —
우리가 공간 중복 대신 parity로 간 이유가 바로 이것. **B3 슬라이드에서 "엣지 CNN에는
RoCoIn이 상시 중복으로 답했지만, LLM KV cache는 그 비용이 2×라 우리는 잉여-코딩으로
전환했다"는 프레이밍이 가능**하다.

### 4.2 부분 적용 — 근사 복구는 우리 규격에 안 맞음

RoCoIn의 graceful degradation(정확도 하락 허용)은 우리의 정확 복구(토큰 일치) 규격과
충돌한다. 채택 불가. 단, **"정확 복구 vs 근사 복구"를 related work 축으로 세우면**
우리의 exact-recovery 주장이 더 도드라진다.

### 4.3 미적용 — 데이터센터 계열

AnchorTP(intra-node만), Tarragon/ReviveMoE(MoE), PipeBoost(serverless)는 무대·가정이
달라 직접 적용 없음. related work의 "데이터센터는 여분 용량을 가정한다" 대조군으로만 인용.

---

## 5. related-work 포지셔닝 문장 (원고용 초안)

> 엣지 장애복원 문헌은 두 갈래로 갈린다. **stateless CNN 협력추론**(RoCoIn)은 중복
> 그룹으로 장애를 견디되 상태 재구성이 필요 없고 근사 열화를 허용한다. **stateful LLM
> serving**의 장애복원(DejaVu, GhostServe, KevlarFlow, LUMEN)은 KV cache를 다루지만
> 데이터센터 GPU 클러스터·빠른 interconnect·여분 용량을 가정한다. RADP는 그 사이의
> 빈 칸 — **여분 없는 이종 엣지에서의 stateful LLM 정확복구** — 를 메운다.

---

## 6. 후속 (검색은 넓지만 얕음)

- RoCoIn 전문 PDF 미보유. 관련성 높으면 corpus에 추가하고 카탈로그 컨벤션으로 등재 권장.
- 이번 검색은 arxiv/ieee/acm 4쿼리·후보 2편 전문 확인 수준. 체계적 리뷰 아님.
- 확인 못 한 각도: 엣지 FL(federated) 복구, 위성/드론 간헐연결 추론, RL 기반 엣지 backup 배치.
