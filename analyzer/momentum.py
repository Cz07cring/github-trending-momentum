"""
动量因子分析引擎

核心思想：把 total_stars 当作"股价"，每小时快照当 K 线
- 动量因子 = (当前值 / N 期均线 - 1)，捕捉偏离均线的加速度
- 正值 = 增速快于历史平均 → 正在爆发
- 值越大 = 爆发越猛烈
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from storage.database import Database

logger = logging.getLogger(__name__)

# AI 相关关键词（仓库名、描述、topics 中命中任一即算 AI 项目）
AI_KEYWORDS = [
    "ai", "llm", "gpt", "agent", "chat", "copilot",
    "transformer", "diffusion", "stable-diffusion", "midjourney",
    "langchain", "llamaindex", "rag", "embedding",
    "openai", "anthropic", "claude", "gemini", "ollama", "llama",
    "machine-learning", "deep-learning", "neural", "ml", "dl",
    "nlp", "cv", "computer-vision", "speech", "tts", "stt",
    "model", "inference", "fine-tune", "finetune", "lora",
    "prompt", "reasoning", "multimodal", "vision",
    "mcp", "a]i-agent", "agentic", "workflow",
    "stable", "comfyui", "automatic1111",
    "huggingface", "vllm", "mlx", "moe",
]


@dataclass
class MomentumResult:
    """单个仓库的动量分析结果"""
    repo_full_name: str
    description: str = ""
    language: str = ""
    total_stars: int = 0
    today_stars: int = 0
    forks: int = 0

    # 动量因子
    momentum: float = 0.0        # 主动量：total_stars 偏离 MA 的程度
    delta_momentum: float = 0.0  # 二阶动量：每小时 star 增量的加速度
    volume_surge: float = 0.0    # 量能突破：today_stars 偏离均值的倍数
    freshness: float = 0.0       # 新鲜度：首次上榜越近分越高

    # 综合得分
    composite_score: float = 0.0

    # 元信息
    repo_age_days: int = -1      # 仓库创建天数，-1 表示未知
    first_seen_hours: float = -1 # 首次上榜距今（小时）
    snapshot_count: int = 0      # 快照数量（数据充分度）
    hours_tracked: float = 0.0   # 追踪时长（小时）
    tags: list[str] = field(default_factory=list)
    url: str = ""


class MomentumAnalyzer:
    """
    动量因子分析器

    四个核心因子：
    1. price_momentum  = total_stars / MA(n) - 1
       类比股价动量，>0 说明当前 star 增速快于近 N 期平均

    2. delta_momentum  = delta_stars / MA(delta, n) - 1
       delta_stars = 相邻快照的 total_stars 差值（每小时新增）
       二阶动量，捕捉"加速度的加速度"

    3. volume_surge    = today_stars / MA(today_stars, n) - 1
       类比成交量突破，today_stars 突然飙升意味着项目正在被大量关注

    4. freshness       = 仓库年龄越短分越高
       新仓库突然爆火 → 更有话题性 → 做视频更吸粉
       7天内创建=1.0, 30天=0.7, 90天=0.4, 1年=0.15, 老项目=0.05
    """

    def __init__(self, db: Database, config: dict | None = None):
        self.db = db
        cfg = config or {}
        # 均线窗口（快照数，每小时 1 次 → 6 = 近 6 小时）
        self.ma_window = cfg.get("ma_window", 6)
        # 综合得分权重（新鲜度最高 → 抢信息差）
        self.w_momentum = cfg.get("w_momentum", 0.20)
        self.w_delta = cfg.get("w_delta", 0.20)
        self.w_volume = cfg.get("w_volume", 0.20)
        self.w_freshness = cfg.get("w_freshness", 0.40)
        # 回看小时数
        self.lookback_hours = cfg.get("lookback_hours", 48)

    def analyze_all(self, ai_only: bool = True, top_n: int = 5) -> list[MomentumResult]:
        """
        对所有仓库做动量分析

        Args:
            ai_only: 是否只保留 AI 相关项目
            top_n: 返回前 N 个

        Returns:
            按 composite_score 降序排列的结果
        """
        df_all = self._load_all_snapshots()
        if df_all.empty:
            logger.warning("没有快照数据")
            return []

        # 去重：同一仓库同一时间只保留一条（可能不同语言筛选重复抓到）
        df_all = df_all.sort_values("scraped_at").drop_duplicates(
            subset=["repo_full_name", "scraped_at"], keep="last"
        )

        # 加载仓库元数据（created_at）
        meta_cache = self._load_meta_cache()

        results = []
        for repo_name, df_repo in df_all.groupby("repo_full_name"):
            if len(df_repo) < 2:
                continue

            # AI 过滤
            if ai_only and not self._is_ai_related(df_repo.iloc[-1]):
                continue

            meta = meta_cache.get(repo_name, {})
            result = self._calc_factors(repo_name, df_repo, meta)
            if result:
                results.append(result)

        results.sort(key=lambda x: x.composite_score, reverse=True)

        # 打标签
        for i, r in enumerate(results):
            if i < 3 and r.composite_score > 0:
                r.tags.append("强势爆发")
            if r.delta_momentum > 0.5:
                r.tags.append("加速中")
            if r.volume_surge > 1.0:
                r.tags.append("量能翻倍")
            if 0 <= r.first_seen_hours <= 6:
                r.tags.append("刚上榜")
            elif 0 <= r.first_seen_hours <= 24:
                r.tags.append("今日上榜")
            elif 0 <= r.first_seen_hours <= 72:
                r.tags.append("近3天上榜")
            if 0 <= r.repo_age_days <= 30:
                r.tags.append(f"建仓仅{r.repo_age_days}天")

        return results[:top_n]

    def _load_meta_cache(self) -> dict[str, dict]:
        """加载所有仓库的元数据到内存字典"""
        conn = self.db._get_conn()
        try:
            # created_at
            meta_rows = conn.execute(
                "SELECT repo_full_name, created_at FROM repo_meta WHERE created_at != ''"
            ).fetchall()
            cache = {r["repo_full_name"]: {"created_at": r["created_at"]} for r in meta_rows}

            # first_seen（首次出现在 Trending 的时间）
            seen_rows = conn.execute(
                """SELECT repo_full_name, MIN(scraped_at) as first_seen
                   FROM snapshots GROUP BY repo_full_name"""
            ).fetchall()
            for r in seen_rows:
                cache.setdefault(r["repo_full_name"], {})["first_seen"] = r["first_seen"]

            return cache
        finally:
            conn.close()

    def _load_all_snapshots(self) -> pd.DataFrame:
        """从 DB 加载所有快照到 DataFrame"""
        conn = self.db._get_conn()
        try:
            df = pd.read_sql_query(
                """SELECT repo_full_name, owner, name, description, language,
                          total_stars, forks, today_stars, scraped_at
                   FROM snapshots
                   WHERE scraped_at >= datetime('now', ?)
                   ORDER BY scraped_at ASC""",
                conn,
                params=(f"-{self.lookback_hours} hours",),
            )
            if not df.empty:
                df["scraped_at"] = pd.to_datetime(df["scraped_at"])
            return df
        finally:
            conn.close()

    def _calc_factors(self, repo_name: str, df: pd.DataFrame,
                      meta: dict | None = None) -> MomentumResult | None:
        """计算单个仓库的四个动量因子"""
        df = df.sort_values("scraped_at").reset_index(drop=True)
        n = self.ma_window
        latest = df.iloc[-1]
        meta = meta or {}

        # === 因子 1: price_momentum ===
        df["ma_stars"] = df["total_stars"].rolling(n, min_periods=1).mean()
        ma_val = df["ma_stars"].iloc[-1]
        momentum = (latest["total_stars"] / ma_val) - 1 if ma_val > 0 else 0.0

        # === 因子 2: delta_momentum ===
        df["delta_stars"] = df["total_stars"].diff().fillna(0).clip(lower=0)
        df["ma_delta"] = df["delta_stars"].rolling(n, min_periods=1).mean()
        ma_delta_val = df["ma_delta"].iloc[-1]
        current_delta = df["delta_stars"].iloc[-1]
        if ma_delta_val > 0:
            delta_momentum = (current_delta / ma_delta_val) - 1
        else:
            delta_momentum = current_delta

        # === 因子 3: volume_surge ===
        df["ma_today"] = df["today_stars"].rolling(n, min_periods=1).mean()
        ma_today_val = df["ma_today"].iloc[-1]
        volume_surge = (latest["today_stars"] / ma_today_val) - 1 if ma_today_val > 0 else 0.0

        # === 因子 4: freshness（新鲜度）===
        freshness, first_seen_hours, age_days = self._calc_freshness(meta)

        # === 综合得分 ===
        composite = (
            momentum * self.w_momentum
            + max(delta_momentum, 0) * self.w_delta
            + max(volume_surge, 0) * self.w_volume
            + freshness * self.w_freshness
        )

        # 追踪时长
        time_span = (df["scraped_at"].iloc[-1] - df["scraped_at"].iloc[0]).total_seconds() / 3600

        return MomentumResult(
            repo_full_name=repo_name,
            description=latest.get("description", ""),
            language=latest.get("language", ""),
            total_stars=int(latest["total_stars"]),
            today_stars=int(latest["today_stars"]),
            forks=int(latest["forks"]),
            momentum=round(momentum, 4),
            delta_momentum=round(delta_momentum, 4),
            volume_surge=round(volume_surge, 4),
            freshness=round(freshness, 4),
            composite_score=round(composite, 4),
            repo_age_days=age_days,
            first_seen_hours=round(first_seen_hours, 1),
            snapshot_count=len(df),
            hours_tracked=round(time_span, 1),
            url=f"https://github.com/{repo_name}",
        )

    @staticmethod
    def _calc_freshness(meta: dict) -> tuple[float, float, int]:
        """
        新鲜度因子：主要看"首次登上 Trending 距今多久"

        核心逻辑：刚被大众发现的项目 → 做视频最有信息差
          首次上榜 ≤6h   → 1.0  （刚上榜，抢先机！）
          首次上榜 ≤24h  → 0.7~1.0
          首次上榜 ≤72h  → 0.4~0.7
          首次上榜 ≤7天  → 0.2~0.4
          首次上榜 >7天  → 0.1（老面孔了）

        仓库创建时间作为加成：新仓库额外 +0.1 bonus

        Returns: (freshness_score, first_seen_hours, repo_age_days)
        """
        now = datetime.now(timezone.utc)

        # ---- 主信号：首次上榜距今 ----
        first_seen = meta.get("first_seen")
        if first_seen:
            try:
                # DB 里存的是本地时间 ISO 格式
                seen_dt = datetime.fromisoformat(first_seen).replace(tzinfo=timezone.utc)
                first_seen_hours = max((now - seen_dt).total_seconds() / 3600, 0)
            except (ValueError, TypeError):
                first_seen_hours = -1
        else:
            first_seen_hours = -1

        if first_seen_hours < 0:
            base_score = 0.5  # 未知，给中间值
        elif first_seen_hours <= 6:
            base_score = 1.0
        elif first_seen_hours <= 24:
            base_score = 1.0 - (first_seen_hours - 6) / 18 * 0.3  # 1.0 → 0.7
        elif first_seen_hours <= 72:
            base_score = 0.7 - (first_seen_hours - 24) / 48 * 0.3  # 0.7 → 0.4
        elif first_seen_hours <= 168:  # 7天
            base_score = 0.4 - (first_seen_hours - 72) / 96 * 0.2  # 0.4 → 0.2
        else:
            base_score = 0.1

        # ---- 加成：仓库创建时间 ----
        created_at = meta.get("created_at")
        age_days = -1
        bonus = 0.0
        if created_at:
            try:
                created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                age_days = max((now - created_dt).days, 0)
                if age_days <= 30:
                    bonus = 0.15  # 一个月内创建的新仓库，额外加成
                elif age_days <= 90:
                    bonus = 0.08
            except (ValueError, TypeError):
                pass

        return min(base_score + bonus, 1.0), first_seen_hours, age_days

    @staticmethod
    def _is_ai_related(row) -> bool:
        """判断项目是否 AI 相关"""
        text = f"{row.get('repo_full_name', '')} {row.get('description', '')}".lower()
        return any(kw in text for kw in AI_KEYWORDS)


def format_momentum_report(results: list[MomentumResult]) -> str:
    """格式化动量分析报告（终端输出）"""
    if not results:
        return "暂无符合条件的 AI 项目"

    lines = []
    for i, r in enumerate(results, 1):
        tags_str = " ".join(f"[{t}]" for t in r.tags) if r.tags else ""
        lines.append(f"\n{'─' * 55}")
        lines.append(f" {i}. {r.repo_full_name}  {tags_str}")
        lines.append(f"    {r.description[:70] if r.description else '暂无描述'}")
        lines.append(f"    ⭐ {r.total_stars:,} (+{r.today_stars} today) | {r.language or '未知'}")
        # 格式化首次上榜时间
        if r.first_seen_hours < 0:
            seen_str = "未知"
        elif r.first_seen_hours < 1:
            seen_str = f"{r.first_seen_hours * 60:.0f}分钟前"
        elif r.first_seen_hours < 24:
            seen_str = f"{r.first_seen_hours:.0f}小时前"
        else:
            seen_str = f"{r.first_seen_hours / 24:.1f}天前"
        age_str = f"建仓{r.repo_age_days}天" if r.repo_age_days >= 0 else ""
        lines.append(f"    📊 动量因子:")
        lines.append(f"       价格动量 = {r.momentum:+.2%}  (star 偏离均线)")
        lines.append(f"       增速动量 = {r.delta_momentum:+.2%}  (增量加速度)")
        lines.append(f"       量能突破 = {r.volume_surge:+.2%}  (today_stars 偏离)")
        lines.append(f"       新鲜度   = {r.freshness:.2f}    (首次上榜: {seen_str} {age_str})")
        lines.append(f"    🎯 综合得分 = {r.composite_score:.4f}")
        lines.append(f"    📈 数据: {r.snapshot_count} 个快照, 追踪 {r.hours_tracked}h")
        lines.append(f"    🔗 {r.url}")

    return "\n".join(lines)


def format_momentum_wechat(results: list[MomentumResult]) -> str:
    """格式化动量分析报告（企微 Markdown）"""
    if not results:
        return ""

    lines = ["**🚀 AI 项目动量雷达 - 爆发预警**\n"]
    for i, r in enumerate(results, 1):
        tags = " ".join(f"`{t}`" for t in r.tags)
        stars_fmt = f"{r.total_stars / 1000:.1f}k" if r.total_stars >= 1000 else str(r.total_stars)
        lines.append(
            f"{i}. **[{r.repo_full_name}](https://github.com/{r.repo_full_name})** {tags}\n"
            f"   {r.description[:50] if r.description else '暂无描述'}\n"
            f"   ⭐ {stars_fmt} (+{r.today_stars} today) | {r.language or '未知'}\n"
            f"   动量 `{r.momentum:+.1%}` | 加速 `{r.delta_momentum:+.1%}` "
            f"| 量能 `{r.volume_surge:+.1%}` | 新鲜 `{r.freshness:.2f}`\n"
            f"   **综合得分: {r.composite_score:.4f}**"
        )

    return "\n".join(lines)
