# Claude Code 논문 작업 인수인계

`/Users/hjkim24/RADP`에서 논문 작업 맥락을 다시 불러와줘.

인계 범위는 내가 Codex에게 “이전 Claude Code 대화와 프로젝트 문서를 참고해서 논문 작업을 다시 시작하자”고 요청한 시점부터 2026-08-30 현재까지다. 예전 auto-memory만 믿지 말고, 아래 파일과 현재 Git 상태를 실제로 읽어서 최신 상태를 복원해줘.

우선은 파일을 수정하지 말고, 아래 자료를 읽은 뒤 현재 상태·확정된 결정·낡은 내용·다음 작업을 요약해서 보고해줘.

## 1. 가장 먼저 확인할 상태

다음 명령으로 현재 브랜치와 미커밋 변경을 확인해라.

- `git status --short`
- `git log --oneline -20`
- `git diff --check`
- `git diff -- PHASES.md experiments/REPORT.md paper/refs/baseline-references-2026-07-30.md ppt/prompt_0730.md`

현재 기준:

- main과 origin/main은 `c82c0da`까지 동기화되어 있다.
- 다음 네 파일에는 아직 커밋하지 않은 최신 변경이 있다. 절대 reset/checkout으로 없애지 마라.
  - `PHASES.md`
  - `experiments/REPORT.md`
  - `paper/refs/baseline-references-2026-07-30.md`
  - `ppt/prompt_0730.md`
- 주요 최근 커밋:
  - `25fc143 docs(paper): draft KV-CARE core sections and algorithms`
  - `83b220f fix(experiments): measure client-observed reconfigure recovery`
  - `c82c0da chore(overleaf): add one-command paper sync`

## 2. 현재 논문에서 우선 읽을 파일

다음 순서로 읽어라.

### 현재 LaTeX 원고

1. `paper/main.tex`
2. `paper/sections/introduction.tex`
3. `paper/sections/related.tex`
4. `paper/sections/design.tex`
5. `paper/references.bib`
6. `paper/algorithms/recovery_algorithms.tex`

`main.tex`이 현재 실제 섹션 구성의 source of truth다.

현재 큰 섹션은 다음처럼 단순화됐다.

1. Introduction
2. Related Work
3. KV-CARE Design
4. Evaluation
5. Discussion and Conclusion

예전처럼 Background and Motivation과 System Design을 각각 큰 섹션으로 나누지 않는다. 관련 배경은 Introduction과 Design에 녹였고, Design 아래에 여러 subsection을 둔다.

현재 Design subsection은 다음과 같다.

- System Overview and Architecture
- Execution and Recovery Model
- Cross-Stage KV Parity
- KV Recovery and Fallback
- Recovery-Aware Layer Placement
- Runtime Integration

`paper/sections/background.tex`은 현재 `main.tex`에 포함되지 않는 과거 파일이다.

### 논리·주장 검증용 문서

- `paper/draft/intro-brief-iotj.md`
- `paper/draft/introduction-v4-iotj.md`
- `experiments/REPORT.md`
  - 특히 B1-FLEET
  - B1-PARITY
  - B1-REPLICATE
  - B1-REACTIVE
  - B1-OVERHEAD
  - B1-RUNTIME-OVERHEAD
  - B1-FIDELITY
  - B1-RAID6
  - §14 Limitations
  - 부록 A6
- `PHASES.md`
  - Phase B1-RAID6
  - Phase B1-METRIC-REFRESH
- `paper/refs/baseline-references-2026-07-30.md`
- `paper/refs/PAPERS.md`
- `paper/refs/recovery-comparison.md`
- `paper/refs/comparison.md`

`paper/README.md`, `paper/DRAFTING.md`, `paper/sections/skeleton/`은 예전 OSDI/NSDI·한글 초안 워크플로우를 설명하는 낡은 문서다. 현재 원고 구조나 venue 판단의 근거로 사용하지 마라.

`paper/sections/abstract.tex`, `evaluation.tex`, `discussion.tex`도 Introduction/Related Work/Design보다 훨씬 오래된 상태다. 특히 `evaluation.tex`은 placement 중심의 과거 RADP 원고이므로 최신 FT 중심 Evaluation으로 다시 작성해야 한다.

## 3. Notion 원고 구조

현재 작업 페이지:

https://app.notion.com/p/Recovery-Aware-DP_-3c825e27cfcd80eabec4d58ddd7a4ab4

