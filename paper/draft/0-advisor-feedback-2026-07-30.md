# 지도교수 미팅 피드백 (2026-07-30)

> 출처: 2026-07-30 미팅 — progress report 0730 발표 후 교수님 메모 5항목.
> 07-16 FT 피벗(`0-advisor-feedback-analysis.md`) 이후 두 번째 정리.

## 원문 (5항목, verbatim)

1. **replicate는 parity랑 비교했을 때 큰 차이가 없어보임** (복구 시간은 애초에 비슷할 수밖에 없고, 저장 용량 차이인데 절대적으로 봤을 때 **3.6KB vs 1.6KB** 정도라 큰 차이 x)
   → 더 큰 모델을 써서 절대적인 차이가 더 생기는지 보고, **차이 미미하면 아예 baseline에서 빼버리자**

2. **각 baseline에 대해 reference로 삼을만한 논문 찾기** (reactive, full-replay, surgical(Petals))

3. **KV 캐시 정확도를 통해 output에 대한 정확도 측정 필요**, 이것도 **TTR처럼 그래프 그리기**

4. **네트워크 오버헤드는 빼기** → 우리 방식이 필연적으로 더 안 좋을 수밖에 없음

5. **슬슬 논문 인트로 다시 잡기**

---

## 우리 상태와의 연결 + 액션

### #1 replicate ≈ parity → 큰 모델로 재확인, 미미하면 제외
- 현재 측정(OPT-350M): `parity=16384 B`, `replicate=36864 B`, 비율 **2.25×**. TTR은 사실상 동률(교차 P≈25) — 교수님 지적과 일치.
- ⚠️ **단위 reconcile 필요**: 교수님 메모는 "3.6KB vs 1.6KB", 우리 측정은 16384/36864 B(= 16/36 KB, 또는 per-token). 자릿수·granularity(per-token vs 누적) 표기가 발표에서 어떻게 나갔는지 확인. 비율(2.25×)·결론(절대 차이 작음)은 동일.
- **액션**: 더 큰 모델(OPT-1.3B 등) placement로 저장 오버헤드 재계산 — `replication_overhead`/`shipping_overhead`는 모델 무관 공식이라 placement 인자만 큰 모델 걸로 바꾸면 즉시 나옴. 큰 모델에서도 절대 차이 미미하면 **replicate를 baseline에서 제외**(parity vs full-replay/surgical/reactive만).
- 함의: 5계열 → 4계열 가능. 2D Pareto에서 replicate 점 제거.

### #2 baseline별 reference 논문 (= 방금 사용자와 논의한 그 검색)
- **reactive**: "spare 없이 생존자 재배치" — elastic/resilient training(TorchElastic, Oobleck, Varuna, Bamboo) + 오케스트레이션 재스케줄(K8s/KubeEdge). 추론 서빙 선례는 드묾.
- **full-replay**: (표준 참조 미정 — 재계산 전량 복구 계열, 찾아야 함)
- **surgical = Petals** (교수님 명시 — client-side input cache 재생과 같은 계열, 이미 `radp-recovery-prior-art`에 있음).
- **액션**: literature-review 스킬로 계열별 reference 정리(엣지+데이터센터, 각 논문 실제 주장 범위 확인).

### #3 output 정확도(KV 정확도)를 TTR처럼 그래프로
- 방금 구현·측정한 **② fidelity가 정확히 이것**. 단, 현재는 **point 1회**(cuda↔cpu, 스테이지 1, 입력 1) — 교수님은 "TTR처럼 그래프"를 원함 → **곡선/분포 필요**.
- **액션**: fidelity를 그래프로 만들 축 확정. 후보: x=시퀀스 길이(또는 P) → y=KV 불일치율 / max-abs-diff, 계열별 선(parity·replicate = 0 flat, 재계산 계열 = 발산). 스테이지·입력 여러 개로 분포. 정량·cross-arch 주장하려면 반복 측정 필수(CUDA↔CUDA로 same-arch 정확 확인 포함).
- 함의: ②가 "표"에서 "그래프"로 승격 = **논문 핵심 그림 후보**.

### #4 네트워크 오버헤드 빼기
- 방금 구현·측정한 **① network overhead — 교수님은 빼라**고 함. 이유: parity/replicate는 KV shipping 세금을 필연적으로 더 냄 → 우리가 **지는 축**이라 보여줄 이유 없음.
- **액션**: ①을 발표/논문 비교에서 **제외**. 코드·측정(`shipping_overhead`, `gen_overhead`, b1_ft_overhead 네트워크 필드)은 백로그·정직성 기록으로 **남겨두되 논문 축으로는 안 씀**. 0730 델타 프롬프트의 "슬라이드 A(네트워크)"도 뺌.
- ⚠️ 방금 SDD로 ①을 완성했는데 교수님이 빼라고 함 — 코드는 유지, 논문 프레이밍에서만 제외. "미러 = surgical 폴백 대가" 분석은 REPORT 해석으로만 남김(폐기 아님).

### #5 논문 인트로 다시
- FT 축들이 어느 정도 모였으니 intro 재작성 시점. TII 산업 프레이밍 + FT 중심.
- **액션**: `draft/2-introduction-v2-TII.md` 기반으로 intro 갱신.

---

## 종합 방향 변화

- **넣는다**: ② fidelity — 그래프로 승격, 핵심 그림. (반복 측정 + 축 확정 필요)
- **뺀다**: ① network overhead(지는 축, 교수님 지시), 어쩌면 replicate(큰 모델서도 절대 차이 미미하면).
- **한다**: baseline reference 논문 정리(#2), 큰 모델 저장 재측정(#1), intro 재작성(#5).
- 방금 SDD로 만든 ①은 논문엔 미사용이나 코드/정직성 기록으로 유지. ②는 강화(그래프+반복) 필요.

## 열린 질문 (다음 미팅/작업 전 정리)
- #1 저장 단위 reconcile: 발표에 나간 저장 숫자가 per-token(16384 B)인지 누적인지 — 3.6/1.6 KB 메모와 자릿수 맞추기.
- #3 fidelity 그래프 x축을 무엇으로(시퀀스 길이 vs 티어 쌍 vs 스테이지)? — TTR(P)와 대칭 맞추려면 x=P나 x=시퀀스 길이가 자연스러움.
- replicate를 뺄지 여부는 #1 큰-모델 재측정 결과에 종속.
