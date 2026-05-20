# Recovery-Aware DP for Distributed LLM Inference on Heterogeneous Edge Clusters

## 1. 프로젝트 개요

### 1.1 연구 주제
PETALS 기반 분산 LLM 추론 환경에서 **이기종 엣지 디바이스(Jetson Nano)** 를 활용한 파이프라인 병렬화 구현. 핵심 기여는 **레이어 배치와 장애 복구를 통합한 단일 최적화 문제 (Recovery-Aware DP)** 설계.

### 1.2 동기

기존 시스템의 한계:

| 시스템 | 한계 |
|---|---|
| PETALS | Greedy 레이어 배치 → 처리량 최대 2.38× 손실 (Helix 실측). FT는 레이어 redundancy 전제 → 4GB 환경에서 불가능 |
| EdgeShard Algo.2 | DP로 배치 최적화하나 FT 부재. 부분집합 탐색으로 O(N²×2^M×M²) |
| Jupiter | 모든 디바이스 참여 가정으로 O(L²×\|D\|), but 정적 오프라인 계획. FT 부재 |

**근본 문제**: 현재 배치 결정이 복구 가능성을 전혀 고려하지 않음. Jetson Nano 4GB 메모리 환경에서는 레이어 redundancy 유지가 어려워, 장애 시 대체 노드가 메모리 여유가 없으면 복구 자체가 불가능.

### 1.3 목표

**단일 DP로 배치 최적화와 복구 가능성을 동시에 해결**하는 Recovery-Aware DP 설계 및 구현.

---

## 2. 시스템 아키텍처

### 2.1 구성 요소

```
┌─────────────────────────────────────┐
│  Coordinator Node (성능 좋은 보드)    │
│  ┌─────────────────────────────┐    │
│  │ DP Scheduler                │    │
│  │ - Recovery-Aware DP 실행     │    │
│  │ - 배치 Ψ + 복구 테이블 R 산출  │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ Failure Detector            │    │
│  │ - Heartbeat 모니터링         │    │
│  │ - 장애 시 R 조회 및 복구 트리거 │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ Activation Cache            │    │
│  │ - 각 스테이지 입력 activation │    │
│  │   미러링 저장                 │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ Request Gateway             │    │
│  │ - 사용자 요청 입출력          │    │
│  └─────────────────────────────┘    │
└─────────────────────────────────────┘
              │
   ┌──────────┼──────────┐
   ▼          ▼          ▼
┌─────────┐ ┌─────────┐ ┌─────────┐
│Jetson #1│ │Jetson #2│ │Jetson #3│
│ - 담당   │ │ - 담당   │ │ - 담당   │
│   레이어 │→│   레이어 │→│   레이어 │
│ - Reserve│ │ - Reserve│ │ - Reserve│
│   slot   │ │   slot   │ │   slot   │
└─────────┘ └─────────┘ └─────────┘
```

### 2.2 데이터 흐름

**정상 추론**:
```
User → Coordinator → Stage 1 → activation 캐싱 → Stage 2 → ... → Stage N → Output → User
```

**장애 복구**:
```
1. Coordinator: 노드 j 장애 감지 (heartbeat timeout)
2. R(j) = k 조회 (precomputed)
3. 노드 k의 reserve slot에 노드 j의 레이어 가중치 다운로드
4. Coordinator가 캐싱한 activation을 노드 k로 전송
5. 노드 k가 자기 레이어 + 복구 레이어 순차 처리
6. 다운로드 중 해당 구간 신규 요청은 큐잉
```

---

## 3. 핵심 알고리즘: Recovery-Aware DP

### 3.1 DP 상태 정의

```
A(1→y, Dn) = 첫 y개 레이어를 첫 n개 디바이스 Dn = {d_1, ..., d_n}로 
              처리할 때 최적 균형 파이프라인의 최대 스테이지 시간
```

### 3.2 점화식

```
A(1→y, Dn) = min over l (1 ≤ l < y):
             max{ A(1→l, Dn-1),  T_stage(l+1→y, d_n) + T_comm(d_{n-1} → d_n) }

T_stage(l+1→y, d_n) = Σ T_comp(i, d_n) for i = l+1 to y
```

