"""通过 GitHub API 获取仓库详情"""

import base64
import logging

import requests

from storage.models import RepoDetail

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


def get_repo_detail(full_name: str, token: str = "") -> RepoDetail | None:
    """
    通过 GitHub REST API 获取仓库详情

    Args:
        full_name: 仓库全名，如 "owner/repo"
        token: GitHub Token（可选）

    Returns:
        RepoDetail 或 None
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "GitHubTrendingScraper",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{GITHUB_API}/repos/{full_name}"
    logger.debug("获取仓库详情: %s", full_name)

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.warning("获取仓库详情失败 [%s]: %s", full_name, e)
        return None

    # 获取 README 摘要
    readme_summary = _get_readme_summary(full_name, headers)

    detail = RepoDetail(
        full_name=full_name,
        readme_summary=readme_summary,
        topics=data.get("topics", []),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        open_issues=data.get("open_issues_count", 0),
        license=data.get("license", {}).get("spdx_id", "") if data.get("license") else "",
    )
    return detail


def _get_readme_summary(full_name: str, headers: dict, max_chars: int = 500) -> str:
    """获取 README 内容的前 N 个字符作为摘要"""
    url = f"{GITHUB_API}/repos/{full_name}/readme"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return ""
        data = resp.json()
        content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="ignore")
        # 取前 max_chars 个字符作为摘要
        return content[:max_chars].strip()
    except Exception as e:
        logger.debug("获取 README 失败 [%s]: %s", full_name, e)
        return ""
