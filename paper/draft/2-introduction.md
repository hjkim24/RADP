# Introduction — 초안 (Phase 1, 한글)

> 문체: 논문 어투 이전 단계. 논리 흐름 정리용 줄글 + 필요한 곳만 불렛.
> 용어(placement, throughput, recovery, KV cache 등)는 영문 유지.
> 수치는 기존 원고에서 가져온 값이며 최종 전 `REPORT.md` 대조 필요(→ 맨 아래 메모).

---

## 1. 배경 — 분산 추론이 왜 필요한가

많은 실제 응용에서 추론은 데이터가 생성되는 엣지에서 로컬로
수행되기를 요구한다 — on-device assistant, robotics, AR/VR, 산업
현장·off-grid 배포처럼 사용자·센서와 즉시 상호작용하는 워크로드다
`[확인 필요: 예시 확정]`. 가장 손쉬운 대안인 클라우드 offload는
매 token마다의 왕복 latency, 민감 입력의 외부 유출(privacy),
그리고 오프라인·불안정 링크에서의 사용 불가(connectivity) 때문에
바로 이 로컬 추론의 전제를 무너뜨린다. 즉 추론은 엣지에 남아야 한다.

**진짜 벽은 capacity다.** 최근 LLM은 billion-parameter를 넘어섰고,
inference 시점에는 model weight뿐 아니라 sequence가 길어질수록 불어나는
KV cache까지 메모리에 얹어야 한다. 이 예산은 엣지 디바이스 한 대의
용량을 쉽게 초과한다 — Jetson Nano급 보드는 가용 메모리가 4GB
수준이라, billion-parameter 모델은 애초에 **단일 디바이스에 적재조차
되지 않는다.** 엣지에 남아야 한다는 요구와, 한 대로는 못 올린다는
물리적 한계가 정면으로 충돌하는 지점이다.

"더 강력한 GPU 한 대"는 이 충돌의 답이 아니다. billion-parameter
모델을 한 대로 감당하려면 datacenter-class accelerator(A100/H100 등)가
필요한데, 이는 capacity는 충족해도 엣지 배포 맥락에서는 capex와
전력·운영 부담이 비현실적이고 `[확인 필요: 구체 가격 인용 시]`
"로컬에서 돌린다"는 목적 자체와도 어긋난다. 정작 현장에 이미 깔려 있는
자원은 저가 consumer GPU·embedded 보드(예: Jetson 계열) **여러 대**다.

그래서 남는, 그리고 자연스러운 선택지는 **이미 보유한 저가 이기종
엣지 디바이스 여러 대를 하나의 클러스터로 묶는 것**이다. model을 layer
단위로 쪼개 pipeline/model parallelism으로 배치하면, 개별 디바이스로는
불가능한 규모의 모델도 클라우드 없이 로컬에서 서빙할 수 있다
(distributed/collaborative inference). 이 방향의 이점은 단순히 "싸다"가
아니라 두 겹이다 — (i) 단일 저가 디바이스로는 **불가능한 것을 가능하게**
하고(capacity aggregation), (ii) 이미 배치된 commodity 하드웨어를
재활용하므로 추가 capex도, 클라우드 recurring cost도 들지 않는다.
그리고 이 방향은 이미 여러 시스템이 실제로 가능함을 보였다.

## 2. 기존 시스템과 그 한계

대표적으로 세 시스템이 이 그림을 밀어붙였다:

- **Petals** — consumer GPU들의 swarm으로 billion-parameter 모델을 서빙
- **EdgeShard** — DP 기반의 latency-optimal layer placement
- **Jupiter** — TBT(Token-Between-Time) 제약을 명시한 throughput-optimal
placement

문제는 이들이 데이터센터에서 물려받은 두 가정을 깔고 있고, 엣지 환경은
그 두 가정을 모두 깨뜨린다는 점이다.