### 3.3 제약 조건

**(1) 메모리 제약 (핵심 기여)**:
```
Σ mem(i) for i in stage(k)  +  Σ Σ mem(i) for j in R⁻¹(k), i in stage(j)  ≤  Mem(k)
└────────── 자기 담당 ──────────┘  └─────────── 백업 reserve slot ───────────┘

R⁻¹(k) = { j : R(j) = k }
```

**(2) SLO 제약**:
```
TTFT(Ψ) ≤ TTFT_SLO  (예: 300ms)
TBT(Ψ)  ≤ TBT_SLO   (예: 100ms)
```

**(3) 복구 가능성**:
```
∀ j ∈ D, ∃ R(j) ∈ D \ {j}  (모든 노드는 백업이 존재)
```

**(4) 커버리지**:
```
∀ i ∈ {1, ..., L}, ∃! k ∈ D s.t. Ψ(i) = k  (모든 레이어가 유일하게 배치)
```

제약 위반 시 A(y, n) = ∞ 처리 → min 연산에서 자동 배제.

### 3.4 복구 테이블 R 결정

```
R(j) = argmin over k ∈ D \ {j}: 
       [ T_download(j → k) + T_recompute(k) ]
       
s.t.  Σ mem(stage(j)) ≤ free_mem(k)
```

**구현 단순화**: R을 휴리스틱으로 먼저 결정한 후 DP 1회 실행. 향후 R-Ψ alternating optimization으로 확장 가능.

### 3.5 시간 복잡도

```
Recovery 결정: O(|D|²)
DP forward:    O(L² × |D|)
Backtracking:  O(|D|)

전체: O(L² × |D|)
```

---

## 4. 구현 모듈 설계

### 4.1 모듈 구조

```
project/
├── coordinator/
│   ├── __init__.py
│   ├── scheduler.py          # Recovery-Aware DP 메인
│   ├── recovery_table.py     # R 결정 로직
│   ├── failure_detector.py   # Heartbeat 모니터
│   ├── activation_cache.py   # 스테이지 입력 캐싱
│   └── gateway.py            # 사용자 요청 처리
├── worker/
│   ├── __init__.py
│   ├── stage_runner.py       # 레이어 추론 실행
│   ├── weight_loader.py      # 가중치 동적 로드
│   └── heartbeat_sender.py   # 코디네이터로 상태 보고
├── profiler/
│   ├── __init__.py
│   ├── layer_profiler.py     # 레이어별 연산/메모리 측정
│   └── network_profiler.py   # 노드 간 대역폭 측정
├── common/
│   ├── __init__.py
│   ├── protocol.py           # 코디네이터-워커 통신 프로토콜
│   ├── model_utils.py        # LLM 로딩, 레이어 분할
│   └── types.py              # 공통 타입 정의 (Psi, R, etc.)
└── experiments/
    ├── run_normal.py         # 정상 운영 벤치마크
    ├── run_failure.py        # 장애 시나리오
    └── analyze.py            # 결과 분석
```

### 4.2 Phase별 구현 우선순위

#### Phase 1: 오프라인 컴포넌트 (단독 실행 가능)
- [ ] `profiler/layer_profiler.py` — Jetson에서 레이어별 실측
- [ ] `profiler/network_profiler.py` — 노드 간 대역폭 측정
- [ ] `coordinator/scheduler.py` — DP 알고리즘 본체 (단위 테스트로 검증)
- [ ] `coordinator/recovery_table.py` — R 결정 휴리스틱

#### Phase 2: 분산 추론 인프라
- [ ] `common/protocol.py` — gRPC 또는 ZeroMQ 기반 메시지 정의
- [ ] `worker/stage_runner.py` — 단일 스테이지 추론 실행
- [ ] `worker/weight_loader.py` — 동적 가중치 로딩
- [ ] `coordinator/gateway.py` — 사용자 요청 입출력
- [ ] `coordinator/activation_cache.py` — activation 미러링 저장

#### Phase 3: 장애 처리 메커니즘
- [ ] `worker/heartbeat_sender.py`
- [ ] `coordinator/failure_detector.py`
- [ ] 복구 트리거 → 가중치 다운로드 → activation 전달 흐름 연결

