# RADP gRPC Proto Reference

`radp.proto` 가 정의하는 **두 service + 15 RPC + message 필드** 의 운영자 가이드.

`radp.proto` 자체가 single-source-of-truth — 이 문서는 그 내용을 운영자 / 신규 기여자가 빠르게 훑기 위한 *사용처 매핑* 이다. proto 가 바뀌면 이 문서도 갱신.

---

## 한 줄 그림

```
[클라이언트] ──Generate──► [CoordinatorService]
                               ▲      │
                               │      │
                  Heartbeat, MirrorActivation, ResultReady
                               │      │
                               │      ▼
                          [WorkerService] × N 워커
                  LoadStage / RunStage / LoadBackup / PromoteBackup /
                  EvictRequest / Ping / MeasurePeer / ProfileLayers /
                  SetNextHop / LoadHead
```

방향: **Coord → Worker** RPC 가 11개 (워커가 servicer), **Worker / Client → Coord** RPC 가 4개 (코디가 servicer).

---

## WorkerService — 코디 → 워커 호출 (11 RPC)

### 1. 가중치 적재 / 추론 핵심

| RPC | Request 필드 | Response 필드 | 호출 시점 |
|---|---|---|---|
| **LoadStage** | `device_id, start_layer, end_layer, model_id` | `ok, error` | 부팅 시 coord 가 워커마다 1회. `start..end` 범위의 decoder block 가중치를 *primary 슬롯* 에 적재 |
| **RunStage** | `activation, request_id, is_prefill, start_layer, end_layer, position, replay_only, async_chain` | `activation, request_id, has_next_token, next_token_id` | **매 토큰마다** — 가장 빈번한 RPC. coord 가 chain head 에 1번 던지면 워커끼리 forward |
| **EvictRequest** | `request_id` | `ok` | 요청 종료 시 coord 가 모든 워커에 호출 → KV 캐시 정리 |

**RunStage 필드 풀이** (가장 dense, hot path):
- `activation` — serialized 텐서 payload (hidden state + 필요 시 attention mask)
- `is_prefill` — True = 프롬프트 전체 처리 (첫 step), False = decode token 1 개
- `start_layer / end_layer` — 워커가 *어느 stage* 를 실행할지 lookup key. 워커가 primary + 다수 backup 들고 있을 수 있어 명시 필요
- `position` — per-request step index. 0 = prefill, 1, 2, ... = decode 토큰 순서. `MirrorActivation` 의 ordering key 와 동일
- `replay_only` — 복구 시 *KV 캐시만 재건* + chain forward / head sampling 안 함
- `async_chain` — 동기/비동기 chain mode 토글. True 면 워커가 fire-and-forget

### 2. 복구 — backup peer 관리

| RPC | Request 필드 | Response 필드 | 호출 시점 |
|---|---|---|---|
| **LoadBackup** | `for_device_id, start_layer, end_layer, model_id` | `ok` | 부팅 시 coord 가 R 테이블에 따라 *백업 슬롯* 에 가중치 적재 (eager mode). `for_device_id` = 자신이 누구를 백업하는지 |
| **PromoteBackup** | `for_device_id` | `ok` | 장애 감지 시 coord 가 backup 보유자에게 호출 → primary 로 swap. 워커의 stage_runner 가 backup 슬롯을 primary 슬롯으로 옮기는 동작 |

### 3. 프로파일링 — 부팅 시 fleet 측정 (Phase D)

| RPC | Request 필드 | Response 필드 | 호출 시점 |
|---|---|---|---|
| **Ping** | `payload, sent_ns` | `payload (echo), sent_ns, echo_ns` | coord 가 각 워커에 *RTT 측정* — coord ↔ worker 네트워크 링크 추정 |
| **MeasurePeer** | `peer_address, payload_bytes, rounds` | `bandwidth_bps, latency_seconds, ok, error` | coord 가 워커 A 에게 *"워커 B 를 ping 해라"* 시킴. 워커 A 가 잠시 클라이언트가 되어 B 와 N round 측정 → bandwidth/latency 보고. **full-mesh (N×N) 네트워크 프로필** 용 |
| **ProfileLayers** | `model_id, warmup, repeats, seq_length` | `serialized_profiles (JSON), ok, error` | coord 가 각 워커에 *"이 모델로 self-profiling 해라"* 시킴. 워커가 임시로 모델 적재 → 레이어별 per-layer time 측정 → JSON 반환. **Auto-scheduling DP 의 입력** |

### 4. Chain topology routing (EXP-D3)

