"""程序级输出质量门。

P2 修复：在生成流程末端提供一个只读、可测试的最终质量门。
- `OutputValidationError`: 验证失败时抛出的异常
- `OutputValidator`: 聚合多个质量检查（标题、字数、截断、AI 痕迹、跨章相似度）
- `TitleSanitizer`: 无 LLM 的标题清洗（剥除脏词、长度规范化）

设计原则：
1. **只读**：验证器不修改文本，所有改写由 `_post_generation_recovery`/`dilute_ai_traces` 等修复层负责
2. **可测试**：所有检查是纯函数，无 I/O、无 LLM 调用
3. **可配置**：通过构造函数参数注入阈值，便于在不同场景下复用
4. **复用优先**：标题脏词检测复用 `PlannerAgent._is_dirty_title`、截断检测复用 `WriterAgent._is_truncated_ending`、相似度复用 `WriterAgent._is_too_similar`，不重新实现

使用方式：
    from core.validators import OutputValidator, OutputValidationError
    validator = OutputValidator(ai_trace_phrases=settings.AI_TRACE_PHRASES, ...)
    validator.validate_all(title=..., content=..., target_words=..., is_last_chapter=False, previous_ending="")
    # 无违规时不抛错；有违规时抛 OutputValidationError
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("validators")


class OutputValidationError(Exception):
    """最终输出质量门未通过。

    Attributes:
        violations: 违规描述列表（每项为可读中文短句）
        category: 违规分类，取值 'title' | 'word_count' | 'truncation' | 'ai_trace' | 'similarity' | 'mixed'
        recoverable: 是否可重试。False 表示这是配置/数据问题，不应通过重试解决
    """

    def __init__(self, violations: list[str], category: str = "mixed", recoverable: bool = True):
        self.violations = violations
        self.category = category
        self.recoverable = recoverable
        super().__init__(f"OutputValidationError[{category}]: {'；'.join(violations)}")


@dataclass
class OutputValidator:
    """纯函数式最终质量门。失败抛 OutputValidationError。"""

    # 必填：从 settings 注入
    ai_trace_phrases: list[str] = field(default_factory=list)
    ai_trace_max: int = 3
    # 字数阈值
    word_count_lower_pct: float = 0.85        # 普通章
    word_count_lower_pct_last: float = 0.95   # 末章（高潮必须达标）
    word_count_absolute_min: int = 200        # 绝对下限（硬地板）
    # AI 痕迹密度（每千字）
    ai_trace_density_limit: float = 1.5
    # 跨章相似度（Jaccard）
    similarity_threshold: float = 0.5

    # ---- 标题检查 ----
    def validate_title(self, title: str) -> list[str]:
        """脏词标题检查。复用 PlannerAgent.DIRTY_TITLE_PATTERNS。

        直接读类属性而非调实例方法，避免对 planner_agent 实例化产生依赖。
        """
        if not title or not title.strip():
            return ["标题为空"]
        # 延迟导入避免循环依赖
        from agents.planner_agent import PlannerAgent
        patterns = PlannerAgent.DIRTY_TITLE_PATTERNS
        if len(title.strip()) <= 2:
            return [f"标题过短: '{title}'"]
        for pat in patterns:
            if pat in title:
                return [f"标题包含脏词 '{pat}': '{title}'"]
        return []

    # ---- 字数检查 ----
    def validate_word_count(self, text: str, target: int, *, is_last_chapter: bool = False) -> list[str]:
        from core.word_counter import count_chinese_words
        words = count_chinese_words(text or "")
        # 绝对下限
        if words < self.word_count_absolute_min:
            return [f"字数 {words} 低于绝对下限 {self.word_count_absolute_min}"]
        if target <= 0:
            return []  # 未指定目标字数时不校验比例
        lower_pct = self.word_count_lower_pct_last if is_last_chapter else self.word_count_lower_pct
        required = int(target * lower_pct)
        if words < required:
            tag = "末章" if is_last_chapter else "本章"
            return [f"{tag}字数 {words} 低于目标 {target} 的 {int(lower_pct*100)}%（需 {required}）"]
        return []

    # ---- 截断检查 ----
    def validate_truncation(self, text: str) -> list[str]:
        from agents.writer_agent import WriterAgent
        if WriterAgent._is_truncated_ending(text or ""):
            return ["章节末尾未以正常标点结尾（疑似截断）"]
        return []

    # ---- AI 痕迹检查 ----
    def validate_ai_traces(self, text: str) -> list[str]:
        violations: list[str] = []
        if not text:
            return violations
        # 1) 短语硬阈值
        for phrase in self.ai_trace_phrases:
            count = text.count(phrase)
            if count > self.ai_trace_max:
                violations.append(
                    f"AI 痕迹短语 '{phrase}' 出现 {count} 次（> {self.ai_trace_max}）"
                )
        # 2) 密度（每千字）
        from core.word_counter import count_chinese_words
        words = count_chinese_words(text)
        if words > 0:
            total_traces = sum(text.count(p) for p in self.ai_trace_phrases)
            density = total_traces / (words / 1000.0)
            if density > self.ai_trace_density_limit:
                violations.append(
                    f"AI 痕迹密度 {density:.2f}/千字 超过 {self.ai_trace_density_limit}"
                )
        return violations

    # ---- 标题唯一性检查（跨章）----
    # 短标题允许长度（避免 2-3 字短标题被无意义地拒绝）
    title_uniqueness_min_length: int = 3
    # 与最近 N 章做前缀比对（捕捉"扩大组织、"这种 stage 坍缩）
    title_uniqueness_recent_window: int = 5
    # 标题"主体"前缀比对长度（剥除"第N章 "后的核心前缀）
    title_uniqueness_core_prefix_len: int = 3

    @staticmethod
    def _strip_chapter_number(title: str) -> str:
        """剥除"第N章 "前缀，返回纯标题主体。"""
        import re
        m = re.match(r"^\s*第\s*\d+\s*章\s*", title)
        return title[m.end():] if m else title

    def validate_title_uniqueness(
        self, title: str, previous_titles: Optional[list[str]]
    ) -> list[str]:
        """跨章标题唯一性检查。复检两道：

        1) **精确重复**：当前标题在历史标题列表里完全相同
        2) **前缀坍缩**：剥除"第N章 "后，标题主体前 K 字与最近 N 章任一标题主体相同
           （捕捉"扩大组织·初现/暗涌/试探"这种 stage 桶坍缩）
        """
        if not title or not previous_titles:
            return []
        t = title.strip()
        if len(t) < self.title_uniqueness_min_length:
            return []  # 短标题不强制唯一

        # 1) 精确重复
        prev_stripped = [p.strip() for p in previous_titles if p and p.strip()]
        if t in prev_stripped:
            return [f"标题与历史章节重复: '{t}'"]

        # 2) 前缀坍缩：仅看最近 N 章；先剥"第N章 "再比核心前缀
        window = prev_stripped[-self.title_uniqueness_recent_window :]
        t_core = self._strip_chapter_number(t)
        k = self.title_uniqueness_core_prefix_len
        for prev in window:
            prev_core = self._strip_chapter_number(prev)
            if (
                len(t_core) >= k
                and len(prev_core) >= k
                and t_core[:k] == prev_core[:k]
            ):
                return [f"标题与近章高度相似（前缀坍缩）: '{t}' ≈ '{prev}'"]
        return []

    # ---- 跨章相似度检查 ----
    def validate_similarity(self, text: str, previous_ending: Optional[str]) -> list[str]:
        if not text or not previous_ending:
            return []
        from agents.writer_agent import WriterAgent
        # _is_too_similar 是实例方法。构造一个无依赖临时实例。
        agent = WriterAgent.__new__(WriterAgent)
        if agent._is_too_similar(text, previous_ending, threshold=self.similarity_threshold):
            return [f"与上一章结尾相似度超过 {self.similarity_threshold}（疑似重复开场）"]
        return []

    # ---- 聚合 ----
    def validate_all(
        self,
        *,
        title: str,
        content: str,
        target_words: int = 0,
        is_last_chapter: bool = False,
        previous_ending: Optional[str] = None,
        previous_titles: Optional[list[str]] = None,
    ) -> None:
        """聚合所有检查。违规时抛 OutputValidationError；无违规时不抛错。

        Args:
            title: 章节标题
            content: 章节正文
            target_words: 目标字数（0 表示跳过比例检查）
            is_last_chapter: 是否为最后一章
            previous_ending: 上一章最后若干字（用于跨章相似度检查；空字符串或 None 跳过）
            previous_titles: 历史章节标题列表（用于跨章唯一性检查；空列表/None 跳过）
        """
        violations: list[str] = []
        category_counts: dict[str, int] = {}

        for cat, vlist in [
            ("title", self.validate_title(title)),
            ("title_unique", self.validate_title_uniqueness(title, previous_titles)),
            ("word_count", self.validate_word_count(content or "", target_words, is_last_chapter=is_last_chapter)),
            ("truncation", self.validate_truncation(content or "")),
            ("ai_trace", self.validate_ai_traces(content or "")),
            ("similarity", self.validate_similarity(content or "", previous_ending)),
        ]:
            for v in vlist:
                violations.append(v)
                category_counts[cat] = category_counts.get(cat, 0) + 1

        if not violations:
            return

        # 选择 category：以数量最多的类目为主；并列时优先选"title_unique"（对目录可读性最关键）
        # 然后按声明顺序：title → title_unique → word_count → ...
        _CATEGORY_PRIORITY = ["title_unique", "title", "word_count", "truncation", "ai_trace", "similarity"]
        if not category_counts:
            category = "mixed"
        else:
            max_count = max(category_counts.values())
            tied = [c for c, n in category_counts.items() if n == max_count]
            # 在并列里按 _CATEGORY_PRIORITY 选优先级最高的
            category = next((c for c in _CATEGORY_PRIORITY if c in tied), tied[0])
        # 不可恢复的情况：空内容（任何修复都不可能补出）
        recoverable = bool((content or "").strip()) and len(content or "") >= 50
        raise OutputValidationError(violations=violations, category=category, recoverable=recoverable)


@dataclass
class TitleSanitizer:
    """无 LLM 的标题清洗。

    用于在 LLM 标题生成失败或输出仍含脏词时，剥除脏词得到一个可用的回退标题。

    使用方式：
        sanitizer = TitleSanitizer()
        safe_title = sanitizer.clean("主角离开安全区", chapter_index=13)
        # -> "安全区"（剥除前缀"主角"）
    """

    max_title_length: int = 6
    min_title_length: int = 2

    def clean(self, title: str, *, chapter_index: Optional[int] = None) -> str:
        """清洗标题。

        步骤：
        1. 去除空白
        2. 剥除 DIRTY_TITLE_PATTERNS 中所有模式（从前缀和后缀方向）
        3. 长度规范化：超长截断、过短补"第N章"占位
        4. 若仍为空，用 `第{idx+1}节` 兜底
        """
        if not title:
            return self._fallback(chapter_index)

        text = title.strip()
        if not text:
            return self._fallback(chapter_index)

        # 延迟导入
        from agents.planner_agent import PlannerAgent
        patterns = PlannerAgent.DIRTY_TITLE_PATTERNS

        # 反复剥除前缀和后缀中的脏词模式（最多 5 轮，防止异常输入死循环）
        for _ in range(5):
            changed = False
            for pat in patterns:
                if text.startswith(pat):
                    text = text[len(pat):]
                    changed = True
                if text.endswith(pat):
                    text = text[: -len(pat)] if len(text) > len(pat) else ""
                    changed = True
            if not changed:
                break

        text = text.strip()
        if not text:
            return self._fallback(chapter_index)

        # 长度截断
        if len(text) > self.max_title_length:
            text = text[: self.max_title_length]
        if len(text) < self.min_title_length:
            # 太短，尝试补一个"第N章"占位
            if chapter_index is not None:
                return f"第{chapter_index + 1}章"
            return text  # 至少返回非空

        return text

    def _fallback(self, chapter_index: Optional[int]) -> str:
        if chapter_index is not None:
            return f"第{chapter_index + 1}节"
        return "未命名章节"

    def clean_batch(self, outlines: list) -> list:
        """批量清洗 ChapterOutline 列表的 title 字段。原地修改并返回。"""
        for i, outline in enumerate(outlines):
            title = getattr(outline, "title", None) or ""
            fixed = self.clean(title, chapter_index=i)
            if hasattr(outline, "title"):
                outline.title = fixed
        return outlines