#### Phase 4: 실험 및 평가
- [ ] `experiments/run_normal.py`
- [ ] `experiments/run_failure.py`
- [ ] `experiments/analyze.py`

---

## 5. 알고리즘 의사코드 (구현 가이드)

### 5.1 Phase 1: 복구 테이블 결정

```python
def determine_recovery_table(D, mem_layers, Mem_nodes, BW, current_placement):
    """
    R(j): 각 노드 j의 백업 노드를 결정
    """
    R = {}
    for j in D:
        best_k = None
        best_cost = float('inf')
        
        for k in D:
            if k == j:
                continue
            
            # j의 레이어 메모리를 k가 받을 수 있는지
            j_layer_mem = sum(mem_layers[i] for i in current_placement[j])
            if Mem_nodes[k] - current_used_mem(k) < j_layer_mem:
                continue
            
            # 복구 비용: 다운로드 + 재계산
            cost = T_download(j, k, BW) + T_recompute(k, j_layer_mem)
            
            if cost < best_cost:
                best_cost = cost
                best_k = k
        
        if best_k is None:
            raise NoRecoveryError(f"Node {j} has no backup candidate")
        R[j] = best_k
    
    return R
```

### 5.2 Phase 2: Recovery-Aware DP Forward

```python
def recovery_aware_dp(L, D, T_comp, T_comm, mem_layers, Mem_nodes, R, SLO):
    M = len(D)
    A = [[float('inf')] * (M + 1) for _ in range(L + 1)]
    choice = [[-1] * (M + 1) for _ in range(L + 1)]
    
    # Base case: n=1, d_1 혼자
    for y in range(1, L + 1):
        if memory_check(D[0], 1, y, R, mem_layers, Mem_nodes):
            A[y][1] = sum(T_comp[i][D[0]] for i in range(1, y + 1))
    
    # Main loop
    for n in range(2, M + 1):
        d_n = D[n - 1]
        d_prev = D[n - 2]
        
        for y in range(n, L + 1):
            for l in range(n - 1, y):
                # Constraint 1: Memory (self + backup)
                if not memory_check(d_n, l + 1, y, R, mem_layers, Mem_nodes):
                    continue
                
                T_stage = sum(T_comp[i][d_n] for i in range(l + 1, y + 1))
                T_communication = T_comm[d_prev][d_n]
                
                # Constraint 2: SLO
                if not slo_check(A[l][n - 1], T_stage, T_communication, SLO):
                    continue
                
                cost = max(A[l][n - 1], T_stage + T_communication)
                
                if cost < A[y][n]:
                    A[y][n] = cost
                    choice[y][n] = l
    
    if A[L][M] == float('inf'):
        raise NoFeasibleSolutionError()
    
    return A, choice
```

### 5.3 Phase 3: Backtracking

```python
def backtrack(choice, L, M, D):
    Psi = []
    y = L
    
    for n in range(M, 0, -1):
        d_n = D[n - 1]
        if n == 1:
            Psi.append((1, y, d_n))
        else:
            l = choice[y][n]
            Psi.append((l + 1, y, d_n))
            y = l
    
    Psi.reverse()
    return Psi
```

### 5.4 메모리 제약 검사

```python
def memory_check(node_k, start, end, R, mem_layers, Mem_nodes, current_placement):
    """노드 k가 자기 레이어 + 백업 레이어를 모두 담을 수 있는가"""
    
    # 자기 담당 레이어 메모리
    self_mem = sum(mem_layers[i] for i in range(start, end + 1))
    
    # R⁻¹(k): k가 백업해야 할 노드들
    backup_nodes = [j for j, dest in R.items() if dest == node_k]
    backup_mem = sum(
        sum(mem_layers[i] for i in current_placement[j])
        for j in backup_nodes
    )
    
    return self_mem + backup_mem <= Mem_nodes[node_k]
```

---

## 6. 실험 환경 및 평가 계획

### 6.1 하드웨어 환경

- **코디네이터**: 성능 좋은 보드 (예: Jetson Orin AGX 또는 x86 미니PC)
- **워커**: Jetson Nano 4GB × N대 (이기종 보드 혼합 가능)
- **네트워크**: 유선 LAN (1Gbps), Linux TC 도구로 대역폭 변동 시뮬레이션 가능

