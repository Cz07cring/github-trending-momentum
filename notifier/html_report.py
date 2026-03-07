"""生成独立 HTML 报告"""

from __future__ import annotations

import html
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analyzer.momentum import MomentumResult
    from analyzer.trend import RepoScore


_LANG_COLORS: dict[str, str] = {
    "Python": "#3572A5",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "Rust": "#dea584",
    "Go": "#00ADD8",
    "Java": "#b07219",
    "C++": "#f34b7d",
    "C": "#555555",
    "C#": "#178600",
    "Ruby": "#701516",
    "Swift": "#F05138",
    "Kotlin": "#A97BFF",
    "Scala": "#c22d40",
    "Shell": "#89e051",
    "Jupyter Notebook": "#DA5B0B",
}


def _lang_color(lang: str) -> str:
    return _LANG_COLORS.get(lang, "#8b949e")


def _esc(text: str) -> str:
    return html.escape(str(text or ""))


def _format_stars(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _format_hours(hours: float) -> str:
    if hours < 0:
        return "未知"
    if hours < 1:
        return f"{hours * 60:.0f} 分钟前"
    if hours < 24:
        return f"{hours:.0f} 小时前"
    return f"{hours / 24:.1f} 天前"


def _factor_bar(value: float, label: str, color: str, fmt: str = "+.1%") -> str:
    """渲染单个因子进度条"""
    display = f"{value:{fmt}}" if fmt else f"{value:.2f}"
    # 将因子值映射到 0-100% 宽度（正向因子）
    pct = min(max(abs(value) * 100, 0), 100) if "%" in fmt else min(value * 100, 100)
    bar_color = color if value >= 0 else "#f85149"
    return f"""
        <div class="factor">
          <div class="factor-header">
            <span class="factor-label">{label}</span>
            <span class="factor-value" style="color:{bar_color}">{display}</span>
          </div>
          <div class="factor-track">
            <div class="factor-fill" style="width:{pct:.1f}%;background:{bar_color}"></div>
          </div>
        </div>"""


def _tag_html(tags: list[str]) -> str:
    colors = {
        "强势爆发": ("rgba(255,107,53,.15)", "#ff6b35"),
        "加速中":   ("rgba(240,185,11,.15)", "#f0b90b"),
        "量能翻倍": ("rgba(88,166,255,.15)", "#58a6ff"),
        "刚上榜":   ("rgba(63,185,80,.15)",  "#3fb950"),
        "今日上榜": ("rgba(63,185,80,.10)",  "#3fb950"),
        "近3天上榜":("rgba(63,185,80,.07)", "#7ee787"),
    }
    parts = []
    for t in tags:
        bg, fg = colors.get(t, ("rgba(139,148,158,.15)", "#8b949e"))
        parts.append(f'<span class="tag" style="background:{bg};color:{fg}">{_esc(t)}</span>')
    return "".join(parts)


def _momentum_card(rank: int, r: "MomentumResult") -> str:
    lang_color = _lang_color(r.language)
    age_str = f"建仓 {r.repo_age_days} 天" if r.repo_age_days >= 0 else ""
    seen_str = _format_hours(r.first_seen_hours)

    return f"""
    <div class="card">
      <div class="card-rank">#{rank}</div>
      <div class="card-body">
        <div class="card-top">
          <div class="repo-info">
            <a class="repo-name" href="{_esc(r.url)}" target="_blank">{_esc(r.repo_full_name)}</a>
            <div class="tags">{_tag_html(r.tags)}</div>
            <p class="desc">{_esc(r.description[:100]) if r.description else "暂无描述"}</p>
          </div>
          <div class="card-score">
            <div class="score-value">{r.composite_score:.4f}</div>
            <div class="score-label">综合得分</div>
          </div>
        </div>

        <div class="stats-row">
          <span class="stat">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="#f0b90b">
              <path d="M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z"/>
            </svg>
            {_format_stars(r.total_stars)}
            <span class="stat-sub">+{r.today_stars} today</span>
          </span>
          {"<span class='stat lang-dot' style='--c:" + lang_color + "'>" + _esc(r.language) + "</span>" if r.language else ""}
          <span class="stat muted">首次上榜: {seen_str}</span>
          {f'<span class="stat muted">{_esc(age_str)}</span>' if age_str else ""}
          <span class="stat muted">{r.snapshot_count} 个快照 · 追踪 {r.hours_tracked}h</span>
        </div>

        <div class="factors">
          {_factor_bar(r.momentum,       "价格动量", "#58a6ff")}
          {_factor_bar(r.delta_momentum, "增速动量", "#3fb950")}
          {_factor_bar(r.volume_surge,   "量能突破", "#bc8cff")}
          {_factor_bar(r.freshness,      "新鲜度",   "#f0b90b", ".2f")}
        </div>
      </div>
    </div>"""


def _trend_row(rank: int, r: dict) -> str:
    lang = r.get("language") or ""
    lang_color = _lang_color(lang)
    repo_name = r.get("repo_full_name", "")
    description = r.get("description") or ""
    total_stars = r.get("total_stars", 0)
    today_stars = r.get("today_stars", 0)
    return f"""
      <tr>
        <td class="rank-cell">#{rank}</td>
        <td>
          <a class="repo-link" href="https://github.com/{_esc(repo_name)}" target="_blank">
            {_esc(repo_name)}
          </a>
          <div class="muted small">{_esc(description[:60])}</div>
        </td>
        <td class="num-cell">⭐ {_format_stars(total_stars)}</td>
        <td class="num-cell green">+{today_stars}</td>
        {"<td><span class='lang-dot' style='--c:" + lang_color + "'>" + _esc(lang) + "</span></td>" if lang else "<td>—</td>"}
      </tr>"""


_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0d1117; --surface: #161b22; --border: #30363d;
  --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
}
body { background: var(--bg); color: var(--text); font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; font-size: 14px; line-height: 1.6; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

.container { max-width: 960px; margin: 0 auto; padding: 24px 16px; }

/* Header */
.header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 32px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
.header h1 { font-size: 20px; font-weight: 600; }
.header h1 span { color: var(--accent); }
.header .meta { color: var(--muted); font-size: 12px; text-align: right; }

/* Section */
.section-title { font-size: 16px; font-weight: 600; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
.section-title::before { content: ''; display: block; width: 3px; height: 16px; background: var(--accent); border-radius: 2px; }

/* Momentum Cards */
.cards { display: flex; flex-direction: column; gap: 16px; margin-bottom: 40px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; display: flex; overflow: hidden; transition: border-color .2s; }
.card:hover { border-color: var(--accent); }
.card-rank { width: 48px; display: flex; align-items: center; justify-content: center; font-size: 18px; font-weight: 700; color: var(--muted); background: rgba(255,255,255,.02); flex-shrink: 0; }
.card-body { flex: 1; padding: 16px; min-width: 0; }
.card-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 12px; }
.repo-info { flex: 1; min-width: 0; }
.repo-name { font-size: 16px; font-weight: 600; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
.tag { padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 500; border: 1px solid transparent; }
.desc { color: var(--muted); font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card-score { text-align: center; flex-shrink: 0; }
.score-value { font-size: 22px; font-weight: 700; color: #f0b90b; }
.score-label { font-size: 11px; color: var(--muted); }

/* Stats row */
.stats-row { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; }
.stat { display: flex; align-items: center; gap: 4px; font-size: 13px; }
.stat-sub { color: #3fb950; font-size: 12px; }
.muted { color: var(--muted); }
.lang-dot { display: flex; align-items: center; gap: 5px; }
.lang-dot::before { content: ''; display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: var(--c, #8b949e); }

/* Factors */
.factors { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 20px; }
.factor { }
.factor-header { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 3px; }
.factor-label { color: var(--muted); }
.factor-value { font-weight: 600; font-family: monospace; }
.factor-track { height: 4px; background: rgba(255,255,255,.07); border-radius: 2px; overflow: hidden; }
.factor-fill { height: 100%; border-radius: 2px; transition: width .3s; }

/* Trend Table */
.table-wrap { overflow-x: auto; margin-bottom: 40px; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; padding: 8px 12px; font-size: 12px; font-weight: 600; color: var(--muted); border-bottom: 1px solid var(--border); }
td { padding: 10px 12px; border-bottom: 1px solid rgba(48,54,61,.5); vertical-align: top; }
tr:hover td { background: rgba(255,255,255,.02); }
.rank-cell { color: var(--muted); font-size: 13px; width: 40px; }
.num-cell { text-align: right; font-family: monospace; color: var(--muted); white-space: nowrap; }
.num-cell.green { color: #3fb950; }
.repo-link { font-weight: 500; display: block; }
.small { font-size: 12px; }

/* Footer */
.footer { text-align: center; color: var(--muted); font-size: 12px; padding-top: 24px; border-top: 1px solid var(--border); }
"""


def generate_html(
    momentum_results: list["MomentumResult"],
    trend_results: list[dict] | None = None,
    ai_only: bool = True,
) -> str:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode_label = "AI 项目" if ai_only else "全部项目"

    # Momentum section
    cards_html = "".join(
        _momentum_card(i + 1, r) for i, r in enumerate(momentum_results)
    ) if momentum_results else '<p class="muted" style="padding:24px 0">暂无足够数据（需要 ≥2 次快照才能计算动量）</p>'

    # Trend section
    if trend_results:
        rows_html = "".join(_trend_row(i + 1, r) for i, r in enumerate(trend_results))
        trend_section = f"""
    <div class="section-title">今日 Trending TOP {len(trend_results)}（按今日新增 Stars 排序）</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th></th><th>仓库</th><th style="text-align:right">Stars</th>
            <th style="text-align:right">Today +</th><th>语言</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>"""
    else:
        trend_section = ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>GitHub Trending 动量分析</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>GitHub Trending <span>动量雷达</span></h1>
      <div class="meta">
        <div>筛选: {mode_label}</div>
        <div>生成时间: {now_str}</div>
      </div>
    </div>

    <div class="section-title">动量因子排行 · TOP {len(momentum_results)}</div>
    <div class="cards">{cards_html}</div>

    {trend_section}

    <div class="footer">
      由 github-trending-momentum 生成 · 数据来源 GitHub Trending
    </div>
  </div>
</body>
</html>"""


def save_report(
    path: str,
    momentum_results: list["MomentumResult"],
    trend_results: list[dict] | None = None,
    ai_only: bool = True,
) -> str:
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content = generate_html(momentum_results, trend_results, ai_only)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
