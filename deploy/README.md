# RADP fleet deployment (Ansible + systemd)

`ansible-playbook` 한 줄로 N개의 Jetson Nano + 1개의 코디네이터 호스트에 RADP를 설치/실행. 런타임 오버헤드는 0 (k8s 같은 daemon 없음); systemd가 부팅 시 자동 시작 + 프로세스 죽으면 재시작 담당. 노드 통째로 죽었을 때의 추론 복구는 RADP 자체 Phase 3 메커니즘이 처리.

## 한 번만 (당신 노트북/맥에서)

```bash
brew install ansible          # 또는 pipx install --include-deps ansible
cd deploy/
cp inventory.ini.example inventory.ini   && $EDITOR inventory.ini
cp group_vars/all.yml.example group_vars/all.yml  && $EDITOR group_vars/all.yml
```

`inventory.ini`에 각 Jetson의 IP + `device_id`, 코디네이터 호스트 1개를 채워 넣습니다. `group_vars/all.yml`에서:
- `jetson_torch_wheel_url`: NVIDIA 인덱스에서 본인 JetPack 버전 wheel URL (예시는 파일에 주석)
- `model_id`, `model_dtype`, `model_torch_device`
- `schedule_mode`: 아래 참고
- (manual 모드 한정) `cluster_placement`, `cluster_recovery`

## 스케줄링 모드 (Phase D3)

| Mode | 동작 | yaml에 적는 것 |
|---|---|---|
| `auto` (권장) | 코디네이터가 부팅 시 모든 워커에 `ProfileLayers` + 워커-워커 `MeasurePeer`를 돌려 layer/network/device profile을 수집 → Recovery-Aware DP로 Ψ + R 자동 결정 | `schedule_mode: auto` + `slo_*` + `profiling_*` 변수만. `cluster_placement`/`cluster_recovery`는 무시됨 (생략 가능) |
| `manual` | 사용자가 적은 placement/recovery를 그대로 LoadStage | `schedule_mode: manual` + `cluster_placement` + `cluster_recovery` (둘 다 필수) |

auto 모드 부팅 시 코디네이터 로그에 다음이 순서대로 찍힘:
```
coordinator listening on 0.0.0.0:50050 (schedule_mode=auto)
auto-scheduling: waiting for 5 workers (timeout=60s)
all 5 workers heartbeated: ['jetson-1', ..., 'jetson-5']
auto-scheduling: profiling layers (facebook/opt-125m)
layer profiles merged: 12 layers, 5 devices
auto-scheduling: profiling network
network profile built: 20/20 pairs successful
auto-scheduling: solving DP (devices=5, layers=12)
auto-scheduling: solution max_stage_time=0.0820s converged=True iterations=2
  placement: jetson-1 ← layers[1..3]
  ...
  recovery:  jetson-1 → jetson-2 (backup)
  ...
deploying placement to 5 workers
```

## 배포

```bash
ansible-playbook playbook.yml
```

처음 실행은 수 분~수십 분 (torch wheel + radp + transformers 다운로드). 끝나면 모든 워커가 `systemctl status radp-worker`, 코디네이터가 `systemctl status radp-coordinator`로 떠 있어야 함.

확인:
```bash
# 모든 워커 상태 한꺼번에
ansible workers -a "systemctl status radp-worker --no-pager"

# 코디네이터 로그
ansible coordinator -a "journalctl -u radp-coordinator -n 50 --no-pager"

# end-to-end smoke (당신 노트북에서)
python -c "
from radp.common.protocol import CoordinatorClient
with CoordinatorClient('<COORD_IP>:50050') as c:
    print(''.join(c.generate('The quick brown fox', max_tokens=5)))
"
```

## 자주 쓰는 flag

```bash
# 코드만 업데이트 (서비스 재시작 포함)
ansible-playbook playbook.yml --tags update

# cluster.yaml만 다시 렌더 + 코디네이터 재시작 (placement / recovery 변경 시)
ansible-playbook playbook.yml --tags config

# 한 보드만 빼고
ansible-playbook playbook.yml --limit '!jetson-2'

# 한 보드만
ansible-playbook playbook.yml --limit jetson-1

# 무엇이 바뀔지만 미리 보기
ansible-playbook playbook.yml --check --diff

# 서비스 재시작만 (코드/설정 안 건드림)
ansible workers     -a "systemctl restart radp-worker"   --become
ansible coordinator -a "systemctl restart radp-coordinator" --become
```