### 6.2 모델

- 메모리 제약 고려하여 양자화된 소형 모델:
  - OPT-6.7B (INT4)
  - LLaMA-7B (INT4)
- 추론 태스크: WikiText-2 기반 텍스트 생성

### 6.3 비교 대상 (Baseline)

| 시스템 | 배치 방식 | FT |
|---|---|---|
| PETALS 원본 | Greedy | Reactive (dual-cache, redundancy 전제) |
| Jupiter-style DP | DP (처리량만) | 없음 |
| **우리 시스템** | **Recovery-Aware DP** | **복구 테이블 R 기반** |

### 6.4 평가 지표

**정상 운영**:
- 처리량 (tokens/s)
- TTFT (Time To First Token)
- TBT (Time Between Tokens)

**장애 시나리오**:
- 복구 시작까지 걸리는 시간
- 복구 완료까지 걸리는 시간 (가중치 다운로드 포함)
- 장애 중 드롭된 요청 수
- 복구 가능 여부 (redundancy 없는 환경)

**알고리즘 자체**:
- DP 실행 시간 (오프라인)
- 복구 메모리 예약으로 인한 정상 처리량 손실

### 6.5 실험 시나리오

1. **정상 운영 성능 비교**: 장애 없이 처리량/지연 비교
2. **단일 노드 장애 복구**: 임의 노드 강제 종료 → 복구 시간 비교
3. **메모리 여유 민감도**: 가용 메모리를 단계적으로 줄여가며 복구 가능성 측정
4. **이기종 환경 효과**: 노드 성능 차이가 클수록 DP 우위 확대 여부

---

## 7. 핵심 가정 및 한계

### 7.1 핵심 가정

- **디바이스 순서**: D는 외부에서 정렬되어 들어옴 (네트워크 토폴로지 기반). 모든 노드 참여 가정.
- **단일 사용자 / 단일 운영자**: 코디네이터가 master 역할로 동작.
- **레이어 1:1 매핑**: 각 레이어는 하나의 노드에만 배치 (메모리 제약상 redundancy 불가).
- **장애는 노드 단위**: 단일 노드 장애만 고려, 동시 다중 장애는 범위 외.

### 7.2 인정해야 할 한계

- **복구 시간 = 가중치 다운로드 시간 지배**: PETALS dual-cache처럼 즉시 복구는 불가능. Redundancy 없이는 본질적으로 다운로드 시간이 병목.
- **Proactive 예측 부재**: 장애를 사전 예측하지 않음 (Reactive 복구만).
- **단일 노드 장애만 처리**: 동시 다중 장애 시 복구 불가능할 수 있음.
- **R 휴리스틱**: 현재 단순 휴리스틱으로 R 결정. 진짜 joint 최적은 R-Ψ alternating optimization 필요.

---

## 8. 향후 확장 가능성

- **R-Ψ Alternating Optimization**: 더 정교한 복구 테이블 결정
- **동시 다중 장애 대응**: R(j)를 단일 노드가 아닌 후보 리스트로 확장
- **Online 재배치**: 부하 변화 시 동적 재배치 (현재는 정적 배치)
- **하드웨어 텔레메트리 기반 Proactive 예측**: 향후 연구 방향

---

## 9. 참고 논문

- **PETALS**: Borzunov et al., "Petals: Collaborative Inference and Fine-tuning of Large Models", ACL 2023; "Distributed Inference and Fine-tuning of Large Language Models Over The Internet", NeurIPS 2023.
- **EdgeShard**: Zhang et al., "EdgeShard: Efficient LLM Inference via Collaborative Edge Computing", arXiv 2024.
- **Jupiter**: Ye et al., "Jupiter: Fast and Resource-Efficient Collaborative Inference of Generative LLMs on Edge Devices", INFOCOM 2025.
- **Helix**: Mei et al., "Helix: Serving Large Language Models over Heterogeneous GPUs and Network via Max-Flow", ASPLOS 2025.
- **Parallax**: Tong et al., "Parallax: Efficient LLM Inference Service over Decentralized Environment", 2025.