# Introduction v4 — IEEE Internet of Things Journal

## 문단 1 — IoT 현장에서는 local inference가 운영 전제다

- **주장:** 일부 IoT 배치는 cloud offload를 안정적으로 사용할 수 없으므로 LLM inference를 현장에 남겨야 한다.
- **근거 및 전개:**
  - air-gapped 산업망은 외부 연결을 허용하지 않고, 원격 인프라·오지·해상 설비는 지속적인 cloud link를 전제하기 어렵다.
  - 현장 로봇과 드론은 통신 단절 중에도 판단을 이어가야 하므로 per-token cloud round trip에 의존할 수 없다.
  - LLM은 battery management, 항공 조립 fault diagnosis, industrial visual monitoring, ICS protocol emulation 등 IoT·산업 현장 문제에 이미 적용되고 있다 [Zhang'26 TII] [Liu'24 TII] [Wang'24 TII] [Chamotra'26 TII] **[확인 — IOTJ/IoT-venue citation needed]**.
  - 이 논문의 local inference 동기는 cloud availability가 정하는 배치 조건에 둔다.
- **다음 문단 연결:** local execution이 필요해도 모델과 실행 상태가 한 장치에 들어가지 않으면 여러 현장 노드를 묶어야 한다.

## 문단 2 — 단일 장치의 capacity wall이 heterogeneous pipeline을 요구한다

- **주장:** billion-parameter model의 weight와 sequence length에 따라 누적되는 KV cache를 함께 수용하려면 여러 heterogeneous edge node에 layer를 나눠야 한다.
- **근거 및 전개:**
  - autoregressive inference는 model weight와 매 token마다 증가하는 KV state를 계속 보존하므로 loader peak와 runtime state가 device memory를 함께 압박한다.
  - 우리 fleet의 Jetson Orin Nano에서 single-bin OPT-1.3B (2.6 GB)는 세 번의 배포 시도 모두 실패했다. auto-placement의 18-layer load는 OOM reboot, 재시도의 18-layer LoadStage는 OS reboot, manual 4–5-layer placement는 swap-thrash를 일으켰다.
  - 원인은 `torch.load`가 single-bin checkpoint 전체를 materialize해 layer split 이후에도 worker peak가 model size에 접근한 데 있다. Sharded checkpoint는 이 loader peak를 피하는 방법이며 본 연구 범위 밖이다.
  - 이미 배치된 GPU tier와 CPU-only node의 처리량은 같은 fleet에서도 최대 **76×** 차이 나므로 균등 분할은 적절하지 않다.
  - cloud–edge–end collaborative inference는 여러 장치에 computation을 나누는 접근을 확립했고 [Lin'20 TII] [Wu'21 TII], EdgeShard와 Jupiter는 heterogeneity와 memory budget을 반영해 layer placement를 최적화한다 [EdgeShard] [Jupiter].
- **다음 문단 연결:** 이 pipeline은 한 장치의 memory 한계를 넘지만, 어느 한 stage의 failure가 전체 generation state를 끊는 새로운 failure domain을 만든다.

## 문단 3 — Edge pipeline의 실제 공백은 unreliability다

- **주장:** heterogeneous placement가 성능 문제를 다뤘더라도, 실행 중 worker failure를 복구하지 못하면 IoT serving stream은 첫 장애에서 중단된다.
- **근거 및 전개:**
  - IoT node는 energy depletion과 hardware malfunction에 노출되며 [Kaur'23 TII], 한 computing node의 failure는 data loss와 performance degradation으로 이어질 수 있다 [Xu'20 TII].
  - 우리 fleet에서도 crash, OOM, network partition을 직접 관측했다.
  - EdgeShard와 Jupiter는 heterogeneity를 정면으로 다루지만 각 layer의 active copy를 한 device에 두며 in-flight recovery path를 제공하지 않는다 [EdgeShard] [Jupiter].
  - 따라서 한 stage가 사라지면 그 stage에 있던 KV state와 pipeline continuity가 함께 사라져 진행 중 stream이 abort된다.
- **다음 문단 연결:** recovery path를 추가하려면 spare state를 어디에 둘지 결정해야 하며, memory-tightness가 가능한 해법을 제한한다.

## 문단 4 — 기존 복구법의 운영 전제가 memory-tight IoT edge와 맞지 않는다

