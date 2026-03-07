# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Setup config
cp config.yaml.example config.yaml

# One-shot scrape + full analysis + notify
python main.py --now

# Momentum analysis only (no scrape)
python main.py --momentum

# Momentum analysis for all repos (not AI-only)
python main.py --momentum --all

# Continuous daemon: scrape every N minutes + notify
python main.py

# Custom config path
python main.py --config path/to/config.yaml
```

There are no automated tests in this project.

## Architecture

This is a Python CLI tool that monitors GitHub Trending and applies quantitative momentum factors (similar to stock market analysis) to surface emerging AI repositories early.

**Data flow:**
1. `scraper/trending.py` — scrapes `github.com/trending` via BeautifulSoup (HTML parsing of `article.Box-row` elements)
2. `scraper/repo_detail.py` — calls GitHub REST API to fetch `created_at` and topics for each new repo
3. `storage/database.py` — persists hourly snapshots to SQLite (`data/github_trending.db`); two tables: `snapshots` (time-series) and `repo_meta` (created_at, topics)
4. `analyzer/momentum.py` — core engine: loads snapshots into pandas DataFrames, computes four factors per repo
5. `analyzer/trend.py` — simpler trend analysis (new entries, acceleration detection)
6. `notifier/wechat.py` — pushes results to Enterprise WeChat via webhook
7. `main.py` — CLI entry point and `schedule`-based daemon

**Four-factor momentum model** (`analyzer/momentum.py:MomentumAnalyzer`):
- `price_momentum` = `total_stars / MA(n) - 1` — star count deviation from moving average
- `delta_momentum` = `delta_stars / MA(delta, n) - 1` — acceleration of hourly star growth
- `volume_surge` = `today_stars / MA(today_stars, n) - 1` — daily star spike vs. average
- `freshness` — based on time since first appearance on Trending, multiplied by repo age factor

Composite score weights are configurable; freshness defaults to 0.40 (highest) to prioritize newly discovered repos.

**AI detection** (`analyzer/momentum.py:_is_ai_related`): Two-tier keyword matching — substring match for long compound terms (e.g. `langchain`, `llama`), word-boundary regex for short ambiguous terms (e.g. `ai`, `ml`, `rag`).

**Key config knobs** (`config.yaml`):
- `momentum.ma_window` — moving average window in snapshots (default: 6 = ~6 hours)
- `momentum.lookback_hours` — how far back to load snapshots (default: 48h)
- `momentum.ai_only` — filter to AI-related repos only
- `momentum.w_*` — factor weights
- `languages` — list of languages to scrape (empty string = all)

**Accuracy note:** The system needs ≥2 snapshots per repo to compute any momentum. Factors become meaningful after ~7 days of hourly data when the MA window is fully populated.
