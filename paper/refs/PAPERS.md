# PAPERS.md — paper/refs 논문 카탈로그

> RADP related work용 선행연구 정리. **논문에 명시된 사실만** 기록 (comparison.md와 같은 원칙).
> 서론 엣지 동기부여 비교는 [comparison.md](comparison.md) 참조. venue는 dblp로 게재본 확인(프리프린트면 arXiv).

## 유지 규칙 (새 논문 추가 시)

1. 파일명: `{SystemName}_{Full-Title-With-Dashes}.pdf` (시스템명 없으면 `{Title-With-Dashes}.pdf`). 공백/콜론 금지, ASCII만.
2. 아래 인덱스 테이블에 행 추가 (연도 내림차순).
3. 상세 섹션 추가: 저자·년도·venue / 분야 태그 / 핵심 아이디어 / 실험 환경(scale·하드웨어·모델·실측 여부) / RADP 관련성.
4. venue는 dblp 등에서 게재본 확인(vol/no/pages/doi), 없으면 arXiv id. 중복 파일은 md5 확인 후 정리.

현재 32편.

## 인덱스

| 시스템/논문 | 년도 | Venue | 주요 분야 | 실험 환경 | 실측 |
|---|---|---|---|---|---|
| [GhostServe](#ghostserve) | 2026 | MLSys 2026; arXiv:2605.00831 | Fault Tolerance, LLM Serving, Erasure Coding | 데이터센터 | 실측 |
| [KevlarFlow](#kevlarflow) | 2026 | arXiv:2601.22438 (preprint) | Fault Tolerance, LLM Serving, KV Replication | 데이터센터(지리분산) | 실측 |
| [LUMEN](#lumen) | 2026 | arXiv:2606.17787 (preprint) | Fault Tolerance, LLM Serving, Scheduling/SLO | 데이터센터 | 실측+시뮬레이션 |
| [DualMap](#dualmap) | 2026 | ICLR 2026 (Published as a conference paper at I... | Load Balancing, Scheduling/SLO, Distributed Inference | 데이터센터 | 실측 |
| [DyBAP](#dybap) | 2026 | IEEE Transactions on Mobile Computing (accepted... | Distributed Inference, Collaborative Edge Inference, Model Partitioning/Placement | 하이브리드 | 시뮬레이션 |
| [HybridFlow](#hybridflow) | 2026 | ICML 2026 (poster); arXiv:2512.22137 | Collaborative Edge Inference, Scheduling/SLO, Model Partitioning/Placement | 하이브리드 | 실측 |
| [QEIL](#qeil) | 2026 | arXiv:2602.06057v2 [cs.DC] (9 Feb 2026) | Energy Efficiency, Heterogeneous Clusters, Fault Tolerance | 엣지 | 실측 |
| [A Matching Game for LLM Layer Deployme](#a-matching-game-for-llm-layer-deployment-in-heterogeneous-edge-networks) | 2025 | IEEE Open Journal of the Communications Society... | Distributed Inference, Collaborative Edge Inference, Model Partitioning/Placement | 엣지 | 실측+시뮬레이션 |
| [Efficient LLM Inference over Heterogen](#efficient-llm-inference-over-heterogeneous-edge-networks-with-speculative-decoding) | 2025 | arXiv:2510.11331v1 [eess.SY], 13 Oct 2025 (prep... | Collaborative Edge Inference, Speculative Decoding, Model Partitioning/Placement | 시뮬레이션 | 시뮬레이션 |
| [Fault Tolerance in Triplet Network Tra](#fault-tolerance-in-triplet-network-training-analysis-evaluation-and-protection-methods) | 2025 | IEEE Transactions on Emerging Topics in Computi... | Fault Tolerance, Training, Neural Network Reliability (stuck-at fault model) | 시뮬레이션 | 시뮬레이션 |
| [FedAttn](#fedattn) | 2025 | arXiv:2511.02647 (v1, 4 Nov 2025) | Distributed Inference, Collaborative Edge Inference, Privacy | 엣지 | 시뮬레이션 |
| [Helix](#helix) | 2025 | ASPLOS '25: Proceedings of the 30th ACM Interna... | Distributed Inference, Model Partitioning/Placement, Heterogeneous Clusters | 데이터센터 | 실측+시뮬레이션 |
| [Hetis](#hetis) | 2025 | SC '25 (The International Conference for High P... | Distributed Inference, Heterogeneous Clusters, Load Balancing | 데이터센터 | 실측+시뮬레이션 |
| [HexGen-2](#hexgen-2) | 2025 | ICLR 2025 (Int'l Conf. on Learning Representati... | Disaggregated Serving, Heterogeneous Clusters, Distributed Inference | 데이터센터 | 실측 |
| [Jupiter](#jupiter) | 2025 | IEEE INFOCOM 2025 (doi:10.1109/INFOCOM55648.202... | Collaborative Edge Inference, Distributed Inference, Model Partitioning/Placement | 엣지 | 실측 |
| [MDI-LLM](#mdi-llm) | 2025 | IEEE LANMAN 2025 (doi:10.1109/LANMAN66415.2025.... | Distributed Inference, Collaborative Edge Inference, Model Partitioning/Placement | 엣지 | 실측 |
| [Parallax](#parallax) | 2025 | arXiv:2509.26182 | Distributed Inference, Model Partitioning/Placement, Scheduling/SLO | 하이브리드 | 실측 |
| [SLICE](#slice) | 2025 | arXiv:2510.18544v3 [cs.DC] (header shows placeh... | Scheduling/SLO, Edge LLM Serving, Batching/Rate Allocation | 엣지 | 실측 |
| [TK-SLT](#tk-slt) | 2025 | 2025 17th Int'l Conf. on Wireless Communication... | Collaborative Edge Inference, Speculative Decoding, Wireless Networking | 하이브리드 | 실측+시뮬레이션 |
| [DejaVu](#dejavu) | 2024 | ICML 2024 (PMLR 235); arXiv:2403.01876 | Fault Tolerance, LLM Serving, KV Streaming | 데이터센터 | 실측 |
| [Andes](#andes) | 2024 | arXiv:2404.16283v2 [cs.DC] (13 Dec 2024) | QoE, Scheduling/SLO, LLM Serving | 데이터센터 | 실측 |
| [Decentralized LLM Inference over Edge ](#decentralized-llm-inference-over-edge-networks-with-energy-harvesting) | 2024 | IEEE GLOBECOM 2024, pp.3703-3708 (doi:10.1109/G... | Distributed Inference, Collaborative Edge Inference, Energy Efficiency | 엣지 | 실측+시뮬레이션 |
| [Distributed Mixture-of-Agents for Edge](#distributed-mixture-of-agents-for-edge-inference-with-large-language-models) | 2025 | IEEE PIMRC 2025 (doi:10.1109/PIMRC62392.2025.11275145); arXiv:2412.21200 | Distributed Inference, Collaborative Edge Inference, Mixture-of-Agents | 엣지 | 실측+시뮬레이션 |
| [EdgeShard](#edgeshard) | 2024 | IEEE Internet of Things Journal, 2025 (doi:10.1... | Distributed Inference, Collaborative Edge Inference, Model Partitioning/Placement | 하이브리드 | 실측 |
| [HexGen](#hexgen) | 2024 | ICML 2024, pp.21946-21961 (PMLR 235) | Distributed Inference, Heterogeneous Clusters, Model Partitioning/Placement | 데이터센터 | 실측 |
| [JARVIS](#jarvis) | 2024 | MILCOM 2024 (IEEE Military Communications Confe... | Distributed Inference, Collaborative Edge Inference, Fault Tolerance | 엣지 | 실측 |
| [LLM-PQ](#llm-pq) | 2024 | ACM PPoPP 2024, pp.460-462 (doi:10.1145/3627535... | Distributed Inference, Heterogeneous Clusters, Quantization | 데이터센터 | 실측 |
| [PA-MDI](#pa-mdi) | 2024 | arXiv:2412.12371v1 [cs.DC], 16 Dec 2024 | Distributed Inference, Collaborative Edge Inference, Model Partitioning/Placement | 엣지 | 실측 |
| [Privacy-Preserving Handover Optimizati](#privacy-preserving-handover-optimization-using-federated-learning-and-lstm-networks) | 2024 | Sensors (MDPI) 2024, vol. 24, article 6685, doi... | Wireless Networking, Privacy, Training | 엣지 | 실측+시뮬레이션 |
| [SpotServe](#spotserve) | 2024 | ASPLOS'24 (Proceedings of the 29th ACM Internat... | Distributed Inference, Fault Tolerance, Model Partitioning/Placement | 데이터센터 | 실측 |
| [Petals](#petals) | 2023 | 37th Conference on Neural Information Processin... | Distributed Inference, Fault Tolerance, Load Balancing | 하이브리드 | 실측+시뮬레이션 |
| [LBRCQT](#lbrcqt) | 2021 | Journal of Communications and Networks, vol. 23... | Load Balancing, Wireless Networking, SDN Routing | 시뮬레이션 | 시뮬레이션 |

---

## 상세

### DualMap — DualMap: Enabling Both Cache Affinity and Load Balancing for Distributed LLM Serving

- **파일**: `DualMap_Enabling-Both-Cache-Affinity-and-Load-Balancing-for-Distributed-LLM-Serving.pdf`
- **저자**: Ying Yuan, Pengfei Zuo, Bo Wang, Zhangyu Chen, Zhipeng Tan, et al. (Huazhong University of Science and Technology)
- **년도/Venue**: 2026 — ICLR 2026 (Published as a conference paper at ICLR 2026)
- **분야**: Load Balancing, Scheduling/SLO, Distributed Inference, KV Cache Reuse / Prefix Caching, Fault Tolerance
- **핵심 아이디어**: 분산 LLM serving에서 cache affinity(prefix가 같은 요청을 같은 instance로 보내 KV cache 재사용 극대화)와 load balancing이 단일 mapping space에서는 상충한다는 문제를 지적하고, 요청 prefix를 두 개의 독립 hash function으로 두 candidate instance에 매핑한 뒤 "power of two choices" 원리로 더 나은 쪽을 고르는 dual-mapping scheduling을 제안한다. 예상 TTFT가 SLO를 초과할 때만 load-aware routing으로 전환하는 SLO-aware request routing, Cuckoo hashing에서 착안해 overload된 instance의 요청을 backup candidate로 non-recursive single-round batch migration하는 hotspot-aware rebalancing, consistent hashing 기반 dual-hash-ring으로 instance 증감 시 global remapping 없이 elastic scaling을 지원하는 기법을 결합했다. vLLM 위에 global scheduling layer로 구현되어 동일 TTFT SLO 하에서 effective request capacity를 최대 2.25배 개선했다.
- **실험 환경**: **데이터센터** (실측) — Distributed LLM serving cluster; each node equipped with 8 Ascend NPUs (910B4: 32GB HBM or 910B3: 64GB HBM) and 1.5TB DRAM; 8-instance cluster in experiments (910B4 for 7B model, 910B3 for 14B model)
- **평가 모델**: Qwen2.5-7B and Qwen2.5-14B (float16), served with vLLM; workloads: Mooncake Conversation and Tool&Agent real-world traces
- **RADP 관련성**: DualMap의 각 요청이 항상 두 candidate instance(primary+backup)를 갖고 hotspot 시 backup으로 migration한다는 설계는 RADP의 recovery-aware placement에서 backup capacity가 placement를 결정짓는 ψ+R coupling 아이디어와 구조적으로 유사하며, SLO 기반 routing 전환 기준(ttft_slo_threshold)도 RADP의 SLO-aware 논의에 인용 가능한 datacenter-side related work다. 다만 edge 이기종 클러스터가 아닌 동종 NPU datacenter 대상이고 node failure recovery가 아닌 load hotspot 대응이라는 점에서 문제 설정이 다르다.

### DyBAP — Joint Optimization of Dynamic Batching and Adaptive Partitioning for Distributed LLMs Inference in Mobile Edge Computing

- **파일**: `DyBAP_Joint-Optimization-of-Dynamic-Batching-and-Adaptive-Partitioning-for-Distributed-LLMs-Inference-in-Mobile-Edge-Computing.pdf`
- **저자**: Tong Zheng, Yuanguo Bi, Guangjie Han, Tianao Xiang, Lexi Xu, et al. (Northeastern University, Shenyang, China)
- **년도/Venue**: 2026 — IEEE Transactions on Mobile Computing (accepted, early access; DOI 10.1109/TMC.2026.3650838)
- **분야**: Distributed Inference, Collaborative Edge Inference, Model Partitioning/Placement, Scheduling/SLO, Heterogeneous Clusters, Wireless Networking, Dynamic Batching, Multi-Agent Reinforcement Learning
- **핵심 아이디어**: End-edge-cloud 협업 MEC 환경에서 LLM inference를 위한 DyBAP(Dynamic Batching and Adaptive Partitioning) 스킴 제안. Latency·accuracy 제약 하에 inference latency와 resource usage를 최소화하는 배치 문제를 NP-hard pipeline scheduling 변형으로 formulation하고, (1) 실시간 시스템 상태에 따라 요청을 batch로 병합해 batch size를 적응 조절하는 dynamic batch fusion 알고리즘과 (2) transformer block을 이기종 노드에 할당하는 block-aware partition 알고리즘을 결합. Partition은 multi-agent RL(PPO 기반, base station별 독립 agent + experience sharing + actor/critic alternating update)로 풀며 user mobility awareness를 통합해 dynamic network topology에 대응. Simulation에서 baseline 대비 inference latency 17.94% 감소, memory 11.12% 절감, throughput 최대 21.91% 향상을 보고.
- **실험 환경**: **하이브리드** (시뮬레이션) — Simulated only: end devices assumed 4-core/8-core 5 GHz CPU, edge servers NVIDIA 4090 GPU, cloud servers NVIDIA A100 GPU (19 base stations w/ 19 edge servers, 2 cloud servers, 200-500 end devices)
- **평가 모델**: GPT-J-6B model structure (28 transformer blocks, d_m=4096); input 32 / max output 64 tokens, batch size 1-80
- **RADP 관련성**: Transformer block 단위 partitioning을 memory·latency 제약 하에 이기종 end-edge-cloud 노드에 배치한다는 점에서 RADP의 placement 문제 공간과 직접 겹치며, batching이 memory footprint에 미치는 영향을 명시적으로 모델링한 점도 참고 가치가 있음. 다만 failure/recovery는 다루지 않고(관련 연구로 device-failure robust partitioning [26]만 인용) mobility로 인한 topology 변화를 MARL로 대응하며, 실측 없이 simulation-only라는 점이 RADP의 recovery-aware objective 및 실기기 테스트베드와의 차별화 포인트.

### HybridFlow — HybridFlow: Resource-Adaptive Subtask Routing for Efficient Edge-Cloud LLM Inference

- **파일**: `HybridFlow_Resource-Adaptive-Subtask-Routing-for-Efficient-Edge-Cloud-LLM-Inference.pdf`
- **저자**: Jiangwen Dong, Jiayu Li, Tianhang Zheng, Wanyu Lin (Hong Kong Polytechnic University)
- **년도/Venue**: 2026 — **ICML 2026** (accepted poster; icml.cc/virtual/2026/poster/62628); preprint arXiv:2512.22137v4 [cs.DC], Jan 2026
- **분야**: Collaborative Edge Inference, Scheduling/SLO, Model Partitioning/Placement, Edge-Cloud Routing, Multi-step Reasoning
- **핵심 아이디어**: 복잡 query를 dependency 명시 subtask DAG로 분해해 의존성 풀린 subtask를 병렬 실행하고, 각 subtask를 edge small model vs cloud LLM 중 learned utility predictor + budget-aware dual threshold로 online 라우팅. offline profiling warm-start MLP + LinUCB online calibration으로 accuracy-cost-latency trade-off를 실시간 최적화.
- **실험 환경**: **하이브리드** (실측) — Edge: 단일 RTX 3090; Cloud: GPT-4.1 (API)
- **평가 모델**: Edge: Llama3.2-3B; Cloud: GPT-4.1; embedding qwen3-embedding-0.6b
- **RADP 관련성**: edge SM+cloud LLM 협업에서 subtask 단위 placement/routing을 budget 제약 하 online 결정하는 점이 RADP와 직접 겹침. 단 목적함수가 recovery가 아니라 accuracy-cost-latency utility.

### QEIL — Quantifying Edge Intelligence: Inference-Time Scaling Formalisms for Heterogeneous Computing

- **파일**: `QEIL_Quantifying-Edge-Intelligence-Inference-Time-Scaling-Formalisms-for-Heterogeneous-Computing.pdf`
- **저자**: Satyam Kumar, Saurabh Jha (affiliation marked with superscript 1 but not stated in PDF text)
- **년도/Venue**: 2026 — arXiv:2602.06057v2 [cs.DC] (9 Feb 2026)
- **분야**: Energy Efficiency, Heterogeneous Clusters, Fault Tolerance, Model Partitioning/Placement, Scheduling/SLO, Disaggregated Serving, Inference-Time Scaling Laws
- **핵심 아이디어**: QEIL은 edge 이기종 하드웨어(CPU/GPU/NPU)에서 LLM inference-time scaling을 정량화하는 5개의 empirical scaling formalism을 제시한다: coverage가 C(S,N,T)=1-exp(-α·N^βN·S^βS·T^δ) 형태의 power-law를 따르며 exponent β≈0.7이 transformer 모델 패밀리 전반에서 안정적임을 보인다. 이를 기반으로 IPW(Intelligence Per Watt), ECE, PPP 복합 지표로 multi-objective 최적화를 통합하고, inference를 embedding/decoder layers/LM head로 분해해 greedy layer assignment로 device별 hardware affinity에 맞게 배치한다(compute-bound prefill은 GPU, memory-bound decode는 NPU로 라우팅). 특히 safety-first 설계로 thermal throttling protection(85% 온도 상한), 100ms 내 fault detection과 workload redistribution, graceful degradation을 구현하며 safety monitor가 optimization engine보다 우선권(override authority)을 가진다. 5개 모델 패밀리에서 최적 homogeneous 대비 4.82-5.6배 IPW 개선, 47.7-78% energy 절감, +10.5pp coverage, zero thermal throttling과 100% fault recovery를 달성했다.
- **실험 환경**: **엣지** (실측) — Single edge platform: Intel Core Ultra 9 285HX CPU (8 cores, 2.80 GHz, 128 GB RAM / 127 GB usable), Intel AI Boost NPU (20 GB dedicated), NVIDIA RTX PRO 5000 Blackwell GPU (96.2 GB total VRAM), Intel Graphics GPU (72.7 GB shared memory)
- **평가 모델**: GPT-2 (125M), Granite-350M, Qwen2-0.5B, Llama-3.2-1B, LFM2-2.6B; benchmarks WikiText-103, GSM8K, ARC-Challenge
- **RADP 관련성**: RADP와 직접 관련: 100ms 내 fault detection 후 healthy device로 workload redistribution, 50% capacity 점진 복귀, latency bound τ_degraded ≤ τ_optimal·D/D_healthy 같은 formal degradation guarantee는 RADP의 recovery-aware placement 논의에서 비교 대상이 된다. 다만 QEIL은 단일 머신 내 CPU/GPU/NPU 오케스트레이션이며 recovery를 placement에 사전 반영하지 않는 reactive 방식이라, 다중 노드 edge 클러스터에서 backup memory를 placement 결정에 결합하는 RADP의 proactive 접근과의 차별화 지점을 제공한다.

### A Matching Game for LLM Layer Deployment in Heterogeneous Edge Networks

- **파일**: `A-Matching-Game-for-LLM-Layer-Deployment-in-Heterogeneous-Edge-Networks.pdf`
- **저자**: Benedetta Picano, Dinh Thai Hoang, Diep N. Nguyen (University of Florence, Italy)
- **년도/Venue**: 2025 — IEEE Open Journal of the Communications Society, vol. 6, pp. 3795-3804, 2025 (DOI 10.1109/OJCOMS.2025.3561605; Special Issue on Generative AI and LLMs Enhanced 6G Wireless Communication and Sensing)
- **분야**: Distributed Inference, Collaborative Edge Inference, Model Partitioning/Placement, Heterogeneous Clusters, Wireless Networking, Matching Theory / Game Theory
- **핵심 아이디어**: LLM transformer layer들을 heterogeneous edge node에 배치하는 문제를 two-sided matching game으로 정식화한다. 각 layer는 communication time과 inference time 기여도 기반 preference list로 노드에 propose하고, 노드는 선호 layer를 수락하는 deferred-acceptance 방식으로 진행하며, sequential pipeline 실행에서 발생하는 bubble time(idle waiting)을 game externality로 모델링한다. 알고리즘이 S2ES(stable) matching에 수렴함을 증명하고 O(EL log L) complexity를 보이며, Kolkata game·Random·First-bid Auction 대비 inference latency를 최대 약 10% 개선한다.
- **실험 환경**: **엣지** (실측+시뮬레이션) — Simulations: Apple M1 Pro CPU with 32 GB RAM (Python 3.10 + NumPy). Testbed: 4 edge nodes — (A) Intel Core i7-12700K + NVIDIA RTX 3090, (B) AMD Ryzen 7 3700X, (C) Intel Core i7-9700K, (E) AMD Ryzen Threadripper 1950X-16, plus a network element and UPS
- **평가 모델**: LLaMA-7B (32 transformer layers) distributed across four edge nodes for autonomous-driving decision support with multi-modal multi-view sensor data; tested on CARLA-Leaderboard. Simulations use synthetic layer cost/memory parameters (30-120 layers)
- **RADP 관련성**: RADP와 동일한 문제 공간(heterogeneous edge cluster에서 LLM layer placement, compute+communication joint 고려)을 matching theory로 푸는 대안적 접근이라 placement 알고리즘 비교 baseline/related work로 직접 유용하다. 다만 failure recovery나 backup memory 같은 fault-tolerance 요소는 전혀 다루지 않아, RADP의 recovery-aware coupling 주장을 대비시키는 근거로 인용 가능하다.

### Efficient LLM Inference over Heterogeneous Edge Networks with Speculative Decoding

- **파일**: `Efficient-LLM-Inference-over-Heterogeneous-Edge-Networks-with-Speculative-Decoding.pdf`
- **저자**: Bingjie Zhu, Zhixiong Chen, Liqiang Zhao, Hyundong Shin, Arumugam Nallanathan (Xidian University)
- **년도/Venue**: 2025 — arXiv:2510.11331v1 [eess.SY], 13 Oct 2025 (preprint; 2026-07-09 재확인: 게재본 미검출)
- **분야**: Collaborative Edge Inference, Speculative Decoding, Model Partitioning/Placement, Scheduling/SLO, Wireless Networking, Heterogeneous Clusters
- **핵심 아이디어**: 작은 draft model을 SBS(small base station), 큰 verify model을 MBS(macro base station)에 배치해 speculative decoding으로 협업 추론하고, pipeline parallelism으로 서로 다른 task의 draft/verify 단계를 overlap시킨다. speculation length·task batching·wireless 자원할당을 하나의 latency 최소화 문제로 jointly 최적화(wireless는 closed-form, batching/speculation은 DP).
- **실험 환경**: **시뮬레이션** (시뮬레이션) — Simulation with modeled GPUs: RTX 3080(SBS) + RTX 4500(MBS); Jetson TX2 8GB는 메모리 한계 예시로만 언급
- **평가 모델**: LLaMA-68M/1.1B/7B/13B (draft-verify pairs)
- **RADP 관련성**: 이종 edge node(MBS/SBS)에 서로 다른 모델을 placement하고 latency를 batching·통신과 함께 joint 최적화하는 점은 RADP와 겹치나, recovery는 없고 simulation-only.

### Fault Tolerance in Triplet Network Training: Analysis, Evaluation and Protection Methods

- **파일**: `Fault-Tolerance-in-Triplet-Network-Training-Analysis-Evaluation-and-Protection-Methods.pdf`
- **저자**: Ziheng Wang, Farzad Niknia, Shanshan Liu, Pedro Reviriego, Ahmed Louri, Fabrizio Lombardi (Northeastern University, Dept. of Electrical and Computer Engineering, Boston, MA)
- **년도/Venue**: 2025 — IEEE Transactions on Emerging Topics in Computing, vol. 13, no. 3, pp. 714-, July-September 2025 (DOI 10.1109/TETC.2024.3481962)
- **분야**: Fault Tolerance, Training, Neural Network Reliability (stuck-at fault model)
- **핵심 아이디어**: Triplet Network(TN, 3개의 weight-sharing subnetwork로 구성된 deep metric learning 구조)의 학습 과정에서 functional stuck-at fault(stuck-at-zero, stuck-at-max/min)의 영향을 분석. anchor/positive subnetwork의 fault에는 매우 강건하지만(accuracy loss < 0.1%), negative subnetwork의 fault는 faulty term이 negative distance를 지배해 triplet loss가 거짓으로 0이 되는 "false convergence"(partial/complete failure)를 유발해 학습이 조기에 잘못 수렴함을 수식과 fault injection simulation으로 보임. 방어책으로 (1) anchor output에 대한 regularization term 추가, (2) 초기 negative distance 기반 modified margin M' = M + 2*floor(d_-) 두 가지를 제안해 accuracy loss를 0.00108% 미만으로 억제.
- **실험 환경**: **시뮬레이션** (시뮬레이션) — not stated
- **평가 모델**: 3~5-layer MLP subnetworks with tanh activation (e.g., 1024-512-256-128-128, 784-1024-512, 256-256-128 layer configs; CNN version in appendix) trained with Triplet Loss on MNIST, Fashion-MNIST, CIFAR-10, SVHN; one-hidden-layer MLP prediction network
- **RADP 관련성**: RADP는 edge LLM inference serving의 recovery-aware placement를 다루는 반면, 이 논문은 training-time의 neuron-level stuck-at fault 분석이라 직접적 관련성은 낮음. fault tolerance의 일반 배경(fault model 분류, fault가 시스템 실패로 이어지는 경로) 인용 정도로만 활용 가능하며 inference placement/recovery와는 무관.

### FedAttn — Federated Attention: A Distributed Paradigm for Collaborative LLM Inference over Edge Networks

- **파일**: `FedAttn_Federated-Attention-A-Distributed-Paradigm-for-Collaborative-LLM-Inference-over-Edge-Networks.pdf`
- **저자**: Xiumei Deng, Zehui Xiong, Binbin Chen, Dong In Kim, Merouane Debbah, H. Vincent Poor (SUTD, Singapore)
- **년도/Venue**: 2025 — arXiv:2511.02647 (v1, 4 Nov 2025); submitted to IEEE JSAC (2026-07-09 재확인: 게재본 미검출, 리뷰 중 추정)
- **분야**: Distributed Inference, Collaborative Edge Inference, Privacy, Federated Learning, Self-Attention
- **핵심 아이디어**: federated learning 패러다임을 self-attention에 이식한 non-autoregressive distributed inference. 다수 participant가 각자 private prompt 세그먼트에 local self-attention을 수행하고, interval마다 KV matrix를 교환·집계해 raw prompt 노출 없이 협력 추론. local forwards 수 H가 quality vs communication/computation 효율의 trade-off를 지배.
- **실험 환경**: **엣지** (시뮬레이션) — not stated (FLOPs·peak memory만 보고, 구체 하드웨어 미명시)
- **평가 모델**: Qwen2.5 0.5B/1.5B/3B/7B; GSM8K (CoT)
- **RADP 관련성**: edge network에서 KV 통신비용을 명시 모델링하며 attention을 분산하는 점은 RADP와 문제공간 공유. 단 축은 recovery-aware placement가 아니라 privacy-preserving 협력 추론.

### Helix — Helix: Serving Large Language Models over Heterogeneous GPUs and Network via Max-Flow

- **파일**: `Helix_Serving-Large-Language-Models-over-Heterogeneous-GPUs-and-Network-via-Max-Flow.pdf`
- **저자**: Yixuan Mei, Yonghao Zhuang, Xupeng Miao, Juncheng Yang, Zhihao Jia, et al. (Carnegie Mellon University)
- **년도/Venue**: 2025 — ASPLOS '25: Proceedings of the 30th ACM International Conference on Architectural Support for Programming Languages and Operating Systems, Volume 1, March 30-April 3 2025, Rotterdam, Netherlands, pp. 586-, DOI 10.1145/3669940.3707215
- **분야**: Distributed Inference, Model Partitioning/Placement, Heterogeneous Clusters, Scheduling/SLO, Load Balancing
- **핵심 아이디어**: 이기종 GPU 클러스터에서의 LLM inference를 directed weighted graph 위의 max-flow 문제로 정식화한다. 노드는 GPU instance, 엣지는 network 연결을 나타내며 각각의 capacity로 GPU/network 이질성을 동시에 포착한다. Mixed integer linear programming (MILP)으로 model placement를 최적화하고, per-request pipelines를 도입해 request마다 독립적인 pipeline으로 scheduling함으로써 placement와 scheduling이라는 강하게 얽힌 두 문제를 joint optimization한다. Swarm/separate-pipeline 대비 최대 3.3x throughput 향상과 prompt/decode latency 각각 최대 66%/24% 감소를 달성했다.
- **실험 환경**: **데이터센터** (실측+시뮬레이션) — Google Compute Engine GPU nodes: single cluster = 4x A100 + 8x L4 + 12x T4 nodes (10 Gb/s network); geo-distributed 24-node clusters (100 Mb/s, 50 ms inter-cluster, simulated); high-heterogeneity 42-node cluster with 7 GPU types (A100, V100, L4, T4, 2xL4, 2xT4, 4xT4, simulated); MILP solved on 14-core CPU with Gurobi
- **평가 모델**: LLaMA-1 30B and LLaMA-2 70B (FP16)
- **RADP 관련성**: Helix는 heterogeneous GPU/network 환경에서 placement와 scheduling이 결합된(coupled) 문제임을 MILP 정식화로 다뤄 RADP의 coupled feasibility 논지와 직접 맞닿는 핵심 related work다. 다만 datacenter/cloud 규모의 max-flow throughput 최적화에 집중하고 node failure나 recovery는 고려하지 않아, RADP의 recovery-aware placement(backup memory 제약 포함)가 차별화되는 지점을 명확히 보여주는 대조 사례다.

### Hetis — Hetis: Serving LLMs in Heterogeneous GPU Clusters with Fine-grained and Dynamic Parallelism

- **파일**: `Hetis_Serving-LLMs-in-Heterogeneous-GPU-Clusters-with-Fine-grained-and-Dynamic-Parallelism.pdf`
- **저자**: Zizhao Mo, Jianxiong Liao, Huanle Xu, Zhi Zhou, Chengzhong Xu — University of Macau (first author)
- **년도/Venue**: 2025 — SC '25 (The International Conference for High Performance Computing, Networking, Storage and Analysis, St Louis, MO, Nov 16-21, 2025), DOI 10.1145/3712285.3759784; also arXiv:2509.08309
- **분야**: Distributed Inference, Heterogeneous Clusters, Load Balancing, Model Partitioning/Placement, Scheduling/SLO, Disaggregated Serving
- **핵심 아이디어**: 이기종 GPU 클러스터에서 기존 heterogeneity-aware serving(Splitwise의 phase-splitting, Hexgen의 parameter-splitting)이 갖는 memory 비효율과 computation 비효율을 지적하고, module 단위의 fine-grained + dynamic parallelism을 제안. compute-intensive한 dense module(MLP, prefill Attention)은 optimization 문제로 선별된 GPU subset에만 parallelize하여 통신 오버헤드를 억제하고, parameter-free한 decode Attention은 head 단위로 모든(저사양 포함) GPU에 dynamic하게 분산해 남는 KV cache 공간을 활용. online dispatching policy가 network delay, computation, memory를 명시적으로 정량화해 request별 attention head 할당을 실시간 최적화하며, threshold 기반 re-dispatching과 head-wise cache migration으로 memory 고갈에 대응. vLLM 위에 구현해 throughput 최대 2.25x, latency 최대 1.49x 개선.
- **실험 환경**: **데이터센터** (실측+시뮬레이션) — Local heterogeneous GPU cluster: 1 host with 4x NVIDIA A100-80GB, 2 hosts with 2x NVIDIA RTX 3090 each, 1 host with 4x NVIDIA P100; 100Gbps LAN interconnect, GPUs connected via PCIe within each host
- **평가 모델**: Llama-13B, OPT-30B, Llama-70B (GQA) for end-to-end evaluation; OPT-2.7b and Llama2-13B for profiling/motivation; workloads: ShareGPT, HumanEval, LongBench; baselines: Splitwise, Hexgen; built on vLLM
- **RADP 관련성**: RADP처럼 heterogeneous 환경에서 computation-memory coupling이 placement를 제약한다는 문제의식(KV cache 공간과 dense computation 배분이 서로 묶여 있어 static partitioning이 memory를 낭비)을 datacenter GPU 스케일에서 다루며, module/head 단위 dynamic re-dispatching은 RADP의 recovery-aware placement에 대비되는 runtime 재배치 사례로 related work에 유용. 다만 failure/recovery는 다루지 않고 edge가 아닌 100Gbps 데이터센터 클러스터 전제라는 점이 RADP와의 차별점.

### HexGen-2 — HexGen-2: Disaggregated Generative Inference of LLMs in Heterogeneous Environment

- **파일**: `HexGen-2_Disaggregated-Generative-Inference-of-LLMs-in-Heterogeneous-Environment.pdf`
- **저자**: Youhe Jiang, Ran Yan, Binhang Yuan; The Hong Kong University of Science and Technology (Dept. of Computer Science and Engineering)
- **년도/Venue**: 2025 — ICLR 2025 (Int'l Conf. on Learning Representations); preprint arXiv:2502.07903
- **분야**: Disaggregated Serving, Heterogeneous Clusters, Distributed Inference, Model Partitioning/Placement, Scheduling/SLO
- **핵심 아이디어**: Prefill/decoding을 분리하는 disaggregated LLM inference paradigm을 heterogeneous GPU 클러스터에 배치하는 scheduling 문제를 constraint optimization으로 정식화한다. Graph partitioning(spectral partitioning + Kernighan-Lin)으로 GPU들을 prefill/decode model serving group으로 나누고, max-flow 알고리즘으로 각 replica의 TP/PP parallel strategy와 KV cache communication 경로를 co-optimize하며, max-flow가 유도하는 edge-swap 기반 iterative refinement로 placement를 개선한다. 동일 클라우드 비용 예산에서 HexGen/DistServe 대비 throughput 최대 2.0×(평균 1.3×), latency 평균 1.5× 개선하고, 70% 예산으로도 homogeneous baseline과 동등한 성능을 달성한다.
- **실험 환경**: **데이터센터** (실측) — RunPod 클라우드에서 임대한 NVIDIA H100-80G(8x, homogeneous), 그리고 H100/A100/L40/A6000 조합의 5개 heterogeneous 세팅 (예: 2xH100+6xA100+4xL40+8xA6000); Figure 1 microbenchmark는 단일 A100
- **평가 모델**: OPT-30B, Llama-2-70B (batching microbenchmark에 Llama-2-7B); 워크로드는 Azure Conversation dataset 기반 HPLD/HPHD/LPHD/LPLD
- **RADP 관련성**: Heterogeneous GPU 환경에서 placement·parallelism·KV cache communication을 coupled optimization으로 푸는 대표 시스템으로, RADP의 heterogeneity-aware placement 정식화와 직접 비교/인용 대상이다. 다만 datacenter GPU 임대 시나리오이며 failure/recovery를 고려하지 않아, RADP의 recovery-aware term과 edge 규모가 차별점으로 대비된다.

### Jupiter — Jupiter: Fast and Resource-Efficient Collaborative Inference of Generative LLMs on Edge Devices

- **파일**: `Jupiter_Fast-and-Resource-Efficient-Collaborative-Inference-of-Generative-LLMs-on-Edge-Devices.pdf`
- **저자**: Shengyuan Ye, Bei Ouyang, Liekang Zeng, Tianyi Qian, Xiaowen Chu, et al. (School of Computer Science and Engineering, Sun Yat-sen University, Guangzhou, China)
- **년도/Venue**: 2025 — IEEE INFOCOM 2025 (doi:10.1109/INFOCOM55648.2025.11044734); preprint arXiv:2504.08242
- **분야**: Collaborative Edge Inference, Distributed Inference, Model Partitioning/Placement, Heterogeneous Clusters, Speculative/Decoding, Quantization, Scheduling/SLO
- **핵심 아이디어**: TP 기반 기존 collaborative edge inference의 과도한 통신 오버헤드를 피하기 위해 pipelined architecture를 원칙으로 채택하고, prefill과 decoding 두 phase를 각각 다르게 최적화한다. Prefill phase에서는 입력 sequence를 sub-sequence로 나눠 pipeline에 동시 주입하는 intra-sequence pipeline parallelism과, device heterogeneity·memory budget·가변 입력 길이를 고려한 dynamic programming 기반 LLM/sequence partitioning planning을 제안한다. Decoding phase에서는 speculative decoding(Medusa token tree)을 통합하고, 답변 outline을 먼저 생성한 뒤 각 point를 병렬 point-extending request로 pipeline에 주입하는 outline-based pipeline parallel decoding으로 여러 device를 동시에 활용한다. 실제 Jetson 테스트베드에서 SOTA 대비 최대 26.1x end-to-end latency 감소를 달성하면서 생성 품질은 유사하게 유지한다.
- **실험 환경**: **엣지** (실측) — Jetson Xavier NX (384-core Volta GPU, 8GB, 20W), Jetson TX2 (256-core Pascal, 8GB, 20W), Jetson Nano (128-core Maxwell, 8GB, 10W); Homogeneous Env A = 4x Xavier NX, Heterogeneous Env B = 1x NX + 2x TX2 + 1x Nano; network bandwidth adjusted 100Mbps-1Gbps
- **평가 모델**: Llama2-7B and Llama2-13B (both INT4 quantized); datasets LiMA, Vicuna-80, WizardLM; Medusa speculative decoding; GPT-4o-powered FastChat for quality scoring
- **RADP 관련성**: RADP와 동일한 문제 공간(heterogeneous edge cluster에서 pipeline 방식의 LLM layer partitioning/placement, Jetson 실측)을 다루는 직접적 관련 연구이자 대표 baseline 후보이며, DP 기반 memory/heterogeneity-aware partitioning은 RADP placement solver와의 비교 지점이다. 다만 Jupiter는 순수 성능(latency) 최적화만 다루고 device failure나 recovery/backup memory를 전혀 고려하지 않아, RADP의 recovery-aware placement 동기를 뒷받침하는 대비 사례로 인용하기 좋다.

### MDI-LLM — Model-Distributed Inference for Large Language Models at the Edge

- **파일**: `MDI-LLM_Model-Distributed-Inference-for-Large-Language-Models-at-the-Edge.pdf`
- **저자**: Davide Macario, Hulya Seferoglu, Erdem Koyuncu — University of Illinois Chicago
- **년도/Venue**: 2025 — IEEE LANMAN 2025 (doi:10.1109/LANMAN66415.2025.11154542); preprint arXiv:2505.18164
- **분야**: Distributed Inference, Collaborative Edge Inference, Model Partitioning/Placement, Pipeline Parallelism
- **핵심 아이디어**: LLM을 layer 단위 partition으로 나눠 저전력 edge device들의 ring overlay(starter node + secondary nodes, TCP/IP로 intermediate activation 교환)에 배치하는 model-distributed inference 프레임워크. 핵심 기여는 "recurrent pipeline parallelism" — autoregressive generation에서 여러 text sample을 파이프라인으로 돌려 각 device의 idle time을 제거하고, sample별 rotating KV cache와 GQA를 분산 환경에 적용해 message 크기(마지막 token embedding만 전송)와 재계산을 줄임. 결과적으로 단일 device 메모리를 초과하는 모델(TinyLlama 1.1B, 8GB TX2에 단독 탑재 불가)을 실행 가능하게 하고, node 수 증가에 따라 token generation throughput 증가 및 per-device 메모리 감소(3-node에서 1.3GB/device 절감)를 보임.
- **실험 환경**: **엣지** (실측) — 3x Nvidia Jetson TX2 boards (8 GB shared RAM, 1.33 TFLOPS, FP16 미지원) connected via a gigabit ethernet switch
- **평가 모델**: NanoLlama (custom 304M-param Llama-2-architecture toy model, Tiny Shakespeare로 학습) and TinyLlama Chat v1.0 (1.1B); built on LitGPT, Llama 2/3 family features (RoPE, GQA, KV cache)
- **RADP 관련성**: RADP와 동일한 문제 공간(edge device들에 걸친 pipeline-parallel LLM inference, 단일 device 메모리 초과 모델 배치)의 직접적 related work/baseline로, layer-to-node partition은 능력 비례 수동 배분 수준이고 node failure나 recovery를 전혀 다루지 않음. 따라서 MDI-LLM류 시스템의 static placement 한계가 RADP의 recovery-aware placement 동기를 뒷받침하는 인용 포인트가 됨.

### Parallax — Parallax: Efficient LLM Inference Service over Decentralized Environment

- **파일**: `Parallax_Efficient-LLM-Inference-Service-over-Decentralized-Environment.pdf`
- **저자**: Chris Tong, Youhe Jiang, Gufeng Chen, Tianyi Zhao, Sibian Lu, et al. (Gradient)
- **년도/Venue**: 2025 — arXiv:2509.26182
- **분야**: Distributed Inference, Model Partitioning/Placement, Scheduling/SLO, Load Balancing, Heterogeneous Clusters, Decentralized/Volunteer Computing
- **핵심 아이디어**: 이기종·저대역폭 볼런티어 GPU 풀 위에서 LLM 추론을 서빙하기 위한 two-phase scheduler를 제안한다. Phase 1(model allocation)은 region-based·latency-dominant 휴리스틱과 water-filling을 결합한 dynamic programming으로 각 model replica의 layer들을 GPU에 placement하여 per-request latency 최소화와 system throughput 최대화를 동시에 노린다. Phase 2(GPU pipeline chain selection)는 placement를 DAG로 취급하고 요청 시점에 DP로 서로 다른 replica의 stage들을 이어 붙여 end-to-end pipeline chain을 선택해 load balancing한다. DHT의 live per-layer latency/RTT metric을 이용해 GPU join/leave 같은 dynamic membership에 localized adjustment 또는 global rebalancing으로 적응한다.
- **실험 환경**: **하이브리드** (실측) — 5x RTX 5090 machines + 2x RTX 4090 machines across geographically separated data centers over public networks (avg inter-machine latency 10 ms); scheduler scalability measured up to 256 GPUs (algorithm running time)
- **평가 모델**: Qwen3-32B (BF16 and FP8/16B precisions); traces subsampled from ShareGPT and WildGPT
- **RADP 관련성**: RADP와 동일하게 heterogeneous 환경에서 placement(layer 할당)와 request-time routing의 coupled optimization을 다루며, HexGen을 baseline으로 이긴 최신 비교 대상이다. 특히 GPU leave 시 layer de-allocation과 coefficient-of-variation 기반 global rebalancing, replica 간 stage stitching은 RADP의 recovery-aware placement가 사전에 backup을 심어두는 접근과 대비되는 reactive recovery 사례로 related work에서 직접 대조할 수 있다.

### SLICE — SLICE: SLO-Driven Scheduling for LLM Inference on Edge Computing Devices

- **파일**: `SLICE_SLO-Driven-Scheduling-for-LLM-Inference-on-Edge-Computing-Devices.pdf`
- **저자**: Will Chow (affiliation not stated; paper anonymously hosted for double-blind review)
- **년도/Venue**: 2025 — arXiv:2510.18544v3 [cs.DC] (header shows placeholder "Journal of LaTeX Class Files" IEEE template; no actual journal/conference stated)
- **분야**: Scheduling/SLO, Edge LLM Serving, Batching/Rate Allocation, QoE
- **핵심 아이디어**: 단일 edge GPU에서 LLM inference task마다 상이한 SLO(TTFT/TPOT)를 갖는 상황을 대상으로, 기존 FCFS 일괄 batching이 batch 크기 증가 시 per-token latency를 폭증시켜 real-time task의 TPOT SLO를 위반하는 문제를 지적한다. SLICE는 2단계 전략을 쓴다: (1) utility-maximizing task selection으로 real-time task에 10-100배 높은 utility를 부여해 우선 스케줄링하고, (2) decode-mask matrix를 column-wise scanning하는 cycle 기반 rate allocation으로 task별 decoding rate를 SLO 요구에 맞게 개별 제어한다. FastLLM 위에 약 1,000줄 C++로 구현되어 Orca/FastServe 대비 최대 35배 SLO attainment, 3.4배 빠른 task completion time을 달성한다.
- **실험 환경**: **엣지** (실측) — NVIDIA RTX 4060 Ti (16GB GDDR6) GPU, PCIe 3.0 x16; host with 22GB memory and Intel Xeon E5-2690 v4
- **평가 모델**: ChatGLM2-6B-INT4 (evaluation); ChatGLM2-6B on RTX 4060 Ti in motivation study
- **RADP 관련성**: RADP가 다루는 multi-device recovery-aware placement와 달리 SLICE는 단일 edge GPU 내부의 decode-level batch scheduling/rate allocation을 다루므로 직접 경쟁 관계는 아니고 orthogonal한 축이다. 다만 edge LLM serving에서 TPOT/TTFT SLO를 1급 제약으로 다루는 framing은 RADP의 SLO 논의(related work의 SLO-aware serving 축)에 인용할 만하다.

### TK-SLT — Communication-Efficient Collaborative LLM Inference via Distributed Speculative Decoding

- **파일**: `TK-SLT_Communication-Efficient-Collaborative-LLM-Inference-via-Distributed-Speculative-Decoding.pdf`
- **저자**: Ce Zheng, Tingting Yang (Pengcheng Laboratory, Shenzhen)
- **년도/Venue**: 2025 — 2025 17th Int'l Conf. on Wireless Communications and Signal Processing (WCSP), IEEE
- **분야**: Collaborative Edge Inference, Speculative Decoding, Wireless Networking, Communication-Efficient Inference, AI-RAN
- **핵심 아이디어**: device에 SLM, BS/edge에 LLM을 두는 distributed speculative decoding에서, draft 검증을 위해 전체 vocabulary 확률분포를 uplink로 올리는 통신 병목을 top-K logit+token ID만 전송(TK-SLT)해 해결. standalone LLM과 확률적 동등성 유지하며 uplink 대역폭 절감. optimal draft length를 Lambert W로 closed-form 유도.
- **실험 환경**: **하이브리드** (실측+시뮬레이션) — 2×NVIDIA A800 80GB(각각 68M draft, 7B verify); 무선은 Hardware-in-the-Loop 시뮬레이션(FP16 logits, 50MHz)
- **평가 모델**: 68M-Llama(draft) + 7B-Llama(verify), Llama2 계열, vocab 32K
- **RADP 관련성**: device(SLM)-BS(LLM) 배치와 통신비용(uplink payload)·latency를 명시 모델링하는 점은 RADP의 T_comm 근거로 참고되나 recovery 관점은 없음.

### Andes — Andes: Defining and Enhancing Quality-of-Experience in LLM-Based Text Streaming Services

- **파일**: `Andes_Defining-and-Enhancing-Quality-of-Experience-in-LLM-Based-Text-Streaming-Services.pdf`
- **저자**: Jiachen Liu, Jae-Won Chung, Zhiyu Wu, Fan Lai, Myungjin Lee, et al. (University of Michigan)
- **년도/Venue**: 2024 — arXiv:2404.16283v2 [cs.DC] (13 Dec 2024)
- **분야**: QoE, Scheduling/SLO, LLM Serving, Preemptive Token-Level Scheduling
- **핵심 아이디어**: LLM text streaming 서비스에서 서버 중심 metric(throughput, TTFT, P99 TPOT)이 사용자 경험과 misalign된다는 점을 지적하고, 사용자의 Ideal Consumption Timeline(reading/listening speed 기반) 대비 Actual Consumption Timeline의 편차로 QoE를 formal하게 정의한다. Andes는 이 QoE를 최적화하는 서버-클라이언트 co-design으로, 서버 측에서는 각 요청의 expected QoE gain과 GPU resource usage 기반으로 token granularity의 preemptive scheduling을 수행하고(preemption overhead를 refiner가 명시적으로 추정해 net QoE gain이 양수일 때만 실행), 클라이언트 측에서는 token pacer가 초과 생성된 토큰을 buffering해 사용자 consumption speed에 맞춰 전달한다. vLLM/Sarathi-Serve 대비 평균 QoE 최대 4.7배 향상 또는 동일 QoE 유지 시 GPU 자원 61% 절감을 달성했다.
- **실험 환경**: **데이터센터** (실측) — NVIDIA A100 SXM4 40GB GPUs (tensor parallelism, A100x4 for Phi-3-mini, A100x8 for the rest) on one AWS p4d.24xlarge instance
- **평가 모델**: Phi-3-mini 3.8B, Command R 32B, Phi-3.5-MoE 16x3.8B, Llama 3.1 70B
- **RADP 관련성**: RADP와는 datacenter serving 스케줄링이라는 점에서 층위가 다르지만, preemption/restoration overhead(recomputation vs swapping)를 offline-profile해서 scheduling 결정의 비용 항으로 명시적으로 반영하는 구조는 RADP의 recovery-aware cost modeling과 정신적으로 가깝다. 또한 token delivery timeline 기반 QoE 정의는 edge LLM inference에서 failure/recovery 중 사용자 체감 저하를 정량화하는 지표 설계에 참고할 수 있다.

### Decentralized LLM Inference over Edge Networks with Energy Harvesting

- **파일**: `Decentralized-LLM-Inference-over-Edge-Networks-with-Energy-Harvesting.pdf`
- **저자**: Aria Khoshsirat, Giovanni Perin, Michele Rossi — Department of Information Engineering (DEI), University of Padova, Italy
- **년도/Venue**: 2024 — IEEE GLOBECOM 2024, pp.3703-3708 (doi:10.1109/GLOBECOM52923.2024.10901542); preprint arXiv:2408.15907
- **분야**: Distributed Inference, Collaborative Edge Inference, Energy Efficiency, Scheduling/SLO, Load Balancing, Energy Harvesting, Semi-Markov Modeling
- **핵심 아이디어**: Petals 스타일의 decentralized LLM inference를 배터리+energy harvesting(예: 소형 태양광 패널) 기반 edge device 그룹 위에서 수행하는 상황을 다룬다. 각 device의 (job queue, battery energy, power-saving 여부) 상태를 semi-Markov chain으로 모델링하여, battery가 threshold 아래로 떨어져 power-saving downtime에 진입할 확률(risk)을 stationary distribution으로 계산한다. 이 risk 모델을 이용해 uniform/long-term/adaptive 세 가지 job scheduling 정책을 설계하고(Brent's method로 최대 허용 input rate 도출), battery level에 따라 Jetson power mode(15/30/60W)를 전환하는 dynamic power mode를 제안하여 downtime을 낮추면서 throughput을 높인다. 실측 결과 dynamic power mode는 30W 고정 대비 job 완료 수를 늘리면서 평균 battery를 18% 개선하고, adaptive scheduling은 uniform 대비 downtime 확률을 최대 절반 이하로 줄인다.
- **실험 환경**: **엣지** (실측+시뮬레이션) — NVIDIA Jetson AGX Orin (single device for empirical energy/time measurements; power modes 15 W, 30 W, 50 W, 60 W). Network-level evaluation: simulation of 3 groups x 3 nodes parameterized by the Orin measurements, 100 kJ battery per node, delta=100 s time slots
- **평가 모델**: Synthetic LLM transformer block: 100 encoder layers + 100 decoder layers, each with 100 attention heads, input size 64x16x512 (no named pretrained LLM); framework builds on Petals-style split inference
- **RADP 관련성**: RADP의 recovery-aware placement처럼 node availability를 확률 모델(여기서는 semi-Markov 기반 battery downtime risk)로 정량화해 job scheduling에 반영한다는 점에서 관련 — 다만 failure/recovery가 아닌 energy 고갈로 인한 downtime을 다루고, placement가 아닌 scheduling 수준에서 대응한다. 또한 Jetson AGX Orin의 power mode별 throughput/energy tradeoff 실측은 RADP 테스트베드(ao-1/ao-2, nvpmodel 이슈)와 직접 맞닿아 있어 관련 연구로 인용 가치가 있다.

### Distributed Mixture-of-Agents for Edge Inference with Large Language Models

- **파일**: `Distributed-Mixture-of-Agents-for-Edge-Inference-with-Large-Language-Models.pdf`
- **저자**: Purbesh Mitra, Priyanka Kaswan, Sennur Ulukus (University of Maryland; Kaswan: Princeton)
- **년도/Venue**: 2025 — **IEEE PIMRC 2025** (36th Int'l Symp. on Personal, Indoor and Mobile Radio Communications, doi:10.1109/PIMRC62392.2025.11275145); preprint arXiv:2412.21200v1 [cs.IT], 30 Dec 2024
- **분야**: Distributed Inference, Collaborative Edge Inference, Mixture-of-Agents, Fault Tolerance, Gossip/Queuing
- **핵심 아이디어**: 중앙 서버 없이 각 사용자가 엣지 디바이스에서 개별 LLM을 호스팅하고 decentralized gossip으로 prompt/response를 이웃과 교환해 Mixture-of-Agents(proposer+aggregator) 협력 추론. 엣지 memory 제약으로 queue가 bounded되어야 하므로 arrival rate·inference time·layer·proposer 수에 대한 queuing stability 조건 α((k+1)M+1)λ<1을 유도.
- **실험 환경**: **엣지** (실측+시뮬레이션) — not stated (구체 엣지 하드웨어 미명시; accuracy는 GPT-4 API로 판정)
- **평가 모델**: Llama-3-70B, Qwen-1.5-72B, Mixtral-8x22B, dbrx-instruct; AlpacaEval 2.0 (10 samples)
- **RADP 관련성**: 중앙 서버 single point of failure를 피하고 엣지 간 diverse connection으로 robustness를 얻으며 memory 제약 하 queue bounded를 명시하는 점에서 RADP 동기와 강하게 겹침. 단 placement 최적화·명시적 recovery mechanism은 없음.

### EdgeShard — EdgeShard: Efficient LLM Inference via Collaborative Edge Computing

- **파일**: `EdgeShard_Efficient-LLM-Inference-via-Collaborative-Edge-Computing.pdf`
- **저자**: Mingjin Zhang, Jiannong Cao, Xiaoming Shen, Zeyang Cui (The Hong Kong Polytechnic University, Hong Kong)
- **년도/Venue**: 2024 — IEEE Internet of Things Journal, 2025 (doi:10.1109/JIOT.2024.3524255); preprint arXiv:2405.14371
- **분야**: Distributed Inference, Collaborative Edge Inference, Model Partitioning/Placement, Heterogeneous Clusters, Pipeline Parallelism
- **핵심 아이디어**: EdgeShard는 heterogeneous edge devices와 cloud server를 하나의 collaborative edge computing 자원 풀로 묶어 LLM을 layer 단위 shard로 partition/배치하는 general inference framework다. offline profiling(layer별 실행 시간, activation 크기, memory, bandwidth)을 기반으로 joint device selection + model partition 문제를 정식화하고, latency 최소화와 throughput 최대화 각각에 대한 dynamic programming 알고리즘(복잡도 O(N^2 x 2^M x M^2))을 설계했다. pipeline-parallel 실행 시 autoregressive 특성으로 생기는 bubble을 줄이기 위해 micro-batch 완료를 기다리지 않고 즉시 token generation을 시작하는 EdgeShard-No-bubbles 전략도 제안한다. 실물 testbed에서 Edge-Solo 및 cloud-edge collaboration baseline 대비 최대 50% latency 감소, 2x throughput 향상을 보였고, 단일 device에 안 들어가는 Llama2-70B도 full precision으로 서빙 가능함을 보였다.
- **실험 환경**: **하이브리드** (실측) — 15 devices: 12x NVIDIA Jetson AGX Orin (32GB, 3.33 TFLOPS), 2x Jetson Orin NX (16GB, 1.88 TFLOPS), 1x cloud server with RTX 3090 (24GB, 36 TFLOPS); router+switch 1000Mbps, Linux TC로 bandwidth/latency 조절 (1-50Mbps sweep)
- **평가 모델**: Llama2-7B, Llama2-13B, Llama2-70B (full precision, WikiText-2, input 32 tokens / generate 96 tokens)
- **RADP 관련성**: RADP와 동일한 문제 공간(heterogeneous edge 클러스터에서 DP 기반 layer-wise partitioning + device selection)을 다루는 가장 직접적인 baseline/related work이지만, failure나 recovery를 전혀 고려하지 않는 성능-only placement라서 RADP의 recovery-aware placement가 채우는 gap을 정확히 보여준다. Jetson Orin 계열 실측 testbed와 DP formulation(memory constraint 포함)이 RADP 실험 setup 및 cost model과 직접 비교 가능하다.

### HexGen — HexGen: Generative Inference of Large Language Model over Heterogeneous Environment

- **파일**: `HexGen_Generative-Inference-of-Large-Language-Model-over-Heterogeneous-Environment.pdf`
- **저자**: Youhe Jiang, Ran Yan, Xiaozhe Yao, Yang Zhou, Beidi Chen, Binhang Yuan; Dept. of Computer Science and Engineering, The Hong Kong University of Science and Technology
- **년도/Venue**: 2024 — ICML 2024, pp.21946-21961 (PMLR 235); preprint arXiv:2311.11514
- **분야**: Distributed Inference, Heterogeneous Clusters, Model Partitioning/Placement, Scheduling/SLO, Decentralized/Cross-Datacenter Serving
- **핵심 아이디어**: HexGen은 heterogeneous GPU와 heterogeneous network(cross-datacenter, cross-region)에서 LLM generative inference를 서빙하는 flexible distributed inference engine으로, 각 pipeline stage가 서로 다른 layer 수와 tensor model parallel degree를 갖는 asymmetric parallelism을 지원한다. Scheduling을 communication/computation cost와 memory constraint를 포함한 constrained optimization으로 정식화하고, two-phase search — pipeline layout을 정하는 dynamic programming + device partition을 탐색하는 genetic algorithm(mutation: split/swap/merge) — 으로 placement를 결정한다. 동일 클라우드 예산에서 homogeneous A100 datacenter(FlashAttention) 대비 최대 2.3배 낮은 latency deadline과 최대 4배 높은 peak request rate를 달성하고, 절반 예산으로도 유사한 SLO attainment를 유지한다.
- **실험 환경**: **데이터센터** (실측) — Homogeneous baseline: two AWS p4d.24xlarge instances (each 8x NVIDIA A100-40G, $65.54/hr). Heterogeneous: FluidStack cloud GPUs across regions — full-price: two 3090Ti x8 (Iceland), two 3090Ti x3 (Norway), one A5000 x8 (Nevada), one A6000 x8, one A5000 x8, one A40 x4 (Illinois), $65.04/hr; half-price: two 3090Ti x8, two 3090Ti x3, one A5000 x8, $29.6/hr. Inter-region latency 40-150ms, bandwidth 0.3-1.0 Gbps
- **평가 모델**: Llama-2 (70B)
- **RADP 관련성**: RADP와 마찬가지로 heterogeneous device 집합 위에서 cost model 기반 asymmetric partition/placement search(DP + genetic algorithm)를 수행하는 대표적 비교 대상 시스템이다. 다만 failure에 대해서는 GPU 이탈 시 30초 내 search를 reactive하게 re-run하는 방식(§5.3의 4-GPUs-offline 시나리오)에 그쳐, recovery를 placement 단계에서 사전 고려하는 RADP의 recovery-aware placement와 명확히 대비되는 baseline/related work이다.

### JARVIS — JARVIS: Disjoint Large Language Models on Radio VLANs for Intelligent Services

- **파일**: `JARVIS_Disjoint-Large-Language-Models-on-Radio-VLANs-for-Intelligent-Services.pdf`
- **저자**: Miquel Sirera Perelló, Joshua Groen, Wan Liu, Stratis Ioannidis, Kaushik Chowdhury — Institute for the Wireless Internet of Things, Northeastern University, Boston, MA, USA
- **년도/Venue**: 2024 — MILCOM 2024 (IEEE Military Communications Conference), Track 5 - Machine Learning for Communications and Networking, pp. 869-874, DOI 10.1109/MILCOM61039.2024.10773726
- **분야**: Distributed Inference, Collaborative Edge Inference, Fault Tolerance, Model Partitioning/Placement, Wireless Networking, Heterogeneous Clusters
- **핵심 아이디어**: LLM의 decoder layer들을 wireless(LTE/Wi-Fi)와 wired(Ethernet) link가 혼재된 여러 edge node에 분산 배치하는 framework. UE가 tokenizer/embedder와 첫·마지막 transformer layer, sampler를 담당하고 나머지 layer들은 token ring topology의 node들에 분산되어, 각 token 생성마다 hidden state가 ring을 한 바퀴 도는 pipeline 구조. Node failure에 대해서는 layer skipping(다음 hop으로 재라우팅)과 peer-level layer duplication으로 recovery하며, MMLU에서 layer 1~2개 제거 시 accuracy degradation heatmap을 측정해 어떤 layer 조합이 skip 가능한지(첫 layer와 일부 middle layer가 critical, 후반 layer는 skip에 강건) 실증. 18개 SDR node로 구성된 tactical 환경에서 layer skip이 wireless hop 제거로 generation time을 225초 단축하는 등 network link type이 성능을 지배함을 보임.
- **실험 환경**: **엣지** (실측) — 18 software-defined radio nodes in the NSF Colosseum wireless network emulator (hardware-in-the-loop); links: cellular LTE via SCOPE framework, Wi-Fi 802.11 a/g/p via GNU Radio-based stack, wired 10 Gbps Ethernet; specific CPU/GPU models not stated
- **평가 모델**: Google Gemma 2B and Gemma 7B (deployed/split; MMLU layer-skip evaluation); Gemma 2B for network traffic experiments; Table I additionally compares LLaMA3 8B, Mistral 7B v0.1, Phi-3 mini 128k (not deployed)
- **RADP 관련성**: RADP와 매우 가까운 선행 연구 — layer-level partitioning에 node failure 대비 peer-level layer duplication(backup)과 layer skipping recovery를 결합한 점이 recovery-aware placement 문제의식과 직결된다. 다만 JARVIS는 placement를 최적화 문제로 풀지 않고(수동 configuration file 기반) skip 시 accuracy degradation을 감수하는 degraded operation 중심이라, RADP의 coupled feasibility/최적화 접근과 차별화 지점이 명확한 비교 대상이다.

### LLM-PQ — LLM-PQ: Serving LLM on Heterogeneous Clusters with Phase-Aware Partition and Adaptive Quantization

- **파일**: `LLM-PQ_Serving-LLM-on-Heterogeneous-Clusters-with-Phase-Aware-Partition-and-Adaptive-Quantization.pdf`
- **저자**: Juntao Zhao, Borui Wan, Yanghua Peng, Haibin Lin, Chuan Wu (University of Hong Kong)
- **년도/Venue**: 2024 — ACM PPoPP 2024, pp.460-462 (doi:10.1145/3627535.3638480); preprint arXiv:2403.01136
- **분야**: Distributed Inference, Heterogeneous Clusters, Quantization, Model Partitioning/Placement, Scheduling/SLO
- **핵심 아이디어**: Heterogeneous GPU cluster에서 LLM serving 시 prefill/decode 두 phase의 상이한 latency 특성(prefill은 compute-bound, decode는 memory-bound)을 반영한 phase-aware model partition과, GPU별 메모리/커널 특성에 맞춘 adaptive mixed-precision quantization을 jointly 결정하는 시스템. Device topology ordering과 micro-batch size를 열거하고 각 조합에 대해 layer partition + per-layer bitwidth를 ILP(GUROBI)로 푸는데, layer의 quantization sensitivity를 variance indicator로 측정해 model quality 제약을 반영한다. Offline task(프롬프트 길이·생성 토큰 수를 사전에 아는 batch workload)를 타깃으로 하며, ILP 대신 bitwidth transfer heuristic과 layer grouping으로 solver 시간을 단축한다. 11개 클러스터의 production workload에서 PipeEdge/Uniform/FlexGen 대비 최대 2.88x(평균 2.26x) throughput 향상을 보였다.
- **실험 환경**: **데이터센터** (실측) — Production AI cluster, 11 cluster configurations of NVIDIA T4, P100, V100-32G, A100-40G, A800-80G GPUs; NV-LINK intra-node, 800Gbps or 100Gbps Ethernet inter-node; Intel Xeon E5-2630 v4 (P100 nodes), Xeon Gold 6230 (V100/A800), Xeon Platinum 8260 (T4), AMD EPYC 7H12 (A100-40G); Ubuntu 20.04.6
- **평가 모델**: OPT-13b, OPT-30b, OPT-66b, BLOOM-176b (cost-model fidelity에 BLOOM-560m/1b7, 동기 실험에 OPT-1.3b/BLOOM-3b)
- **RADP 관련성**: RADP와 같은 heterogeneous cluster 위 LLM placement 계열로, quantization bitwidth와 layer partition의 coupled feasibility를 ILP로 함께 푸는 선례라 RADP의 ψ+R coupling 논증에서 비교 대상이 된다. 다만 failure/recovery는 미고려(on-the-fly weight loader가 recovery speed를 부수적으로 언급하는 수준)이고 offline batch workload 전용이라, recovery-aware placement의 차별점을 드러내는 related work로 적합하다.

### PA-MDI — Priority-Aware Model-Distributed Inference at Edge Networks

- **파일**: `PA-MDI_Priority-Aware-Model-Distributed-Inference-at-Edge-Networks.pdf`
- **저자**: Teng Li, Hulya Seferoglu (Electrical and Computer Engineering, University of Illinois Chicago)
- **년도/Venue**: 2024 — arXiv:2412.12371v1 [cs.DC], 16 Dec 2024
- **분야**: Distributed Inference, Collaborative Edge Inference, Model Partitioning/Placement, Scheduling/SLO, Load Balancing, Heterogeneous Clusters, Priority-Aware Task Offloading
- **핵심 아이디어**: 여러 data source가 공존하는 model-distributed inference (MDI)에서 source마다 priority weight γ_m을 부여하고, task 성공 확률(worker 이탈·packet loss 반영)을 곱한 accuracy를 maximize하면서 inference delay를 minimize하는 convex optimization 문제를 formulate한다. 최적해의 구조에서 per-task 결정 규칙 — (comm delay + task age + FLOPs×compute time + queue backlog) / (γ_m·α_m)을 minimize하는 이웃 worker 선택 — 을 도출해 decentralized PA-MDI 알고리즘으로 구현한다. 각 worker는 FLOPS(F_n)와 queue(Q_n)를 이웃과 교환하고, CSMA/CA의 RTS/CTS에서 착안한 RTC/CTC 메시징으로 여러 worker가 같은 노드에 동시에 offload해 과부하되는 것을 방지하며, multi-hop heterogeneous topology에서도 동작한다. Time-Sensitive source의 average inference time을 AR-MDI/MS-MDI 대비 최대 75.3%/73.2%(Jetson), 71.4%/61.0%(multi-hop), 56.4%/34.8%(GPT-2) 줄인다.
- **실험 환경**: **엣지** (실측) — NVIDIA Jetson Xavier x5 (6-core Carmel CPU @1900MHz, 16GB RAM) fully-connected WiFi ad-hoc mesh (~20Mbps); multi-hop 이종 토폴로지는 Jetson Xavier x3 + Jetson Nano x3 (4-core Cortex-A57 @1430MHz, 4GB RAM); Colosseum wireless testbed의 Standard Radio Node x5 (Intel Xeon E5-2650 46-core, NVIDIA Tesla K40m 장착이나 inference는 CPU-only, 120GB memory, 10Gb Base-T 가상 네트워크)
- **평가 모델**: ResNet-50, ResNet-56 (CIFAR-10, 224x224 resize 포함), GPT-2 (117M params, 12 layers, HuggingFace)
- **RADP 관련성**: RADP처럼 edge 노드들에 layer-wise partition을 배치/offload하는 문제를 다루며, objective에 worker 이탈·wireless packet loss로 인한 task 실패 확률 ∏(1-P)를 명시적으로 넣어 failure-aware placement라는 점에서 RADP의 recovery-aware 관점과 직접 맞닿는다. 다만 실패를 확률적 페널티로만 반영할 뿐 backup/recovery 메커니즘이나 recovery-time 보장은 없어, RADP의 명시적 recovery provisioning과의 차별화 지점(related work 대비 포인트)으로 인용하기 좋다.

### Privacy-Preserving Handover Optimization Using Federated Learning and LSTM Networks

- **파일**: `Privacy-Preserving-Handover-Optimization-Using-Federated-Learning-and-LSTM-Networks.pdf`
- **저자**: Wei-Che Chien, Yu Huang, Bo-Yu Chang, Wu-Yuin Hwang (Department of Computer Science and Information Engineering, National Dong Hwa University, Taiwan)
- **년도/Venue**: 2024 — Sensors (MDPI) 2024, vol. 24, article 6685, doi:10.3390/s24206685
- **분야**: Wireless Networking, Privacy, Training, Federated Learning, Handover/Mobility Management, Heterogeneous Clusters
- **핵심 아이디어**: 3GPP Event A3 같은 고정 threshold handover의 ping-pong 문제를 해결하기 위해, Federated Learning(FedAvg)으로 LSTM(F-LSTM)을 분산 학습시켜 serving cell RSRP와 인접 셀 NR-RSRP를 예측하고, 예측된 signal strength에 따라 HOM/TTT threshold를 실시간으로 조정하는 dynamic handover algorithm을 제안한다. 클라이언트는 raw signal data 대신 model weights만 서버로 전송하여 privacy를 보장하며, heterogeneous(실제 Raspberry Pi 클라이언트)와 homogeneous(시뮬레이션) FL 설정을 비교한 결과 FL 방식이 centralized LSTM보다 낮은 prediction error를 보였고 dynamic algorithm이 Event A3 대비 불필요한 handover를 줄였다.
- **실험 환경**: **엣지** (실측+시뮬레이션) — FL server/centralized training: Intel i5-13500 CPU + NVIDIA RTX 4060 GPU; heterogeneous FL clients: Raspberry Pi 4 Model B; homogeneous FL: simulated clients via Flower Virtual Client Engine on the same i5-13500/RTX 4060 machine
- **평가 모델**: LSTM (Federated LSTM, F-LSTM) trained with FedAvg via the Flower framework and PyTorch; compared against a centralized LSTM baseline; 10 clients on a real-world cellular dataset (HSPA+/LTE/5G RSRP traces)
- **RADP 관련성**: RADP(edge LLM inference의 recovery-aware placement)와 직접적 관련성은 낮음 — 본 논문은 cellular handover 파라미터 최적화를 위한 federated LSTM training이며 inference serving이나 placement 문제를 다루지 않는다. 다만 Raspberry Pi 기반 heterogeneous edge 환경에서 device computing capability 및 network latency 차이가 분산 학습 성능에 미치는 영향을 실측했다는 점에서 edge heterogeneity 논의의 주변 참고문헌 정도로 활용 가능.

### SpotServe — SpotServe: Serving Generative Large Language Models on Preemptible Instances

- **파일**: `SpotServe_Serving-Generative-Large-Language-Models-on-Preemptible-Instances.pdf`
- **저자**: Xupeng Miao, Chunan Shi, Jiangfei Duan, Xiaoli Xi, Dahua Lin, et al. (Carnegie Mellon University)
- **년도/Venue**: 2024 — ASPLOS'24 (Proceedings of the 29th ACM International Conference on Architectural Support for Programming Languages and Operating Systems, Volume 2, April 27-May 1, 2024, San Diego, CA); also arXiv:2311.15566
- **분야**: Distributed Inference, Fault Tolerance, Model Partitioning/Placement, Scheduling/SLO, Preemptible/Spot Instances, Cost-Efficient Serving
- **핵심 아이디어**: SpotServe는 preemptible(spot) GPU instance 위에서 LLM을 서빙하는 최초의 분산 시스템. instance 가용성과 request arrival rate 변화에 따라 data/tensor/pipeline parallelism configuration (D,P,M)을 동적으로 재조정(dynamic reparallelization)하고, 새 configuration으로의 instance migration을 bipartite graph matching 문제로 formulate하여 Kuhn-Munkres 알고리즘으로 model parameter와 KV cache 재사용을 극대화하는 최소 통신비용 migration plan을 계산한다. 또한 cloud가 제공하는 grace period를 활용해 token 단위로 inference 진행 상황을 commit하는 stateful inference recovery를 도입, preemption 후 recomputation 없이 저렴하게 inference를 재개한다. 실제 spot preemption trace에서 기존 시스템 대비 P99 tail latency 2.4-9.1x 개선, on-demand 대비 monetary cost 54% 절감.
- **실험 환경**: **데이터센터** (실측) — AWS g4dn.12xlarge instances (4 NVIDIA Tesla T4 GPUs per instance); real 12-hour AWS g4dn spot instance availability trace replayed; up to 16 GPUs (min for LLaMA-30B)
- **평가 모델**: OPT-6.7B, GPT-20B, LLaMA-30B (inference engine built on FasterTransformer)
- **RADP 관련성**: SpotServe는 node 이탈(preemption)을 전제로 parallel configuration을 동적으로 재조정하고 KV cache/parameter migration으로 recovery 비용을 최소화한다는 점에서 RADP의 recovery-aware placement와 문제의식이 직결되는 핵심 related work다. 다만 SpotServe는 grace period가 보장되는 cloud spot instance 환경의 reactive reparallelization인 반면, RADP는 예고 없는 failure가 있는 heterogeneous edge cluster에서 backup memory를 placement 단계에 proactive하게 반영한다는 차별점을 대비시킬 수 있다.

### Petals — Distributed Inference and Fine-tuning of Large Language Models Over The Internet

- **파일**: `Petals_Distributed-Inference-and-Fine-tuning-of-Large-Language-Models-Over-The-Internet.pdf`
- **저자**: Alexander Borzunov, Max Ryabinin, Artem Chumachenko, Dmitry Baranchuk, Tim Dettmers, et al. (HSE University / Yandex)
- **년도/Venue**: 2023 — 37th Conference on Neural Information Processing Systems (NeurIPS 2023); arXiv:2312.08361
- **분야**: Distributed Inference, Fault Tolerance, Load Balancing, Model Partitioning/Placement, Quantization, Heterogeneous Clusters, Decentralized/Volunteer Computing
- **핵심 아이디어**: 인터넷으로 연결된 신뢰할 수 없는(unreliable) 지리적 분산 소비자급 GPU 노드들 위에서 50B+ LLM의 pipeline-parallel inference를 수행하는 fault-tolerant 알고리즘을 제안한다. dual attention cache를 이용해 서버 장애 시 전체 generation을 재시작하지 않고 실패한 stage의 KV cache만 복구하여 대체 서버로 load를 재할당하며, 각 서버에 transformer block을 배정해 전체 시스템 throughput을 최대화하는 탈중앙 load-balancing (greedy rebalancing) 프로토콜을 함께 설계했다. 이를 Petals 시스템으로 구현하여 Llama 2 (70B)와 BLOOM (176B)을 인터넷 상에서 offloading 대비 최대 10배 빠른 interactive generation으로 서빙함을 보였다.
- **실험 환경**: **하이브리드** (실측+시뮬레이션) — 4x GeForce 1080 Ti (single system, dual Xeon Gold 6148, 64GB DDR4) for fault-tolerance experiments; 3x T4 (16GB) for Llama 2; 3x A100 (80GB) and 10x RTX 3090 (24GB) for BLOOM; 12 heterogeneous virtual servers (partitioned A100 80GB); real-world setup with 14 servers holding 2x RTX 3060, 4x RTX 2080Ti, 2x RTX 3090, 2x A4000, 4x A5000 across Europe and North America (100-1000 Mbit/s)
- **평가 모델**: BLOOM-7.1B (fault-tolerance ablation), Llama 2 (70B) with 4-bit NormalFloat quantization, BLOOM (176B) with 8-bit matrix decomposition
- **RADP 관련성**: RADP와 가장 직접적으로 경쟁/보완 관계인 선행 연구로, 서버 장애 시 attention cache 복구와 block 재할당(rebalancing)을 다루지만 failure recovery cost를 placement 결정 시점에 선반영하지 않고 사후(reactive) rebalancing에 의존한다는 점에서 RADP의 recovery-aware placement와 차별화 지점이 명확하다. backup memory와 placement의 coupled feasibility 논증 및 related work에서 반드시 인용해야 할 baseline이다.

### LBRCQT — Load Balancing Routing Under Constraints of Quality of Transmission in Mesh Wireless Network based on Software Defined Networking

- **파일**: `LBRCQT_Load-Balancing-Routing-Under-Constraints-of-Quality-of-Transmission-in-Mesh-Wireless-Network-based-on-SDN.pdf`
- **저자**: Le Huu Binh, Thuy-Van T. Duong (Le Huu Binh: Institute of Engineering and Technology, Thu Dau Mot University, Binh Duong Province, Vietnam)
- **년도/Venue**: 2021 — Journal of Communications and Networks, vol. 23, no. 1, pp. 12-21, February 2021 (KICS, DOI 10.23919/JCN.2021.000004)
- **분야**: Load Balancing, Wireless Networking, SDN Routing, QoT-aware Routing, Wireless Mesh Networks
- **핵심 아이디어**: Wireless mesh network(WMN)에서 load balancing routing은 traffic bottleneck을 줄이지만 긴 multi-hop route로 인해 quality of transmission(QoT)을 떨어뜨리고, 반대로 QoT-aware routing은 특정 링크에 부하를 집중시키는 trade-off가 있음을 지적한다. 이를 해결하기 위해 SDN controller에서 중앙집중식으로 동작하는 LBRCQT 알고리즘을 제안하는데, SNR/BER/end-to-end delay 등 QoT constraint를 만족하는 route 후보 중 link load(Erlang)가 최소인 route를 선택한다. WMN을 Kleinrock independence approximation 기반 M/M/1/K queuing network로 모델링하여 각 링크의 blocking probability와 load offers를 해석적으로 계산하고, ILP 형태의 route selection을 O(K) 복잡도로 푼다. OMNeT++ 시뮬레이션에서 shortest path routing(SPR) 대비 PDR 약 6.4-8%p 향상, throughput 14.7% 증가, heavy load 시 EED 감소를 보였다.
- **실험 환경**: **시뮬레이션** (시뮬레이션) — not stated (simulation on OMNeT++ 4.2.2 with INET framework 2.0; 17 access points, 30-60 mobile hosts, 802.11ac/256-QAM, 1000x1000 m^2 area)
- **평가 모델**: none (no LLM/DNN; network routing simulation)
- **RADP 관련성**: 두 상충하는 목적(load balancing vs QoT constraint)을 하나의 constraint-coupled route selection으로 결합하는 구조는 RADP의 coupled feasibility(성능 placement와 recovery/backup memory constraint의 결합) 주장과 개념적 유사성이 있으나, 무선 mesh packet routing 대상이라 edge LLM inference placement와는 간접적 참고 수준이다.

---

### DejaVu — DéjàVu: KV-cache Streaming for Fast, Fault-tolerant Generative LLM Serving

- **파일**: `DejaVu_KV-cache-Streaming-for-Fast-Fault-tolerant-Generative-LLM-Serving.pdf`
- **저자·년도·venue**: Strati et al., 2024, ICML 2024 (PMLR 235); arXiv:2403.01876
- **분야**: Fault Tolerance, LLM Serving, KV Streaming
- **핵심 아이디어**: pipeline-parallel LLM serving에서 KV cache **자체를** ring 이웃 워커로 per-token·비동기 스트리밍해 복제. 워커 crash(heartbeat 감지) 시 이웃이 replica를 반송하고, controller가 per-token ack로 "마지막 복제 시점 (microbatch j, step t)"을 판정 → **그 이후 토큰만 재계산**. 단일 장애 latency 증가 1.91×→1.24×. DejaVuLib 스트리밍 오버헤드 "within 2% for local SSD and remote CPU memory". microbatch swapping(GPU↔CPU)·prompt-token disaggregation은 별도 메커니즘.
- **실험 환경**: A100-80GB×2 VM(40Gbps inter-VM) / V100-16GB VM(32Gbps), FasterTransformer, OPT-13B/66B·BLOOM-176B, 4-stage pipeline. 실측.
- **RADP 관련성**(해석): "입력 재생(Petals/RADP) vs KV 자체 보호"의 대표 대조군. 이웃 replica는 노드당 KV **~2×** 메모리 + 수십 Gbps 링크 전제 → 4GB Jetson·저속 LAN에선 복제 자체가 병목/불가. RADP related work의 "KV-보호 계열은 memory headroom 전제" 논거.

### GhostServe — A Lightweight Checkpointing System in the Shadow for Fault-Tolerant LLM Serving

- **파일**: `GhostServe_A-Lightweight-Checkpointing-System-in-the-Shadow-for-Fault-Tolerant-LLM-Serving.pdf`
- **저자·년도·venue**: MLSys 2026 (oral); arXiv:2605.00831
- **분야**: Fault Tolerance, LLM Serving, Erasure Coding
- **핵심 아이디어**: streaming KV cache를 chunk 단위로 **erasure coding**(XOR/RDP/RS, 헤드라인 8:2 → K=2 동시 GPU 장애 허용). 코딩 그룹 = **한 노드 안 tensor-parallel N개 shard**(같은 요청의 KV를 든 N GPU), parity는 **호스트 RAM으로 offload**("eliminating GPU memory overhead"). fused CUDA 커널로 encode/decode. 복구는 비용모델로 "앞 r chunk는 재계산 + 나머지는 parity+생존 shard 디코드" 하이브리드. 70B·64K 토큰에서 5초 미만 복구(SSD 방식 ~2분), 8:2가 full replication 대비 overhead 75% 절감, 평시 오버헤드 <5–10%.
- **실험 환경**: H200×8(NVLink Gen4), 1TB DDR5, PCIe4, SGLang 0.5.1, LLaMA-3-8B/70B 등. **"primarily designed for intra-node serving, particularly for tensor parallelism"** — cross-node/pipeline-parallel + inter-node 대역폭은 명시적 future work. 실측.
- **RADP 관련성**(해석): parity 기반 KV 보호의 대표. **cross-node pipeline(저속 링크)이 논문 스스로 남긴 공백** = RADP의 레짐. 엣지 이식 난제: 코딩 그룹을 TP shard→stage 간으로 재설계, parity를 1TB 호스트 RAM→coordinator/peer로, 저속 링크 amortization. RADP mirror 채널이 자연 후보.

### KevlarFlow — Towards Resiliency in Large Language Model Serving

- **파일**: `KevlarFlow_Towards-Resiliency-in-Large-Language-Model-Serving.pdf`
- **저자·년도·venue**: 2026, arXiv:2601.22438 (preprint)
- **분야**: Fault Tolerance, LLM Serving, KV Replication
- **핵심 아이디어**: "runtime node failure를 견디는 최초의 LLM serving framework" 주장. 요청별 KV cache를 load-balancing 그룹 내 **다른 노드의 GPU 메모리**에 PagedAttention block 단위·ring 토폴로지로 백그라운드 복제(전용 CUDA stream 오버랩, NCCL/GPUDirect). 장애 시 같은 stage weight를 든 healthy 노드로 교체 + 복제된 KV block에서 재개("non-interruptive" = 진행 중 요청을 처음부터 재시도하지 않음). MTTR 29–35s(기존 ~10분, 20×). 평시 오버헤드 avg 2.3–4.0%. 메모리 압박 시 replica drop 후 필요 시 재계산(graceful).
- **실험 환경**: A10 24GB×8/16노드, 미국 4개 데이터센터 지리분산, **1Gbps Ethernet·no-NVLink**(의도적), TensorRT-LLM, Llama-3.1-8B 4-stage pipeline, **동시 파이프라인 인스턴스 2–4개**(load-balancing 그룹) 전제. 실측.
- **RADP 관련성**(해석): 1Gbps·no-NVLink라 엣지에 가장 근접한 KV-복제 계열이지만, **웜 여분 파이프라인 + GPU 메모리 헤드룸(50–60% util) 전제**가 4GB 단일 사본 엣지와 정반대. "spare 없는 레짐" 논거의 핵심 대조군.

### LUMEN — Coordinated Failure Recovery for Distributed LLM Serving

- **파일**: `LUMEN_Coordinated-Failure-Recovery-for-Distributed-LLM-Serving.pdf`
- **저자·년도·venue**: 2026, arXiv:2606.17787 (preprint)
- **분야**: Fault Tolerance, LLM Serving, Scheduling/SLO
- **핵심 아이디어**: 복구를 3개 결정점의 load-aware coordination으로: (i) **장애 전 checkpoint placement** — 요청별 KV checkpoint의 보관 워커를 h(r)=argmin(q_w+λ·p_w(r))로 선택(prefill 완료 시 확정, 요청 단위·연속적), (ii) 장애 시 interrupted-request 분배(checkpoint 보유자로 라우팅 + 과부하 시 greedy 이주), (iii) reload 중 capacity 복원(draft 모델 speculation-assist → hotswap). 8-worker Qwen3-14B에서 복구 29.9s(고정 checkpoint 82.8s, 재시작 83.3s).
- **실험 환경**: A800-80GB, NVLink 200GB/s+10Gbps Ethernet, 200GB DRAM/노드, SGLang, Qwen3-14B/32B. **워커 = 모델 전체 사본**("a worker is a complete copy of the model weights") — 파이프라인 분할은 워커 내부 구현일 뿐. checkpoint 예산 80–160GB/워커. 실측+시뮬레이션.
- **RADP 관련성**(해석): "장애 전 배치 결정"이라는 표현이 겹쳐 보이나 실체는 **full-replica들 사이 요청별 KV checkpoint 보관자 선택**이며, **layer placement와 backup placement의 결합 최적화는 없음**(모든 워커가 전 layer 보유라 결합할 대상 자체가 없음). RADP의 ψ+R(메모리 상한 하 layer×backup 공동 배치) novelty와 **비충돌** 확인. 단 "KV를 checkpoint해 재사용(재계산 회피)"은 입력-재생 대비 우월한 지점이라 related work에서 대응 필요.

## TII 산업 프레이밍 논문 (venue-fit, 2026-07-08 추가)

> RADP를 **IEEE TII**에 제출 → 산업 관련성 인용 후보. **전부 IEEE TII 게재 확인(Crossref/dblp + `10.1109/TII.*` DOI).** 역할별 상세·원문 인용 문구는 [TII-industrial-refs.md](TII-industrial-refs.md).
> 역할: **A**=LLM이 이미 산업에, **B**=분산/협업 추론, **C**=엣지 offloading/scheduling, **D**=fault tolerance(RADP recovery 산업 명분 ★).
> PDF: arXiv 프리프린트 있는 2편만 확보(✓), 나머지 18편은 IEEE 유료 → 메타데이터/DOI만.

| 논문 | 역할 | 년 | vol/pp | DOI | PDF | 요지 |
|---|---|---|---|---|---|---|
| Fine-Tuning a 3B-Parameter Large Language Model for Multi... | A | 2026 | 22 no.5 pp.3985-3996 | 10.1109/TII.2026.3654078 | — | 3B LLM을 배터리(BMS) multistate co-estimation에 fine-tune → billion-param L… |
| Advancing Industrial Honeypots: FSM and LLM Integration f... | A | 2026 | 22 no.2 pp.1038-1049 | 10.1109/TII.2025.3620426 | — | FSM+RAG-LLM honeypot으로 ICS 프로토콜 real-time 에뮬레이션. |
| Leveraging Large Language Models to Empower Bayesian Netw... | A | 2025 | 21 no.4 pp.3117-3126 | 10.1109/TII.2024.3523551 | — | LLM으로 Bayesian network를 강화해 공장 human-robot 협업 분해계획. |
| DefectGLM: Large-Scale Visual Language Model Boosted by C... | A | 2024 | 20 no.12 pp.14114-14123 | 10.1109/TII.2024.3441638 | — | LVLM을 웨이퍼 defect inspection(산업 visual monitoring)에 domain-adapt. |
| Joint Knowledge Graph and Large Language Model for Fault ... | A | 2024 | 20 no.6 pp.8160-8169 | 10.1109/TII.2024.3366977 | — | KG+LLM(prefix-tuning)으로 항공 조립 fault diagnosis; online reconfiguration으… |
| A Collaborative AI-Enabled Pretrained Language Model for ... | A | 2022 | 18 no.5 pp.3387-3396 | 10.1109/TII.2021.3097183 | — | foundation LM(RoBERTa_AIoT)을 산업 AIoT 도메인 QA에 적응. |
| DNN Deployment, Task Offloading, and Resource Allocation ... | B | 2023 | 19 no.2 pp.1634-1646 | 10.1109/TII.2022.3192882 | — | end-edge-cloud 협업 DNN deployment+offloading+resource allocation joint … |
| Accuracy-Guaranteed Collaborative DNN Inference in Indust... | B | 2021 | 17 no.7 pp.4988-4998 | 10.1109/TII.2020.3017573 | ✓ | device-edge 협업 DNN 추론을 deep RL로(sampling+offload+compute 할당) 정확도 보장하에 … |
| EdgeKE: EdgeKE: An On-Demand Deep Learning IoT System for... | B | 2021 | 17 no.9 pp.6144-6152 | 10.1109/TII.2020.3044930 | — | distillation+early-exit로 산업 엣지 on-device DNN 추론을 on-demand 정확도/지연 충족. |
| Cost-Driven Off-Loading for DNN-Based Applications Over C... | B | 2020 | 16 no.8 pp.5456-5466 | 10.1109/TII.2019.2961237 | — | DNN layer를 cloud/edge/end로 partition(self-adaptive PSO+GA)해 비용 최소화 = R… |
| Fairness-Aware Deterministic Joint Offloading and Schedul... | C | 2026 | 22 no.5 pp.4032-4043 | 10.1109/TII.2026.3654608 | — | 산업 엣지 computing에서 deterministic latency+fairness 보장 offloading+schedul… |
| DSAC-Configured Differential Evolution for Cloud-Edge-Dev... | C | 2024 | 20 no.2 pp.1753-1763 | 10.1109/TII.2023.3281661 | — | RL-configured differential evolution으로 cloud-edge-device 협업 task sched… |
| Distributed Multidomain Resource Allocation for IIoT-Base... | C | 2024 | 20 no.12 pp.14006-14016 | 10.1109/TII.2024.3438280 | — | IIoT 제어 시스템용 multidomain 분산 자원할당 최적화. |
| Robust Trajectory and Offloading for Energy-Efficient UAV... | C | 2024 | 20 no.1 pp.38-49 | 10.1109/TII.2023.3256375 | ✓ | UAV 엣지 computing의 trajectory+offloading joint 최적화(원격 IIoT). |
| Task Co-Offloading for D2D-Assisted Mobile Edge Computing... | C | 2023 | 19 no.1 pp.480-490 | 10.1109/TII.2022.3158974 | — | D2D-assisted MEC에서 IIoT task co-offloading. |
| An Intelligent Fault Tolerant Data Routing Scheme for Wir... | D | 2023 | 19 no.4 pp.5543-5553 | 10.1109/TII.2022.3204560 | — | WSN-IIoT에서 노드/링크 fault를 감지·허용하는 지능형 data routing. 인용: 'sensors ... vul… |
| Performance Analysis of Fault-Tolerant Multiagent Coordin... | D | 2023 | 19 no.9 pp.9821-9832 | 10.1109/TII.2023.3234606 | — | faulty agent 하 분산 MAS coordination 성능 분석(FT 선택이 latency 4.2× 개선). |
| Resource-Optimal Fault-Tolerant Scheduler Design for Task... | D | 2021 | 17 no.11 pp.7325-7337 | 10.1109/TII.2020.3042161 | — | supervisory control로 processor fault에도 deadline 지키는 resource-optimal F… |
| DRPM: Dynamic Resource Provisioning With Fault Tolerance ... | D | 2020 | 16 no.9 pp.6172-6181 | 10.1109/TII.2019.2959258 | — | 장애 task 복구+makespan 재최적화하는 fault-tolerant 동적 provisioning. 인용: 'when a… |
| FTTRS: A Fault-Tolerant Ethernet for Hard Real-Time Adapt... | D | 2019 | 15 no.5 pp.2980-2991 | 10.1109/TII.2019.2895046 | — | replicated-star Ethernet(FTTRS)로 network fault를 hard real-time 보장하며 허용… |

총 20편 (A:6 B:4 C:5 D:5). Intro 배치: A→§1(LLM 실수요), B/C→§2(분산추론 산업 확립), D→§4(recovery 산업 명분). 상세는 TII-industrial-refs.md.
