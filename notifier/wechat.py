"""企业微信机器人通知"""

import logging

import requests

from analyzer.momentum import MomentumResult, format_momentum_wechat
from analyzer.trend import RepoScore

logger = logging.getLogger(__name__)


class WeChatNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def _send(self, content: str) -> bool:
        """发送 Markdown 消息到企业微信群"""
        if not self.webhook_url:
            logger.warning("未配置企业微信 Webhook URL，跳过通知")
            return False

        payload = {
            "msgtype": "markdown",
            "markdown": {"content": content},
        }
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            if result.get("errcode") == 0:
                logger.info("企微通知发送成功")
                return True
            else:
                logger.error("企微通知发送失败: %s", result)
                return False
        except requests.RequestException as e:
            logger.error("企微通知请求失败: %s", e)
            return False

    def notify_new_entries(self, repos: list[RepoScore]) -> bool:
        """通知新上榜项目"""
        if not repos:
            return True

        lines = ["**🔥 GitHub 热榜预警 - 新上榜项目**\n"]
        for i, repo in enumerate(repos[:10], 1):
            tags = " ".join(f"`{t}`" for t in repo.tags)
            lines.append(
                f"{i}. **[{repo.repo_full_name}](https://github.com/{repo.repo_full_name})** "
                f"- {repo.description[:60] if repo.description else '暂无描述'}\n"
                f"   ⭐ {_format_stars(repo.total_stars)} (+{repo.today_stars} today) "
                f"| {repo.language or '未知'} {tags}"
            )

        content = "\n".join(lines)
        return self._send(content)

    def notify_accelerating(self, repos: list[RepoScore]) -> bool:
        """通知加速上升的项目"""
        if not repos:
            return True

        lines = ["**📈 GitHub 热榜预警 - 加速上升**\n"]
        for i, repo in enumerate(repos[:10], 1):
            lines.append(
                f"{i}. **[{repo.repo_full_name}](https://github.com/{repo.repo_full_name})** "
                f"- Stars 增速提升 {repo.acceleration:.0f}%\n"
                f"   ⭐ {_format_stars(repo.total_stars)} (+{repo.today_stars} today) "
                f"| {repo.language or '未知'}"
            )

        content = "\n".join(lines)
        return self._send(content)

    def notify_daily_report(self, top_repos: list[RepoScore],
                            new_entries: list[RepoScore]) -> bool:
        """每日汇总推送"""
        lines = ["**📊 GitHub 热榜日报**\n"]

        # TOP 5
        lines.append("**🏆 今日 TOP 5：**")
        for i, repo in enumerate(top_repos[:5], 1):
            tags = " ".join(f"`{t}`" for t in repo.tags)
            lines.append(
                f"{i}. **[{repo.repo_full_name}](https://github.com/{repo.repo_full_name})** "
                f"(评分 {repo.score:.1f})\n"
                f"   {repo.description[:50] if repo.description else '暂无描述'}\n"
                f"   ⭐ {_format_stars(repo.total_stars)} (+{repo.today_stars} today) "
                f"| {repo.language or '未知'} {tags}"
            )

        # 新上榜
        if new_entries:
            lines.append("\n**📌 新上榜项目：**")
            for i, repo in enumerate(new_entries[:5], 1):
                lines.append(
                    f"{i}. **[{repo.repo_full_name}](https://github.com/{repo.repo_full_name})** "
                    f"- {repo.description[:60] if repo.description else '暂无描述'}\n"
                    f"   ⭐ {_format_stars(repo.total_stars)} (+{repo.today_stars} today) "
                    f"| {repo.language or '未知'}"
                )

        content = "\n".join(lines)
        return self._send(content)


    def notify_momentum(self, results: list[MomentumResult]) -> bool:
        """推送动量因子分析结果"""
        content = format_momentum_wechat(results)
        if not content:
            return True
        return self._send(content)


def _format_stars(stars: int) -> str:
    """格式化 star 数量显示"""
    if stars >= 1000:
        return f"{stars / 1000:.1f}k"
    return str(stars)
