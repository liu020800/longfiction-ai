"""异步任务线程池。

用于并发执行多个独立的 LLM 调用，提升生成速度。
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """任务结果。"""
    name: str
    success: bool
    value: Any = None
    error: Optional[Exception] = None
    duration: float = 0.0


class AsyncTaskPool:
    """异步任务池。

    限制并发数，避免对 LLM API 造成过大压力。
    """

    def __init__(self, max_concurrent: int = 4):
        self.max_concurrent = max_concurrent
        self._semaphore: Optional[asyncio.Semaphore] = None

    async def run_many(
        self,
        tasks: list[tuple[str, Callable[[], Awaitable[Any]]]],
    ) -> list[TaskResult]:
        """并发运行多个任务。

        Args:
            tasks: [(name, async_func), ...]

        Returns:
            按输入顺序的结果列表
        """
        if not tasks:
            return []
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)

        async def run_with_sem(name: str, func: Callable[[], Awaitable[Any]]) -> TaskResult:
            import time
            async with self._semaphore:
                start = time.monotonic()
                try:
                    value = await func()
                    return TaskResult(
                        name=name,
                        success=True,
                        value=value,
                        duration=time.monotonic() - start,
                    )
                except Exception as e:
                    return TaskResult(
                        name=name,
                        success=False,
                        error=e,
                        duration=time.monotonic() - start,
                    )

        coros = [run_with_sem(name, func) for name, func in tasks]
        return await asyncio.gather(*coros)

    async def run_with_limit(
        self,
        func: Callable[[Any], Awaitable[Any]],
        items: list[Any],
    ) -> list[Any]:
        """对列表中的每个 item 并发运行 func，限制并发数。"""
        if not items:
            return []
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)

        async def run_one(item):
            async with self._semaphore:
                return await func(item)

        return await asyncio.gather(*[run_one(item) for item in items])


# 全局默认池
_default_pool: Optional[AsyncTaskPool] = None


def get_pool(max_concurrent: int = 4) -> AsyncTaskPool:
    """获取全局任务池。"""
    global _default_pool
    if _default_pool is None:
        _default_pool = AsyncTaskPool(max_concurrent=max_concurrent)
    return _default_pool


# ============================================================
# 向后兼容：旧 API 类名
# ============================================================

class ThreadPool:
    """兼容旧 API 的线程池。

    提供简单的线程池接口。
    """

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.async_pool = AsyncTaskPool(max_concurrent=max_workers)

    async def map(self, func, items: list):
        """异步 map。"""
        return await self.async_pool.run_with_limit(func, items)

    async def run(self, *tasks):
        """运行多个任务。"""
        return await self.async_pool.run_many(tasks)

    def shutdown(self):
        pass
