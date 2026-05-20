# RADP — Recovery-Aware DP for Distributed LLM Inference

PETALS 기반 분산 LLM 추론 환경에서 **이기종 엣지 디바이스(Jetson Nano)** 를 활용한 파이프라인 병렬화 구현. 핵심 기여는 **레이어 배치와 장애 복구를 통합한 단일 최적화 문제 (Recovery-Aware DP)**.

자세한 연구 동기·알고리즘·실험 계획은 [plan.md](./plan.md) 참조.

---

## Quick Start

```bash
# 1) 의존성 설치 (개발 + quant 포함은 옵션)
uv sync --extra dev

# 2) gRPC 스텁 생성
bash scripts/gen_proto.sh

# 3) 점검
uv run ruff check radp tests
uv run mypy radp
uv run pytest --collect-only

# 4) git 훅 활성화 (Conventional Commits 메시지 검증)
git config core.hooksPath scripts/git-hooks
```

## CLI

```bash
uv run radp-coordinator --config experiments/configs/opt_6_7b_int4.yaml
uv run radp-worker      --coord <host:port> --device-id jetson-1
uv run radp-profile     --output profiles/jetson1.json
```

## 디렉터리 구조

```
radp/
├── common/        # 타입, 프로토콜, 모델 유틸 (공통)
├── coordinator/   # DP 스케줄러, 복구 테이블, 장애 감지, 게이트웨이
├── worker/        # 스테이지 추론, 가중치 로더, heartbeat
├── profiler/      # 레이어/네트워크 프로파일링
└── cli/           # 엔트리포인트
experiments/       # 벤치마크 / 시나리오 / 분석 스크립트
tests/             # pytest 단위 테스트
```

## 구현 단계 (plan.md §4.2)

- **Phase 1**: 오프라인 컴포넌트 (profiler + scheduler + recovery_table)
- **Phase 2**: 분산 추론 인프라 (protocol + stage_runner + weight_loader + gateway)
- **Phase 3**: 장애 처리 (heartbeat + failure_detector + 복구 트리거)
- **Phase 4**: 실험 및 평가
