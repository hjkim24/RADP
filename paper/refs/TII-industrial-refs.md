# TII 산업 프레이밍용 인용 후보 (IEEE Transactions on Industrial Informatics)

> RADP를 **TII**에 제출하기로 결정(2026-07-08) → Introduction에 산업 관련성을 더하기 위해 수집.
> **전부 IEEE TII 게재 확인** (Crossref `container-title` + `10.1109/TII.*` DOI, 또는 dblp `IEEE Trans. Ind. Informatics`). 서브에이전트 4각도 검색 → DOI 검증.
> 역할별로 묶음 — intro에서 어느 주장을 뒷받침하는지 표기. **인용 시 원문 재확인 권장**(초록 기반 요약 포함).

---

## 역할 A — "LLM이 이미 산업 현장에 배치되고 있다" (why LLM at industrial edge is a real, active need)

| 논문 | 년/vol | DOI | 산업 관련성 |
|---|---|---|---|
| Zhu et al., *A Collaborative AI-Enabled Pretrained Language Model for AIoT Domain Question Answering* | 2022, 18(5):3387-3396 | 10.1109/TII.2021.3097183 | foundation LM을 산업 AIoT 도메인 QA에 적응 |
| Wang et al., *Large-Scale Visual Language Model Boosted by Contrast Domain Adaptation for Intelligent Industrial Visual Monitoring* (DefectGLM) | 2024, 20(12):14114-14123 | 10.1109/TII.2024.3441638 | LVLM을 웨이퍼 defect inspection(제조 visual monitoring)에 |
| **Zhang et al., *Fine-Tuning a 3B-Parameter Large Language Model for Multistate Coestimation of Lithium-Ion Batteries...*** | 2026, 22(5):3985-3996 | 10.1109/TII.2026.3654078 | **3B LLM을 배터리관리(BMS) 임베디드 산업 하드웨어에** — "billion-param LLM on resource-bounded industrial hardware"의 직접 근거 |
| Xia et al., *Leveraging LLMs to Empower Bayesian Networks for ... Human-Robot Collaborative Disassembly ... Remanufacturing* | 2025, 21(4):3117-3126 | 10.1109/TII.2024.3523551 | LLM을 공장 shop-floor human-robot 협업에 |
| Chamotra et al., *Advancing Industrial Honeypots: FSM and LLM Integration for Realistic ICS Protocol Emulation* | 2026, 22(2):1038-1049 | 10.1109/TII.2025.3620426 | RAG-LLM을 ICS/OT 보안 인프라에 real-time 서빙 |
| Liu et al., *Joint Knowledge Graph and Large Language Model for Fault Diagnosis ... Aviation Assembly* | 2024, 20(6):8160-8169 | 10.1109/TII.2024.3366977 | LLM을 항공 조립 fault diagnosis에; "online reconfiguration ... avoids a massive computational load" → **산업 자원 제약 하 compute-efficient LLM 배치 동기** |
| (선택) Generative AI-Empowered Digital Twin: A Comprehensive Survey | 2025, 21(6):4287-4295 | 10.1109/TII.2025.3540473 | generative AI ↔ 산업 digital twin/CPS 서베이 (motivational) |

## 역할 B — "분산/협업 추론 + 모델 파티셔닝은 이미 확립된 산업적 접근" (distributed inference is an established TII topic)

| 논문 | 년/vol | DOI | 비고 |
|---|---|---|---|
| **Lin et al., *Cost-Driven Off-Loading for DNN-Based Applications Over Cloud, Edge, and End Devices*** | 2020, 16(8):5456-5466 | 10.1109/TII.2019.2961237 | **DNN layer partitioning across cloud/edge/end** = RADP layer placement의 산업판 (가장 직접적) |
| Wu et al., *Accuracy-Guaranteed Collaborative DNN Inference in Industrial IoT via Deep RL* | 2021, 17(7):4988-4998 | 10.1109/TII.2020.3017573 | device-edge 협업 분산 DNN 추론 (IIoT) |
| Fan et al., *DNN Deployment, Task Offloading, and Resource Allocation for Joint Task Inference in IIoT* | 2023, 19(2):1634-1646 | 10.1109/TII.2022.3192882 | end-edge-cloud 협업 DNN 추론 (2개 에이전트 교차확인) |
| Fang et al., *EdgeKE: An On-Demand Deep Learning IoT System for Cognitive Big Data on Industrial Edge Devices* | 2021, 17(9):6144-6152 | 10.1109/TII.2020.3044930 | 산업 엣지 on-device DNN 추론(distillation+early-exit) |