| RPC | Request 필드 | Response 필드 | 호출 시점 |
|---|---|---|---|
| **SetNextHop** | `next_address, start_layer, end_layer, next_start_layer, next_end_layer` | `ok, error` | coord 가 deploy / 복구 시 각 워커에 *"네 다음 워커는 X 야"* 알림. 빈 문자열 = chain tail. `(start, end)` 는 *내 stage* 의 lookup key, `next_*` 는 *다음 워커가 실행할 stage 범위* |
| **LoadHead** | `model_id` | `ok, error` | coord 가 tail 워커 (Path A) 또는 매니저 자신 (Path B) 에게 head module (final_layer_norm + lm_head) 적재. tail+head 면 sampling 까지 워커 측 |

---

## CoordinatorService — 워커 / 클라이언트 → 코디 호출 (4 RPC)

### 1. 클라이언트 facing

| RPC | Request 필드 | Response (streaming) 필드 | 호출 시점 |
|---|---|---|---|
| **Generate** | `prompt, max_tokens, temperature, top_k, top_p, eos_token_id, seed` | `text, done` (stream chunks) | 클라이언트 (사용자) 가 coord 에 호출. coord 가 전체 디코드 루프 + tokenizer 처리. Stream 으로 토큰 단위 텍스트 반환. `done=True` = EOS 또는 max_tokens 도달 |

### 2. 워커 → coord 신호

| RPC | Request 필드 | Response 필드 | 호출 시점 |
|---|---|---|---|
| **Heartbeat** | `device_id, free_memory_bytes, ts_ns, total_memory_bytes, device_class` | `ack` | 워커가 0.5s ~ 1s 마다 coord 에 *liveness + memory 상황* 보고. coord 가 *5s timeout* 안 답하는 워커 = dead 표시. Phase D 가 `total_memory_bytes`, `device_class` 추가해 *hot-swap 워커 감지* 가능 |
| **MirrorActivation** | `request_id, start_layer, end_layer, activation, is_prefill, position` | `ok` | **각 워커가 RunStage 실행 *직전* 에 단방향** (response 무시) 으로 호출. 들어온 activation 을 coord 에 보내 mirror cache 에 저장. chain 중간 워커 죽으면 coord 가 이 cache 로 backup 에 *replay* |
| **ResultReady** | `request_id, position, activation, has_next_token, next_token_id` | `ok` | **async chain mode 에서만**. chain tail 이 결과 만들고 *coord 에 직접* 호출 → coord 의 `(request_id, position)` Event 깨움. 동기에서 사라진 응답 채널의 대체 |

---

## Message 별 등장 시점 (life-of-a-request)

### 부팅 (코드 `deploy()`)

```
1. Worker startup → Heartbeat 시작 (정기적)
2. Coord 가 모든 worker 에 ProfileLayers + Ping/MeasurePeer 발사
   → fleet profile (per-layer time + N×N 네트워크) 수집
3. Coord 가 DP 풀어 placement Ψ + R 결정
4. Coord 가 모든 worker 에 LoadStage(자기 stage) + LoadBackup(R 의 백업) 발사
5. Coord 가 chain head/middle/tail 에 SetNextHop 발사
6. Coord 가 tail worker (또는 자기) 에 LoadHead 발사
```

### 한 요청의 평생 — 정상

```
Client → Generate(prompt) ──► Coord
                                │
                                ├─ tokenizer.encode(prompt) → input_ids
                                │
                                ├─ RunStage(activation, position=0, is_prefill=true) ──► Chain head
                                │                                          │
                                │      [Sync chain: response nested]      │ MirrorActivation (per stage)
                                │      [Async chain: ResultReady]         │ → coord
                                │                                          ▼
                                │      ← head/sampling 결과 (token_id)  Chain tail
                                │
                                ├─ tokenizer.decode([token_id]) → text
                                ├─ GenerateChunk(text=..., done=false) ──► Client (stream)
                                │
                                ├─ RunStage(activation, position=1, is_prefill=false) ──► ... (decode step)
                                │   ... (반복)
                                │
                                ├─ EOS 또는 max_tokens 도달
                                ├─ EvictRequest(request_id) ──► 모든 worker
                                └─ GenerateChunk(done=true) ──► Client
```

### 장애 발생 — sync chain