- **① Homogeneity(동질성) 가정** — 실제 엣지 fleet은 GPU tier가 섞여 있고
(AGX Orin, Orin Nano 등) CPU-only 보드까지 끼어든다. 우리 6-worker
Jetson fleet(+ AGX Xavier coordinator) 측정에서 AGX MAXN이 Nano CUDA
보다 1.36× 빠르고 `[확인 필요]`, Nano CPU 보드까지 포함하면 fleet 내
성능 격차가 ~76×까지 벌어진다 `[확인 필요]`.
- **② Reliability(신뢰성) 가정** — 보드는 crash하고, 내부 저장소는 가득
차고, network는 partition된다. 측정 캠페인 동안 여러 보드에서 이 셋을
모두 겪었다. 이를 무시한 placement는 **첫 worker 실패 한 번에 스트림
전체가 abort되는** 시스템을 낳는다.

더 근본적인 한계는, 기존 시스템이 layer placement(ψ)와 recovery
routing(R)을 **placement와 분리해 다루거나 아예 다루지 않는다**는 데 있다:

- **EdgeShard** — latency/throughput DP로 ψ만 최적화하고 **recovery는
아예 다루지 않는다**. 각 layer가 정확히 한 device에만 배치되므로(한
layer당 노드 하나, Σ_j X_{i,j}=1), 그 device 하나가 죽으면 해당 stage가
소실되어 stream 전체가 abort된다. 게다가 cloud를 자원 풀에 포함한
edge-cloud·16–32GB device 세팅이라 `[확인 필요: testbed 12×AGX Orin +
2×Orin NX + RTX3090]` 4GB Nano pure-edge frontier와도 거리가 있다.
- **Petals** — greedy placement가 heterogeneous fleet에서 throughput을
2.38× 손해 보고 `[확인 필요]`, swarm-redundancy로 복구는 제공하지만
**16+GB peer**와 **엣지에는 없는 여유 메모리**를 전제한다 — 같은 block의
redundant copy가 여러 peer에 존재한다는 이 가정이 **4GB Nano regime에서는
감당 불가**하다.
- **Jupiter** — throughput-optimal DP지만 **recovery 이야기가 아예 없다**.

핵심 insight는, 이들을 단순히 조합한다고 각자가 포기한 것이 되돌아오지
않는다는 것이다. memory-tight한 엣지에서는 **R과 ψ의 feasibility 영역이
서로 coupled** 되어 있어서, 둘을 분리하면 feasibility 아니면 performance를
잃고 둘 다를 지킬 수 없다. (자세한 논거는 §Background)

## 3. 우리 접근 — RADP

RADP는 ψ와 R을 **하나의 alternating DP** 안에서 함께 푼다. 핵심은
backup-memory 예약량이 다시 placement의 feasibility 체크로 되먹임된다는
점이다. 즉 "어느 worker가 어느 transformer block을 hosting할지"를 정하는
바로 그 DP가 "실패 시 누구의 stage를 누가 흡수할지"까지 같이 결정한다.
그리고 cost knob α 하나로 EdgeShard의 latency regime(α=0)과 Jupiter의
throughput regime(α=1)을 **한 프레임 안에서** 커버한다.

이 joint optimization을 실제 엣지 fleet에서 돌아가게 만드는 런타임
메커니즘이 둘이다:

- **mirror-cache 기반 chain-aware recovery** — 세 조각이 맞물려 mid-stream
장애를 client에게 안 보이게 흡수한다.
  - **(a) mirror cache** — 각 worker가 자기 stage를 돌기 전에 들어온
  activation을 out-of-band one-way RPC로 coordinator에 미리 보내둔다.
  그래서 승격된 backup이 살아있는 chain을 방해하지 않고 KV state를
  재구성할 수 있다.
  - **(b) trailer 기반 failure attribution** — downstream `RunStage` 실패를
  gRPC trailing metadata에 죽은 stage의 (start, end)로 찍어, heartbeat가
  이미 backup으로 갈아탄 뒤에도 **진짜 죽은 worker를 정확히 지목**한다
  (race-safe).
  - **(c) chain replay** — backup만 재시도하면 chain forwarding 특성상
  살아남은 upstream이 이미 진행시킨 position을 double-count하므로,
  survivor의 KV를 **모두 evict하고** mirror cache의 head input history를
  **position 0부터 rewired chain으로 전체 재실행**해 각 stage의 KV를
  결정론적으로 재구성한다 (overhead O(positions × stages); backup만
  재구성하는 surgical replay는 future work).
