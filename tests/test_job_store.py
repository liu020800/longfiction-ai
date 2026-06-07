"""测试 core.job_store.JobStore 的并发安全 CRUD。"""
import asyncio

import pytest

from core.job_store import JobStore


class TestJobStore:
    @pytest.fixture
    def store(self):
        return JobStore()

    @pytest.mark.asyncio
    async def test_create_returns_unique_id(self, store):
        jid1 = await store.create(project_id="p1", job_type="init", label="l1")
        jid2 = await store.create(project_id="p1", job_type="init", label="l2")
        assert jid1 != jid2
        assert jid1.startswith("init_")
        assert jid2.startswith("init_")

    @pytest.mark.asyncio
    async def test_create_initial_status_queued(self, store):
        jid = await store.create(project_id="p1", job_type="init", label="l1")
        job = await store.get(jid)
        assert job is not None
        assert job["status"] == "queued"
        assert job["stage"] == "等待执行"
        assert job["progress"] == 0.0
        assert job["error"] == ""
        assert "created_at" in job
        assert "updated_at" in job

    @pytest.mark.asyncio
    async def test_update_status_and_progress(self, store):
        jid = await store.create(project_id="p1", job_type="init", label="l1")
        await store.update(jid, status="running", stage="生成中", progress=0.5)
        job = await store.get(jid)
        assert job["status"] == "running"
        assert job["stage"] == "生成中"
        assert job["progress"] == 0.5

    @pytest.mark.asyncio
    async def test_update_preserves_other_fields(self, store):
        jid = await store.create(project_id="p1", job_type="init", label="original_label")
        await store.update(jid, status="running")
        job = await store.get(jid)
        # label 等创建时的字段必须保留
        assert job["label"] == "original_label"
        assert job["project_id"] == "p1"
        assert job["type"] == "init"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, store):
        result = await store.get("nonexistent_xxx")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_by_project_filters_correctly(self, store):
        await store.create(project_id="p1", job_type="init", label="a")
        await store.create(project_id="p1", job_type="chapter_0", label="b")
        await store.create(project_id="p2", job_type="init", label="c")

        p1_jobs = await store.list_by_project("p1")
        p2_jobs = await store.list_by_project("p2")

        assert len(p1_jobs) == 2
        assert len(p2_jobs) == 1
        assert all(j["project_id"] == "p1" for j in p1_jobs)
        assert p2_jobs[0]["label"] == "c"

    @pytest.mark.asyncio
    async def test_list_by_project_empty_when_no_match(self, store):
        await store.create(project_id="p1", job_type="init", label="a")
        jobs = await store.list_by_project("nonexistent_project")
        assert jobs == []

    @pytest.mark.asyncio
    async def test_concurrent_creates_are_safe(self, store):
        """50 个并发 create 不应丢失任何 job。"""
        async def create_one(i):
            return await store.create(project_id=f"p{i}", job_type="init", label=f"job-{i}")

        results = await asyncio.gather(*[create_one(i) for i in range(50)])
        assert len(results) == 50
        assert len(set(results)) == 50  # 全部唯一

    @pytest.mark.asyncio
    async def test_concurrent_updates_are_safe(self, store):
        """同一 job 的并发 update 不应丢失写。"""
        jid = await store.create(project_id="p1", job_type="init", label="x")

        async def set_progress(p: float):
            await store.update(jid, progress=p)

        await asyncio.gather(*[set_progress(i / 10) for i in range(10)])
        job = await store.get(jid)
        # 最终 progress 应在 0.0~0.9 之间（最后一次写入决定）
        assert job["progress"] is not None
        assert 0.0 <= job["progress"] <= 0.9

    @pytest.mark.asyncio
    async def test_update_creates_if_not_exists(self, store):
        """update 一个不存在的 job_id 会创建空 dict（设计如此：setdefault 语义）。"""
        await store.update("brand_new_id", status="running")
        job = await store.get("brand_new_id")
        assert job is not None
        assert job["id"] == "brand_new_id"
        assert job["status"] == "running"

    @pytest.mark.asyncio
    async def test_get_returns_copy_not_reference(self, store):
        """get 返回的应是 dict 副本，修改它不应影响 store。"""
        jid = await store.create(project_id="p1", job_type="init", label="x")
        job = await store.get(jid)
        job["status"] = "tampered"
        job2 = await store.get(jid)
        assert job2["status"] == "queued"  # 原值未被修改
