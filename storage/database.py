"""SQLite 数据库操作"""

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from storage.models import TrendingRepo, TrendingSnapshot

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "data/github_trending.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库表"""
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_full_name TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    language TEXT DEFAULT '',
                    total_stars INTEGER DEFAULT 0,
                    forks INTEGER DEFAULT 0,
                    today_stars INTEGER DEFAULT 0,
                    scraped_at TEXT NOT NULL,
                    source_language_filter TEXT DEFAULT '',
                    source_since TEXT DEFAULT 'daily'
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_repo
                    ON snapshots(repo_full_name);
                CREATE INDEX IF NOT EXISTS idx_snapshots_time
                    ON snapshots(scraped_at);
                CREATE INDEX IF NOT EXISTS idx_snapshots_repo_time
                    ON snapshots(repo_full_name, scraped_at);

                CREATE TABLE IF NOT EXISTS repo_meta (
                    repo_full_name TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT '',
                    topics TEXT DEFAULT '',
                    fetched_at TEXT NOT NULL
                );
            """)
            conn.commit()
        finally:
            conn.close()

    def save_snapshot(self, repos: list[TrendingRepo], language_filter: str = "", since: str = "daily"):
        """保存一次抓取结果"""
        conn = self._get_conn()
        try:
            snapshots = [TrendingSnapshot.from_repo(r, language_filter, since) for r in repos]
            conn.executemany(
                """INSERT INTO snapshots
                   (repo_full_name, owner, name, description, language,
                    total_stars, forks, today_stars, scraped_at,
                    source_language_filter, source_since)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (s.repo_full_name, s.owner, s.name, s.description, s.language,
                     s.total_stars, s.forks, s.today_stars, s.scraped_at,
                     s.source_language_filter, s.source_since)
                    for s in snapshots
                ],
            )
            conn.commit()
            logger.info("保存 %d 条快照（语言=%s, 范围=%s）", len(snapshots), language_filter or "all", since)
        finally:
            conn.close()

    def get_history(self, repo_name: str, hours: int = 24) -> list[dict]:
        """获取某仓库近 N 小时的 star 变化"""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT total_stars, today_stars, scraped_at
                   FROM snapshots
                   WHERE repo_full_name = ? AND scraped_at >= ?
                   ORDER BY scraped_at ASC""",
                (repo_name, cutoff),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_new_entries(self) -> list[dict]:
        """找出新上榜的仓库（最近一次抓取中出现、但之前从未出现过的）"""
        conn = self._get_conn()
        try:
            # 获取最近一次抓取的时间
            latest = conn.execute(
                "SELECT MAX(scraped_at) as latest FROM snapshots"
            ).fetchone()
            if not latest or not latest["latest"]:
                return []

            latest_time = latest["latest"]

            # 找到本次抓取的所有仓库中，之前没有记录的
            rows = conn.execute(
                """SELECT s.*
                   FROM snapshots s
                   WHERE s.scraped_at = ?
                     AND s.repo_full_name NOT IN (
                         SELECT DISTINCT repo_full_name
                         FROM snapshots
                         WHERE scraped_at < ?
                     )
                   ORDER BY s.today_stars DESC""",
                (latest_time, latest_time),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_rising_fast(self, hours: int = 24, min_snapshots: int = 2) -> list[dict]:
        """找出 star 增速最快的仓库（需要至少 min_snapshots 条快照来计算增速）"""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        conn = self._get_conn()
        try:
            # 获取有多条快照的仓库
            repos = conn.execute(
                """SELECT repo_full_name, COUNT(*) as cnt
                   FROM snapshots
                   WHERE scraped_at >= ?
                   GROUP BY repo_full_name
                   HAVING cnt >= ?""",
                (cutoff, min_snapshots),
            ).fetchall()

            results = []
            for repo in repos:
                repo_name = repo["repo_full_name"]
                history = conn.execute(
                    """SELECT total_stars, today_stars, scraped_at
                       FROM snapshots
                       WHERE repo_full_name = ? AND scraped_at >= ?
                       ORDER BY scraped_at ASC""",
                    (repo_name, cutoff),
                ).fetchall()

                if len(history) < 2:
                    continue

                first = history[0]
                last = history[-1]
                star_growth = last["total_stars"] - first["total_stars"]

                # 获取最新一条的完整信息
                latest_info = conn.execute(
                    """SELECT * FROM snapshots
                       WHERE repo_full_name = ?
                       ORDER BY scraped_at DESC LIMIT 1""",
                    (repo_name,),
                ).fetchone()

                results.append({
                    **dict(latest_info),
                    "star_growth": star_growth,
                    "snapshot_count": len(history),
                })

            results.sort(key=lambda x: x["star_growth"], reverse=True)
            return results
        finally:
            conn.close()

    def get_latest_snapshot(self) -> list[dict]:
        """获取最近一次抓取的所有仓库"""
        conn = self._get_conn()
        try:
            latest = conn.execute(
                "SELECT MAX(scraped_at) as latest FROM snapshots"
            ).fetchone()
            if not latest or not latest["latest"]:
                return []

            rows = conn.execute(
                """SELECT * FROM snapshots
                   WHERE scraped_at = ?
                   ORDER BY today_stars DESC""",
                (latest["latest"],),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_consecutive_days(self, repo_name: str) -> int:
        """计算仓库连续在榜天数"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT DISTINCT DATE(scraped_at) as day
                   FROM snapshots
                   WHERE repo_full_name = ?
                   ORDER BY day DESC""",
                (repo_name,),
            ).fetchall()

            if not rows:
                return 0

            days = [row["day"] for row in rows]
            consecutive = 1
            for i in range(1, len(days)):
                prev = datetime.strptime(days[i - 1], "%Y-%m-%d")
                curr = datetime.strptime(days[i], "%Y-%m-%d")
                if (prev - curr).days == 1:
                    consecutive += 1
                else:
                    break
            return consecutive
        finally:
            conn.close()

    def get_repo_first_seen(self, repo_name: str) -> Optional[str]:
        """获取仓库首次出现时间"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT MIN(scraped_at) as first_seen FROM snapshots WHERE repo_full_name = ?",
                (repo_name,),
            ).fetchone()
            return row["first_seen"] if row else None
        finally:
            conn.close()

    # ---- repo_meta 表操作 ----

    def get_repo_meta(self, repo_name: str) -> Optional[dict]:
        """获取仓库元数据缓存"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM repo_meta WHERE repo_full_name = ?",
                (repo_name,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def save_repo_meta(self, repo_name: str, created_at: str, topics: str = ""):
        """保存仓库元数据"""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO repo_meta (repo_full_name, created_at, topics, fetched_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(repo_full_name) DO UPDATE SET
                       created_at = excluded.created_at,
                       topics = excluded.topics,
                       fetched_at = excluded.fetched_at""",
                (repo_name, created_at, topics, datetime.now().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def get_repos_without_meta(self) -> list[str]:
        """获取还没有拉过元数据的仓库名列表"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT DISTINCT s.repo_full_name
                   FROM snapshots s
                   LEFT JOIN repo_meta m ON s.repo_full_name = m.repo_full_name
                   WHERE m.repo_full_name IS NULL"""
            ).fetchall()
            return [r["repo_full_name"] for r in rows]
        finally:
            conn.close()