Notion에서는 다음 구조를 유지한다.

- Introduction
  - 0826
  - 0827
- Related Work
  - 0826
  - 0827
- Body
  - 0826
  - 0827
- Evaluation
  - 0827

각 섹션 제목이 상위 toggle이고 그 안에 날짜별 sub-toggle이 있다. 모든 섹션을 하나의 0827 toggle 아래에 넣으면 안 된다. 0826은 역사 기록이고 0827이 현재 작업본이다.

Introduction, Related Work, Body는 0827을 바탕으로 LaTeX 원고가 작성됐다. Evaluation은 Notion 0827에 bullet outline이 있지만 최신 실험 결과를 반영한 LaTeX 본문은 아직 작성되지 않았다.

## 4. 가장 크게 달라진 결정

### Venue와 중심축

- 제출 대상은 IEEE Transactions on Industrial Informatics가 아니라 IEEE Internet of Things Journal이다.
- 논문의 중심축은 layer-placement DP 자체가 아니라 heterogeneous edge LLM inference의 fault tolerance다.
- Cross-stage parity와 recovery mechanism을 먼저 제시하고, recovery-aware placement는 그것을 실행 가능하게 만드는 두 번째 핵심 기여로 설명한다.
- 교수님 방침에 따라 network overhead는 논문의 평가 축에서 제외한다.

### 시스템 이름

현재 논문·Notion·그림·표·발표용 이름은 다음으로 확정됐다.

- `KV-CARE`
- KV Cache Availability and Recovery at the Edge

`Recovery-Aware DP`, `RADP`, `KV-RAID`는 사람에게 보이는 현재 시스템 이름으로 사용하지 않는다.

단, 다음 코드 호환 식별자는 절대 rename하지 않는다.

- repository/package `radp`
- `recovery_mode`
- `RADP_PARITY_K`
- JSON의 mode 값
- `ReplicaCache`
- `ParityCache`
- `full_replay`
- `surgical`
- `parity`
- `replicate`
- `reactive_replacement`

주의: 현재 `AGENTS.md`의 표시 이름 표에는 KV-RAID가 남아 있어 이 부분은 최신 KV-CARE 결정과 충돌한다. 사람에게 보이는 이름은 KV-CARE 결정이 우선한다.

### 용어 및 표현

- 논문 본문에서는 RAID라는 표현을 사용하지 않고 `single parity`, `double parity`, `k-parity`, `cross-stage parity`를 쓴다.
- 장애 개수/허용 parity level은 `k`를 사용하며 현재 구현은 `k∈{1,2}`다.
- bit-exact `KV-State Fidelity`는 parity branch가 recovery contract를 통과해 실제로 완료된 경우에만 보장한다.
- replay fallback은 model forward로 KV를 다시 생성하므로 bit-exact 보장 대상이 아니다.
- Output Correctness는 recovery criterion에서 제외했다.
  - cross-tier KV mismatch는 관찰됐지만 3,156개 greedy decision에서 token flip은 0개였다.
  - 따라서 “재계산이 잘못된 출력을 만든다”라고 쓰면 안 된다.
  - 정확한 대비는 “parity는 bit-exact 보장, recomputation은 실측상 출력은 같았지만 bit-exact 보장은 없음”이다.
- SpotServe는 Reconfigure baseline 구현이 아니다.
  - SpotServe는 advance preemption notice와 grace period가 있는 cloud 환경에서 migration과 state reuse를 수행한다.
  - 우리 Reconfigure는 `reactive_replacement`, 즉 failure 이후 re-solve + cold deploy + position-0 replay다.

## 5. Related Work에서 반영된 변경

현재 subsection 이름은 짧게 통일했다.

- Distributed LLM Inference and Fault Tolerance
- Recomputation
- Replication
- Reconfiguration
- Parity

`Input Replay`, `Checkpointing`, `Migration` 같은 suffix는 제거했다.

baseline mapping:

- Recompute → `full_replay`
- Petals → `surgical`
- DejaVu → `replicate`
- Reconfigure → `reactive_replacement`
- KV-CARE → `parity`

EdgeShard, Jupiter, Petals, DejaVu, SpotServe, GhostServe, KevlarFlow, LUMEN의 설명을 실제 논문과 대조해 수정했다.

특히:

