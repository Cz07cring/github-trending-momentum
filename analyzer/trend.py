"""趋势分析：增速计算、爆款预测"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from storage.database import Database

logger = logging.getLogger(__name__)


@dataclass
class RepoScore:
    """仓库评分结果"""
    repo_full_name: str
    description: str = ""
    language: str = ""
    total_stars: int = 0
    today_stars: int = 0
    forks: int = 0
    score: float = 0.0
    tags: list[str] = field(default_factory=list)
    consecutive_days: int = 0
    acceleration: float = 0.0  # star 增长加速度


class TrendAnalyzer:
    def __init__(self, db: Database, weights: dict | None = None):
        self.db = db
        self.weights = weights or {
            "today_stars_weight": 0.4,
            "consecutive_days_weight": 0.2,
            "acceleration_weight": 0.3,
            "repo_age_weight": 0.1,
        }

    def analyze(self) -> list[RepoScore]:
        """执行完整分析，返回按评分排序的推荐列表"""
        latest = self.db.get_latest_snapshot()
        if not latest:
            logger.warning("没有可分析的数据")
            return []

        new_entries = {r["repo_full_name"] for r in self.db.get_new_entries()}
        rising = {r["repo_full_name"]: r for r in self.db.get_rising_fast()}

        results = []
        for repo in latest:
            repo_name = repo["repo_full_name"]
            consecutive = self.db.get_consecutive_days(repo_name)
            acceleration = self._calc_acceleration(repo_name)

            score = self._calc_score(
                today_stars=repo["today_stars"],
                consecutive_days=consecutive,
                acceleration=acceleration,
                repo_name=repo_name,
            )

            tags = []
            if repo_name in new_entries:
                tags.append("新上榜")
            if acceleration > 0:
                tags.append("加速上升")
            if consecutive >= 3:
                tags.append("持续霸榜")

            results.append(RepoScore(
                repo_full_name=repo_name,
                description=repo["description"],
                language=repo["language"],
                total_stars=repo["total_stars"],
                today_stars=repo["today_stars"],
                forks=repo["forks"],
                score=score,
                tags=tags,
                consecutive_days=consecutive,
                acceleration=acceleration,
            ))

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def _calc_acceleration(self, repo_name: str) -> float:
        """
        计算 star 增长加速度
        对比最近两次快照的 today_stars 变化百分比
        """
        history = self.db.get_history(repo_name, hours=48)
        if len(history) < 2:
            return 0.0

        # 取最近两次的 today_stars
        recent = history[-1]["today_stars"]
        previous = history[-2]["today_stars"]

        if previous <= 0:
            return float(recent) * 100 if recent > 0 else 0.0

        return ((recent - previous) / previous) * 100

    def _calc_score(self, today_stars: int, consecutive_days: int,
                    acceleration: float, repo_name: str) -> float:
        """计算爆款评分"""
        w = self.weights

        # 今日 stars 归一化（以 1000 为满分基准）
        stars_score = min(today_stars / 1000.0, 1.0) * 100

        # 连续在榜天数（以 7 天为满分基准）
        days_score = min(consecutive_days / 7.0, 1.0) * 100

        # 加速度归一化（以 200% 为满分基准）
        accel_score = min(max(acceleration, 0) / 200.0, 1.0) * 100

        # 仓库年龄（越新分越高）
        age_score = self._calc_age_score(repo_name)

        total = (
            stars_score * w["today_stars_weight"]
            + days_score * w["consecutive_days_weight"]
            + accel_score * w["acceleration_weight"]
            + age_score * w["repo_age_weight"]
        )
        return round(total, 2)

    def _calc_age_score(self, repo_name: str) -> float:
        """仓库年龄评分：越新分越高"""
        first_seen = self.db.get_repo_first_seen(repo_name)
        if not first_seen:
            return 100.0  # 第一次见到，给满分

        try:
            first_dt = datetime.fromisoformat(first_seen)
            days_known = (datetime.now() - first_dt).days
            # 1天内 = 100分，7天 = 50分，30天+ = 10分
            if days_known <= 1:
                return 100.0
            elif days_known <= 7:
                return max(100.0 - (days_known - 1) * 8.3, 50.0)
            else:
                return max(50.0 - (days_known - 7) * 1.7, 10.0)
        except (ValueError, TypeError):
            return 50.0

    def get_new_entries(self) -> list[RepoScore]:
        """仅返回新上榜仓库"""
        all_scores = self.analyze()
        return [r for r in all_scores if "新上榜" in r.tags]

    def get_accelerating(self, threshold: float = 100.0) -> list[RepoScore]:
        """返回加速度超过阈值的仓库"""
        all_scores = self.analyze()
        return [r for r in all_scores if r.acceleration >= threshold]

    def get_top_n(self, n: int = 10) -> list[RepoScore]:
        """返回 TOP N 推荐"""
        all_scores = self.analyze()
        return all_scores[:n]