- **주장:** 기존 swarm·datacenter recovery는 guaranteed spare memory, 관리된 failure model, 고성능 interconnect를 전제로 하며 이 조건들은 memory-tight IoT fleet의 운영 조건과 맞지 않는다.
- **근거 및 전개:**
  - Petals는 failed stage의 과거 입력을 replay할 replacement peer가 같은 layer를 이미 보유한다고 가정한다 [Petals].
  - DejaVu의 full KV replication은 replica를 상시 보관할 memory headroom을 요구한다 [DejaVu].
  - GhostServe의 erasure-coded checkpoint는 datacenter-class host memory와 intra-node serving infrastructure에 맞춰 설계되었다 [GhostServe].
  - SpotServe는 예고된 preemption에 맞춘 migration과 stateful recovery를 사용하므로 abrupt crash·OOM·network partition이 발생하는 edge failure model과 조건이 다르다 [SpotServe].
  - 이 regime에서 warm spare와 stored-KV replica는 보장된 capacity가 아니며, datacenter recovery substrate를 그대로 전제할 수 없다.
- **다음 문단 연결:** 전제의 차이를 확인한 뒤에는 각 recovery family가 recovery time과 steady-state storage에서 지불하는 비용을 비교해야 한다.

## 문단 5 — Edge에 맞는 recovery strategy는 recovery time과 steady-state storage를 함께 봐야 한다

- **주장:** recovery time과 steady-state storage의 두 축이 heterogeneous, memory-tight edge의 recovery design space를 정의하며, 이 regime에 맞는 strategy는 선행 연구에서 정립되지 않았다.
- **근거 및 전개:**
  - recompute-from-scratch는 pipeline 전체를 다시 실행하고, Petals 계열 input replay는 failed stage만 mirror된 입력으로 다시 실행하므로 둘 다 failure position (P)까지의 진행량에 따라 recovery work가 증가한다 [Petals].
  - stored-KV는 model forward pass를 제거하지만, DejaVu식 full replication은 모든 non-head stage의 KV를 보존해 pipeline depth N에 따라 steady-state storage가 증가한다 [DejaVu].
  - GhostServe는 datacenter serving 안에서 erasure-coded KV checkpointing으로 replication storage를 줄인다 [GhostServe]. RADP는 coding group을 heterogeneous, memory-tight node의 pipeline stage들로 구성하며, 그 storage cost를 정하는 ψ가 recovery requirement의 제약도 함께 받는 문제를 다룬다.
  - proactive backup 없이 survivor 위에서 placement를 다시 풀면 recovery는 P와 무관하게 약 **53초**의 median을 보였고, cold weight reload와 position 0 replay가 비용을 지배했다.
  - SpotServe가 bipartite matching migration과 stateful recovery로 naive cold restart를 회피한 설계도 no-backup reconfiguration의 비용을 뒷받침한다 [SpotServe].
- **다음 문단 연결:** RADP는 이 trade-off에서 recomputation과 stage-sum storage를 동시에 피하기 위해 cross-stage parity를 사용한다.

## 문단 6 — Cross-stage parity는 failed stage의 KV를 model forward 없이 복원한다

- **주장:** RADP의 single-parity 구성은 non-head stage들의 KV state를 하나의 parity column으로 결합해 단일 stage failure에서 원래 KV byte를 직접 복원한다.
- **근거 및 전개:**
  - 각 non-head stage는 새 KV column을 coordinator로 보내고, coordinator는 서로 다른 stage 길이를 zero-padding한 뒤 byte-wise parity로 누적한다.
  - failure가 발생하면 coordinator는 parity column과 surviving stage의 KV column을 결합해 failed stage의 KV를 복원하고 promoted backup에 설치한다.
  - 이 경로에는 model forward pass가 없으므로 recovery work가 failure position에 비례해 늘지 않는다.
  - 저장된 byte를 역연산해 복원하므로 primary parity path가 실행된 경우 recovered KV는 원본과 bit-identical이라는 guarantee를 갖는다.
  - 같은 stage를 CUDA와 CPU에서 재계산하면 KV 원소의 **26.9%**가 달랐고 최대 absolute error는 **2⁻⁸**이었다. 이 결과는 stored-byte recovery의 reproducibility guarantee를 지지한다.
  - **3156**번의 token decision은 모두 일치했으므로 output error에 대한 개선 claim은 세우지 않는다.
