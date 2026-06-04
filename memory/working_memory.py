"""工作记忆。

存储当前章节生成所需的活跃信息（短期焦点），区别于短期记忆的"历史章节"。
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class SceneContext:
    """当前场景上下文（兼容旧 API）。"""
    location: str = ""
    time: str = ""
    characters: list[str] = field(default_factory=list)
    mood: str = ""
    tension: int = 5
    last_action: str = ""
    pending_reveals: list[str] = field(default_factory=list)


@dataclass
class WorkingMemoryItem:
    """工作记忆项。"""
    key: str
    value: Any
    priority: int = 5  # 1-10, 10 = 最高
    added_at: float = 0.0
    access_count: int = 0


class WorkingMemory:
    """工作记忆。

    容量有限（默认 20 项），按优先级和最近访问淘汰。
    用于存储当前章节生成时最相关的信息：
    - 当前场景描述
    - 正在描写的角色
    - 关键物品/伏笔
    - 用户的创作指导
    """

    def __init__(self, capacity: int = 20):
        self.capacity = capacity
        self._items: OrderedDict[str, WorkingMemoryItem] = OrderedDict()

    def set(self, key: str, value: Any, priority: int = 5):
        """设置工作记忆项。"""
        import time
        if key in self._items:
            self._items[key].value = value
            self._items[key].priority = priority
            self._items.move_to_end(key)
        else:
            if len(self._items) >= self.capacity:
                # 淘汰最低优先级 + 最久未访问
                self._evict()
            self._items[key] = WorkingMemoryItem(
                key=key,
                value=value,
                priority=priority,
                added_at=time.time(),
            )

    def get(self, key: str, default: Any = None) -> Any:
        """获取工作记忆项。"""
        if key in self._items:
            self._items[key].access_count += 1
            self._items.move_to_end(key)
            return self._items[key].value
        return default

    def has(self, key: str) -> bool:
        return key in self._items

    def remove(self, key: str):
        if key in self._items:
            del self._items[key]

    def clear(self):
        self._items.clear()

    def _evict(self):
        """淘汰一项。"""
        if not self._items:
            return
        # 找到优先级最低且最久未访问的
        min_item = min(
            self._items.values(),
            key=lambda x: (x.priority, x.added_at),
        )
        del self._items[min_item.key]

    def keys(self) -> list[str]:
        return list(self._items.keys())

    def values(self) -> list[Any]:
        return [item.value for item in self._items.values()]

    def to_prompt(self) -> str:
        """转换为 prompt 文本。"""
        if not self._items:
            return ""
        lines = ["## 当前场景焦点\n"]
        for item in self._items.values():
            if isinstance(item.value, str):
                lines.append(f"- [{item.priority}] {item.key}: {item.value}")
            else:
                lines.append(f"- [{item.priority}] {item.key}: {str(item.value)[:200]}")
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key: str) -> bool:
        return key in self._items
