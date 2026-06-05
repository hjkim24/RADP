"""Local FastAPI server that serves an interactive JSON browser for
`experiments/results/*.json`.

Run with:
    python -m experiments.results_browser            # default port 8090
    python -m experiments.results_browser --port 9000

Opens at http://localhost:8090/. The browser app is a single page with:

  * Left sidebar: list of result JSON files with detected shape + size
    + mtime. Click to load.
  * Main panel: shape-aware visualization:
      - "baseline" (single Generate run with per_request + scheduler)
        → TTFT / TBT distributions, throughput card, placement view
      - "failure_trials" (run_failure_remote N=K)
        → recovery latency bar per trial, per-token TBT trace,
          stage routing diff at recovery step
      - "a3b_cells" (run_a3_remote multi-baseline)
        → grouped bar chart of TBT p50/p95, throughput, failure outcome
      - "algorithmic" (run_algorithm sweep)
        → line chart of greedy vs ours over the swept axis
      - else → formatted JSON tree (collapsible)
  * Footer: raw JSON drawer (always available).

Shape detection is heuristic but covers every file we have today.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

RESULTS_DIR = Path(__file__).parent / "results"


# ---------------------------------------------------------------------------
# Shape detection — tells the frontend how to render
# ---------------------------------------------------------------------------
def detect_shape(payload: dict[str, Any]) -> str:
    """Return a coarse shape label the frontend uses to pick a renderer."""
    # algorithmic sweeps (run_algorithm output)
    if "scenario" in payload and "rows" in payload:
        return "algorithmic"
    # a3_baselines (algorithmic baseline comparison from sidecar)
    if "baselines" in payload and "source_sidecar" in payload:
        return "a3_baselines"
    # run_a3_remote (live multi-baseline)
    if "cells" in payload and isinstance(payload.get("cells"), list):
        return "a3b_cells"
    # run_failure_remote (multi-trial failure injection)
    if "trials" in payload and "aggregate" in payload:
        return "failure_trials"
    # single failure trial (run_failure_remote --trials 1 legacy)
    if "trial" in payload and "summary" in payload and "scheduler_before" in payload:
        return "failure_single"
    # run_e2e_remote baseline
    if "per_request" in payload and "scheduler" in payload:
        return "baseline"
    return "unknown"


def file_meta(path: Path) -> dict[str, Any]:
    """Quick metadata + shape detection for one file (without sending the
    full body)."""
    try:
        payload = json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        return {
            "name": path.name,
            "size": path.stat().st_size,
            "mtime": path.stat().st_mtime,
            "shape": "error",
            "error": str(e),
        }
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "mtime": path.stat().st_mtime,
        "shape": detect_shape(payload),
    }


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
INDEX_HTML = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>RADP — 실험 결과 브라우저</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0d1117; --panel: #161b22; --border: #30363d;
    --text: #c9d1d9; --muted: #8b949e; --accent: #58a6ff;
    --green: #56d364; --amber: #d29922; --red: #f85149;
    --grid: #21262d;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    font-size: 14px;
  }
  .app { display: grid; grid-template-columns: 280px 1fr; height: 100vh; }
  aside {
    border-right: 1px solid var(--border); overflow-y: auto;
    padding: 12px; background: var(--panel);
  }
  main { overflow-y: auto; padding: 20px 28px; }
  h1 { font-size: 16px; margin: 0 0 12px 0; color: var(--accent); }
  h2 { font-size: 14px; color: var(--muted); text-transform: uppercase;
        letter-spacing: 0.5px; margin-top: 24px; }
  h3 { font-size: 13px; color: var(--muted); margin: 16px 0 6px 0; }
  .file {
    padding: 8px 10px; border-radius: 4px; cursor: pointer; margin-bottom: 4px;
    border: 1px solid transparent;
  }
  .file:hover { background: rgba(88,166,255,0.08); }
  .file.active { background: rgba(88,166,255,0.15); border-color: var(--accent); }
  .file .name { font-family: ui-monospace, monospace; font-size: 12px; word-break: break-all; }
  .file .meta { font-size: 10px; color: var(--muted); margin-top: 2px; }
  .file .badge {
    display: inline-block; padding: 1px 6px; border-radius: 8px;
    font-size: 9px; font-weight: 600; text-transform: uppercase;
    margin-right: 4px;
  }
  .badge.baseline { background: rgba(86,211,100,0.15); color: var(--green); }
  .badge.failure_trials, .badge.failure_single { background: rgba(248,81,73,0.15); color: var(--red); }
  .badge.a3b_cells { background: rgba(88,166,255,0.15); color: var(--accent); }
  .badge.algorithmic, .badge.a3_baselines { background: rgba(210,153,34,0.15); color: var(--amber); }
  .badge.unknown, .badge.error { background: var(--border); color: var(--muted); }
  .panel {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 6px; padding: 14px 18px; margin-bottom: 16px;
  }
  .row { display: flex; gap: 12px; flex-wrap: wrap; }
  .row > * { flex: 1 1 240px; }
  .chart-wrap { position: relative; height: 280px; margin-top: 6px; }
  .chart-wrap.tall { height: 360px; }
  .metric { display: flex; justify-content: space-between; padding: 4px 0;
            border-bottom: 1px dashed var(--border); font-size: 13px; }
  .metric .k { color: var(--muted); }
  .metric .v { font-family: ui-monospace, monospace; font-weight: 600; }
  .big-num { font-size: 28px; font-weight: 700; color: var(--accent);
              font-family: ui-monospace, monospace; }
  .small-label { font-size: 11px; color: var(--muted); text-transform: uppercase;
                  letter-spacing: 0.5px; }
  .pill { display: inline-block; padding: 1px 8px; border-radius: 10px;
          font-size: 11px; font-weight: 600; }
  .pill.green { background: rgba(86,211,100,0.15); color: var(--green); }
  .pill.red { background: rgba(248,81,73,0.15); color: var(--red); }
  details { margin-top: 12px; }
  summary { cursor: pointer; color: var(--accent); font-size: 12px;
             user-select: none; }
  pre.json {
    background: var(--bg); border: 1px solid var(--border); padding: 12px;
    border-radius: 4px; overflow-x: auto; font-size: 11px;
    color: var(--muted); max-height: 400px;
  }
  pre.json .k { color: var(--accent); }
  pre.json .s { color: var(--green); }
  pre.json .n { color: var(--amber); }
  .placement {
    font-family: ui-monospace, monospace; font-size: 12px;
    background: var(--bg); padding: 8px; border-radius: 4px; margin: 4px 0;
  }
  .placement .dev { color: var(--accent); }
  .placement .rng { color: var(--muted); }
  .empty { color: var(--muted); padding: 40px; text-align: center; }
  table { border-collapse: collapse; width: 100%; font-size: 12px; margin-top: 6px; }
  th, td { padding: 4px 10px; text-align: left; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 600; font-size: 11px; }
  td.num { font-family: ui-monospace, monospace; text-align: right; }
</style>
</head>
<body>
<div class="app">

<aside>
  <h1>실험 결과</h1>
  <div id="file-list">loading…</div>
</aside>

<main id="main">
  <div class="empty">왼쪽에서 파일을 선택하세요.</div>
</main>

</div>

<script>
const FILES_URL = '/api/files';
const FILE_URL  = (name) => `/api/file/${encodeURIComponent(name)}`;

Chart.defaults.color = '#c9d1d9';
Chart.defaults.borderColor = '#30363d';

let currentChart = []; // 차트 인스턴스들 (떨어뜨릴 때 destroy)

function destroyCharts() {
  currentChart.forEach(c => c.destroy && c.destroy());
  currentChart = [];
}

function fmtSize(b) {
  if (b < 1024) return b + ' B';
  if (b < 1024*1024) return (b/1024).toFixed(1) + ' KB';
  return (b/1024/1024).toFixed(1) + ' MB';
}
function fmtTime(t) {
  const d = new Date(t * 1000);
  return d.toLocaleString('ko-KR', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
}

async function loadFileList() {
  const r = await fetch(FILES_URL);
  const files = await r.json();
  // 정렬: shape 분류 + 이름
  files.sort((a, b) => (b.mtime - a.mtime));
  const div = document.getElementById('file-list');
  div.innerHTML = '';
  for (const f of files) {
    const el = document.createElement('div');
    el.className = 'file';
    el.dataset.name = f.name;
    el.innerHTML = `
      <span class="badge ${f.shape}">${f.shape}</span>
      <div class="name">${f.name}</div>
      <div class="meta">${fmtSize(f.size)} · ${fmtTime(f.mtime)}</div>`;
    el.addEventListener('click', () => loadFile(f.name));
    div.appendChild(el);
  }
}

async function loadFile(name) {
  document.querySelectorAll('.file').forEach(e => e.classList.remove('active'));
  document.querySelector(`.file[data-name="${name}"]`)?.classList.add('active');
  const r = await fetch(FILE_URL(name));
  if (!r.ok) {
    document.getElementById('main').innerHTML = `<div class="empty">load failed: ${r.statusText}</div>`;
    return;
  }
  const payload = await r.json();
  destroyCharts();
  render(name, payload);
}

function render(name, p) {
  const main = document.getElementById('main');
  const shape = detectShape(p);
  const header = `<h1>${name} <span class="small-label" style="margin-left:8px">${shape}</span></h1>`;
  let body = '';
  if (shape === 'baseline')          body = renderBaseline(p);
  else if (shape === 'failure_trials') body = renderFailureTrials(p);
  else if (shape === 'failure_single') body = renderFailureSingle(p);
  else if (shape === 'a3b_cells')     body = renderA3bCells(p);
  else if (shape === 'algorithmic')   body = renderAlgorithmic(p);
  else if (shape === 'a3_baselines')  body = renderA3Baselines(p);
  else                                body = renderUnknown(p);
  body += renderRawJson(p, shape === 'unknown');
  main.innerHTML = header + body;
  // 차트들을 실제 렌더링 (DOM에 들어간 후 호출)
  if (shape === 'baseline')          mountBaseline(p);
  else if (shape === 'failure_trials') mountFailureTrials(p);
  else if (shape === 'failure_single') mountFailureSingle(p);
  else if (shape === 'a3b_cells')     mountA3bCells(p);
  else if (shape === 'algorithmic')   mountAlgorithmic(p);
  else if (shape === 'a3_baselines')  mountA3Baselines(p);
}

// 동일한 shape detection을 클라이언트에도 (서버가 잘못 분류해도 클라가 복구)
function detectShape(p) {
  if (p && p.scenario && p.rows) return 'algorithmic';
  if (p && p.baselines && p.source_sidecar) return 'a3_baselines';
  if (p && Array.isArray(p.cells)) return 'a3b_cells';
  if (p && p.trials && p.aggregate) return 'failure_trials';
  if (p && p.trial && p.summary && p.scheduler_before) return 'failure_single';
  if (p && p.per_request && p.scheduler) return 'baseline';
  return 'unknown';
}

// ===== BASELINE (run_e2e_remote) =====
function renderBaseline(p) {
  const ttft = p.ttft_seconds || {};
  const tbt = p.tbt_seconds || {};
  const tput = p.throughput_tokens_per_sec || {};
  const sched = p.scheduler || {};
  return `
    <div class="row">
      <div class="panel">
        <div class="small-label">TTFT p50</div>
        <div class="big-num">${(ttft.p50*1000).toFixed(0)} ms</div>
        <div class="metric"><span class="k">mean</span><span class="v">${(ttft.mean*1000).toFixed(0)}</span></div>
        <div class="metric"><span class="k">p95</span><span class="v">${(ttft.p95*1000).toFixed(0)}</span></div>
      </div>
      <div class="panel">
        <div class="small-label">TBT p50</div>
        <div class="big-num">${(tbt.p50*1000).toFixed(0)} ms</div>
        <div class="metric"><span class="k">mean</span><span class="v">${(tbt.mean*1000).toFixed(0)}</span></div>
        <div class="metric"><span class="k">p95</span><span class="v">${(tbt.p95*1000).toFixed(0)}</span></div>
        <div class="metric"><span class="k">p99</span><span class="v">${(tbt.p99*1000).toFixed(0)}</span></div>
        <div class="metric"><span class="k">n</span><span class="v">${tbt.count}</span></div>
      </div>
      <div class="panel">
        <div class="small-label">처리량</div>
        <div class="big-num">${tput.mean?.toFixed(2)} tok/s</div>
        <div class="metric"><span class="k">requests</span><span class="v">${p.n_requests}</span></div>
        <div class="metric"><span class="k">max_tokens</span><span class="v">${p.max_tokens}</span></div>
      </div>
    </div>
    <div class="panel"><h3>per-request TBT 분포</h3>
      <div class="chart-wrap"><canvas id="ch-baseline-tbt"></canvas></div>
    </div>
    ${renderPlacement(sched.placement, sched.recovery)}
  `;
}
function mountBaseline(p) {
  const tbts = (p.per_request || []).flatMap(r => r.tbt_seconds_each || []).map(t => t*1000);
  const bins = histogram(tbts, 20);
  currentChart.push(new Chart(document.getElementById('ch-baseline-tbt'), {
    type: 'bar',
    data: { labels: bins.labels, datasets: [{
      label: 'TBT (ms)', data: bins.counts,
      backgroundColor: 'rgba(88,166,255,0.5)', borderColor: '#58a6ff',
    }]},
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { x: { title: { display: true, text: 'TBT bin (ms)' }},
                y: { title: { display: true, text: '개수' }}}}
  }));
}

// ===== FAILURE_TRIALS (run_failure_remote N=K) =====
function renderFailureTrials(p) {
  const agg = p.aggregate || {};
  const rec = agg.recovery_step_seconds || {};
  const validN = (agg.n_valid || 0);
  return `
    <div class="row">
      <div class="panel">
        <div class="small-label">trial 결과 (N=${p.n_trials_requested})</div>
        <div class="big-num">${p.n_trials_completed}/${p.n_trials_requested}</div>
        <div class="metric"><span class="k">유효 trial</span><span class="v">${validN}</span></div>
        <div class="metric"><span class="k">victim</span><span class="v">${p.victim}</span></div>
      </div>
      <div class="panel">
        <div class="small-label">recovery step (ms)</div>
        <div class="big-num">${(rec.mean*1000).toFixed(0)}</div>
        <div class="metric"><span class="k">p50</span><span class="v">${(rec.p50*1000).toFixed(0)}</span></div>
        <div class="metric"><span class="k">p95</span><span class="v">${(rec.p95*1000).toFixed(0)}</span></div>
        <div class="metric"><span class="k">range</span><span class="v">${(rec.min*1000).toFixed(0)}-${(rec.max*1000).toFixed(0)}</span></div>
      </div>
    </div>
    <div class="panel"><h3>per-trial recovery latency</h3>
      <div class="chart-wrap"><canvas id="ch-recovery"></canvas></div>
    </div>
    <div class="panel"><h3>per-token TBT trace (trial 1)</h3>
      <div class="chart-wrap tall"><canvas id="ch-trace"></canvas></div>
    </div>
  `;
}
function mountFailureTrials(p) {
  const rec = (p.aggregate?.recovery_step_seconds?.values || []).map(v => v*1000);
  currentChart.push(new Chart(document.getElementById('ch-recovery'), {
    type: 'bar',
    data: { labels: rec.map((_,i)=>`trial ${i+1}`),
            datasets: [{ data: rec, backgroundColor: 'rgba(86,211,100,0.5)', borderColor:'#56d364'}]},
    options: { responsive: true, maintainAspectRatio: false, plugins:{legend:{display:false}},
      scales: { y: { title: { display: true, text: 'recovery step (ms)' }}}}
  }));
  const t0 = p.trials?.[0]?.trial;
  if (t0?.per_token) {
    const trace = t0.per_token.map(t => t.step_seconds*1000);
    const kill_at = t0.killed_at_token;
    currentChart.push(new Chart(document.getElementById('ch-trace'), {
      type: 'line',
      data: { labels: trace.map((_,i)=>i), datasets: [{
        label: 'TBT (ms)', data: trace,
        borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,0.1)',
        pointRadius: 2, tension: 0.1, fill: true,
      }]},
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false },
                   annotation: { annotations: { kill: {
                     type: 'line', xMin: kill_at, xMax: kill_at,
                     borderColor: '#f85149', borderWidth: 2, borderDash: [6,4]
                   }}}},
        scales: { x: { title: { display: true, text: '토큰 index' }},
                  y: { title: { display: true, text: 'TBT (ms)' }}}}
    }));
  }
}

// ===== FAILURE_SINGLE (legacy single trial) =====
function renderFailureSingle(p) {
  const s = p.summary || {};
  const ms = (v) => v ? (v*1000).toFixed(0) : '—';
  return `
    <div class="row">
      <div class="panel">
        <div class="small-label">recovery step</div>
        <div class="big-num">${ms(s.recovery_step_seconds)} ms</div>
        <div class="metric"><span class="k">spike vs pre p50</span><span class="v">+${ms(s.spike_over_pre_p50_seconds)} (${s.spike_factor?.toFixed(2)}x)</span></div>
        <div class="metric"><span class="k">pre p50</span><span class="v">${ms(s.pre_kill_tbt?.p50)} ms</span></div>
        <div class="metric"><span class="k">post p50</span><span class="v">${ms(s.post_recovery_tbt?.p50)} ms</span></div>
      </div>
      <div class="panel">
        <div class="small-label">victim</div>
        <div class="big-num">${p.trial?.victim || '?'}</div>
        <div class="metric"><span class="k">tokens emit</span><span class="v">${p.trial?.tokens_emitted}/${p.trial?.max_tokens_requested}</span></div>
        <div class="metric"><span class="k">in-flight</span><span class="v">${s.tokens_in_flight_during_kill}</span></div>
      </div>
    </div>
    <div class="panel"><h3>per-token TBT trace</h3>
      <div class="chart-wrap tall"><canvas id="ch-trace"></canvas></div>
    </div>
  `;
}
function mountFailureSingle(p) {
  const trace = (p.trial?.per_token || []).map(t => t.step_seconds*1000);
  const kill_at = p.trial?.killed_at_token;
  currentChart.push(new Chart(document.getElementById('ch-trace'), {
    type: 'line',
    data: { labels: trace.map((_,i)=>i), datasets: [{
      label: 'TBT (ms)', data: trace,
      borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,0.1)',
      pointRadius: 2, tension: 0.1, fill: true,
    }]},
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
                 annotation: { annotations: { kill: {
                   type: 'line', xMin: kill_at, xMax: kill_at,
                   borderColor: '#f85149', borderWidth: 2, borderDash: [6,4]
                 }}}},
      scales: { x: { title: { display: true, text: '토큰 index' }},
                y: { title: { display: true, text: 'TBT (ms)' }}}}
  }));
}

// ===== A3B_CELLS (run_a3_remote multi-baseline) =====
function renderA3bCells(p) {
  const rows = (p.cells || []).filter(c => !c.skipped).map(c => {
    const n = c.normal, f = c.failure;
    return {
      name: c.name,
      placement: c.placement,
      tbt_p50: n?.tbt_seconds?.p50*1000,
      tbt_p95: n?.tbt_seconds?.p95*1000,
      ttft_p50: n?.ttft_seconds?.p50*1000,
      throughput: n?.throughput_tokens_per_sec?.mean,
      catastrophic: f?.n_catastrophic || 0,
      graceful: f?.n_graceful || 0,
      n_trials: f?.n_trials || 0,
      recovery_mean: f?.aggregate?.recovery_step_seconds?.mean*1000,
      cat_tokens: f?.catastrophic_tokens_before_failure?.values || [],
    };
  });
  let placementSection = '';
  for (const r of rows) {
    placementSection += `<div class="placement"><strong>${r.name}:</strong> ` +
      r.placement.map(s => `<span class="dev">${s.device}</span><span class="rng">[${s.start}..${s.end}]</span>`).join(' ') +
      `</div>`;
  }
  return `
    <div class="panel"><h3>정상 운영 latency 비교</h3>
      <div class="chart-wrap"><canvas id="ch-a3b-tbt"></canvas></div>
    </div>
    <div class="row">
      <div class="panel"><h3>장애 시 outcome</h3>
        <table><thead><tr><th>baseline</th><th>kind</th><th>tokens / 60</th><th>recovery (ms)</th></tr></thead>
        <tbody>
        ${rows.map(r => `<tr>
          <td>${r.name}</td>
          <td>${r.catastrophic ? `<span class="pill red">catastrophic ${r.catastrophic}/${r.n_trials}</span>` : `<span class="pill green">graceful ${r.graceful}/${r.n_trials}</span>`}</td>
          <td class="num">${r.cat_tokens.length ? r.cat_tokens.join(', ') : '60/60'}</td>
          <td class="num">${r.recovery_mean ? r.recovery_mean.toFixed(0) : '—'}</td>
        </tr>`).join('')}
        </tbody></table>
      </div>
      <div class="panel"><h3>placement 비교</h3>
        ${placementSection}
      </div>
    </div>
  `;
}
function mountA3bCells(p) {
  const rows = (p.cells || []).filter(c => !c.skipped);
  const labels = rows.map(c => c.name);
  const palette = ['rgba(248,81,73,0.5)','rgba(210,153,34,0.5)','rgba(88,166,255,0.5)','rgba(86,211,100,0.5)'];
  currentChart.push(new Chart(document.getElementById('ch-a3b-tbt'), {
    type: 'bar',
    data: { labels, datasets: [
      { label: 'TBT p50 (ms)', data: rows.map(c => c.normal.tbt_seconds.p50*1000),
        backgroundColor: palette[2], borderColor: '#58a6ff' },
      { label: 'TBT p95 (ms)', data: rows.map(c => c.normal.tbt_seconds.p95*1000),
        backgroundColor: palette[1], borderColor: '#d29922' },
      { label: 'TTFT p50 (ms)', data: rows.map(c => c.normal.ttft_seconds.p50*1000),
        backgroundColor: palette[3], borderColor: '#56d364' },
    ]},
    options: { responsive: true, maintainAspectRatio: false,
      scales: { y: { title: { display: true, text: 'milliseconds' }}}}
  }));
}

// ===== A3_BASELINES (a3_baselines algorithmic) =====
function renderA3Baselines(p) {
  const bs = p.baselines || {};
  const rows = Object.entries(bs).map(([k,v]) => ({
    name: k,
    max_stage: v.max_stage_time_seconds*1000,
    n_stages: v.n_stages,
    feas_primary: v.feasibility?.primary_ok,
    feas_backup: v.feasibility?.with_backup_ok,
    placement: v.placement,
  })).filter(r => !isNaN(r.max_stage));
  return `
    <div class="panel"><h3>algorithm max_stage_time 비교 (예측)</h3>
      <div class="chart-wrap"><canvas id="ch-a3a"></canvas></div>
    </div>
    <div class="panel"><h3>baseline 상세</h3>
      <table><thead><tr><th>name</th><th>max_stage (ms)</th><th>stages</th><th>primary</th><th>+backup</th></tr></thead>
      <tbody>
      ${rows.map(r => `<tr>
        <td>${r.name}</td>
        <td class="num">${r.max_stage.toFixed(1)}</td>
        <td class="num">${r.n_stages}</td>
        <td>${r.feas_primary ? '✓' : '<span class="pill red">FAIL</span>'}</td>
        <td>${r.feas_backup ? '✓' : '<span class="pill red">FAIL</span>'}</td>
      </tr>`).join('')}
      </tbody></table>
    </div>
  `;
}
function mountA3Baselines(p) {
  const bs = p.baselines || {};
  const rows = Object.entries(bs).filter(([_,v]) => v.max_stage_time_seconds);
  currentChart.push(new Chart(document.getElementById('ch-a3a'), {
    type: 'bar',
    data: { labels: rows.map(([k,_])=>k),
            datasets: [{ label: 'max_stage_time (ms)',
              data: rows.map(([_,v]) => v.max_stage_time_seconds*1000),
              backgroundColor: 'rgba(88,166,255,0.5)', borderColor:'#58a6ff'}]},
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }},
      scales: { y: { title: { display: true, text: 'milliseconds (예측)' }}}}
  }));
}

// ===== ALGORITHMIC (run_algorithm) =====
function renderAlgorithmic(p) {
  const rows = p.rows || [];
  return `
    <div class="panel"><h3>${p.scenario} sweep</h3>
      <div class="chart-wrap"><canvas id="ch-alg"></canvas></div>
    </div>
    <div class="panel"><h3>row 상세</h3>
      <table><thead><tr>${Object.keys(rows[0] || {}).map(k => `<th>${k}</th>`).join('')}</tr></thead>
      <tbody>
      ${rows.map(r => '<tr>' + Object.values(r).map(v => `<td class="num">${typeof v === 'number' ? v.toFixed(4) : Array.isArray(v) ? '['+v.join(',')+']' : v}</td>`).join('') + '</tr>').join('')}
      </tbody></table>
    </div>
  `;
}
function mountAlgorithmic(p) {
  const rows = p.rows || [];
  // 첫 번째 numeric x axis 추측
  const keys = Object.keys(rows[0] || {});
  const xKey = keys.find(k => typeof rows[0][k] === 'number') || keys[0];
  const yKeys = keys.filter(k => k !== xKey && typeof rows[0][k] === 'number');
  const palette = ['#58a6ff','#56d364','#d29922','#f85149','#bc8cff'];
  currentChart.push(new Chart(document.getElementById('ch-alg'), {
    type: 'line',
    data: { labels: rows.map(r => r[xKey]),
            datasets: yKeys.map((k,i) => ({
              label: k, data: rows.map(r => r[k]),
              borderColor: palette[i % palette.length],
              backgroundColor: palette[i % palette.length] + '20',
              tension: 0.2,
            }))},
    options: { responsive: true, maintainAspectRatio: false,
      scales: { x: { title: { display: true, text: xKey }}}}
  }));
}

// ===== placement helper =====
function renderPlacement(placement, recovery) {
  if (!placement) return '';
  let html = '<div class="panel"><h3>placement</h3>';
  html += '<div class="placement">' + placement.map(s =>
    `<span class="dev">${s.device}</span><span class="rng">[${s.start}..${s.end}]</span>`).join(' ') + '</div>';
  if (recovery && Object.keys(recovery).length) {
    html += '<h3>recovery (j → backup k)</h3>';
    html += '<div class="placement">' + Object.entries(recovery).map(([j,k]) =>
      `<span class="dev">${j}</span><span class="rng">→</span><span class="dev">${k}</span>`).join('  ') + '</div>';
  }
  html += '</div>';
  return html;
}

// ===== unknown — top-level summary + JSON drawer auto-open =====
function renderUnknown(p) {
  if (!p || typeof p !== 'object') {
    return `<div class="panel"><div class="empty">스칼라 값: ${JSON.stringify(p)}</div></div>`;
  }
  const entries = Array.isArray(p)
    ? p.slice(0, 100).map((v, i) => [i, v])
    : Object.entries(p);
  let rows = '';
  for (const [k, v] of entries) {
    let typeLabel = typeof v;
    let preview = '';
    if (v === null) { typeLabel = 'null'; preview = '—'; }
    else if (Array.isArray(v)) {
      typeLabel = `array[${v.length}]`;
      preview = v.length === 0 ? '[]'
        : typeof v[0] === 'object' ? `[${typeof v[0]} × ${v.length}]`
        : JSON.stringify(v.slice(0, 5)) + (v.length > 5 ? ' …' : '');
    }
    else if (typeof v === 'object') {
      typeLabel = `object`;
      preview = `keys: ${Object.keys(v).slice(0, 6).join(', ')}${Object.keys(v).length > 6 ? ' …' : ''}`;
    }
    else if (typeof v === 'number') {
      typeLabel = 'number';
      preview = String(v);
    }
    else { preview = String(v).slice(0, 80); }
    rows += `<tr><td><code>${escapeHtml(String(k))}</code></td>
                 <td><span class="small-label">${typeLabel}</span></td>
                 <td><code style="color:var(--muted);font-size:11px">${escapeHtml(preview)}</code></td></tr>`;
  }
  return `<div class="panel">
    <div class="small-label">알 수 없는 형태 — top-level 키 목록</div>
    <table style="margin-top:6px"><thead><tr><th>키</th><th>타입</th><th>미리보기</th></tr></thead>
      <tbody>${rows}</tbody></table>
    <div class="empty" style="padding:8px;margin-top:8px;font-size:12px">
      원시 JSON drawer가 아래에 자동으로 펼쳐져 있습니다.
    </div>
  </div>`;
}

// ===== raw JSON drawer =====
function renderRawJson(p, openByDefault) {
  const json = JSON.stringify(p, null, 2);
  return `<details ${openByDefault ? 'open' : ''}><summary>원시 JSON (${(json.length/1024).toFixed(1)} KB)</summary>
    <pre class="json">${escapeHtml(json)}</pre></details>`;
}
function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ===== histogram helper =====
function histogram(values, nBins) {
  if (!values.length) return { labels: [], counts: [] };
  const min = Math.min(...values), max = Math.max(...values);
  const w = (max - min) / nBins || 1;
  const counts = new Array(nBins).fill(0);
  for (const v of values) {
    const i = Math.min(nBins-1, Math.floor((v - min) / w));
    counts[i]++;
  }
  const labels = counts.map((_, i) => `${(min + i*w).toFixed(0)}`);
  return { labels, counts };
}

loadFileList();
</script>
</body>
</html>
"""


