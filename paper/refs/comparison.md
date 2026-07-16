# Edge 분산추론 선행연구 서론 비교 — "왜 데이터센터 GPU 대신 엣지인가"

> 목적: RADP Introduction 보완용. 세 선행연구가 서론에서 **엣지 디바이스를 통한 분산추론**을 어떻게 정당화했는지 비교.
> **원칙: 각 논문에 실제로 명시된 사실/표현만 사용** (인용은 원문 영어 그대로). 해석·추론은 맨 아래 "RADP 시사점"에만 분리.

---

## 0. 대상 논문

| 약칭 | 제목 | 출처 | 엣지 디바이스 | 아키텍처 성격 |
|---|---|---|---|---|
| **MDI-LLM** | Model-Distributed Inference for Large Language Models at the Edge | IEEE LANMAN 2025 (Macario, Seferoglu, Koyuncu, UIC; arXiv:2505.18164) | (저전력 엣지, 명시 device 없음 — "low-power devices") | **순수 엣지**, model/pipeline parallelism (recurrent pipeline) |
| **EdgeShard** | EdgeShard: Efficient LLM Inference via Collaborative Edge Computing | IEEE Internet of Things Journal 2025 (Zhang, Cao, Shen, Cui, PolyU; arXiv:2405.14371) | 이기종 엣지 + 클라우드 (AGX Orin, Orin NX, RTX3090) | **엣지-클라우드 협업(CEC)** |
| **EnergyHarvest** | Decentralized LLM Inference over Edge Networks with Energy Harvesting | IEEE GLOBECOM 2024 (Khoshsirat, Perin, Rossi, U. Padova; arXiv:2408.15907) | Jetson AGX Orin (15/30/50/60W) | **분산(Petals 기반)** + 에너지 하베스팅 |

PDF는 이 폴더(`paper/refs/`)에 저장됨.

---

## 1. 각 논문 서론의 "엣지 동기부여" 논리 (명시된 사실만)

### MDI-LLM (§I Introduction)
- **LLM 규모 → 클라우드 밖 배포 불가/고비용**: "LLMs grew ... billions of parameters (GPT-3 175B, PaLM 540B). This translates into the need for a huge amount of computation power, making it **impossible, or very expensive, to deploy LLMs outside the cloud**."
- **엣지 단일 디바이스의 한계**: "generative AI is still unexplored for applications at the edge, as the corresponding devices **typically lack the capabilities to run LLMs independently** and have to rely on a remote cloud."
- **엣지가 바람직한 이유(명시 3개)**: "Deploying AI/ML models at the edge can be desirable for many reasons, including **privacy, availability, and the rising cost of cloud resources**."
- **왜 model parallelism인가(메모리 논거)**: data parallelism은 "the need to **fit the full model on every network device**"라는 단점 → model parallelism은 "**reduces the memory requirements** as compared to data parallelism thanks to partitioning the model."
- **pooling 효과**: "Adding more secondary nodes to the system allows **larger LLMs and more samples** to be processed." + abstract: "enables the deployment of LLMs that **exceed the memory capacity of individual devices** ... on low-cost hardware."

### EdgeShard (§I Introduction)
- **클라우드 의존의 3대 문제**:
  - latency: "the reliance on cloud computing hampers the capability for **rapid model inference** necessary for real-time applications such as robotics control, navigation, or exploration."
  - bandwidth/network: "the transmission of large amounts of data ... to the cloud data centers leads to **substantial bandwidth consumption and immense strain on the network**."
  - privacy: "cloud-based LLMs raise significant **privacy issues**, especially when handling sensitive data like hospitals and banks, as well as personal data."
- **엣지 단일 디바이스의 한계(수치 명시)**: "the inference of a full-precision **Llama2-7B model requires at least 28GB memory, which may exceed the capacity of most edge devices**." (Table I: 스마트폰 6–12GB, Orin NX 8–16GB)
- **기존 대안의 한계**: quantization → "**accuracy loss**"; cloud-edge collaboration → "the latency between edge devices and cloud servers is usually **high and unstable**."
- **해법**: Collaborative Edge Computing — "integrate the computing resources of ubiquitous **geo-distributed edge devices and cloud servers**" (즉 클라우드도 자원 풀에 포함).

