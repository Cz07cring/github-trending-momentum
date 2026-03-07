"""入口：调度器"""

import argparse
import logging
import sys
import time

import schedule
import yaml

from analyzer.momentum import MomentumAnalyzer, format_momentum_report
from analyzer.trend import TrendAnalyzer
from notifier.html_report import save_report
from notifier.wechat import WeChatNotifier
from scraper.repo_detail import get_repo_detail
from scraper.trending import fetch_trending
from storage.database import Database

logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def run_scrape(config: dict, db: Database):
    """执行一次完整抓取流程"""
    languages = config.get("languages", [""])
    since = config.get("since", "daily")

    total = 0
    for lang in languages:
        repos = fetch_trending(language=lang, since=since)
        if repos:
            db.save_snapshot(repos, language_filter=lang, since=since)
            total += len(repos)
        # 避免请求过快
        if lang != languages[-1]:
            time.sleep(2)

    logger.info("本轮抓取完成，共获取 %d 条记录", total)

    # 为新仓库拉取 created_at 元数据
    _fetch_missing_meta(config, db)

    return total


def _fetch_missing_meta(config: dict, db: Database):
    """为还没有元数据的仓库调 GitHub API 拉 created_at"""
    missing = db.get_repos_without_meta()
    if not missing:
        return

    token = config.get("github_token", "")
    logger.info("拉取 %d 个新仓库的创建时间...", len(missing))
    fetched = 0
    for repo_name in missing:
        detail = get_repo_detail(repo_name, token=token)
        if detail is None:
            # API 限流，停止继续请求，下次再补
            logger.warning("API 限流，暂停元数据拉取，剩余 %d 个下次补",
                           len(missing) - fetched)
            break
        if detail.created_at:
            topics_str = ",".join(detail.topics) if detail.topics else ""
            db.save_repo_meta(repo_name, detail.created_at, topics_str)
            fetched += 1
        # 不带 token 限速：每秒 1 个请求
        if not token:
            time.sleep(1)
    logger.info("元数据拉取完成: %d/%d", fetched, len(missing))


def run_analysis_and_notify(config: dict, db: Database, notifier: WeChatNotifier):
    """执行分析并发送通知"""
    weights = config.get("scoring", {})
    analyzer = TrendAnalyzer(db, weights=weights if weights else None)
    alerts = config.get("alerts", {})

    # 新上榜检测
    new_entries = analyzer.get_new_entries()
    if new_entries:
        logger.info("发现 %d 个新上榜项目", len(new_entries))
        notifier.notify_new_entries(new_entries)

    # 加速上升检测
    threshold = alerts.get("acceleration_threshold", 100)
    accelerating = analyzer.get_accelerating(threshold=threshold)
    if accelerating:
        logger.info("发现 %d 个加速上升项目", len(accelerating))
        notifier.notify_accelerating(accelerating)

    return new_entries, accelerating


def run_momentum(config: dict, db: Database, notifier: WeChatNotifier | None = None):
    """动量因子分析"""
    mcfg = config.get("momentum", {})
    analyzer = MomentumAnalyzer(db, config=mcfg)
    top_n = mcfg.get("top_n", 5)
    ai_only = mcfg.get("ai_only", True)

    results = analyzer.analyze_all(ai_only=ai_only, top_n=top_n)

    if results and notifier and notifier.webhook_url:
        notifier.notify_momentum(results)
        logger.info("动量分析通知已推送")

    return results


def run_daily_report(config: dict, db: Database, notifier: WeChatNotifier):
    """每日汇总报告"""
    weights = config.get("scoring", {})
    analyzer = TrendAnalyzer(db, weights=weights if weights else None)

    top_repos = analyzer.get_top_n(10)
    new_entries = analyzer.get_new_entries()

    if top_repos:
        notifier.notify_daily_report(top_repos, new_entries)
        logger.info("每日汇总报告已推送")
    else:
        logger.info("暂无数据，跳过每日汇总")