```
Worker M (mid-chain) 죽음
   │
   ├─ Worker M-1 의 RunStage(downstream) 가 RpcError ─┐
   │                                                  │
   │                          gRPC trailer 에 (M의 stage 범위) stamp
   │                                                  │
   ├─ Coord 의 _invoke 가 UNAVAILABLE 받음 ◄──────────┘
   │
   ├─ Coord: trailer 보고 R(M) = X 식별
   │
   ├─ PromoteBackup(for_device_id=M) ──► Worker X
   │
   ├─ SetNextHop(...) ──► Worker M-1, Worker X  (체인 재배선)
   │
   ├─ MirrorActivation cache 에서 (request_id, position) 의 활성화 꺼냄
   │
   ├─ RunStage(replay_only=true) ──► Worker X  (KV cache 재건)
   │
   └─ 정상 흐름 재개
```

### 장애 발생 — async chain

```
Worker M 죽음
   │
   ├─ Coord: 30s 안에 ResultReady 안 옴 → Event.wait() timeout
   │   OR  ◄─ 5s 안에 Heartbeat timeout (먼저 발생하는 쪽)
   │
   ├─ Coord: trailer 못 씀 → heartbeat 가 누구 죽었는지 알려줘야
   │   heartbeat 가 먼저 알면: M 식별 → R(M) = X
   │   heartbeat 가 race 지면: chain head 를 dead 로 임시 표시 → R(head) = Y
   │
   ├─ PromoteBackup + SetNextHop 같음
   │
   └─ MirrorActivation cache 에서 replay
```

---

## RPC 호출 빈도 매트릭스

| Service | RPC | 평시 호출 빈도 | Hot path? |
|---|---|---|---|
| WorkerService | LoadStage | 부팅 / 복구 시만 | |
| WorkerService | **RunStage** | **매 토큰** | ✅ |
| WorkerService | LoadBackup | 부팅 시만 | |
| WorkerService | PromoteBackup | 장애 시만 | |
| WorkerService | EvictRequest | 요청 종료 시 | |
| WorkerService | Ping | 부팅 시만 | |
| WorkerService | MeasurePeer | 부팅 시만 | |
| WorkerService | ProfileLayers | 부팅 시만 | |
| WorkerService | SetNextHop | 부팅 / 복구 시만 | |
| WorkerService | LoadHead | 부팅 시만 | |
| WorkerService | LoadStage | 부팅 시만 | |
| CoordinatorService | Generate | 요청 시 (1회 / stream) | |
| CoordinatorService | Heartbeat | **워커 × 1Hz** | ✅ |
| CoordinatorService | **MirrorActivation** | **매 stage × 매 토큰** | ✅ |
| CoordinatorService | **ResultReady** | **매 토큰 (async only)** | ✅ |

**Hot path RPC 4개**: RunStage, Heartbeat, MirrorActivation, ResultReady. 나머지는 부팅 또는 장애 시에만.

---

## 두 가지 path — head 어디에 두느냐

`LoadHead` 가 어디로 가는지에 따라 매 토큰의 *코디네이터로 가는 데이터 크기* 가 달라진다.

| | Path A (tail+head) | Path B (coord+head) |
|---|---|---|
| `LoadHead` 호출 대상 | tail 워커 | coord 자기 자신 |
| `RunStage` 응답에 채워지는 것 | `has_next_token=True, next_token_id=...` | `activation=...` (hidden state) |
| 매 토큰 매니저에 가는 데이터 | int64 (8 B) | hidden_dim × fp16 (~8 KB) |
| Sampling 위치 | tail 워커 | coord |

**Path A 가 default** — 네트워크 비용 1000× 가벼움. Path B 는 *tail 워커가 head 메모리 부족* 또는 *과도기 복구 단계* 에서 fallback.

---

## 변경 이력 매핑

| 필드 / RPC | 추가된 Phase | 동기 |
|---|---|---|
| `RunStage.position` | EXP-D3 Phase 2 | MirrorActivation ordering key |
| `RunStage.replay_only` | EXP-D3 Phase 3 | KV cache 재건 시 chain forward 안 함 |
| `RunStage.async_chain` | EXP-D3 Phase F | 비동기 체인 토글 |
| `RunStageResponse.has_next_token / next_token_id` | EXP-D3 Phase 1b | tail+head sampling |
| `HeartbeatRequest.total_memory_bytes / device_class` | Phase D0 | hot-swap 워커 감지 |
| `Ping / MeasurePeer / ProfileLayers` | Phase D0 | auto-scheduling 의 fleet profiling |
| `SetNextHop / LoadHead` | EXP-D3 Phase 1a / 1b | chain topology 도입 |
| `MirrorActivation` | EXP-D3 Phase 2 | chain mid-failure 의 replay 가능성 확보 |
| `ResultReady` | EXP-D3 Phase F | sync chain 의 응답 채널 대체 |