## 역할 C — "엣지 offloading/scheduling/자원할당이 산업정보학의 활발한 주제" (distributed processing hot in industry)

| 논문 | 년/vol | DOI |
|---|---|---|
| Yao et al., *Fairness-Aware Deterministic Joint Offloading and Scheduling for Industrial Edge Computing* | 2026, 22(5):4032-4043 | 10.1109/TII.2026.3654608 |
| Laili et al., *DSAC-Configured Differential Evolution for Cloud-Edge-Device Collaborative Task Scheduling* | 2024, 20(2):1753-1763 | 10.1109/TII.2023.3281661 |
| Dai et al., *Task Co-Offloading for D2D-Assisted Mobile Edge Computing in Industrial Internet of Things* | 2023, 19(1):480-490 | 10.1109/TII.2022.3158974 |
| Wu et al., *Distributed Multidomain Resource Allocation for IIoT-Based Control Systems* | 2024, 20(12):14006-14016 | 10.1109/TII.2024.3438280 |
| Tang et al., *Robust Trajectory and Offloading for Energy-Efficient UAV Edge Computing in IIoT* | 2024, 20(1):38-49 | 10.1109/TII.2023.3256375 |

## 역할 D — "fault tolerance는 산업 분산 시스템의 1급 관심사; 노드 장애는 흔하고 비용이 크다" (RADP recovery 기여의 산업 명분) ★핵심★

| 논문 | 년/vol | DOI | 인용 가치 (원문 문구) |
|---|---|---|---|
| **Kaur & Chanak, *An Intelligent Fault Tolerant Data Routing Scheme for WSN-Assisted IIoT*** | 2023, 19(4):5543-5553 | 10.1109/TII.2022.3204560 | "sensors in the IIoT are **vulnerable to failures due to energy depletion and hardware malfunctioning**. It significantly reduces the reliability of the network." |
| **Xu et al., *Dynamic Resource Provisioning With Fault Tolerance for Data-Intensive Meteorological Workflows*** | 2020, 16(9):6172-6181 | 10.1109/TII.2019.2959258 | "When any of the computing nodes ... **fail**, all sorts of consequences (**data loss, makespan enlargement, performance degradation**) could arise." |
| Gessner et al., *A Fault-Tolerant Ethernet for Hard Real-Time Adaptive Systems* | 2019, 15(5):2980-2991 | 10.1109/TII.2019.2895046 | "Distributed embedded systems that perform **critical tasks** ... must be **reliable, hard real-time**"; 공유 네트워크가 **single point of failure** |
| Devaraj & Sarkar, *Resource-Optimal Fault-Tolerant Scheduler Design for Task Graphs Using Supervisory Control* | 2021, 17(11):7325-7337 | 10.1109/TII.2020.3042161 | 안전필수 real-time에서 FT를 **hard design constraint**로 |
| Pinciroli & Trubiani, *Performance Analysis of Fault-Tolerant Multiagent Coordination Mechanisms* | 2023, 19(9):9821-9832 | 10.1109/TII.2023.3234606 | 분산 MAS는 "software/hardware failures"를 전제; FT 선택이 latency 4.2× 개선 |

---

## Intro에서의 배치 제안 (시나리오 2 하이브리드 기준)
- **①-a (LLM at industrial edge가 실수요)**: 역할 A 2–3편 (Zhang'26 3B-LLM-on-BMS, Xia'25 shop-floor, Liu'24 fault-diagnosis) → "LLM이 이미 배터리관리·조립·검사 등 산업 현장에 들어오고 있다."
- **①-b (왜 엣지 — 산업 offline/reliability)**: 산업 현장은 air-gapped·원격·latency-critical이라 클라우드 부적합 + 역할 D로 "산업 분산 시스템에서 노드 장애는 흔하고(에너지·HW) 비용이 크다(데이터손실·안전)".
- **②-a (분산 추론이 산업에서 확립됨)**: 역할 B (Lin'20 DNN partitioning, Wu'21 collaborative) + 역할 C 1편 → "분산/협업 추론·offloading이 산업정보학의 활발한 주제."
- **⑤ (RADP recovery의 산업 필수성)**: 역할 D를 recovery 기여와 직접 연결 → "기존 산업 FT는 routing/scheduling/network 수준이고, LLM **분산 추론의 placement+recovery joint**는 공백."

## 주의 (정직성)
- 위 요약은 초록/제목 기반 — **인용 전 원문 재확인**. 특히 역할 D 문구는 원문 그대로 재확인 후 인용.
- 이들은 대부분 IEEE 유료라 PDF 미보관(메타데이터/DOI만). paper/refs PDF 폴더엔 없음.
