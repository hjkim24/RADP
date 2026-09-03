# Paper figures (IEEE IoT-J, black and white)

`make_*.py`와 공용 `_paper.py`로 생성한다. 기본값은 논문 메인인 OPT-6.7B이고,
`RADP_FIG_MODEL=350m`을 지정하면 `_350m.pdf` microscopy 버전을 만든다.

```sh
for f in paper/figures/paper/make_*.py; do .venv/bin/python "$f"; done
```

| Figure | Default 7B source | Evaluation use |
|---|---|---|
| `fig_recovery_latency.pdf` | `b1_ft_fleet_7b.json`, `b1_ft_fleet_7b_part2.json`, `b1_ft_fleet_7b_reactive_log_20260901.json` | recovery latency versus failure position; Reconfigure is points+median, no slope |
| `fig_recovery_pareto.pdf` | same latency files + `b1_storage_7b.json` | latency at P=32 versus retained state; Reconfigure uses its valid-position median |
| `fig_storage_tolerance.pdf` | measured 7B placement geometry, non-head layers 4/4/4/7/7 | k-parity versus replication; crossover `sum/max=3.71`; only k=1,2 implemented |
| `fig_protection_cost.pdf` | `b1_steady_7b_n3.json` | failure-free throughput/TBT cost, interleaved N=3 |

`fig_storage_scaling.pdf`는 모델별 projection 대신 원고의 measured two-scale table을 사용하면서 본문에서 제거됐다.
350M의 30.3초 double-parity 결과는 concentrated-backup artifact를 설명하는 보조 결과이며 메인 figure로 그리지 않는다.
KV-State Fidelity와 Recovery Feasibility는 각각 표로 보고한다; D2.9의 7B 원자료는
`d29_coupling_threshold_20260902.json`에 저장돼 있다.

결과 JSON은 `experiments/results/` 아래의 gitignored 로컬 파일이다. figure PDF는 Overleaf에 추적되지만,
생성 스크립트는 Overleaf 작업 트리에서 제외된다.
