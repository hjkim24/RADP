# AGENTS.md — RADP 프로젝트 에이전트 컨텍스트

Recovery-Aware DP (RADP): 이종 Jetson 엣지 fleet 분산 LLM 추론, fault-tolerance 중심. 제출 타깃 IEEE TII.

> 이 파일은 Codex 등 `AGENTS.md`를 읽는 에이전트용. Claude Code는 별도로
> `~/.claude/projects/-Users-hjkim24-RADP/memory/`(auto-memory)를 로드함 —
> 같은 사실을 여기 요약해 둠. 상세는 `experiments/REPORT.md`·`PHASES.md`.

## 복구 계열 네이밍: 논문/덱 이름 ↔ 코드 식별자 (헷갈리지 말 것)

표시 이름만 새로 정했고(2026-08-05), **코드 식별자는 rename 금지**(안정 인터페이스).

| 논문/덱/figure 이름 | 코드 식별자 (`recovery_mode` 등) | 뭐냐 |
|---|---|---|
| **KV-RAID** (우리 방식) | `parity` | cross-stage GF 패리티. KV-RAID-5=단일(k=1), KV-RAID-6=이중(k=2, `RADP_PARITY_K=2`) |
| **Recompute** | `full_replay` | 전체 재계산 strawman |
| **Petals** | `surgical` | input-replay 복구 |
| **DejaVu** | `replicate` | 전체 KV 복제 (DéjàVu, ICML'24) |
| **Reconfigure** | `reactive_replacement` | naive re-solve + cold restart |

- 표시 이름 매핑은 `paper/figures/_slide.py`의 `NAME` dict에 중앙화(display-only).
- `recovery_mode` 값·`RADP_PARITY_K` env·결과 JSON `t["mode"]`·`ReplicaCache`/`ParityCache` 클래스는 절대 rename 안 함.
- **Reconfigure ≠ SpotServe**: Reconfigure 베이스라인 = naive re-solve + cold reload + position 0 재생. SpotServe(ASPLOS'24)는 config를 re-solve하되 cold restart는 일부러 피함(bipartite matching 마이그레이션 + stateful inference recovery). SpotServe는 "왜 서빙이 naive reconfiguration을 피하나"의 근거로 인용하는 것이지 우리 Reconfigure를 구현한 시스템이 아님.

## KV-RAID-6 상태 (구현·라이브검증 완료 + 함정 2개)

KV-RAID-6 = GF(2⁸) double-parity (P=XOR ⊕ Q=Σgⁱ·Dᵢ, 토글 `RADP_PARITY_K=1|2`, Anvin RAID-6). 동시 2개 non-head stage 실패를 재계산 0으로 복구. **k=1은 기존 KV-RAID-5 byte-for-byte**, 워커 무변경(Q는 coordinator가 계산). 구현: `radp/coordinator/gf256.py`(2-erasure solver)·`parity_cache.py`(Q blob)·`gateway.py`(`_recover_parity_double`). 라이브 fleet **5/5 bit-correct**.

- **함정 1 — TTR 절편:** 라이브 `TTR(P)=30.29s + 2.78ms·P`에서 **절편 30.3s는 알고리즘 비용이 아니라 이 fleet의 축퇴 복구테이블 아티팩트**. 자동 solve된 R이 non-head 백업을 전부 `on-2`로 몰아 약한 Nano가 stage 3개+cold-load(같은 fleet 단일 실패 KV-RAID 복구는 284ms). 집중은 상수 offset만 더하고 **기울기(≈0, zero-recompute)는 안 오염** → "재계산 0" 결론 유효. 절대 TTR은 백업 분산 R에서 재측정 필요(future work). 30s를 알고리즘 비용으로 표기 금지.
- **함정 2 — 일반 RS(k≥3) 미채택:** k-parity가 replicate(DejaVu) 대비 저장 이득 있으려면 `k < Σ(non-head)/max(non-head)`. 현 fleet Σ/max=**2.25** → k=1,2만 이기고 k≥3은 저장이 replicate 초과+내성 약함=dominated. RAID-6(k=2)가 이 fleet 실질 상한.
- 상세: `experiments/REPORT.md §B1-RAID6`, `PHASES.md` Phase B1-RAID6, spec `docs/superpowers/specs/2026-08-03-raid6-double-parity-recovery-design.md`, 결과 `experiments/results/b1_ft_raid6.json`.

## 상시 규칙

- 새 feature/phase 완료 시 `PHASES.md`에 섹션 추가.
- `paper/refs`에 PDF 추가 시 `PAPERS.md`에 항목 + 파일명 `{System}_{Title-With-Dashes}.pdf`.
- 지도교수 방침(2026-07-16 이후): 논문 작성보다 실험 우선, FT를 중심축으로. network overhead는 논문에서 제외(2026-07-30).