def run_once(config: dict):
    """手动触发一次完整流程"""
    db = Database(config.get("database_path", "data/github_trending.db"))
    notifier = WeChatNotifier(config.get("wechat_webhook", ""))

    print("=" * 60)
    print("开始抓取 GitHub Trending...")
    print("=" * 60)

    # 抓取
    total = run_scrape(config, db)
    print(f"\n✅ 抓取完成，共获取 {total} 条记录\n")

    # 分析
    weights = config.get("scoring", {})
    analyzer = TrendAnalyzer(db, weights=weights if weights else None)

    top_repos = analyzer.get_top_n(10)
    new_entries = analyzer.get_new_entries()

    # 打印结果
    if top_repos:
        print("=" * 60)
        print("📊 今日 TOP 10 推荐")
        print("=" * 60)
        for i, repo in enumerate(top_repos[:10], 1):
            tags = " | ".join(repo.tags) if repo.tags else ""
            print(f"\n{i}. {repo.repo_full_name} (评分: {repo.score:.1f})")
            print(f"   {repo.description[:80] if repo.description else '暂无描述'}")
            print(f"   ⭐ {repo.total_stars} (+{repo.today_stars} today) | {repo.language or '未知'}")
            if tags:
                print(f"   🏷️  {tags}")

    if new_entries:
        print(f"\n{'=' * 60}")
        print(f"📌 新上榜项目 ({len(new_entries)} 个)")
        print("=" * 60)
        for i, repo in enumerate(new_entries[:10], 1):
            print(f"\n{i}. {repo.repo_full_name}")
            print(f"   {repo.description[:80] if repo.description else '暂无描述'}")
            print(f"   ⭐ {repo.total_stars} (+{repo.today_stars} today) | {repo.language or '未知'}")

    # 动量因子分析
    print(f"\n{'=' * 60}")
    print("🚀 AI 项目动量因子分析")
    print("=" * 60)
    momentum_results = run_momentum(config, db)
    if momentum_results:
        print(format_momentum_report(momentum_results))
    else:
        print("\n  暂无足够数据（需要 ≥2 次快照才能计算动量）")
        print("  提示：等待下一次抓取后再运行，或手动再执行一次 --now")

    # 发送通知
    if notifier.webhook_url:
        print(f"\n{'=' * 60}")
        print("📤 发送企微通知...")
        run_analysis_and_notify(config, db, notifier)
        if momentum_results:
            notifier.notify_momentum(momentum_results)
        print("✅ 通知已发送")
    else:
        print("\n💡 提示：未配置企微 Webhook，跳过通知推送")

    print(f"\n{'=' * 60}")
    print("🎉 完成！")


def start_scheduler(config: dict):
    """启动定时调度"""
    db = Database(config.get("database_path", "data/github_trending.db"))
    notifier = WeChatNotifier(config.get("wechat_webhook", ""))
    interval = config.get("scrape_interval_minutes", 60)
    report_hour = config.get("daily_report_hour", 8)
    report_minute = config.get("daily_report_minute", 0)

    def job_scrape():
        logger.info("定时任务：开始抓取")
        run_scrape(config, db)
        run_analysis_and_notify(config, db, notifier)
        # 每次抓取后运行动量分析
        run_momentum(config, db, notifier)

    def job_daily_report():
        logger.info("定时任务：每日汇总")
        run_daily_report(config, db, notifier)

    # 每 N 分钟抓取一次
    schedule.every(interval).minutes.do(job_scrape)

    # 每日定时汇总
    report_time = f"{report_hour:02d}:{report_minute:02d}"
    schedule.every().day.at(report_time).do(job_daily_report)

    logger.info("调度器已启动：每 %d 分钟抓取，每日 %s 推送汇总", interval, report_time)

    # 启动时立即执行一次
    job_scrape()

    while True:
        schedule.run_pending()
        time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description="GitHub Trending 热榜趋势抓取")
    parser.add_argument("--now", action="store_true", help="立即执行一次抓取并输出结果")
    parser.add_argument("--momentum", action="store_true", help="仅运行动量因子分析（不抓取）")
    parser.add_argument("--all", action="store_true", help="动量分析时包含所有项目（不限 AI）")
    parser.add_argument("--html", action="store_true", help="生成 HTML 报告并在浏览器打开")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config.get("log_level", "INFO"))

    if args.html:
        db = Database(config.get("database_path", "data/github_trending.db"))
        ai_only = not args.all
        if args.all:
            config.setdefault("momentum", {})["ai_only"] = False
        momentum_results = run_momentum(config, db)
        raw_snapshots = db.get_latest_round_snapshot()
        trend_results = sorted(raw_snapshots, key=lambda x: x.get("today_stars", 0), reverse=True)[:20]
        out_path = config.get("html_report_path", "data/report.html")
        save_report(out_path, momentum_results, trend_results, ai_only=ai_only)
        print(f"HTML 报告已生成: {out_path}")
        import webbrowser, os
        webbrowser.open(f"file://{os.path.abspath(out_path)}")
    elif args.momentum:
        db = Database(config.get("database_path", "data/github_trending.db"))
        if args.all:
            config.setdefault("momentum", {})["ai_only"] = False
        print("=" * 60)
        print("🚀 AI 项目动量因子分析")
        print("=" * 60)
        results = run_momentum(config, db)
        if results:
            print(format_momentum_report(results))
        else:
            print("\n  暂无足够数据（需要 ≥2 次快照才能计算动量）")
    elif args.now:
        run_once(config)
    else:
        print("🚀 GitHub Trending 热榜监控已启动")
        print(f"   抓取间隔: 每 {config.get('scrape_interval_minutes', 60)} 分钟")
        print(f"   监控语言: {', '.join(l or '全部' for l in config.get('languages', ['']))}")
        print(f"   按 Ctrl+C 停止\n")
        try:
            start_scheduler(config)
        except KeyboardInterrupt:
            print("\n👋 已停止")
            sys.exit(0)


if __name__ == "__main__":
    main()
