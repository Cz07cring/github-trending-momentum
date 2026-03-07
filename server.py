"""FastAPI 服务：动量雷达 Web 看板"""

import threading
from dataclasses import asdict
from datetime import datetime

import yaml
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from analyzer.momentum import MomentumAnalyzer
from storage.database import Database

app = FastAPI(title="GitHub Trending 动量雷达")

_config: dict = {}
_db: Database | None = None


def _get_db() -> Database:
    assert _db is not None
    return _db


# ── API ──────────────────────────────────────────────────────────────────────

@app.get("/api/momentum")
def api_momentum(all: bool = False):
    db = _get_db()
    mcfg = _config.get("momentum", {})
    cfg = dict(mcfg)
    if all:
        cfg["ai_only"] = False
    analyzer = MomentumAnalyzer(db, config=cfg)
    top_n = cfg.get("top_n", 10)
    ai_only = cfg.get("ai_only", True)
    results = analyzer.analyze_all(ai_only=ai_only, top_n=top_n)
    return [asdict(r) for r in results]


@app.get("/api/trending")
def api_trending():
    db = _get_db()
    rows = db.get_latest_round_snapshot()
    rows_sorted = sorted(rows, key=lambda x: x.get("today_stars", 0), reverse=True)[:30]
    return rows_sorted


@app.get("/api/scrape")
def api_scrape():
    """触发一次后台抓取（非阻塞）"""
    def _scrape():
        import time
        from scraper.trending import fetch_trending
        db = _get_db()
        languages = _config.get("languages", [""])
        since = _config.get("since", "daily")
        for lang in languages:
            repos = fetch_trending(language=lang, since=since)
            if repos:
                db.save_snapshot(repos, language_filter=lang, since=since)
            if lang != languages[-1]:
                time.sleep(2)

    t = threading.Thread(target=_scrape, daemon=True)
    t.start()
    return {"status": "started", "time": datetime.now().isoformat()}


