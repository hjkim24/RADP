# RADP 논문 초안 작성 워크플로우 (작업 프롬프트)

> 이 문서는 **재사용 작업 프롬프트**다. 사용자가 "다음은 ○○ 섹션, 내용은 …"
> 하고 지시할 때마다 Claude는 이 문서를 먼저 참고해 규칙대로 초안을 만든다.

---

## 0. 목적과 큰 그림

`skeleton.tex` 골격을 채워 논문을 완성한다. 두 단계로 나눠 진행한다.

1. **Phase 1 — 초안 (지금 단계):** 섹션별로 **한글** 초안을 먼저 쓴다.
   완성된 논문 어투가 아니라 **논리 흐름 정리**가 목적. 줄글 위주에
   불렛을 약간 섞는다.
2. **Phase 2 — 완성 (나중):** 확정된 한글 초안에 살을 붙여 **영문 학술
   문장**으로 옮기고, `sections/skeleton/*.tex` 에 넣어 IEEE 논문으로
   완성한다.

지금은 **Phase 1**만 진행한다. Phase 2 규칙은 §5에 미리 적어둔다.

---

## 1. 파일 배치 (초안 ↔ 최종 매핑)

한글 초안은 빌드와 분리해 마크다운으로 쓴다 (IEEEtran+Times는 한글을
렌더하지 않으므로 `.tex`에 바로 넣지 않는다).

| 순서 | 섹션 | 한글 초안 (Phase 1) | 최종 영문 (Phase 2) | 하위절 |
|---|---|---|---|---|
| 1 | Abstract | `draft/1-abstract.md` | `sections/skeleton/abstract.tex` | — |
| 2 | Introduction | `draft/2-introduction.md` | `sections/skeleton/introduction.tex` | (드롭캡 첫 문단 / 기여 목록 / 구성) |
| 3 | Related Work | `draft/3-related.md` | `sections/skeleton/related.tex` | 주제별 문단 |
| 4 | Background & Motivation | `draft/4-background.md` | `sections/skeleton/background.tex` | A. Pipeline-parallel / B. Why prior fails |
| 5 | System Design | `draft/5-design.md` | `sections/skeleton/design.tex` | A. Recovery-Aware DP / B. Mirror cache / C. Async forwarding / D. Runtime |
| 6 | Evaluation | `draft/6-evaluation.md` | `sections/skeleton/evaluation.tex` | A. Setup / B. ψ+R vs baselines / C. Recovery / D. Latency vs throughput / E. Subset & hop |
| 7 | Discussion & Conclusion | `draft/7-discussion.md` | `sections/skeleton/discussion.tex` | — |

> 섹션 순서는 `main.tex`/`skeleton.tex` 기준: Intro → **Related** → Background
> → Design → Evaluation → Discussion.

---

## 2. Phase 1 초안 작성 규칙 (핵심)

Claude가 초안을 쓸 때 지키는 규칙:

- **언어:** 한글.
- **문체:** 처음부터 논문 어투로 쓰지 **않는다**. 아이디어와 논리 순서를
  드러내는 게 우선. **줄글을 기본**으로 하되, 근거·항목·대비처럼 나열이
  자연스러운 곳에만 **불렛을 약간** 섞는다. 불렛으로 도배하지 않는다.
- **전문용어:** placement, throughput, recovery, pipeline, baseline,
  latency, TBT, greedy decoding 등 학술 용어는 **영문 그대로** 둔다
  (일반 서술어만 한글 — `main_kor.tex` 작성 원칙과 동일).
- **입력:** 사용자가 그 섹션에 넣을 **내용(요점·논리·근거·수치)**을 준다.
  Claude는 그 범위 안에서 초안을 구성한다. 사용자가 안 준 주장·수치를
  임의로 만들지 않는다.
- **사실/수치:** 지어내지 않는다. 필요한데 값이 없으면 본문에
  `[확인 필요: …]` 로 표시한다. 실측 출처는 §4 참조.
- **분량:** 초안은 과하게 길게 쓰지 않는다. 요점을 담되 Phase 2에서 늘릴
  여지를 남긴다.
- **출력 위치:** 해당 `draft/N-<section>.md` 파일에 저장한다. 하위절이
  있으면 `##`/`###` 헤딩으로 구분한다.

---

## 3. 사용자 지시 형식 & 내가 하는 일

사용자 지시 예시:

```
섹션: Design (A. Recovery-Aware DP)
내용:
- ψ는 layer placement, R은 recovery routing. 둘을 한 DP에서 번갈아 최적화.
- backup 메모리 예약량이 placement 제약으로 되먹임되는 게 핵심.
- 수렴은 실측상 3 iteration 이내 (REPORT 참조).
```

이때 Claude는:
1. 이 문서(§2 규칙)를 기준으로,
2. 해당 `draft/*.md`의 그 하위절에 한글 초안을 쓰고,
3. 지어낸 수치가 없는지, `[확인 필요]` 표시가 적절한지 점검한 뒤,
4. 무엇을 어디에 썼는지 한 줄로 보고한다.

특정 하위절만 주면 그 부분만, 섹션 전체를 주면 전체를 쓴다.

---

## 4. 사실·수치 출처 (지어내기 금지)

- `../experiments/REPORT.md` — 실험 결과(수치, 매트릭스, 회복 실험 등).
- `../PHASES.md` — 구현 이력, 각 변경의 커밋 해시.
- 초안에서 특정 수치를 쓸 땐 어느 출처인지 알 수 있게 하고, 확정 전이면
  `[확인 필요: REPORT §… 값]` 형태로 남긴다.

---

## 5. Phase 2 완성 규칙 (지금은 참고만)

Phase 1 초안이 확정된 뒤 진행:

- 한글 초안을 **영문 학술 어투**로 옮기고 살을 붙인다.
- `sections/skeleton/*.tex` 의 `\todo{…}` 자리를 실제 문장으로 채운다.
- `\cite{}` 로 실제 인용을 넣고, `skeleton.tex`의 임시 `\nocite{*}` 는 제거.
- 그림/표/수식/알고리즘 stub 를 실제 내용으로 채운다.
- Introduction 첫 문단은 `\IEEEPARstart{첫글자}{나머지첫단어}` 로 마무리.
- 빌드 확인: `tectonic --synctex skeleton.tex` (Exit 0 + PDF).

---

## 6. 진행 체크리스트

- [ ] 1. Abstract
- [ ] 2. Introduction
- [ ] 3. Related Work
- [ ] 4. Background & Motivation
- [ ] 5. System Design
- [ ] 6. Evaluation
- [ ] 7. Discussion & Conclusion

(각 섹션은 Phase 1 초안 → Phase 2 완성 두 번 거친다.)
