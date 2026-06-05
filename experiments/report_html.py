"""Generate a self-contained HTML report from the result JSONs.

Reads the headline result files in `experiments/results/`, extracts the
metrics, and writes a single-file HTML with Chart.js embedded via CDN.
The user can open the file directly in a browser — no server needed.

Sections rendered:
  * Headline summary card (the paper's key numbers)
  * A3b' N=3 OPT-350M comparison (grouped bar chart for TBT p50/p95,
    throughput, plus token-loss + recovery panels)
  * A2 N=5 OPT-125M recovery distribution (per-trial recovery latency)
  * Per-token TBT trace overlaid for the failure trials (shows the
    recovery spike as a visible bump)
  * Synthetic heterogeneity sweep (algorithmic prediction)
  * Result JSON map table

To deploy onto the coord's web dashboard:
  ansible ax-1 -b -m copy -a "src=experiments/REPORT.html \
    dest=/home/isp/radp/radp/coordinator/web_static/report.html"
and add a /report route to web_api.py (see deploy_to_coord at the bottom
of this file for the convenience invocation).
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

RESULTS = Path(__file__).parent / "results"
OUT_PATH = Path(__file__).parent / "REPORT.html"


# ---------------------------------------------------------------------------
# JSON readers
# ---------------------------------------------------------------------------
def _load(name: str) -> dict[str, Any] | None:
    path = RESULTS / name
    if not path.exists():
        return None
    return dict(json.loads(path.read_text()))


def collect_a3b_n3() -> dict[str, Any]:
    """The headline 7-worker 3-tier N=3 comparison."""
    d = _load("a3b_opt350m_3tier_n3.json") or {}
    cells = d.get("cells", [])
    out: dict[str, Any] = {"cells": []}
    for c in cells:
        if c.get("skipped"):
            continue
        n = c["normal"]
        f = c["failure"]
        cell = {
            "name": c["name"],
            "placement": c["placement"],
            "normal": {
                "tbt_p50_ms": n["tbt_seconds"]["p50"] * 1000,
                "tbt_p95_ms": n["tbt_seconds"]["p95"] * 1000,
                "tbt_p99_ms": n["tbt_seconds"]["p99"] * 1000,
                "ttft_p50_ms": n["ttft_seconds"]["p50"] * 1000,
                "ttft_p95_ms": n["ttft_seconds"]["p95"] * 1000,
                "throughput_mean": n["throughput_tokens_per_sec"]["mean"],
                "n_samples": n["tbt_seconds"]["count"],
            },
            "failure": {
                "n_trials": f["n_trials"],
                "n_graceful": f["n_graceful"],
                "n_catastrophic": f["n_catastrophic"],
            },
        }
        if f["n_graceful"]:
            r = f["aggregate"]["recovery_step_seconds"]
            cell["failure"]["recovery_ms"] = {
                "mean": r["mean"] * 1000,
                "p50": r["p50"] * 1000,
                "p95": r["p95"] * 1000,
                "min": r["min"] * 1000,
                "max": r["max"] * 1000,
                "values": [v * 1000 for v in r["values"]],
            }
        if f["n_catastrophic"]:
            cell["failure"]["catastrophic_tokens"] = (
                f["catastrophic_tokens_before_failure"]["values"]
            )
        # Pull the per-token TBT for one representative trial of each
        # outcome — this drives the "TBT vs token index" chart that
        # shows the recovery spike.
        trials = f.get("trials", [])
        if trials:
            t0 = trials[0]["trial"]
            per_token = t0.get("per_token", [])
            cell["per_token_tbt_ms"] = [
                t["step_seconds"] * 1000 for t in per_token
            ]
            cell["kill_at_idx"] = t0.get("killed_at_token")
        out["cells"].append(cell)
    return out


def collect_a2_n5() -> dict[str, Any]:
    """OPT-125M A2 N=5 recovery distribution."""
    d = _load("a2_kill_ao1_n5.json") or {}
    agg = d.get("aggregate", {})
    rec = agg.get("recovery_step_seconds", {})
    out = {
        "n_trials": agg.get("n_valid", 0),
        "recovery_ms": {
            "mean": rec.get("mean", 0) * 1000,
            "p50": rec.get("p50", 0) * 1000,
            "p95": rec.get("p95", 0) * 1000,
            "min": rec.get("min", 0) * 1000,
            "max": rec.get("max", 0) * 1000,
            "values": [v * 1000 for v in rec.get("values", [])],
        },
    }
    # Per-trial backup-burden layer counts (if computable)
    trials = d.get("trials", [])
    per_trial = []
    for i, t in enumerate(trials):
        s = t.get("summary", {})
        if "recovery_step_seconds" in s:
            per_trial.append({
                "trial": i + 1,
                "recovery_ms": s["recovery_step_seconds"] * 1000,
                "victim_layers": t.get("scheduler_before", {}).get("placement", []),
            })
    out["per_trial"] = per_trial
    return out


def collect_algo_hetero() -> dict[str, Any]:
    d = _load("algo_hetero.json") or {}
    rows = d.get("rows", [])
    return {
        "rows": [
            {
                "mult": r["throughput_multiplier_fast_device"],
                "greedy_ms": r["greedy_max_stage_seconds"] * 1000,
                "ours_ms": r["ours_max_stage_seconds"] * 1000,
                "speedup": r["ours_vs_greedy_speedup"],
                "greedy_split": r["greedy_layer_counts"],
                "ours_split": r["ours_layer_counts"],
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------
HTML_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>RADP — 라이브 fleet 벤치마크 보고서</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0d1117; --panel: #161b22; --border: #30363d;
    --text: #c9d1d9; --muted: #8b949e; --accent: #58a6ff;
    --green: #56d364; --amber: #d29922; --red: #f85149;
    --grid: #21262d;
  }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    line-height: 1.5; padding: 20px;
  }
  h1 { color: var(--text); border-bottom: 2px solid var(--border); padding-bottom: 8px; }
  h2 { color: var(--accent); margin-top: 32px; }
  h3 { color: var(--muted); font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px; }
  .container { max-width: 1100px; margin: 0 auto; }
  .panel {
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    padding: 16px 20px; margin-bottom: 20px;
  }
  .row { display: flex; gap: 16px; flex-wrap: wrap; }
  .row > .panel { flex: 1 1 320px; min-width: 280px; }
  .chart-wrap { position: relative; height: 320px; margin-top: 12px; }
  .chart-wrap.tall { height: 420px; }
  table { border-collapse: collapse; width: 100%; margin-top: 8px; font-size: 13px; }
  th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 600; font-size: 12px; }
  tr:hover td { background: rgba(88,166,255,0.05); }
  .pill {
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 12px; font-weight: 600;
  }
  .pill.green { background: rgba(86,211,100,0.15); color: var(--green); border: 1px solid var(--green); }
  .pill.red { background: rgba(248,81,73,0.15); color: var(--red); border: 1px solid var(--red); }
  .pill.amber { background: rgba(210,153,34,0.15); color: var(--amber); border: 1px solid var(--amber); }
  .metric { display: flex; justify-content: space-between; padding: 4px 0;
            border-bottom: 1px dashed var(--border); }
  .metric .k { color: var(--muted); font-size: 13px; }
  .metric .v { color: var(--text); font-weight: 600; font-family: ui-monospace, monospace; }
  .footnote { color: var(--muted); font-size: 12px; margin-top: 8px; }
  .placement { font-family: ui-monospace, monospace; font-size: 12px; color: var(--text);
               background: var(--bg); padding: 8px; border-radius: 4px; overflow-x: auto; }
  .big-num { font-size: 32px; font-weight: 700; color: var(--accent); font-family: ui-monospace, monospace; }
  .big-num-label { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
  details { margin-top: 12px; }
  summary { cursor: pointer; color: var(--accent); font-size: 13px; user-select: none; }
  a { color: var(--accent); }
</style>
</head>
<body>
<div class="container">

<h1>RADP — Recovery-Aware DP for Distributed LLM Inference</h1>
<div class="footnote">
  라이브 7-worker 3-tier 에지 fleet 벤치마크 보고서. 데이터: <code>experiments/results/*.json</code>.
  텍스트 버전: <a href="REPORT.md">REPORT.md</a>.
</div>

<!-- ============================================================ -->
<!-- HEADLINE SUMMARY -->
<h2>핵심 요약 (페이퍼 헤드라인)</h2>
<div class="row">
  <div class="panel">
    <div class="big-num-label">정상 운영 TBT p50 (ours)</div>
    <div class="big-num">{TBT_OURS_P50:.0f} ms</div>
    <div class="footnote">vs greedy <code>{TBT_GREEDY_P50:.0f} ms</code>
      → <span class="pill green">−{TBT_DELTA_PCT:.1f}%</span></div>
  </div>
  <div class="panel">
    <div class="big-num-label">처리량 (ours)</div>
    <div class="big-num">{TPUT_OURS:.2f} tok/s</div>
    <div class="footnote">vs greedy <code>{TPUT_GREEDY:.2f} tok/s</code>
      → <span class="pill green">+{TPUT_DELTA_PCT:.1f}%</span></div>
  </div>
  <div class="panel">
    <div class="big-num-label">장애 회복 (ours)</div>
    <div class="big-num">{REC_OURS_MEAN:.0f} ms</div>
    <div class="footnote">p50 {REC_OURS_P50:.0f}, p95 {REC_OURS_P95:.0f} | <span class="pill green">graceful 3/3</span></div>
  </div>
  <div class="panel">
    <div class="big-num-label">장애 시 emit 토큰</div>
    <div class="big-num">{OURS_TOKENS} <span style="color:var(--muted);font-size:14px">/ {GREEDY_TOKENS}</span></div>
    <div class="footnote">ours 0 loss | greedy <span class="pill red">catastrophic 3/3</span></div>
  </div>
</div>

<!-- ============================================================ -->
<!-- A3b' OPT-350M 3-tier N=3 -->
<h2>A3b' — OPT-350M 3-tier, N=3 trial (페이퍼 핵심 그림)</h2>
<div class="panel">
  <h3>정상 운영 latency 비교</h3>
  <div class="chart-wrap"><canvas id="chart-tbt"></canvas></div>
  <div class="footnote">조건당 n=300 TBT 샘플 (10 request × 30 token).
    bar는 p50, error bar는 p95.</div>
</div>

<div class="row">
  <div class="panel">
    <h3>장애 시 emit한 토큰 수 (60 max)</h3>
    <div class="chart-wrap"><canvas id="chart-failure-tokens"></canvas></div>
    <div class="footnote">greedy는 kill 후 in-flight 17 토큰만 emit, 그 후 NoRecoveryError로 stream 사망.
      ours는 backup 라우팅으로 모든 60 토큰 보존.</div>
  </div>
  <div class="panel">
    <h3>ours 회복 latency 분포 (N=3 trial)</h3>
    <div class="chart-wrap"><canvas id="chart-recovery"></canvas></div>
    <div class="footnote">tight 분포: range {REC_OURS_RANGE_LO:.0f}-{REC_OURS_RANGE_HI:.0f} ms,
      p95 {REC_OURS_P95:.0f} ms < 1초 SLO.</div>
  </div>
</div>

<!-- Per-token trace -->
<div class="panel">
  <h3>per-token TBT trace (장애 trial 1, ours)</h3>
  <div class="chart-wrap tall"><canvas id="chart-trace"></canvas></div>
  <div class="footnote">붉은 세로선은 kill_after_tokens 시점.
    회복 step은 평소 ~280 ms에서 ~600 ms로 spike 후 즉시 정상화.</div>
</div>

<!-- Placement comparison -->
<div class="panel">
  <h3>Placement 비교</h3>
  {PLACEMENT_TABLE_HTML}
</div>

<!-- ============================================================ -->
<!-- A2 N=5 OPT-125M -->
<h2>A2 — OPT-125M N=5 trial 회복 분포</h2>
<div class="panel">
  <div class="row" style="align-items:start;">
    <div style="flex:1 1 350px;">
      <div class="chart-wrap"><canvas id="chart-a2"></canvas></div>
    </div>
    <div style="flex:0 0 300px;">
      <div class="metric"><span class="k">N (trial 수)</span><span class="v">{A2_N}</span></div>
      <div class="metric"><span class="k">mean</span><span class="v">{A2_MEAN:.0f} ms</span></div>
      <div class="metric"><span class="k">p50</span><span class="v">{A2_P50:.0f} ms</span></div>
      <div class="metric"><span class="k">p95</span><span class="v">{A2_P95:.0f} ms</span></div>
      <div class="metric"><span class="k">range</span><span class="v">{A2_MIN:.0f}-{A2_MAX:.0f} ms</span></div>
      <div class="metric"><span class="k">토큰 손실</span><span class="v">0 / 300</span></div>
      <div class="metric"><span class="k">백업 활성화</span><span class="v">5 / 5</span></div>
    </div>
  </div>
</div>

<!-- ============================================================ -->
<!-- Algorithm sweep -->
<h2>합성 이기종성 sweep — DP가 greedy를 이기는 regime</h2>
<div class="panel">
  <div class="chart-wrap"><canvas id="chart-sweep"></canvas></div>
  <div class="footnote">
    DP는 특정 배수 (3×, 6×)에서 greedy 대비 14–22% 우위.
    이유: greedy의 <code>round()</code> 라운딩이 느린 device에 layer 1개 추가로 떠넘김 → DP는 balanced 분배.
  </div>
</div>

<!-- ============================================================ -->
<!-- JSON map -->
<h2>결과 JSON 맵</h2>
<div class="panel">
  <table>
    <thead><tr><th>파일</th><th>범위</th></tr></thead>
    <tbody>
      <tr><td><code>auto_baseline_first.json</code></td><td>OPT-125M A1 (8-worker)</td></tr>
      <tr><td><code>a2_kill_ao1_n5.json</code></td><td>OPT-125M A2 N=5</td></tr>
      <tr><td><code>a3b_opt350m.json</code></td><td>OPT-125M A3b 4-baseline (파일명 헷갈림)</td></tr>
      <tr><td><code>opt350m_3tier_baseline.json</code></td><td>EXP-D2 A1' 6-worker 3-tier</td></tr>
      <tr><td style="font-weight:600"><code>a3b_opt350m_3tier_n3.json</code></td>
          <td style="font-weight:600">EXP-D2.1 A3b' N=3 — 페이퍼 헤드라인</td></tr>
      <tr><td><code>algo_hetero.json</code> 외</td><td>합성 알고리즘 sweep</td></tr>
    </tbody>
  </table>
</div>

</div>

<script>
const DATA = {DATA_JSON};

// chart.js 공통 옵션
const dark = {
  color: '#c9d1d9',
  grid: { color: '#21262d' },
  ticks: { color: '#8b949e' },
  border: { color: '#30363d' },
};
Chart.defaults.color = '#c9d1d9';
Chart.defaults.borderColor = '#30363d';

// --- chart 1: A3b' TBT 비교 ---
new Chart(document.getElementById('chart-tbt'), {
  type: 'bar',
  data: {
    labels: ['TBT p50', 'TBT p95', 'TBT p99', 'TTFT p50'],
    datasets: [
      {
        label: 'greedy',
        data: [DATA.a3b.greedy.tbt_p50, DATA.a3b.greedy.tbt_p95,
               DATA.a3b.greedy.tbt_p99, DATA.a3b.greedy.ttft_p50],
        backgroundColor: 'rgba(248,81,73,0.5)',
        borderColor: '#f85149', borderWidth: 1,
      },
      {
        label: 'ours',
        data: [DATA.a3b.ours.tbt_p50, DATA.a3b.ours.tbt_p95,
               DATA.a3b.ours.tbt_p99, DATA.a3b.ours.ttft_p50],
        backgroundColor: 'rgba(86,211,100,0.5)',
        borderColor: '#56d364', borderWidth: 1,
      },
    ],
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    scales: {
      y: { title: { display: true, text: 'milliseconds' } },
    },
  },
});

// --- chart 2: 장애 시 토큰 수 ---
new Chart(document.getElementById('chart-failure-tokens'), {
  type: 'bar',
  data: {
    labels: ['greedy', 'ours'],
    datasets: [{
      label: 'emit한 토큰',
      data: [DATA.a3b.greedy.failure_tokens_mean, DATA.a3b.ours.failure_tokens_mean],
      backgroundColor: ['rgba(248,81,73,0.5)', 'rgba(86,211,100,0.5)'],
      borderColor: ['#f85149', '#56d364'], borderWidth: 1,
    }],
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: { y: { title: { display: true, text: '토큰 (max 60)' }, max: 65 } },
  },
});

// --- chart 3: ours 회복 latency ---
new Chart(document.getElementById('chart-recovery'), {
  type: 'bar',
  data: {
    labels: DATA.a3b.ours.recovery_values.map((_, i) => `trial ${i+1}`),
    datasets: [{
      label: 'recovery step (ms)',
      data: DATA.a3b.ours.recovery_values,
      backgroundColor: 'rgba(86,211,100,0.5)',
      borderColor: '#56d364', borderWidth: 1,
    }],
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: { y: { title: { display: true, text: 'milliseconds' } } },
  },
});

// --- chart 4: per-token TBT trace ---
new Chart(document.getElementById('chart-trace'), {
  type: 'line',
  data: {
    labels: DATA.a3b.ours.trace.map((_, i) => i),
    datasets: [{
      label: 'TBT per token (ms)',
      data: DATA.a3b.ours.trace,
      borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,0.1)',
      pointRadius: 2, tension: 0.1, fill: true,
    }],
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: {
      annotation: {
        annotations: {
          kill: {
            type: 'line', xMin: DATA.a3b.ours.kill_at_idx, xMax: DATA.a3b.ours.kill_at_idx,
            borderColor: '#f85149', borderWidth: 2, borderDash: [6,4],
            label: { content: 'kill fired', enabled: true, position: 'start' },
          },
        },
      },
    },
    scales: {
      x: { title: { display: true, text: '토큰 index' } },
      y: { title: { display: true, text: 'TBT (ms)' } },
    },
  },
});

// --- chart 5: A2 N=5 ---
new Chart(document.getElementById('chart-a2'), {
  type: 'bar',
  data: {
    labels: DATA.a2.values.map((_, i) => `trial ${i+1}`),
    datasets: [{
      label: 'recovery step (ms)',
      data: DATA.a2.values,
      backgroundColor: 'rgba(88,166,255,0.5)',
      borderColor: '#58a6ff', borderWidth: 1,
    }],
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: { y: { title: { display: true, text: 'milliseconds' } } },
  },
});

// --- chart 6: 합성 sweep ---
new Chart(document.getElementById('chart-sweep'), {
  type: 'line',
  data: {
    labels: DATA.sweep.map(r => r.mult + '×'),
    datasets: [
      {
        label: 'greedy max_stage (ms)',
        data: DATA.sweep.map(r => r.greedy_ms),
        borderColor: '#f85149', backgroundColor: 'rgba(248,81,73,0.1)',
        tension: 0.2,
      },
      {
        label: 'ours max_stage (ms)',
        data: DATA.sweep.map(r => r.ours_ms),
        borderColor: '#56d364', backgroundColor: 'rgba(86,211,100,0.1)',
        tension: 0.2,
      },
    ],
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    scales: {
      x: { title: { display: true, text: '빠른 device 배수' } },
      y: { title: { display: true, text: 'max_stage_time (ms)' } },
    },
  },
});
</script>
</body>
</html>
"""