- **다음 문단 연결:** 이 메커니즘의 가치는 single-failure TTR의 (P)-의존성과 steady-state storage scaling을 함께 측정하면 드러난다.

## 문단 7 — Single-parity는 flat-in-P recovery와 O(1) storage를 동시에 보인다

- **주장:** single-failure 실측에서 cross-stage parity는 stored-KV recovery의 낮은 TTR을 유지하면서 full replication보다 적은 steady-state storage를 사용한다.
- **근거 및 전개:**
  - 5-stage OPT-350M Jetson fleet에서 `TTR(P) = 284.1 ms + 0.87 ms·P`였으며, Petals 계열의 **16.21 ms/pos**보다 **19×**, recompute-from-scratch의 **164.32 ms/pos**보다 **188×** 완만했다.
  - P=32에서 no-backup survivor reconfiguration은 cross-stage parity보다 약 **176×** 느렸다.
  - DejaVu는 `239.3 ms + 2.67 ms·P`로 cross-stage parity와 사실상 동률이며, 두 계열이 모두 zero-recompute임을 확인한다 [DejaVu].
  - 같은 head-heavy placement에서 cross-stage parity는 KV token당 **16,384 B**, DejaVu replication은 **36,864 B**를 저장해 전자가 **2.25×** 적다. 이 비율은 head가 15/24 layer를 가진 보수적인 배치에서 얻었다.
  - parity storage는 max non-head stage 하나에 의해 정해져 pipeline depth에 대해 O(1)이고, replication은 non-head stage 합으로 정해져 O(N)이다.
  - per-token 차이는 작지만 누적 격차는 OPT-350M의 2048-token context에서 약 **40 MB**, 균등 pipeline의 OPT-350M@4096에서 약 **230 MB**, OPT-13B@4096에서 약 **1.9 GB**로 커진다. 뒤의 두 값은 model geometry 계산이며 live measurement가 아니다.
- **다음 문단 연결:** parity storage가 max stage 크기에 의해 결정된다는 사실은 fault tolerance를 placement 완료 뒤에 덧붙일 수 없음을 뜻한다.

## 문단 8 — ψ와 R은 feasibility·storage·routing에서 결합된다

- **주장:** finite recovery-hosting capacity에서는 ψ(layer placement)가 recovery storage와 R(recovery routing)의 feasibility·quality를 함께 결정한다.
- **근거 및 전개:**
  - **Storage coupling (structural):** parity column 크기는 `max(non-head stage KV)`이므로 ψ의 partition boundary가 steady-state recovery storage를 정확히 정한다.
  - **Routing coupling (observed):** ψ와 독립적으로 푼 R이 모든 non-head backup을 약한 node 한 대에 집중시키는 degenerate recovery table을 우리 fleet에서 실제로 만들었다.
  - **Feasibility condition:** peer k가 `free(k) − self(k) ≥ max_stage(ψ)`를 만족하지 못하는 memory regime에서는 cost-first ψ에 recovery table이 없을 수 있으므로 ψ와 R의 공동 탐색이 필요하다.
  - **Controlled sweep:** live cluster snapshot의 reported free memory를 device당 600–300 MB로 제한하고 backup host를 pipeline device로 동일하게 맞춘 offline deterministic sweep에서, decoupled procedure는 recovery table을 찾지 못했지만 joint alternating DP는 feasible (ψ, R)을 찾았다. 이 결과는 production solver의 계산이며 live deployment failure가 아니다.
  - **Scope limit:** uncapped OPT-350M fleet은 largest stage 576 MB에 대해 약 5 GB의 peer headroom을 가져 binding band 밖에 있다. 이 조건에서는 cost-only 2-stage와 production 4-stage의 차이가 feasibility 증거가 아니며, `REPORT.md` §12.3의 non-binding 결과와 일치한다.
  - **Backup-host scope:** R이 whole fleet을 사용할 때 decoupled procedure는 250 MB cap까지 유지됐으며, pipeline에 선택되지 않는 CPU-only node의 5–6 GB free memory가 recovery capacity를 제공했다. 이는 backup hosting이 compute speed보다 memory·bandwidth에 좌우됨을 보이는 design-space 결과이며, whole-fleet R 분리는 아직 구현하지 않았다.
- **다음 문단 연결:** RADP는 이 coupling을 ψ와 R이 서로의 제약을 갱신하는 alternating DP로 구현한다.

## 문단 9 — RADP는 ψ와 R을 하나의 alternating DP에서 갱신한다