### EnergyHarvest (§I Introduction, §II)
- **엣지의 이점(명시 3개)**: "Edge networks, which consist of devices located **close to data sources**, provide benefits such as **decreased latency, increased privacy, and improved reliability**."
- **엣지 단일 디바이스의 한계**: "the **constrained energy and memory capacity** of edge devices pose significant challenges to the implementation of resource-intensive models such as LLMs."
- **분산(decentralized)의 이점**: "distributing the workload across multiple devices ... provide **greater flexibility and cost-effectiveness** while **alleviating the burden on individual devices** by harnessing the computational power of multiple devices."
- **고유 각도 — 에너지**: "energy constraints of edge devices remain a critical concern ... **Energy harvesting** techniques, which capture ... solar, kinetic, or thermal energy ... increase their energy reserves and extend their operational lifetime." + carbon footprint 감소.
- **아키텍처 출처**: "**Building upon Petals**, ... our framework distributes the LLM layers between groups of devices, and within a group, **identical portions of the LLM layers are replicated on each device**."

---

## 2. 축별 비교

| 축 | MDI-LLM | EdgeShard | EnergyHarvest |
|---|---|---|---|
| **"왜 클라우드 말고 엣지"** | privacy, availability, **cloud 비용 상승** | **latency**(real-time), **bandwidth/network strain**, **privacy** | **latency, privacy, reliability** (data source 근접) |
| **"왜 단일 디바이스 말고 분산"** | 단일 device가 LLM 실행 능력 없음 / 모델이 **개별 메모리 초과** | full-precision Llama2-7B **28GB > 대부분 엣지** | **constrained energy·memory** |
| **분산이 주는 이점(명시)** | larger LLM 가능, per-device 메모리↓, throughput↑ | 클라우드 포함 자원 풀 통합, latency↓·throughput↑ | flexibility, **cost-effectiveness**, 개별 부담 완화 |
| **클라우드 포함?** | ❌ 순수 엣지 | ✅ 엣지+**클라우드** | ❌ 분산 엣지 |
| **redundancy/복제** | 언급 없음(서론) | 언급 없음 | **그룹 내 layer 복제**(Petals식) |
| **고유 프레이밍** | model-parallelism-이-메모리-줄인다 논거, autoregressive 난제 | 클라우드 3대 문제 → CEC | **에너지 하베스팅·지속가능성·탄소** |
| **비용 언급 방식** | "rising cost of cloud resources", "low-cost hardware" | 직접적 비용 서술 약함(주로 latency/bw/privacy) | "cost-effectiveness"(분산의 이점으로) |

---

## 3. 공통점 / 차이 요약 (명시된 사실 기반)

**공통 (세 논문 모두 명시):**
- **privacy**를 엣지 이유로 명시 (3/3).
- **단일 엣지 디바이스가 LLM을 못 담는다**(메모리/능력 한계)를 분산의 근거로 명시 (3/3). — EdgeShard만 28GB로 수치화.
- 분산으로 **개별 디바이스 부담↓ + 더 큰 모델 가능**을 명시 (3/3).

**차이:**
- **latency**: EdgeShard·EnergyHarvest는 명시, MDI-LLM 서론은 latency보다 **비용·능력**을 앞세움.
- **비용**을 헤드라인급으로 미는 건 **MDI-LLM**("rising cost of cloud resources", "low-cost hardware")과 EnergyHarvest("cost-effectiveness")뿐. EdgeShard는 비용보다 latency/bandwidth/privacy 중심.
- **클라우드 위치**: EdgeShard는 클라우드를 **자원 풀에 포함**(edge-cloud), 나머지 둘은 순수 엣지/분산.
- **고유 축**: MDI-LLM=recurrent pipeline(autoregressive), EdgeShard=CEC 정식화, EnergyHarvest=에너지 하베스팅.

---

## 4. RADP 시사점 (※ 아래는 해석/제안 — 논문 사실 아님)