def make_app() -> FastAPI:
    app = FastAPI(title="RADP 실험 결과 브라우저", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.get("/api/files")
    def list_files() -> list[dict[str, Any]]:
        if not RESULTS_DIR.exists():
            return []
        out = []
        for p in sorted(RESULTS_DIR.glob("*.json")):
            out.append(file_meta(p))
        return out

    @app.get("/api/file/{name}")
    def get_file(name: str) -> JSONResponse:
        # path traversal 방어
        if "/" in name or ".." in name or not name.endswith(".json"):
            raise HTTPException(status_code=400, detail="invalid file name")
        path = RESULTS_DIR / name
        if not path.exists():
            raise HTTPException(status_code=404, detail="file not found")
        # Some result files contain NaN / Infinity (statistics.fmean over an
        # empty list returns NaN, _percentile too). Python's json.loads parses
        # them, but FastAPI's JSONResponse uses strict json.dumps that
        # rejects non-finite floats. Sanitize before sending.
        payload = json.loads(path.read_text())
        return JSONResponse(_sanitize(payload))

    return app


def _sanitize(obj: Any) -> Any:
    """Recursively replace NaN/Infinity floats with None for JSON
    compliance (strict json.dumps rejects them)."""
    import math
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    print(f"results browser: http://{args.host}:{args.port}/")
    print(f"  serving {RESULTS_DIR}")
    uvicorn.run(make_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