- EdgeShard의 latency DP와 throughput formulation을 구분했다.
- Jupiter는 decoding DP뿐 아니라 intra-sequence pipeline-parallel prefill과 speculative/outline decoding을 구분했다.
- Jupiter DOI `10.1109/INFOCOM55648.2025.11044734`를 추가했다.
- Petals의 시스템 논문 `Distributed Inference and Fine-Tuning of Large Language Models over the Internet`을 추가했다.
- Petals의 client-side failed-stage replay와 server-side block rebalancing을 혼동하지 않도록 수정했다.
- GhostServe는 datacenter tensor-parallel shard/host-memory checkpointing이며, heterogeneous pipeline-stage parity와 동일한 시스템으로 묘사하면 안 된다.

관련 PDF는 `paper/refs/`에 있고, 서지와 설명은 `paper/references.bib`, `paper/refs/PAPERS.md`에 반영됐다.

## 6. 현재까지 작성된 LaTeX

커밋 `25fc143`에서 다음이 작성됐다.

- `paper/main.tex`
  - IEEEtran IoT-J 형식
  - `\sys` = KV-CARE
- `paper/sections/introduction.tex`
  - FT-first Introduction
- `paper/sections/related.tex`
  - 실제 논문 기반 Related Work와 baseline comparison table
- `paper/sections/design.tex`
  - coordinator-worker architecture
  - recovery contract
  - single/double parity 수식
  - fallback ladder
  - recovery-aware placement recurrence
  - runtime integration
- `paper/algorithms/recovery_algorithms.tex`
  - Guarded Cross-Stage Parity Recovery
  - Recovery-Aware Alternating Layer Placement
- 렌더링 산출물:
  - `paper/algorithms/recovery_algorithms.pdf`
  - `paper/algorithms/recovery_algorithms-parity.png`
  - `paper/algorithms/recovery_algorithms-placement.png`

Design에서는 애매했던 `absolute KV slot`, `contributor set`, `organization`, `incomplete parity entry`, `parity gate` 같은 표현을 더 구체적인 slot geometry, protected stage set, complete parity entry, recovery contract로 정리했다.

## 7. 2026-08-30에 새로 확정된 실험 결과

### Reconfigure metric 재측정

canonical raw result:

- `experiments/results/b1_ft_fleet_reactive_client_interval_20260830.json`

정의:

- last pre-failure valid token에서 replay catch-up 이후 first new valid token까지의 client-observed `Recovery Latency`

결과:

- P=4: 18.624 s
- P=8: 39.350 s
- P=16: 35.463 s
- P=24: 22.434 s
- P=32: 24.250 s
- median 24.250 s
- range 18.624–39.350 s
- 5/5 valid

P마다 victim이 달라 slope는 해석하지 않는다. 논문에서는 median과 range만 사용한다.

기존 약 53초, 176×, 10× 표현은 다른 wall-time 정의에 기반한 값이므로 폐기한다.

다음 그림과 생성 스크립트는 아직 낡은 reactive JSON과 약 53초 값을 사용하므로 반드시 갱신해야 한다.

- `paper/figures/make_recovery_ttr_slide.py`
- `paper/figures/make_recovery_2d.py`
- `paper/figures/fig_recovery_ttr_slide.{pdf,png}`
- `paper/figures/fig_recovery_2d.{pdf,png}`

### 정상 실행 protection overhead 반복 검증

canonical summary:

- `experiments/results/b1_steady_modes_n3_20260830.json`

프로토콜:

- OPT-350M
- async chain
- 각 cell마다 20-token full-length primer 1회 제외
- 20-token request 10개
- 실행 순서를 교차한 3 round
- 모드별 30 requests, 600 TBT
- round 내부에서는 동일 placement
- 모든 request가 20 tokens 완료
- 모든 cell의 greedy decoded text 동일

N=3 mean ± sample standard deviation:

- Protection off
  - throughput 5.237±0.064 tok/s
  - TBT p50 183.17±1.97 ms
- Single parity
  - throughput −5.11±2.38%
  - TBT p50 +5.79±2.55%
- Double parity
  - throughput −6.31±0.26%
  - TBT p50 +7.26±0.52%
- Replication
  - throughput −6.30±1.24%
  - TBT p50 +7.17±0.73%

Double parity와 replication의 평균 throughput은 각각 4.906238/4.906353 tok/s로 사실상 동일하다. “double parity가 replication보다 추가적인 정상 실행 비용을 만들지 않았다”는 결론으로 사용한다.