- **asynchronous chain forwarding** (+ `ResultReady` reverse channel) —
겉으로는 pipeline인데 실제로는 조용히 직렬화되고 있던 sync chain을 끊어
throughput placement가 의도한 pipeline 병렬성을 실제로 살린다. sync
모드에선 각 worker가 다음 hop을 blocking으로 호출하고 응답이 다 풀릴
때까지 리턴하지 않아, C개 stream이 모든 stage의 handler thread를 붙잡은
채 stage를 늘려도 병렬성 없이 latency만 쌓인다. async는 worker가 next-hop을
던지고 즉시 ACK한 뒤 chain tail이 coordinator의 `ResultReady`로 결과를 직접
올려, 각 stage handler가 자기 일을 마치는 즉시 해제되게 한다.



## 4. 기여 (Contributions)

> 기존 원고 방식대로: [무엇을 했다] + [정량 결과] + (연결 섹션).
> 설계 3 + 평가 2 구성. 수치는 `[확인 필요]` 표시.

- **ψ+R alternating DP** — 다항 시간에 수렴하며, EdgeShard의
latency mode와 Jupiter의 throughput mode를 α로 조절되는 rank function
하나로 일반화한다. (§Design-A)
- **asynchronous mirror cache + chain-aware failure attribution** —
gRPC trailer metadata로, heartbeat가 이미 backup으로 갈아탄 뒤에도
진짜로 죽은 worker를 식별한다. (§Design-B)
- **asynchronous chain forwarding** — per-request locking과 coordinator측
`ResultReady` reverse channel로, chain 길이와 무관하게 C=16에서
17–47% throughput 향상 `[확인 필요]`. (§Design-C)
- **실측 평가** — 6-worker Jetson fleet(+ AGX Xavier coordinator)에서
OPT-350M 24개 operating point(chain length 2 × architecture variant 4
× concurrency 3)와 3× 큰 Llama-3.2-1B의 9-cell 4-stage sub-matrix를
측정 `[확인 필요]`. C≥4인 모든 지점에서 latency-optimal placement가
throughput-optimal placement를 앞서고, 이 우위가 3× model 크기 격차를
가로질러 유지됨을 보인다 — 특정 topology·runtime·model에서만 나오는
우연한 결과가 아니라 ψ+R joint optimization의 구조적 성질이다. (§Eval-D)
또한 mid-stream worker SIGKILL 상황에서 RADP는 기대 token 60개를 모두
정합하게 내보내는 반면, placement-only baseline은 이미 버퍼에 있던 17–20개
token 뒤로 abort된다 `[확인 필요]`. (§Eval-C)
- **cost-model ablation** — outer subset enumeration과 per-hop
γ_hop term을 켰을 때 L≻T 격차가 좁혀지는 게 아니라 오히려 **넓어짐**을
보인다. 남은 격차가 wire-cost 누락이 아니라 multi-stream system-level
효과임을 시사. (§Eval-E)



## 5. 논문 구성 (선택)

이후 구성: §Related에서 관련 연구를, §Background에서 ψ·R coupling의
근거를, §Design에서 알고리즘과 런타임을, §Eval에서 실측 결과를 다루고
§Discussion에서 마무리한다.

---



## (메모) 최종 전 확인 필요 수치 — REPORT.md / PHASES.md 대조

- 1.36× (AGX MAXN vs Nano CUDA, OPT-350M seq=64)
- ~76× (Nano CPU 포함 fleet 내 격차)
- 2.38× (Petals throughput 손해, cite Helix 확인)
- 17–47% @ C=16 (async chain forwarding gain)
- 24 operating points 구성(2×4×3), Llama-3.2-1B 9-cell 4-stage
- SIGKILL 시 60 tokens 정합 vs baseline 17–20 abort
- α=0/α=1 ↔ EdgeShard/Jupiter regime 대응 표현 확인
- (선택) A100/H100급 가격·전력 수치 — 경제적 부담을 수치로 뒷받침할 경우 인용 필요