- 세 논문 모두 **"왜 엣지(=privacy/latency/reliability, cloud 비용)"** 와 **"왜 분산(=단일 디바이스가 모델을 못 담음 → pooling)"** 을 **분리해서** 전개한다. RADP §1도 이 두 질문 분리 구조를 유지하면 선행연구와 정렬됨.
- **비용을 헤드라인으로 쓸 근거**: MDI-LLM·EnergyHarvest가 "cloud 비용 / cost-effectiveness / low-cost hardware"를 명시하므로, RADP도 "이미 보유한 저가 하드웨어 재활용"을 **cite와 함께** 주장 가능 (조작 아님, 선행연구 프레이밍 차용).
- **capacity 벽의 수치화**: EdgeShard의 "Llama2-7B 28GB > 엣지"처럼 **구체 수치**로 단일-디바이스 불가를 못박는 게 설득력 큼 → RADP도 4GB Nano 대비 모델 크기 수치로 대응.
- **차별점**: 세 논문 중 누구도 (i) placement와 recovery를 **joint 최적화**하거나 (ii) **4GB Nano frontier**를 명시 타깃하지 않음 → RADP의 gap 주장은 이들과 겹치지 않음. (EnergyHarvest·EdgeShard는 AGX Orin/RTX 등 넉넉한 device, MDI-LLM은 device 미명시.)

## 5. 추가 엣지 논문 서론 분석 (2026-07-08 추가) — 명시된 사실만

> §1~§3(MDI-LLM/EdgeShard/EnergyHarvest)과 같은 방식으로, 새로 추가한 엣지 관련 5편의 서론이 '왜 데이터센터 GPU 대신 엣지 분산추론인가'를 어떻게 유도하는지 정리. 인용은 원문 영어.

### 5.1 논문별 서론 동기 (facts + 원문 인용)

**Efficient-SD-Edge (Zhu et al.)** — Efficient LLM Inference over Heterogeneous Edge Networks with Speculative Decoding  
_이종 엣지(MBS+SBS) speculative decoding_

- **왜 클라우드/데이터센터 말고 엣지**:
  - 원격 클라우드로 데이터 전송 → 전송 지연·프라이버시: "transmitting user data to remote cloud servers ... introducing significant transmission latency and raising critical data privacy concerns"
  - 엣지 추론이 사용자 근접 자원으로 완화: "edge inference ... provide inference services closer to users, which reduces transmission overhead and enhances privacy protection"
- **왜 단일 디바이스 말고 분산**:
  - 단일 엣지 서버는 다수 동시 task를 저지연 유지하며 감당 곤란: "a single resource-constrained edge server may struggle to support numerous concurrent inference tasks while maintaining low-latency serving"
  - LLaMA-7B ≈14GB > 대부분 엣지(Jetson TX2 8GB): "exceeding the capacity of most edge devices, such as the NVIDIA Jetson TX2 with only 8 GB"
- **분산이 주는 이점(명시)**:
  - draft/target를 다른 엣지 노드에 배치해 지연↓·정확도 유지: "draft and target models are deployed across different edge nodes ... reduces LLM inference latency while preserving model accuracy"
  - pipeline parallelism으로 다중 task 동시 처리: "process multiple inference tasks concurrently and thus reducing total serving latency"
- **고유 각도**: 이종 엣지(MBS+SBS) speculative decoding에 pipeline parallelism을 결합하고 speculation·batching·wireless를 하나의 latency 문제로 joint 최적화.

**FedAttn** — Federated Attention: A Distributed Paradigm for Collaborative LLM Inference over Edge Networks  
_privacy-preserving 협력 추론(FL⊕attention)_

- **왜 클라우드/데이터센터 말고 엣지**:
  - 클라우드는 프라이버시/보안 취약(프롬프트 원격 전송): "privacy and security vulnerabilities, including potential data disclosure ... to sensitive and personally identifiable information"
  - 클라우드는 통신 지연, 특히 무선 대역폭 압박: "communication delays ... heavy data traffic between end devices and a remote cloud can overwhelm the limited transmission bandwidth ... latency-sensitive applications such as autonomous vehicles"
  - 엣지가 사용자에 지리적으로 근접: "reduce communication overhead by utilizing edge infrastructure geographically closer to users than remote clouds"
- **왜 단일 디바이스 말고 분산**:
  - 단일 온디바이스 추론은 연산 병목으로 불가: "computation bottleneck: modern LLMs demand substantial memory and computing power that typically surpass the capabilities of user devices, rendering on-device inference infeasible"
  - 다중 참가자 프롬프트 결합으로 시퀀스 길이↑ → 단일 디바이스 부담↑: "the extended input sequence length from multiple participants substantially increases computational complexity"