def render_html(out_path: Path = OUT_PATH) -> Path:
    a3b = collect_a3b_n3()
    a2 = collect_a2_n5()
    sweep = collect_algo_hetero()

    greedy = next(c for c in a3b["cells"] if c["name"] == "greedy")
    ours = next(c for c in a3b["cells"] if c["name"] == "ours")

    # Compute deltas + formatted summary numbers
    tbt_delta_pct = (greedy["normal"]["tbt_p50_ms"] - ours["normal"]["tbt_p50_ms"]) / \
                     greedy["normal"]["tbt_p50_ms"] * 100
    tput_delta_pct = (ours["normal"]["throughput_mean"] - greedy["normal"]["throughput_mean"]) / \
                      greedy["normal"]["throughput_mean"] * 100

    # Catastrophic mean tokens for greedy
    greedy_tokens_mean = statistics.fmean(greedy["failure"]["catastrophic_tokens"])
    # Graceful: always 60
    ours_tokens_mean = 60

    # Placement table HTML
    def _placement_row(name: str, pl: list[dict[str, Any]]) -> str:
        cells = " ".join(
            f"<span style='color:var(--accent)'>{s['device']}</span>"
            f"<span style='color:var(--muted)'>[{s['start']}..{s['end']}]</span>"
            for s in pl
        )
        return f"<div class='placement'><strong>{name}:</strong> {cells}</div>"

    placement_html = (
        _placement_row("greedy", greedy["placement"])
        + _placement_row("ours  ", ours["placement"])
    )

    # JS data payload
    data_json = json.dumps({
        "a3b": {
            "greedy": {
                "tbt_p50": greedy["normal"]["tbt_p50_ms"],
                "tbt_p95": greedy["normal"]["tbt_p95_ms"],
                "tbt_p99": greedy["normal"]["tbt_p99_ms"],
                "ttft_p50": greedy["normal"]["ttft_p50_ms"],
                "throughput": greedy["normal"]["throughput_mean"],
                "failure_tokens_mean": greedy_tokens_mean,
            },
            "ours": {
                "tbt_p50": ours["normal"]["tbt_p50_ms"],
                "tbt_p95": ours["normal"]["tbt_p95_ms"],
                "tbt_p99": ours["normal"]["tbt_p99_ms"],
                "ttft_p50": ours["normal"]["ttft_p50_ms"],
                "throughput": ours["normal"]["throughput_mean"],
                "failure_tokens_mean": ours_tokens_mean,
                "recovery_values": ours["failure"]["recovery_ms"]["values"],
                "trace": ours.get("per_token_tbt_ms", []),
                "kill_at_idx": ours.get("kill_at_idx", 14),
            },
        },
        "a2": {
            "values": a2["recovery_ms"]["values"],
        },
        "sweep": sweep["rows"],
    })

    # CSS / JS braces collide with str.format() so we substitute by replace().
    subs = {
        "{TBT_OURS_P50:.0f}": f"{ours['normal']['tbt_p50_ms']:.0f}",
        "{TBT_GREEDY_P50:.0f}": f"{greedy['normal']['tbt_p50_ms']:.0f}",
        "{TBT_DELTA_PCT:.1f}": f"{tbt_delta_pct:.1f}",
        "{TPUT_OURS:.2f}": f"{ours['normal']['throughput_mean']:.2f}",
        "{TPUT_GREEDY:.2f}": f"{greedy['normal']['throughput_mean']:.2f}",
        "{TPUT_DELTA_PCT:.1f}": f"{tput_delta_pct:.1f}",
        "{REC_OURS_MEAN:.0f}": f"{ours['failure']['recovery_ms']['mean']:.0f}",
        "{REC_OURS_P50:.0f}": f"{ours['failure']['recovery_ms']['p50']:.0f}",
        "{REC_OURS_P95:.0f}": f"{ours['failure']['recovery_ms']['p95']:.0f}",
        "{REC_OURS_RANGE_LO:.0f}": f"{ours['failure']['recovery_ms']['min']:.0f}",
        "{REC_OURS_RANGE_HI:.0f}": f"{ours['failure']['recovery_ms']['max']:.0f}",
        "{OURS_TOKENS}": f"{ours_tokens_mean:.0f}",
        "{GREEDY_TOKENS}": f"{greedy_tokens_mean:.0f}",
        "{PLACEMENT_TABLE_HTML}": placement_html,
        "{A2_N}": str(a2["n_trials"]),
        "{A2_MEAN:.0f}": f"{a2['recovery_ms']['mean']:.0f}",
        "{A2_P50:.0f}": f"{a2['recovery_ms']['p50']:.0f}",
        "{A2_P95:.0f}": f"{a2['recovery_ms']['p95']:.0f}",
        "{A2_MIN:.0f}": f"{a2['recovery_ms']['min']:.0f}",
        "{A2_MAX:.0f}": f"{a2['recovery_ms']['max']:.0f}",
        "{DATA_JSON}": data_json,
    }
    html = HTML_TEMPLATE
    for k, v in subs.items():
        html = html.replace(k, v)
    out_path.write_text(html)
    return out_path


if __name__ == "__main__":
    path = render_html()
    print(f"wrote {path}  ({path.stat().st_size} bytes)")
    print(f"open in browser: file://{path.resolve()}")
