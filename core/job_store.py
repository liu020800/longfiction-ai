"""内存版任务状态存储。

为长时运行的 init / chapter 生成任务提供查询接口。
- 单进程足够使用
- 多 worker 部署时可替换为 Redis 实现
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4


class JobStore:
    """异步安全的任务状态存储（内存版）。"""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat(timespec="seconds") + "Z"

    async def create(
        self,
        *,
        project_id: str,
        job_type: str,
        label: str,
    ) -> str:
        """创建任务并返回 job_id。"""
        job_id = f"{job_type}_{uuid4().hex[:12]}"
        async with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "project_id": project_id,
                "type": job_type,
                "label": label,
                "status": "queued",
                "stage": "等待执行",
                "progress": 0.0,
                "result": None,
                "error": "",
                "created_at": self._now(),
                "updated_at": self._now(),
            }
        return job_id

    async def update(self, job_id: str, **kwargs: Any) -> None:
        """更新任务字段。"""
        async with self._lock:
            job = self._jobs.setdefault(job_id, {"id": job_id})
            job.update(kwargs)
            job["updated_at"] = self._now()

    async def get(self, job_id: str) -> Optional[dict[str, Any]]:
        """读取单个任务状态。"""
        async with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    async def list_by_project(self, project_id: str) -> list[dict[str, Any]]:
        """列出项目的所有任务。"""
        async with self._lock:
            return [
                dict(job)
                for job in self._jobs.values()
                if job.get("project_id") == project_id
            ]


job_store = JobStore()
