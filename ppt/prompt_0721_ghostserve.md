# 0721 덱 — GhostServe 슬라이드만 추가 (추가 전용)

**이 프롬프트는 `prompt_0721_flow.md` 를 이미 적용한 덱에만 쓴다.**
아직 안 했으면 이걸 쓰지 말고 `prompt_0721_flow.md` 를 한 번 먹여라 —
거기 GhostServe 슬라이드가 이미 들어 있어서 두 번 할 필요 없다.

적용 여부는 이걸로 판별한다: **`c. 공짜 아님 — 3종 장단점` 표 슬라이드가 있으면 적용된 것.**
없으면 적용 안 된 것이다.

---

덱의 다른 슬라이드는 **하나도 건드리지 마라.** 좌표·폰트·색·문구·쪽번호 전부 이미 규격에 맞다.
할 일은 **슬라이드 한 장 삽입**과 **한계 슬라이드에서 한 줄 삭제**뿐이다.

## 작업 1 — parity 원리 슬라이드 바로 뒤에 한 장 삽입

`b. parity 원리 — 재계산 대신 XOR 역산` 슬라이드 **다음**에 넣는다.
밴드 `2. Progress last week`, 워크스트림 `1. RADP`.

- 소제목(굵게, 16pt): `b-2. 선행연구 — 기법은 GhostServe, 레짐이 우리 것`
- 그 아래 한 줄(16pt): `KV erasure coding 자체는 GhostServe(MLSys '26)가 먼저 함`
- 시각물: `paper/figures/fig_ghostserve_delta.png` — **11.73 in 전폭**,
  L 0.63 T 2.55, 배율 100%. 좌측 라벨 붙이지 마라 (그림 자체가 좌우 비교다)
- 캡션(12pt): `차이: 코딩 그룹 = 한 노드 안 TP shard → 노드 간 pipeline stage / parity 보관 = host RAM 1TB → coordinator`
- 마지막 줄(16pt 굵게): `기여는 기법 발명이 아니라 논문이 스스로 남긴 공백으로 옮겨 측정한 것`

왜 여기 두나: 원리만 설명하고 넘어가면 parity 가 우리 아이디어처럼 들린다.
질의응답에서 "그거 GhostServe 아니냐" 가 나오는 것보다 먼저 밝히는 편이 낫다.

### 쓸 수 있는 사실 (근거: `paper/refs/PAPERS.md` GhostServe 항목)

**여기 없는 비교를 지어내지 마라.** 발표 자료가 논문 근거로 이어진다.

GhostServe:
- 코딩 그룹 = **한 노드 안의 tensor-parallel shard** (같은 요청 KV 를 든 N GPU)
- parity 를 **호스트 RAM 으로 offload**, fused CUDA 커널로 encode/decode
- 8:2 erasure coding → **동시 GPU 장애 2대**까지 허용
- 복구는 하이브리드 — 앞쪽 chunk 는 재계산, 나머지는 parity 디코드
- 실험 환경 H200×8 NVLink Gen4, 1TB DDR5
- 논문이 스스로 **"primarily designed for intra-node serving, particularly for
  tensor parallelism"** 이라 밝히고 cross-node/pipeline 은 future work 로 남김

우리:
- 코딩 그룹 = **노드 간 pipeline stage**, parity 는 **coordinator**(Jetson AGX Xavier)
- XOR 단독 → **단일 장애 전용**. 대신 재계산 하이브리드 없이 **순수 디코드**
- Ethernet 로 연결된 Jetson 5-stage 이종 체인. **여분 노드도, offload 할 호스트 RAM 도 없음**

## 작업 2 — 한계 슬라이드에서 선행연구 줄 삭제

`한계` 슬라이드의 `• 선행연구: KV parity 자체는 GhostServe가 먼저 함 …` 불릿을 **지운다.**
방금 만든 슬라이드로 올라갔으므로 그대로 두면 같은 말이 두 번 나온다.
나머지 불릿은 손대지 마라.

## 작업 3 — 마지막 Reference 슬라이드

자리표시자 `[1] Author, "Title," Venue, Year.` 를 아래로 교체한다. IEEE 스타일, 12pt.

```
[1] S. Jayakody, Y. Zhao, C. Nehate, and J. Wang, "GhostServe: A lightweight
    checkpointing system in the shadow for fault-tolerant LLM serving," in Proc.
    Conf. Machine Learning and Systems (MLSys), 2026. [Online]. Available:
    arXiv:2605.00831
```

한 줄로 이어 쓰되 폭이 모자라면 자연스럽게 접어라. 항목 번호 `[1]` 은 유지한다.

## 끝나고 확인할 것

- 슬라이드가 정확히 **1장 늘었는지** (장단점 표가 두 개가 되지 않았는지)
- 새 슬라이드에 쪽번호가 있는지
- Reference 슬라이드에 GhostServe 인용이 들어갔는지
- 새로 쓴 문장이 음슴체·명사 종결인지, 영단어 뒤 조사가 붙어 있는지
  (`GhostServe 가` ✗ → `GhostServe가` ✓)
