"""P2-A：质量门硬/软分级策略。

**这是一个纯分类层**，只回答"某个 gate 名字属于 hard 还是 soft"，不抛异常，
不接 LLM，不修改任何已有质量门实现。

设计目标：
1. **解耦**：把"哪些门必须重试 / 哪些门只警告"集中在一个地方，未来调整不影响调用方
2. **可枚举**：提供 `HARD_GATES` / `SOFT_GATES` / `ALL_GATES` 集合，方便遍历
3. **可观测**：未知 gate 名时 `logger.warning`，方便发现新加的门忘了登记
4. **零依赖**：不 import 任何业务模块（避免循环 import）；调用方自行 import

## 用法

```python
from core.quality_policy import is_hard_gate, is_soft_gate, classify_gate

if is_hard_gate("title"):
    # 失败时重试
else:
    # 软门只 WARN，不重试
```

## 后续扩展

如果 `core.validators.OutputValidator` 被重建（本轮**不**做，详见 plan §8.0），
可以直接 import `is_hard_gate` / `is_soft_gate` 来决定是否抛 `OutputValidationError`。
"""
from __future__ import annotations

import logging
from typing import Final

logger = logging.getLogger(__name__)


# 硬门：失败必须重试（标题空 / 字数严重不足 / 截断 / 完全空）
HARD_GATES: Final[frozenset[str]] = frozenset({
    "title",          # 标题必须存在且非默认占位
    "word_count",     # 字数必须达到下限（严苛）
    "truncation",     # 正文不能在中途截断
    "empty_content",  # 完全空内容
})

# 软门：失败只 WARN（可后续润色），不触发重试
SOFT_GATES: Final[frozenset[str]] = frozenset({
    "ai_traces",       # AI 味偏重，可局部润色
    "similarity",      # 与前文重复度偏高，可调整用词
    "title_unique",    # 标题与历史重复，可微调
    "style_drift",     # 风格漂移，可调整 temperature
})

# 全部已登记的 gate 名
ALL_GATES: Final[frozenset[str]] = HARD_GATES | SOFT_GATES


# 软门帮助文本（便于前端展示 / 调试）
GATE_HELP_TEXT: Final[dict[str, str]] = {
    # 硬门
    "title": "标题必须存在且非默认占位",
    "word_count": "字数必须达到下限（严苛）",
    "truncation": "正文不能在中途截断",
    "empty_content": "完全空内容",
    # 软门
    "ai_traces": "AI 味偏重，可局部润色",
    "similarity": "与前文重复度偏高，可调整用词",
    "title_unique": "标题与历史重复，可微调",
    "style_drift": "风格漂移，可调整 temperature",
}


def is_hard_gate(name: str) -> bool:
    """判断一个 gate 名是否属于"必须重试"的硬门。"""
    return name in HARD_GATES


def is_soft_gate(name: str) -> bool:
    """判断一个 gate 名是否属于"只 WARN"的软门。"""
    return name in SOFT_GATES


def classify_gate(name: str) -> str:
    """三态分类：'hard' | 'soft' | 'unknown'。

    未知 gate 名时打 `logger.warning` 提醒开发者补登记（不会抛异常）。
    """
    if name in HARD_GATES:
        return "hard"
    if name in SOFT_GATES:
        return "soft"
    logger.warning(
        f"[quality_policy] gate {name!r} is not registered; "
        f"known gates: {sorted(ALL_GATES)}"
    )
    return "unknown"


def help_text(name: str) -> str:
    """返回 gate 的中文说明（用于前端 / 日志 / 调试）。未知 gate 返回空串。"""
    return GATE_HELP_TEXT.get(name, "")


__all__ = [
    "HARD_GATES",
    "SOFT_GATES",
    "ALL_GATES",
    "GATE_HELP_TEXT",
    "is_hard_gate",
    "is_soft_gate",
    "classify_gate",
    "help_text",
]