## 디렉터리 구성

```
deploy/
├── ansible.cfg                       # SSH 옵션 + inventory 위치 + forks
├── inventory.ini.example             # 사용자가 채우는 호스트 목록
├── playbook.yml                      # 진입점 (3개 play: common, workers, coordinator)
├── group_vars/
│   └── all.yml.example               # 모델·placement·R·메모리·heartbeat 등 모든 변수
└── roles/
    ├── common/                       # 모든 노드 공통: 패키지, 코드 sync, venv, torch, radp install, proto
    │   └── tasks/main.yml
    ├── radp-worker/                  # 워커 노드: systemd unit 렌더 + enable + start
    │   ├── tasks/main.yml
    │   ├── handlers/main.yml         # 'restart radp-worker'
    │   └── templates/radp-worker.service.j2
    └── radp-coordinator/             # 코디네이터: /etc/radp/cluster.yaml 렌더 + systemd unit + 시작
        ├── tasks/main.yml
        ├── handlers/main.yml
        └── templates/
            ├── radp-coordinator.service.j2
            └── cluster.yaml.j2
```

## 책임 분담

| 계층 | 도구 | 역할 |
|---|---|---|
| 배포/설정 (1회성) | Ansible (이 디렉터리) | OS 셋업, 코드 sync, systemd unit 설치, cluster.yaml 렌더 |
| 프로세스 라이프사이클 | systemd | 부팅 시 자동 시작, 죽으면 `Restart=on-failure` |
| 분산 추론 + 장애 복구 | RADP (Phase 3) | heartbeat / activation cache replay / R-기반 라우팅 |

Ansible은 `playbook.yml` 실행 시점에만 동작; 끝나면 사라짐. 런타임 오케스트레이션은 systemd + RADP 자체가 담당.

## JetPack / PyTorch wheel 가이드

NVIDIA가 빌드한 ARM64 PyTorch wheel을 써야 CUDA가 작동합니다. `pip install torch`는 CPU-only로 떨어지거나 실패.

| JetPack | Python | 권장 wheel | 인덱스 |
|---|---|---|---|
| 6.x | 3.10 | torch 2.3.0+ | https://developer.download.nvidia.com/compute/redist/jp/v60/pytorch/ |
| 5.x | 3.8 | torch 2.0–2.1 | https://developer.download.nvidia.com/compute/redist/jp/v51/pytorch/ |
| 4.x | 3.6 | torch 1.10 max | (Python 3.6은 RADP 지원 범위 밖) |

JetPack 5는 Python 3.8이라 `pyproject.toml`의 `requires-python = ">=3.10"`을 만족 못함. JetPack 6 이상 권장. JetPack 5에서 강행하려면 pyenv로 Python 3.10 별도 설치 + venv를 그쪽 Python으로 만들도록 playbook 수정 필요.

## 한 보드 추가

1. `inventory.ini`의 `[workers]` 섹션에 한 줄 추가
2. `group_vars/all.yml`의 `cluster_placement`, `cluster_recovery` 갱신
3. `ansible-playbook playbook.yml --limit <새-호스트>` (또는 전체)
4. `ansible-playbook playbook.yml --tags config --limit coordinator` (cluster.yaml 재렌더 + 코디네이터 재시작)

## 보드 한 대 빼기

1. `ansible <빼는-호스트> -a "systemctl stop radp-worker"` --become
2. `inventory.ini` + `group_vars/all.yml`에서 제거
3. `ansible-playbook playbook.yml --tags config --limit coordinator`

## 트러블슈팅

| 증상 | 진단 / 해결 |
|---|---|
| `Python interpreter not found` | inventory.ini의 `ansible_python_interpreter` 조정 (기본 `/usr/bin/python3`) |
| 워커 service 못 뜸 → `journalctl -u radp-worker` 보니 `import torch` 실패 | `jetson_torch_wheel_url` 미설정 또는 wheel과 JetPack 버전 불일치 |
| 코디네이터가 워커 못 찾음 | `inventory.ini`의 `ansible_host` IP가 외부에서 접근 가능한지 확인. 방화벽 (`sudo ufw allow 50050,50051/tcp`) |
| heartbeat timeout 잦음 | 네트워크 지연 또는 시간 동기 어긋남. 모든 노드 `timedatectl set-ntp on` 확인 |
| 모델 다운로드 매번 반복 | `HF_HOME`이 디스크 캐시. NFS 공유 마운트면 한 보드만 다운로드하면 됨 |