# ── 前端页面 ──────────────────────────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>GitHub Trending 动量雷达</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #0d1117; --surface: #161b22; --border: #30363d;
      --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    }
    body { background: var(--bg); color: var(--text); font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; font-size: 14px; line-height: 1.6; }
    a { color: var(--accent); text-decoration: none; } a:hover { text-decoration: underline; }
    .container { max-width: 980px; margin: 0 auto; padding: 24px 16px; }

    /* Header */
    .header { display:flex; align-items:center; justify-content:space-between; margin-bottom:28px; padding-bottom:16px; border-bottom:1px solid var(--border); }
    .header h1 { font-size:20px; font-weight:600; }
    .header h1 span { color: var(--accent); }
    .header-right { display:flex; align-items:center; gap:12px; }
    .meta { color:var(--muted); font-size:12px; text-align:right; }
    .btn { padding:6px 14px; border-radius:6px; border:1px solid var(--border); background:var(--surface); color:var(--text); cursor:pointer; font-size:13px; transition:.15s; }
    .btn:hover { border-color:var(--accent); color:var(--accent); }
    .btn:disabled { opacity:.5; cursor:default; }
    .dot { width:8px; height:8px; border-radius:50%; background:#3fb950; display:inline-block; margin-right:6px; animation:pulse 2s infinite; }
    .dot.idle { background:var(--muted); animation:none; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }

    /* Tabs */
    .tabs { display:flex; gap:4px; margin-bottom:20px; border-bottom:1px solid var(--border); }
    .tab { padding:8px 16px; cursor:pointer; font-size:14px; color:var(--muted); border-bottom:2px solid transparent; margin-bottom:-1px; transition:.15s; }
    .tab.active { color:var(--accent); border-bottom-color:var(--accent); }

    /* Filter */
    .toolbar { display:flex; align-items:center; gap:12px; margin-bottom:16px; }
    .filter-btn { padding:4px 12px; border-radius:12px; border:1px solid var(--border); background:transparent; color:var(--muted); cursor:pointer; font-size:12px; transition:.15s; }
    .filter-btn.active { border-color:var(--accent); color:var(--accent); background:rgba(88,166,255,.08); }

    /* Cards */
    .cards { display:flex; flex-direction:column; gap:14px; }
    .card { background:var(--surface); border:1px solid var(--border); border-radius:8px; display:flex; overflow:hidden; transition:border-color .2s; }
    .card:hover { border-color:var(--accent); }
    .card-rank { width:48px; display:flex; align-items:center; justify-content:center; font-size:18px; font-weight:700; color:var(--muted); background:rgba(255,255,255,.02); flex-shrink:0; }
    .card-body { flex:1; padding:14px 16px; min-width:0; }
    .card-top { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:10px; }
    .repo-info { flex:1; min-width:0; }
    .repo-name { font-size:15px; font-weight:600; }
    .tags { display:flex; flex-wrap:wrap; gap:5px; margin:5px 0; }
    .tag { padding:2px 8px; border-radius:12px; font-size:11px; font-weight:500; }
    .desc { color:var(--muted); font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .score-box { text-align:center; flex-shrink:0; }
    .score-value { font-size:20px; font-weight:700; color:#f0b90b; }
    .score-label { font-size:11px; color:var(--muted); }

    /* Stats */
    .stats-row { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:12px; font-size:12px; }
    .stat { display:flex; align-items:center; gap:4px; }
    .stat-green { color:#3fb950; }
    .stat-muted { color:var(--muted); }
    .lang-dot::before { content:''; display:inline-block; width:9px; height:9px; border-radius:50%; background:var(--lc,#8b949e); margin-right:4px; vertical-align:middle; }

    /* Factors */
    .factors { display:grid; grid-template-columns:1fr 1fr; gap:6px 20px; }
    .factor-header { display:flex; justify-content:space-between; font-size:11px; margin-bottom:2px; }
    .factor-label { color:var(--muted); }
    .factor-val { font-weight:600; font-family:monospace; }
    .factor-track { height:3px; background:rgba(255,255,255,.07); border-radius:2px; overflow:hidden; }
    .factor-fill { height:100%; border-radius:2px; }

    /* Table */
    .table-wrap { overflow-x:auto; }
    table { width:100%; border-collapse:collapse; }
    th { text-align:left; padding:8px 12px; font-size:12px; color:var(--muted); border-bottom:1px solid var(--border); font-weight:500; }
    td { padding:9px 12px; border-bottom:1px solid rgba(48,54,61,.5); vertical-align:middle; }
    tr:hover td { background:rgba(255,255,255,.02); }
    .rank-cell { color:var(--muted); font-size:12px; width:36px; }
    .num-right { text-align:right; font-family:monospace; white-space:nowrap; }
    .repo-link { font-weight:500; }
    .sub { color:var(--muted); font-size:11px; display:block; }
    .text-green { color:#3fb950; }
    .text-muted { color:var(--muted); }

    /* Empty / Loading */
    .placeholder { text-align:center; padding:60px 0; color:var(--muted); }
    .spinner { width:32px; height:32px; border:3px solid var(--border); border-top-color:var(--accent); border-radius:50%; animation:spin .7s linear infinite; margin:0 auto 12px; }
    @keyframes spin { to { transform:rotate(360deg); } }

    /* Section title */
    .section-title { font-size:15px; font-weight:600; margin-bottom:14px; display:flex; align-items:center; gap:8px; }
    .section-title::before { content:''; display:block; width:3px; height:15px; background:var(--accent); border-radius:2px; }
  </style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>GitHub Trending <span>动量雷达</span></h1>
    <div class="header-right">
      <span id="status-dot" class="dot idle"></span>
      <div class="meta" id="last-update">未加载</div>
      <button class="btn" id="scrape-btn" onclick="triggerScrape()">抓取</button>
      <button class="btn" id="refresh-btn" onclick="loadAll()">刷新</button>
    </div>
  </div>

  <div class="tabs">
    <div class="tab active" onclick="switchTab('momentum', this)">🚀 AI 动量排行</div>
    <div class="tab" onclick="switchTab('trending', this)">📈 今日 Trending</div>
  </div>

  <!-- Momentum Tab -->
  <div id="tab-momentum">
    <div class="toolbar">
      <button class="filter-btn active" id="filter-ai" onclick="setFilter(true, this)">仅 AI 项目</button>
      <button class="filter-btn" id="filter-all" onclick="setFilter(false, this)">全部项目</button>
    </div>
    <div id="momentum-container"><div class="placeholder"><div class="spinner"></div>加载中...</div></div>
  </div>

  <!-- Trending Tab -->
  <div id="tab-trending" style="display:none">
    <div id="trending-container"><div class="placeholder"><div class="spinner"></div>加载中...</div></div>
  </div>
</div>

<script>
const LANG_COLORS = {
  Python:'#3572A5', JavaScript:'#f1e05a', TypeScript:'#3178c6',
  Rust:'#dea584', Go:'#00ADD8', Java:'#b07219', 'C++':'#f34b7d',
  C:'#555555', 'C#':'#178600', Ruby:'#701516', Swift:'#F05138',
  Kotlin:'#A97BFF', Shell:'#89e051', 'Jupyter Notebook':'#DA5B0B',
};
const TAG_COLORS = {
  '强势爆发': ['rgba(255,107,53,.15)','#ff6b35'],
  '加速中':   ['rgba(240,185,11,.15)','#f0b90b'],
  '量能翻倍': ['rgba(88,166,255,.15)','#58a6ff'],
  '刚上榜':   ['rgba(63,185,80,.15)','#3fb950'],
  '今日上榜': ['rgba(63,185,80,.10)','#3fb950'],
  '近3天上榜':['rgba(63,185,80,.07)','#7ee787'],
};

let aiOnly = true;
let currentTab = 'momentum';
let refreshTimer = null;

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function fmtStars(n) { return n >= 1000 ? (n/1000).toFixed(1)+'k' : String(n); }
function fmtHours(h) {
  if (h < 0) return '未知';
  if (h < 1) return Math.round(h*60)+'分钟前';
  if (h < 24) return Math.round(h)+'小时前';
  return (h/24).toFixed(1)+'天前';
}
function pct(v, scale=100) { return Math.min(Math.abs(v)*scale, 100).toFixed(1); }

function renderTags(tags) {
  return (tags||[]).map(t => {
    const [bg,fg] = TAG_COLORS[t] || ['rgba(139,148,158,.15)','#8b949e'];
    return `<span class="tag" style="background:${bg};color:${fg}">${esc(t)}</span>`;
  }).join('');
}

function renderFactor(label, value, color, isPct=true) {
  const display = isPct ? (value>=0?'+':'')+( value*100).toFixed(2)+'%' : value.toFixed(2);
  const fill = isPct ? pct(value) : Math.min(value*100,100).toFixed(1);
  const c = value >= 0 ? color : '#f85149';
  return `<div>
    <div class="factor-header">
      <span class="factor-label">${label}</span>
      <span class="factor-val" style="color:${c}">${display}</span>
    </div>
    <div class="factor-track"><div class="factor-fill" style="width:${fill}%;background:${c}"></div></div>
  </div>`;
}

function renderCard(r, rank) {
  const lc = LANG_COLORS[r.language] || '#8b949e';
  const ageStr = r.repo_age_days >= 0 ? `建仓 ${r.repo_age_days} 天` : '';
  const seenStr = fmtHours(r.first_seen_hours);
  return `
  <div class="card">
    <div class="card-rank">#${rank}</div>
    <div class="card-body">
      <div class="card-top">
        <div class="repo-info">
          <a class="repo-name" href="${esc(r.url)}" target="_blank">${esc(r.repo_full_name)}</a>
          <div class="tags">${renderTags(r.tags)}</div>
          <div class="desc">${esc((r.description||'暂无描述').slice(0,100))}</div>
        </div>
        <div class="score-box">
          <div class="score-value">${r.composite_score.toFixed(4)}</div>
          <div class="score-label">综合得分</div>
        </div>
      </div>
      <div class="stats-row">
        <span class="stat">⭐ ${fmtStars(r.total_stars)} <span class="stat-green">+${r.today_stars} today</span></span>
        ${r.language ? `<span class="stat lang-dot" style="--lc:${lc}">${esc(r.language)}</span>` : ''}
        <span class="stat stat-muted">首次上榜: ${seenStr}</span>
        ${ageStr ? `<span class="stat stat-muted">${ageStr}</span>` : ''}
        <span class="stat stat-muted">${r.snapshot_count} 个快照 · ${r.hours_tracked}h</span>
      </div>
      <div class="factors">
        ${renderFactor('价格动量', r.momentum, '#58a6ff')}
        ${renderFactor('增速动量', r.delta_momentum, '#3fb950')}
        ${renderFactor('量能突破', r.volume_surge, '#bc8cff')}
        ${renderFactor('新鲜度', r.freshness, '#f0b90b', false)}
      </div>
    </div>
  </div>`;
}

function renderMomentum(data) {
  if (!data.length) {
    return '<div class="placeholder">暂无足够数据（需要 ≥2 次快照才能计算动量）<br><small>请先点击「抓取」收集数据</small></div>';
  }
  return `<div class="cards">${data.map((r,i) => renderCard(r, i+1)).join('')}</div>`;
}

function renderTrending(data) {
  if (!data.length) {
    return '<div class="placeholder">暂无数据，请先点击「抓取」</div>';
  }
  const rows = data.map((r, i) => {
    const lc = LANG_COLORS[r.language] || '#8b949e';
    return `<tr>
      <td class="rank-cell">#${i+1}</td>
      <td>
        <a class="repo-link" href="https://github.com/${esc(r.repo_full_name)}" target="_blank">${esc(r.repo_full_name)}</a>
        <span class="sub">${esc((r.description||'').slice(0,70))}</span>
      </td>
      <td class="num-right text-muted">⭐ ${fmtStars(r.total_stars)}</td>
      <td class="num-right text-green">+${r.today_stars}</td>
      <td>${r.language ? `<span class="lang-dot" style="--lc:${lc}">${esc(r.language)}</span>` : '—'}</td>
    </tr>`;
  }).join('');
  return `<div class="table-wrap">
    <table>
      <thead><tr><th></th><th>仓库</th><th style="text-align:right">Stars</th><th style="text-align:right">Today +</th><th>语言</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

async function loadMomentum() {
  const container = document.getElementById('momentum-container');
  try {
    const res = await fetch(`/api/momentum?all=${!aiOnly}`);
    const data = await res.json();
    container.innerHTML = renderMomentum(data);
  } catch(e) {
    container.innerHTML = `<div class="placeholder">加载失败: ${e.message}</div>`;
  }
}

async function loadTrending() {
  const container = document.getElementById('trending-container');
  try {
    const res = await fetch('/api/trending');
    const data = await res.json();
    container.innerHTML = renderTrending(data);
  } catch(e) {
    container.innerHTML = `<div class="placeholder">加载失败: ${e.message}</div>`;
  }
}

async function loadAll() {
  document.getElementById('status-dot').className = 'dot';
  document.getElementById('refresh-btn').disabled = true;
  await Promise.all([loadMomentum(), loadTrending()]);
  const now = new Date().toLocaleString('zh-CN');
  document.getElementById('last-update').textContent = `更新: ${now}`;
  document.getElementById('status-dot').className = 'dot idle';
  document.getElementById('refresh-btn').disabled = false;
}

async function triggerScrape() {
  const btn = document.getElementById('scrape-btn');
  btn.disabled = true;
  btn.textContent = '抓取中...';
  document.getElementById('status-dot').className = 'dot';
  try {
    await fetch('/api/scrape');
    // 等待约 30 秒后自动刷新（抓取是异步的）
    setTimeout(() => {
      loadAll();
      btn.disabled = false;
      btn.textContent = '抓取';
    }, 30000);
  } catch(e) {
    btn.disabled = false;
    btn.textContent = '抓取';
  }
}

function setFilter(ai, el) {
  aiOnly = ai;
  document.getElementById('filter-ai').classList.toggle('active', ai);
  document.getElementById('filter-all').classList.toggle('active', !ai);
  loadMomentum();
}

function switchTab(tab, el) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('tab-momentum').style.display = tab === 'momentum' ? '' : 'none';
  document.getElementById('tab-trending').style.display = tab === 'trending' ? '' : 'none';
}

// 初始加载，之后每 5 分钟自动刷新
loadAll();
setInterval(loadAll, 5 * 60 * 1000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return _HTML


# ── 启动入口 ──────────────────────────────────────────────────────────────────

def serve(config_path: str = "config.yaml", host: str = "0.0.0.0", port: int = 8000):
    global _config, _db
    with open(config_path, "r", encoding="utf-8") as f:
        _config = yaml.safe_load(f)
    _db = Database(_config.get("database_path", "data/github_trending.db"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    serve(args.config, args.host, args.port)