최초 `b1_steady_modes_20260830.json`은 round 1 역사 기록일 뿐이며, 최종 표와 그림에는 N=3 summary를 사용한다.

실행 순서, placement, raw file mapping, 검증 게이트, 복원 상태는 `experiments/REPORT.md`의 `B1-RUNTIME-OVERHEAD` 실행 로그에 기록돼 있다.

주의: `experiments/results/`는 `.gitignore` 대상이다. 위 JSON들은 이 로컬 workspace에는 있지만 Git에는 올라가지 않는다. 삭제하지 마라.

### Double parity 절대시간 주의

기존 double-parity 측정의 `TTR(P)=30.29s+2.78ms·P`에서 30.3초 절편은 알고리즘 비용이 아니다. backup mapping이 non-head backup을 약한 `on-2`에 집중시킨 배치 아티팩트다.

사용 가능한 결론:

- 5/5 bit-correct
- two non-head failures recovered
- zero prefix recomputation
- observed slope approximately flat

사용하면 안 되는 결론:

- 30.3초가 double parity 고유 복구 비용이라는 주장
- 해당 결과를 ψ-R coupling의 중심 증거로 사용하는 것

## 8. 현재 실험 상태

논문 Evaluation outline에서 미측정이었던 필수 두 항목은 모두 완료됐다.

- 정상 실행 protection overhead
- corrected Reconfigure Recovery Latency

추가 필수 실험은 현재 없다. 다음은 claim을 확장할 때만 필요한 선택 실험이다.

- double parity의 깨끗한 절대 latency를 주장할 때: backup이 분산된 R로 재측정
- Reconfigure의 TTR(P) slope를 주장할 때: 동일 victim으로 반복
- 더 큰 모델·실제 다른 SKU·head/middle/tail sweep: future work

현재 fleet 상태는 2026-08-30 13:50 KST 기준 다음과 같이 복원됐다. 라이브 작업 전에는 다시 확인해라.

- 7 configured workers
- `ready=true`
- 5-stage placement
- recovery table 5 entries
- dead device 없음
- worker `RADP_PARITY` drop-in 없음
- coordinator `RADP_RECOVERY_MODE=surgical`
- `RADP_PARITY_K=1`

## 9. Overleaf 연동

Overleaf는 `paper/`를 worktree로 쓰는 별도 Git metadata `.overleaf-git/`에 연결돼 있다.

동기화 명령:

`./sync-overleaf "커밋 메시지"`

이 명령은 remote에 로컬에 없는 변경이 있으면 push를 중단한다. `paper/`를 수정한 뒤 빌드/검토가 끝났을 때만 실행해라.

현재 Overleaf local branch의 최근 커밋은 다음 흐름이다.

- Draft KV-CARE introduction from 0827 outline
- Update Related Work references
- Write Related Work
- Disambiguate Related Work notation
- Restructure body around KV-CARE design

현재 `paper/refs/baseline-references-2026-07-30.md`의 corrected Reconfigure 값은 아직 Overleaf 쪽에 미동기화된 상태다.

## 10. 지금 이어서 할 작업

가장 자연스러운 다음 작업은 새 실험을 더 돌리는 것이 아니라 다음 순서다.

1. 위 파일들을 실제로 읽고 현재 상태를 요약한다.
2. `make_recovery_ttr_slide.py`와 `make_recovery_2d.py`를 corrected Reconfigure JSON 기준으로 고친다.
3. recovery figure PDF/PNG를 재생성한다.
4. Notion Evaluation 0827과 `experiments/REPORT.md`를 기준으로 `paper/sections/evaluation.tex`을 FT-first 구조로 다시 작성한다.
5. N=3 protection-overhead 표/그림을 Evaluation에 반영한다.
6. 오래된 `abstract.tex`과 `discussion.tex`을 KV-CARE/IoT-J/FT-first 기준으로 갱신한다.
7. 문장과 수치가 확정된 뒤 `./sync-overleaf`로 반영한다.

우선 지금은 수정하지 말고 다음 네 항목을 보고해줘.

1. 네가 이해한 현재 논문의 한 문장 핵심 주장
2. 현재 source of truth와 legacy 파일 구분
3. 아직 고쳐야 하는 stale figure/section 목록
4. 다음 편집을 어떤 순서로 진행할지
