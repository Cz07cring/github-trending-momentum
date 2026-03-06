"""数据模型定义"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class TrendingRepo:
    """Trending 仓库数据"""
    owner: str
    name: str
    description: str = ""
    language: str = ""
    total_stars: int = 0
    forks: int = 0
    today_stars: int = 0
    contributors: list[str] = field(default_factory=list)
    url: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass
class TrendingSnapshot:
    """抓取快照记录"""
    id: Optional[int] = None
    repo_full_name: str = ""
    owner: str = ""
    name: str = ""
    description: str = ""
    language: str = ""
    total_stars: int = 0
    forks: int = 0
    today_stars: int = 0
    scraped_at: str = ""  # ISO 格式时间字符串
    source_language_filter: str = ""  # 抓取时的语言筛选条件
    source_since: str = "daily"  # 抓取时的时间范围

    @staticmethod
    def from_repo(repo: TrendingRepo, language_filter: str = "", since: str = "daily") -> "TrendingSnapshot":
        return TrendingSnapshot(
            repo_full_name=repo.full_name,
            owner=repo.owner,
            name=repo.name,
            description=repo.description,
            language=repo.language,
            total_stars=repo.total_stars,
            forks=repo.forks,
            today_stars=repo.today_stars,
            scraped_at=datetime.now().isoformat(),
            source_language_filter=language_filter,
            source_since=since,
        )


@dataclass
class RepoDetail:
    """仓库详情（通过 GitHub API 获取）"""
    full_name: str = ""
    readme_summary: str = ""
    topics: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    open_issues: int = 0
    license: str = ""
