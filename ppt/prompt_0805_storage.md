# 랩미팅 0805 델타 — "저장 차이는 per-token이라 실제론 MB~GB" 슬라이드 추가

`prompt_0805.md`로 만든 덱에 슬라이드 **한 장** 추가. 지난 미팅에서 교수님이 "byte~kB 차이면
절대적으로 큰 차이가 아니다"라고 하신 것에 대한 답.

- **넣는 자리:** KV-RAID-6 **비용·상한 슬라이드 바로 뒤**. (이후 슬라이드 번호는 하나씩 밀림)
- **그림 있음** — `fig_storage_scaling_models`. 이 그림은 **STASH 슬라이드에 이미 올려뒀으니**(덱을
  3-그림으로 다시 초기화함) 그 이미지를 이 슬라이드로 옮기고 STASH는 삭제.
- **계층·문체는 본 프롬프트 규칙 그대로**: `▸` = 불릿 없는 굵은 소주제, `-` = 그 아래 `•` 내용.
  음슴체·명사 종결, 숫자 유지, 잘 안 쓰는 말 금지.

---

**(비용·상한 뒤) KV-RAID-6 — 저장 차이는 진짜 작은가**
- **소제목(주장):** byte~kB는 토큰 1개당 값 — 실제 저장 차이는 context·모델 크기로 커져 MB~GB

▸ 지난 미팅 지적
- KV-RAID vs DejaVu 저장 차이가 byte~kB면 절대적으로 큰 차이 아님

▸ 그건 토큰 1개당 값이었음
- 그 차이는 **KV 토큰 1개당** 값임. 실제 저장 = (토큰당 차이) × (프롬프트 + 생성 토큰 수) × (모델 크기)
- 우리 fleet 실측 OPT-350M: 토큰 1개 **20 KB** → 2048 토큰 **40 MB** → 4096 토큰 **80 MB**

▸ 모델·context 커지면 GB급
- 시각물: **STASH의 fig_storage_scaling_models** — 가로 = context 길이, 세로 = 저장 차이(DejaVu − KV-RAID, 로그-로그), 선 = 모델 크기. 빨간 원 = 우리 실측 fleet 점(40 MB, head-heavy라 보수적 끝)
- 균형 파이프라인 기준: OPT-350M @4096 토큰 **230 MB**, OPT-13B @4096 토큰 **1.9 GB** — 모델 크고 context 길수록 벌어짐

---

## 발표자 노트용 (슬라이드엔 안 올림)

교수님 지적이 맞는 지점: **토큰 1개만 보면** byte~kB라 안 큼. 반박은 "그 값이 per-token이라 실제
워크로드(긴 context·큰 모델)에선 MB~GB로 커진다"임. 그림의 빨간 원(40 MB)은 실제 측정, 나머지
선은 모델 지오메트리로 계산(모델을 실제로 안 돌림 — 큰 모델은 fleet에 안 올라감). 출처:
`experiments/storage_scaling_models.py`, `paper/figures/fig_storage_scaling_models`, REPORT §B1-REPLICATE.
