import asyncio
import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskRecord:
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0


class TaskQueue:
    def __init__(self, max_size: int = 100, max_concurrent: int = 2):
        self.max_size = max_size
        self.max_concurrent = max_concurrent
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._tasks: dict[str, TaskRecord] = {}
        self._running_count: int = 0
        self._workers: list[asyncio.Task] = []
        self._started = False

    async def submit(self, task_id: str, coro_factory: Callable, *args, **kwargs) -> str:
        if self._queue.full():
            raise ValueError(f"Task queue full (max_size={self.max_size})")
        record = TaskRecord(task_id=task_id)
        self._tasks[task_id] = record
        await self._queue.put((task_id, coro_factory, args, kwargs))
        if not self._started:
            self._start_workers()
        return task_id

    def _start_workers(self):
        self._started = True
        for _ in range(self.max_concurrent):
            worker = asyncio.create_task(self._worker())
            self._workers.append(worker)

    async def _worker(self):
        while True:
            try:
                task_id, coro_factory, args, kwargs = await self._queue.get()
                record = self._tasks.get(task_id)
                if not record:
                    continue
                record.status = TaskStatus.RUNNING
                record.started_at = time.time()
                self._running_count += 1
                try:
                    result = await coro_factory(*args, **kwargs)
                    record.result = result
                    record.status = TaskStatus.COMPLETED
                except Exception as e:
                    record.error = str(e)
                    record.status = TaskStatus.FAILED
                    logger.error(f"Task {task_id} failed: {e}")
                finally:
                    record.completed_at = time.time()
                    self._running_count -= 1
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker error: {e}")

    def get_status(self, task_id: str) -> Optional[TaskRecord]:
        return self._tasks.get(task_id)

    def get_result(self, task_id: str) -> Any:
        record = self._tasks.get(task_id)
        if record and record.status == TaskStatus.COMPLETED:
            return record.result
        return None

    async def shutdown(self):
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._started = False