- **분산이 주는 이점(명시)**:
  - privacy: "Eliminating the need for raw data sharing via local computation and global aggregation"
  - computation efficiency: "Reducing computational and memory complexities via distributed parallel computing"
  - communication efficiency: "Minimizing overall communication overhead via periodic synchronization rounds"
- **고유 각도**: 완전한 프롬프트가 단일 노드에 있다는 가정을 깨고, FL을 self-attention에 이식해 다수 사용자가 private 세그먼트를 노출 없이 KV 교환·집계로 협력 추론하는 최초의 privacy-preserving 패러다임.

**HybridFlow** — HybridFlow: Resource-Adaptive Subtask Routing for Efficient Edge-Cloud LLM Inference  
_edge-cloud subtask DAG routing_

- **왜 클라우드/데이터센터 말고 엣지**:
  - cloud-only는 예산 하 비용·지연 큼: "cloud-only inference can be costly and slow under strict latency and token/API budgets"
  - 클라우드 서빙은 지연·메모리·API 비용 오버헤드: "high inference latency, large memory footprints, and non-trivial API expenses when served from the cloud"
  - 엣지는 peak accuracy가 아니라 budget 내 acceptable accuracy가 목표: "the goal is to achieve acceptable accuracy under strict latency and cost budgets, rather than maximizing accuracy in isolation"
- **왜 단일 디바이스 말고 분산**:
  - 단일 온디바이스 SM은 reasoning/knowledge 용량 부족: "SM-only solutions often struggle on tasks that demand deep reasoning or broad knowledge due to limited model capacity"
  - 단일 클라우드는 예산/지연 위반 → 협업 필요: "This tension motivates edge-cloud collaboration ... to balance accuracy, latency, and cost"
  - 순차 실행은 query 내 concurrency 낭비: "many complex queries naturally decompose into interdependent parts, where unlocked parts could be executed concurrently"
- **분산이 주는 이점(명시)**:
  - 의존성 풀린 subtask 병렬 실행으로 지연↓: "facilitating concurrent execution of subtasks once their dependencies are resolved, thereby reducing end-to-end latency"
  - decomposition+budget routing 결합으로 accuracy-efficiency 균형: "By coupling decomposition with budget-constrained routing, HybridFlow explicitly balances accuracy and efficiency"
- **고유 각도**: edge-cloud 할당을 query가 아니라 dependency-aware DAG의 subtask 단위로 수행해 fine-grained parallelism과 online budget-adaptive routing을 하나의 sequential decision으로 결합.

**TK-SLT** — Communication-Efficient Collaborative LLM Inference via Distributed Speculative Decoding  
_device-BS speculative decoding 통신효율_

- **왜 클라우드/데이터센터 말고 엣지**:
  - 클라우드 추론은 지연·지터·이동성 단절: "cloud inference suffers from latency, jitter, and mobility-induced disconnections"
  - AI-RAN에서 통신·연산 공동관리로 신뢰·저지연 서비스 필요: "where communication and computation are jointly managed, efficient resource orchestration is essential to deliver reliable, low-latency LLM services"
- **왜 단일 디바이스 말고 분산**:
  - 엣지 디바이스 단독은 메모리·에너지·연산 부족: "Edge devices face tight memory, energy, and compute limits"
  - 해법으로 device SLM + BS/edge LLM 협업 배치: "deploys a small language model (SLM) on the device while offloading the large language model (LLM) to a base station (BS) or edge server"
- **분산이 주는 이점(명시)**:
  - 난이도 기반 라우팅으로 비용효율 할당: "cost-efficient assignment of queries to either the small or large model"
  - speculative decoding으로 순차 생성 비효율 완화·품질 유지: "alleviates the inefficiency of sequential token generation while maintaining output quality"
- **고유 각도**: AI-RAN 협업 speculative decoding의 uplink 통신 병목(vocab 크기 비례 payload)을 top-K sparse logit 전송으로 없애되 standalone LLM과 확률적 동등성을 정확히 보존.

**Distributed-MoA (Mitra et al.)** — Distributed Mixture-of-Agents for Edge Inference with Large Language Models  
_탈중앙 gossip MoA_