- **주장:** RADP의 alternating DP는 recovery requirement를 placement feasibility에 반영하고 placement 결과를 다음 recovery-routing 결정에 되돌린다.
- **근거 및 전개:**
  - ψ update는 현재 R이 요구하는 backup-memory reservation을 feasibility check에 포함해 layer boundary와 active stage placement를 선택한다.
  - R update는 현재 ψ가 만든 stage 크기와 남은 device capacity를 사용해 recovery destination을 선택한다.
  - 갱신된 R의 reservation은 다음 ψ update로 돌아가며, 두 결정이 동시에 수용되는 placement와 recovery table을 구성한다.
  - 하나의 cost knob가 latency-optimal regime [EdgeShard]과 throughput-optimal regime [Jupiter]을 같은 formulation에 담지만, 이 통합은 fault-tolerant feasibility를 지원하는 부수 기능이다.
  - automatic node subset selection은 본 논문의 구현 범위 밖이며 future work로 남긴다.
- **다음 문단 연결:** 이 공동 정식화는 parity column 수를 늘리는 제한된 multi-failure extension으로 이어진다.

## 문단 10 — Multi-failure extension은 double-parity 검증 범위로 한정한다

- **주장:** cross-stage parity는 k개 parity column으로 동시 k개 failure를 견디도록 구성할 수 있으며, 본 연구는 double-parity (f=2)까지만 구현하고 live fleet에서 검증했다.
- **근거 및 전개:**
  - double-parity는 GF(2⁸)의 두 parity equation으로 두 failed non-head stage의 KV를 model forward 없이 복원한다.
  - live trial에서 **5/5** sequence가 bit-correct하게 일치했고 TTR slope는 **2.78 ms/pos**로 flat-in-P 성질을 유지했다.
  - double-parity의 steady-state storage는 KV token당 **32,768 B**다.
  - k-parity가 replication보다 적게 저장하려면 `k < Σ(non-head)/max(non-head)`이어야 한다. 현재 placement의 비는 **2.25**이므로 k≥3은 저장이 더 크면서 failure tolerance는 더 약해져 구현하지 않았다.
  - Reed–Solomon erasure-coding 계보에 연결할 확정 citation key는 **[확인]**이다.
- **다음 문단 연결:** 이 제한된 확장까지 포함하면 기여는 recovery mechanism, measured trade-off, recovery-driven placement, 검증 범위로 정리된다.

## 문단 11 — Contributions

- **주장:** RADP의 기여는 heterogeneous IoT edge의 fault tolerance를 주축으로 하며 placement optimization은 그 fault tolerance를 feasible하게 만드는 역할을 맡는다.
- **근거 및 전개:**
  - **Fault-tolerance design space:** heterogeneous, memory-tight edge에서 recovery time과 steady-state storage를 함께 비교해야 함을 보이고, recomputation, input replay, KV replication, survivor reconfiguration 사이에서 cross-stage parity가 차지하는 operating point를 실측했다.
  - **Cross-stage parity:** single-parity가 failed stage의 KV를 zero-recompute·bit-identical하게 복원하며, single-failure TTR이 flat-in-P이고 storage가 pipeline depth에 대해 O(1)임을 보였다.
  - **Recovery-driven placement:** parity storage와 recovery-table quality가 ψ에 의존함을 보였고, matched backup-host scope의 controlled memory-cap sweep에서 decoupled procedure가 recovery table을 잃는 600–300 MB regime에서도 alternating DP가 feasible (ψ, R)을 찾음을 확인했다. Uncapped OPT-350M fleet은 이 binding regime 밖에 있다.
  - **Live evidence:** 5-stage OPT-350M Jetson fleet에서 recovery family별 TTR slope, parity와 DejaVu의 TTR 동률, **2.25×** storage 차이, cross-tier recomputation의 bit-level divergence를 같은 fault-injection framework에서 확인했다.
  - **Bounded multi-failure extension:** k-parity 구성을 제시하고 double-parity (f=2)을 구현해 **5/5** live sequence에서 zero-recompute recovery를 검증했으며 k≥3은 현재 storage geometry에서 제외했다.
- **다음 문단 연결:** 이후 section은 이 순서에 맞춰 recovery model과 cross-stage parity를 먼저 설명하고, 그 제약을 수용하는 alternating DP와 evaluation을 뒤이어 제시한다.
