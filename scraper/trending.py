"""核心：抓取 GitHub Trending 页面"""

import logging
import re

import requests
from bs4 import BeautifulSoup

from storage.models import TrendingRepo

logger = logging.getLogger(__name__)

GITHUB_TRENDING_URL = "https://github.com/trending"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _parse_number(text: str) -> int:
    """解析数字字符串，如 '1,234' 或 '1.2k'"""
    text = text.strip().replace(",", "")
    if not text:
        return 0
    # 处理 k 后缀
    if text.lower().endswith("k"):
        try:
            return int(float(text[:-1]) * 1000)
        except ValueError:
            return 0
    try:
        return int(text)
    except ValueError:
        return 0


def fetch_trending(language: str = "", since: str = "daily") -> list[TrendingRepo]:
    """
    抓取 GitHub Trending 页面

    Args:
        language: 编程语言筛选，如 "python"、"javascript"，空字符串表示全部
        since: 时间范围，"daily" / "weekly" / "monthly"

    Returns:
        TrendingRepo 列表
    """
    url = GITHUB_TRENDING_URL
    if language:
        url = f"{url}/{language.lower()}"

    params = {"since": since}
    logger.info("抓取 Trending: %s (since=%s)", url, since)

    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("请求失败: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    repos = []

    # GitHub Trending 页面的仓库列表
    articles = soup.select("article.Box-row")
    if not articles:
        logger.warning("未找到仓库列表，页面结构可能已变化")
        return []

    for article in articles:
        try:
            repo = _parse_article(article)
            if repo:
                repos.append(repo)
        except Exception as e:
            logger.warning("解析仓库信息失败: %s", e)
            continue

    logger.info("成功解析 %d 个仓库", len(repos))
    return repos


def _parse_article(article) -> TrendingRepo | None:
    """解析单个仓库的 HTML 元素"""
    # 仓库名: h2 > a 标签，href 格式为 /owner/name
    h2 = article.select_one("h2")
    if not h2:
        return None

    link = h2.select_one("a")
    if not link:
        return None

    href = link.get("href", "").strip("/")
    parts = href.split("/")
    if len(parts) < 2:
        return None

    owner = parts[0]
    name = parts[1]

    # 描述
    desc_tag = article.select_one("p")
    description = desc_tag.get_text(strip=True) if desc_tag else ""

    # 语言
    language = ""
    lang_tag = article.select_one("[itemprop='programmingLanguage']")
    if lang_tag:
        language = lang_tag.get_text(strip=True)

    # Stars 和 Forks — 在同一行的链接中
    stats_links = article.select("a.Link--muted")
    total_stars = 0
    forks = 0

    for link_tag in stats_links:
        href_val = link_tag.get("href", "")
        text = link_tag.get_text(strip=True)
        if "/stargazers" in href_val:
            total_stars = _parse_number(text)
        elif "/forks" in href_val:
            forks = _parse_number(text)

    # 今日新增 Stars
    today_stars = 0
    today_tag = article.select_one("span.d-inline-block.float-sm-right")
    if today_tag:
        match = re.search(r"([\d,]+)", today_tag.get_text())
        if match:
            today_stars = _parse_number(match.group(1))

    # 贡献者
    contributors = []
    contrib_links = article.select("a[data-hovercard-type='user'] img")
    for img in contrib_links:
        alt = img.get("alt", "").lstrip("@")
        if alt:
            contributors.append(alt)

    return TrendingRepo(
        owner=owner,
        name=name,
        description=description,
        language=language,
        total_stars=total_stars,
        forks=forks,
        today_stars=today_stars,
        contributors=contributors,
        url=f"https://github.com/{owner}/{name}",
    )