- **왜 클라우드/데이터센터 말고 엣지**:
  - 중앙 서버는 single point of failure(링크 장애·adversarial attack): "a centralized server, which is often a single point of failure susceptible to ... link disruptions and adversarial attacks"
  - 중앙 서버는 엣지와 분리돼 큰 통신 지연: "incurring large communication delays with the edge devices"
  - 엣지 간 다양한 연결이 연산 robustness↑: "maintaining a diverse network of connections among edge devices enhances the overall computational robustness"
- **왜 단일 디바이스 말고 분산**:
  - 단일 LLM보다 협업이 더 나은 응답: "improved responses ... compared to relying on a single LLM"
  - 단일 디바이스 자기 LLM만 쓰면 정확도 낮음: "If a device only uses its own LLM, its response accuracy remains poor"
  - 협업이 개별 디바이스보다 많은 compute power 접근: "more diverse connections to more compute power than individual edge devices"
- **분산이 주는 이점(명시)**:
  - robustness / no single point of failure: "making the system more robust"
  - own data·compute 자원 유지(프라이버시·자율성): "utilize their own data and computational resources without relying on a centralized server"
  - 협업으로 accuracy↑ (proposer+aggregator MoA)
- **고유 각도**: 엣지 디바이스 간 LLM 교환을 semantic gossiping으로 프레이밍하고, gossip 데이터의 semantics(정확도)+timeliness(지연/queue)를 함께 고려해 distributed MoA의 queuing stability를 분석한 최초 시도.

### 5.2 축별 비교표

| 논문 | 구성 | 왜 엣지(not cloud) | 왜 분산(not single) | 분산 이점 핵심 | 고유 각도 |
|---|---|---|---|---|---|
| **Efficient-SD-Edge (Zhu et al.)** | 이종 엣지 2계층 | 전송 지연·privacy | 단일 서버 다중 task 곤란 / 7B>Jetson 8GB | draft/verify 분산+pipeline overlap | speculation·batching·wireless joint 최적화 |
| **FedAttn** | 다수 사용자 엣지 | privacy·무선 지연 | on-device 연산 병목 / 프롬프트 합쳐 시퀀스↑ | privacy+연산+통신 효율 | FL을 attention에 이식(프롬프트 비노출) |
| **HybridFlow** | edge SM + cloud LLM | cloud 비용·지연·API | SM 단독 reasoning 부족 / 순차 실행 낭비 | subtask 병렬로 지연↓ | DAG subtask 단위 budget-adaptive routing |
| **TK-SLT** | device SLM + BS LLM | 지연·지터·이동성 단절 | 엣지 메모리·에너지·연산 부족 | 난이도 라우팅+SD 가속 | uplink vocab payload를 top-K sparse로 제거 |
| **Distributed-MoA (Mitra et al.)** | 탈중앙 엣지 | 중앙서버 SPOF·지연 | 단일 LLM 정확도 낮음 | robustness+협업 accuracy↑ | semantic gossip MoA의 queuing stability |

### 5.3 §1~§3과 합친 관찰

- **privacy**는 8편 중 대다수가 엣지 이유로 명시(§1~§3의 3편 + FedAttn/Efficient-SD-Edge). **latency**도 공통.
- **비용 각도**: HybridFlow가 가장 직접적('cloud-only can be costly ... token/API budgets') — MDI-LLM/EnergyHarvest의 비용 프레이밍과 함께 RADP의 '저가 하드웨어 재활용' 주장 근거로 활용 가능.
- **구성 스펙트럼**: 순수 엣지 분산(FedAttn, Distributed-MoA) ↔ 2계층 엣지(Efficient-SD-Edge) ↔ 엣지-클라우드/BS 협업(HybridFlow, TK-SLT, EdgeShard). RADP는 **동종 엣지 클러스터(클라우드 없음)** + 4GB Nano frontier로 이들과 구분됨.
- **fault/robustness를 서론 동기로 든 건 Distributed-MoA뿐**('single point of failure ... link disruptions and adversarial attacks') — RADP의 recovery 동기와 가장 근접한 서론 프레이밍. 단 MoA는 placement/recovery 최적화가 아니라 queuing stability.
- 5편 모두 **recovery-aware placement**나 **placement+recovery joint 최적화**는 다루지 않음 → RADP gap 유지.

---

## 출처
- MDI-LLM: https://arxiv.org/abs/2505.18164
- EdgeShard: https://arxiv.org/abs/2405.14371
- EnergyHarvest: https://arxiv.org/abs/2408.15907
