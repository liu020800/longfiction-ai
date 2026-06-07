from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from datetime import datetime
import uuid
import logging
from pathlib import Path
import json
import zipfile
import tempfile

from core.config import settings
from core.models import GenerationRequest, TaskType
from core.database import get_db, init_db, SessionLocal
from core.auth import (
    hash_password, verify_password, create_access_token, decode_token,
    get_current_user, get_current_user_optional, require_role, deduct_balance,
    CHAPTER_COST,
)
from core.job_store import job_store
from models.user_service import UserService
from main_pipeline import MainPipeline
from models.db_service import (
    ProjectService, CharacterService, WorldService, 
    ChapterService, TimelineService, PlotArcService, ForeshadowingService
)

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = PROJECT_ROOT / settings.STATIC_DIR

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API请求日志中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    import time as _time
    from core.logging_util import Timer as _Timer
    timer = _Timer()
    body_preview = ""
    try:
        body = await request.body()
        body_str = body.decode("utf-8", errors="replace")
        body_preview = body_str[:200] if len(body_str) > 200 else body_str
    except Exception:
        pass
    logger.info(
        ">>> %s %s  body=%s",
        request.method, request.url.path, body_preview,
    )
    try:
        response = await call_next(request)
        elapsed = timer.elapsed_ms
        logger.info(
            "<<< %s %s → %d (%dms)",
            request.method, request.url.path, response.status_code, elapsed,
        )
        return response
    except Exception as e:
        elapsed = timer.elapsed_ms
        import traceback as _tb
        logger.error(
            "<<< %s %s ✗ %dms %s\n%s",
            request.method, request.url.path, elapsed, e, _tb.format_exc(),
        )
        raise

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

pipelines: dict[str, MainPipeline] = {}
generation_tasks: dict[str, dict] = {}


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _task_key(project_id: str, task_type: str) -> str:
    return f"{task_type}_{project_id}"


def _set_task(task_id: str, *, project_id: str, task_type: str, label: str, stage: str = "准备中", progress: float = 0.0, **extra):
    task = generation_tasks.get(task_id, {})
    task.update({
        "id": task_id,
        "task_id": project_id,
        "project_id": project_id,
        "type": task_type,
        "label": label,
        "stage": stage,
        "status": "running",
        "progress": progress,
        "updated_at": _now_iso(),
    })
    task.update(extra)
    generation_tasks[task_id] = task
    return task


def _complete_task(task_id: str, *, stage: str = "已完成", progress: float = 1.0, **extra):
    task = generation_tasks.get(task_id, {"id": task_id})
    task.update({
        "status": "completed",
        "stage": stage,
        "progress": progress,
        "updated_at": _now_iso(),
        "task_id": task_id,
    })
    task.update(extra)
    generation_tasks[task_id] = task
    return task


def _fail_task(task_id: str, error: Exception | str):
    task = generation_tasks.get(task_id, {"id": task_id})
    err_str = str(error)
    if "Inappropriate" in err_str or "content_policy" in err_str or "safety" in err_str.lower():
        user_msg = "LLM内容安全过滤器拒绝了请求。建议检查大纲和已有章节内容是否涉及敏感话题，修改后重试。"
    elif "timeout" in err_str.lower() or "Timeout" in err_str:
        user_msg = "LLM请求超时。请检查LLM服务是否可用，或稍后重试。"
    elif "Connection" in err_str or "connect" in err_str.lower():
        user_msg = "无法连接LLM服务。请检查网络和API配置。"
    else:
        user_msg = err_str[:300]
    task.update({
        "status": "failed",
        "stage": "失败",
        "error": user_msg,
        "updated_at": _now_iso(),
    })
    generation_tasks[task_id] = task
    return task


def _normalize_api_error(exc: Exception) -> HTTPException:
    message = str(exc)
    lowered = message.lower()
    if "connection error" in lowered or "timeout" in lowered or "api key not configured" in lowered:
        return HTTPException(status_code=503, detail=f"写作模型服务暂时不可用：{message}")
    return HTTPException(status_code=500, detail=message)


def _project_tasks(project_id: str) -> list[dict]:
    tasks = [
        task for task in generation_tasks.values()
        if task.get("project_id") == project_id or task.get("task_id") == project_id
    ]
    status_rank = {"running": 0, "completed": 1}
    return sorted(
        tasks,
        key=lambda item: (status_rank.get(str(item.get("status", "")).split(":")[0], 2), item.get("updated_at", "")),
        reverse=False,
    )


def get_or_load_pipeline(task_id: str) -> MainPipeline | None:
    pipeline = pipelines.get(task_id)
    if pipeline:
        return pipeline
    pipeline = MainPipeline(session_id=task_id)
    if pipeline.load_from_database():
        try:
            pipeline._refresh_enhancement_baseline(force=True)
        except Exception as e:
            logger.warning(f"Enhancement baseline refresh failed for {task_id}: {e}")
        pipelines[task_id] = pipeline
        return pipeline
    if pipeline.load_project_state():
        try:
            pipeline.ensure_project_in_database()
        except Exception as e:
            logger.warning(f"Project state DB migration failed for {task_id}: {e}")
        try:
            pipeline._refresh_enhancement_baseline(force=True)
        except Exception as e:
            logger.warning(f"Enhancement baseline refresh failed for {task_id}: {e}")
        pipelines[task_id] = pipeline
        return pipeline
    return None


class InitResponse(BaseModel):
    task_id: str
    status: str
    result: dict


class ChapterRequest(BaseModel):
    task_id: str
    chapter_index: int = Field(ge=0)
    multi_version: bool = True
    guidance: str = ""
    target_words: int | None = Field(default=None, ge=100, le=10000)
    auto_finalize: bool = True


class ContinueChapterRequest(BaseModel):
    task_id: str
    chapter_index: int = Field(ge=0)
    guidance: str = ""
    target_words: int = Field(default=800, ge=100, le=5000)


class FragmentReviseRequest(BaseModel):
    task_id: str
    chapter_index: int = Field(ge=0)
    fragment: str
    guidance: str = ""


class RegenerateChapterRequest(ChapterRequest):
    pass


class ProjectUpdateRequest(BaseModel):
    task_id: str
    outline: str
    genre: str = "urban_fantasy"
    style: str = "web_novel"
    target_chapters: int = Field(default=12, ge=1, le=300)
    words_per_chapter: int = Field(default=2000, ge=200, le=10000)
    world: dict
    characters: list[dict]
    chapters: list[dict]


class ProjectRegenerateRequest(BaseModel):
    task_id: str
    prompt_hint: str = ""


class StyleFingerprintAnalyzeRequest(BaseModel):
    task_id: str
    sample_text: str = Field(min_length=20, max_length=50000)


class ProjectMetadataRequest(BaseModel):
    task_id: str
    title: str = ""
    outline: str
    genre: str = "urban_fantasy"
    style: str = "web_novel"
    target_chapters: int = Field(default=12, ge=1, le=300)
    words_per_chapter: int = Field(default=2000, ge=200, le=10000)


class ImportNovelRequest(BaseModel):
    task_id: str
    text: str


class ChapterFinalizeRequest(BaseModel):
    task_id: str
    chapter_index: int = Field(ge=0)


class GenerateAllRequest(BaseModel):
    outline: str
    genre: str = "urban_fantasy"
    style: str = "web_novel"
    target_chapters: int = Field(default=12, ge=1, le=300)
    words_per_chapter: int = Field(default=2000, ge=200, le=10000)
    max_chapters: int = Field(default=3, ge=1, le=50)


class BatchGenerateRequest(BaseModel):
    task_id: str
    start_chapter: int = Field(default=0, ge=0)
    end_chapter: int = Field(default=0, ge=0)
    consistency_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    auto_finalize: bool = True
    max_retries: int = Field(default=1, ge=0, le=5)


@app.get("/")
async def root():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"name": settings.PROJECT_NAME, "version": settings.VERSION, "status": "running"}


@app.get("/editor")
async def editor_page():
    return RedirectResponse(url="/", status_code=301)


@app.get("/api/health")
async def health():
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
        "llm_configured": bool(settings.LLM_API_KEY),
        "warnings": settings.config_warnings(),
        "models": {
            "default": settings.LLM_DEFAULT_MODEL,
            "planner": settings.LLM_PLANNER_MODEL,
            "writer": settings.LLM_WRITER_MODEL,
            "style": settings.LLM_STYLE_MODEL,
            "check": settings.LLM_CHECK_MODEL,
            "embedding": settings.EMBEDDING_MODEL,
        },
    }


@app.get("/api/model-router/stats")
async def model_router_stats():
    from core.model_router import model_router
    from core.models import TaskType
    stats = model_router.get_stats()
    recommendations = {}
    for task_type in TaskType:
        recommendations[task_type.value] = model_router.get_recommendation(task_type)
    return {"stats": stats, "recommendations": recommendations}


@app.get("/api/llm-config")
async def get_llm_config(current_user: dict = Depends(get_current_user)):
    is_admin = current_user.get("role") == "admin"
    return {
        "api_base": settings.LLM_API_BASE,
        "api_key_set": bool(settings.LLM_API_KEY),
        "api_key_preview": ("*" * 8 + settings.LLM_API_KEY[-4:]) if settings.LLM_API_KEY and len(settings.LLM_API_KEY) > 4 else "",
        "models": {
            "default": settings.LLM_DEFAULT_MODEL,
            "planner": settings.LLM_PLANNER_MODEL,
            "writer": settings.LLM_WRITER_MODEL,
            "style": settings.LLM_STYLE_MODEL,
            "check": settings.LLM_CHECK_MODEL,
            "embedding": settings.EMBEDDING_MODEL,
        },
        "use_response_format": settings.LLM_USE_RESPONSE_FORMAT,
        "timeout_seconds": settings.LLM_TIMEOUT_SECONDS,
        "warnings": settings.config_warnings(),
        "is_admin": is_admin,
    }


@app.get("/api/llm/test")
async def test_llm(current_user: dict = Depends(get_current_user)):
    """真实 LLM 可用性探针：先 chat 再 json，明确错误分类。"""
    from core.llm_probe import probe_llm_all
    result = await probe_llm_all()
    if not result["ok"]:
        raise HTTPException(status_code=503, detail=result)
    return result


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, current_user: dict = Depends(get_current_user)):
    """查询任务状态。"""
    job = await job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/projects/{task_id}/jobs")
async def list_project_jobs(task_id: str, current_user: dict = Depends(get_current_user)):
    """列出项目所有任务。"""
    return {
        "task_id": task_id,
        "jobs": await job_store.list_by_project(task_id),
    }


class LlmConfigUpdate(BaseModel):
    api_key: str = ""
    api_base: str = ""
    models: dict = {}
    use_response_format: bool = False
    timeout_seconds: int = 90


@app.put("/api/llm-config")
async def update_llm_config(req: LlmConfigUpdate, current_user: dict = Depends(require_role("admin"))):
    logger.info(f"LLM config PUT received, user={current_user.get('username')}")
    body = req.model_dump()
    logger.info(f"LLM config update body keys: {list(body.keys())}")
    try:
        result = _apply_llm_config(body)
        logger.info(f"LLM config applied, env_persisted={result.get('env_persisted')}")
        return result
    except Exception as e:
        logger.error(f"LLM config apply failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"配置应用失败: {e}")


import re as _re

def _persist_env_file(changes: dict[str, str]) -> bool:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        logger.warning(f".env file not found at {env_path}, skipping persist")
        return False

    key_aliases = {
        "LLM_API_KEY": ["LLM_API_KEY", "OPENAI_API_KEY"],
        "LLM_API_BASE": ["LLM_API_BASE", "OPENAI_API_BASE"],
        "LLM_DEFAULT_MODEL": ["LLM_DEFAULT_MODEL", "LLM_MODEL"],
        "EMBEDDING_MODEL": ["EMBEDDING_MODEL"],
    }

    try:
        text = env_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read .env: {e}")
        return False

    for key, val in changes.items():
        aliases = key_aliases.get(key, [key])
        found = False
        for alias in aliases:
            pattern = _re.compile(r"^{}\s*=".format(_re.escape(alias)), _re.MULTILINE)
            m = pattern.search(text)
            if m:
                line_start = m.start()
                line_end = text.find("\n", line_start)
                if line_end == -1:
                    line_end = len(text)
                new_line = f"{alias}={val}"
                text = text[:line_start] + new_line + text[line_end:]
                found = True
                break
        if not found:
            text += f"\n{key}={val}\n"

    try:
        env_path.write_text(text, encoding="utf-8")
        logger.info(f".env file updated at {env_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to write .env: {e}")
        return False


def _apply_llm_config(body: dict):
    from core.llm_router import MODEL_ROUTE, normalize_model_id
    import litellm

    if "api_key" in body and body["api_key"]:
        settings.LLM_API_KEY = body["api_key"]
        litellm.api_key = settings.LLM_API_KEY
    if "api_base" in body and body["api_base"]:
        settings.LLM_API_BASE = body["api_base"]
        litellm.api_base = settings.LLM_API_BASE

    models = body.get("models", {})
    model_field_map = {
        "default": "LLM_DEFAULT_MODEL",
        "planner": "LLM_PLANNER_MODEL",
        "writer": "LLM_WRITER_MODEL",
        "style": "LLM_STYLE_MODEL",
        "check": "LLM_CHECK_MODEL",
    }
    route_map = {
        "planner": [TaskType.PLAN, TaskType.WORLD, TaskType.CHARACTER, TaskType.PLOT],
        "writer": [TaskType.WRITE],
        "style": [TaskType.REWRITE],
        "check": [TaskType.CHECK],
    }
    for key, field in model_field_map.items():
        if key in models and models[key]:
            setattr(settings, field, models[key])
            if key in route_map:
                for tt in route_map[key]:
                    MODEL_ROUTE[tt] = models[key]
    if "embedding" in models and models["embedding"]:
        settings.EMBEDDING_MODEL = models["embedding"]
    if "use_response_format" in body:
        settings.LLM_USE_RESPONSE_FORMAT = bool(body["use_response_format"])
    if "timeout_seconds" in body:
        settings.LLM_TIMEOUT_SECONDS = int(body["timeout_seconds"])

    persist = {
        "LLM_API_KEY": settings.LLM_API_KEY,
        "LLM_API_BASE": settings.LLM_API_BASE,
        "LLM_DEFAULT_MODEL": settings.LLM_DEFAULT_MODEL,
        "LLM_PLANNER_MODEL": settings.LLM_PLANNER_MODEL,
        "LLM_WRITER_MODEL": settings.LLM_WRITER_MODEL,
        "LLM_STYLE_MODEL": settings.LLM_STYLE_MODEL,
        "LLM_CHECK_MODEL": settings.LLM_CHECK_MODEL,
        "EMBEDDING_MODEL": settings.EMBEDDING_MODEL,
        "LLM_USE_RESPONSE_FORMAT": str(settings.LLM_USE_RESPONSE_FORMAT).lower(),
        "LLM_TIMEOUT_SECONDS": str(settings.LLM_TIMEOUT_SECONDS),
    }

    env_persisted = _persist_env_file(persist)

    return {
        "ok": True,
        "env_persisted": env_persisted,
        "models": {
            "default": settings.LLM_DEFAULT_MODEL,
            "planner": settings.LLM_PLANNER_MODEL,
            "writer": settings.LLM_WRITER_MODEL,
            "style": settings.LLM_STYLE_MODEL,
            "check": settings.LLM_CHECK_MODEL,
            "embedding": settings.EMBEDDING_MODEL,
        },
        "api_base": settings.LLM_API_BASE,
        "warnings": settings.config_warnings(),
    }


@app.get("/api/config")
async def get_config():
    return {
        "project": settings.PROJECT_NAME,
        "chapter_min_words": settings.CHAPTER_MIN_WORDS,
        "scene_target_words": settings.SCENE_TARGET_WORDS,
        "multi_version_count": settings.MULTI_VERSION_COUNT,
        "memory_short_term_size": settings.MEMORY_SHORT_TERM_SIZE,
        "llm_configured": bool(settings.LLM_API_KEY),
        "warnings": settings.config_warnings(),
    }


@app.post("/api/init")
async def init_pipeline(
    request: GenerationRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """P0-4：初始化改为后台 Job 模式，1 秒内返回 job_id。"""
    from core.config import settings as app_settings
    absolute_max = getattr(
        app_settings, "MAX_TARGET_CHAPTERS_ABSOLUTE", app_settings.MAX_TARGET_CHAPTERS
    )
    if request.target_chapters > absolute_max:
        raise HTTPException(
            status_code=400,
            detail=f"target_chapters 不能超过 {absolute_max}",
        )
    if request.target_chapters < 1:
        raise HTTPException(status_code=400, detail="target_chapters must be >= 1")

    task_id = str(uuid.uuid4())[:8]
    job_id = await job_store.create(
        project_id=task_id, job_type="init", label="生成项目设定"
    )
    background_tasks.add_task(
        _run_init_job, job_id, task_id, request, current_user["id"]
    )
    return {
        "status": "queued",
        "task_id": task_id,
        "job_id": job_id,
        "message": "项目初始化任务已创建，请轮询 /api/jobs/{job_id}",
    }


async def _run_init_job(job_id: str, task_id: str, request: GenerationRequest, user_id: int):
    """后台执行项目初始化。"""
    from core.llm_probe import probe_llm_all

    await job_store.update(job_id, status="running", stage="检查 LLM 配置", progress=0.05)
    probe = await probe_llm_all()
    if not probe["ok"]:
        await job_store.update(
            job_id,
            status="failed",
            stage="LLM 配置不可用",
            progress=1.0,
            error={
                "error_type": probe.get("error_type"),
                "message": probe.get("error"),
                "chat": probe.get("chat"),
            },
        )
        return

    pipeline = MainPipeline(session_id=task_id)
    try:
        await job_store.update(
            job_id, stage="生成世界观、角色与首阶段章节规划", progress=0.15
        )
        result = await pipeline.initialize(request)
        actual_task_id = result.get("task_id", task_id)
        pipelines[actual_task_id] = pipeline

        with SessionLocal() as db:
            us = UserService(db)
            us.bind_project(user_id, actual_task_id, "owner")

        monitor_id = _task_key(actual_task_id, "init")
        _complete_task(
            monitor_id,
            stage="项目设定草稿已生成",
            project_id=actual_task_id,
            type="init",
            label="生成项目设定",
        )

        await job_store.update(
            job_id,
            status="completed",
            stage="项目设定草稿已生成",
            progress=1.0,
            result={"task_id": actual_task_id, "status": "initialized", "result": result},
        )
    except Exception as exc:
        logger.exception("Init job failed")
        monitor_id = _task_key(task_id, "init")
        _fail_task(monitor_id, exc)
        await job_store.update(
            job_id,
            status="failed",
            stage="初始化失败",
            progress=1.0,
            error=str(exc)[:1000],
        )


@app.post("/api/chapter")
async def generate_chapter(
    req: ChapterRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """P0-4：章节生成改为后台 Job 模式，1 秒内返回 job_id。"""
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    if not pipeline.volume:
        raise HTTPException(status_code=400, detail="Pipeline is not initialized")
    if req.chapter_index >= pipeline.target_chapters:
        raise HTTPException(status_code=400, detail="chapter_index out of range")
    if not pipeline.approved:
        raise HTTPException(status_code=400, detail="Project settings are not approved")
    if req.chapter_index > 0:
        generated_indices = {c.chapter_index for c in pipeline.generated_chapters}
        missing = [i for i in range(req.chapter_index) if i not in generated_indices]
        if missing:
            missing_str = ", ".join(str(i + 1) for i in missing)
            raise HTTPException(
                status_code=400,
                detail=f"顺序生成：第{req.chapter_index + 1}章的前置章节尚未生成（缺第{missing_str}章），请先按顺序生成前面的章节",
            )

    job_id = await job_store.create(
        project_id=req.task_id,
        job_type=f"chapter_{req.chapter_index}",
        label=f"生成第{req.chapter_index + 1}章",
    )
    background_tasks.add_task(_run_chapter_job, job_id, req)
    return {
        "status": "queued",
        "task_id": req.task_id,
        "job_id": job_id,
        "message": "章节生成任务已创建，请轮询 /api/jobs/{job_id}",
    }


async def _run_chapter_job(job_id: str, req: ChapterRequest):
    """后台执行章节生成。"""
    await job_store.update(job_id, status="running", stage="准备生成章节", progress=0.05)
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        await job_store.update(
            job_id, status="failed", stage="项目不存在", progress=1.0, error="Task not found"
        )
        return
    monitor_id = _task_key(req.task_id, f"chapter_{req.chapter_index}")
    try:
        await job_store.update(
            job_id, stage="写前规划、上下文检索与一致性预检", progress=0.15
        )
        generation_tasks[monitor_id].update(
            {"stage": "正文生成、去AI痕迹与一致性检查", "progress": 0.35, "updated_at": _now_iso()}
        )
        await job_store.update(
            job_id, stage="正文生成、去AI痕迹与一致性检查", progress=0.35
        )
        draft = await pipeline.generate_chapter(
            0, req.chapter_index, req.multi_version,
            guidance=req.guidance, target_words=req.target_words,
            auto_finalize=req.auto_finalize,
        )
        _complete_task(
            monitor_id, stage="章节正文已保存",
            chapter=draft.model_dump(), catalog=pipeline.get_chapter_catalog(),
        )
        await job_store.update(
            job_id, status="completed", stage="章节正文已保存",
            progress=1.0,
            result={"chapter": draft.model_dump(), "catalog": pipeline.get_chapter_catalog()},
        )
    except Exception as exc:
        logger.exception("Chapter job failed")
        try:
            pipeline.memory.clear_scene_context()
        except Exception:
            pass
        _fail_task(monitor_id, exc)
        await job_store.update(
            job_id, status="failed", stage="章节生成失败",
            progress=1.0, error=str(exc)[:1000],
        )


@app.post("/api/chapter/regenerate")
async def regenerate_chapter(req: RegenerateChapterRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    if not pipeline.volume:
        raise HTTPException(status_code=400, detail="Pipeline is not initialized")
    if req.chapter_index >= pipeline.target_chapters:
        raise HTTPException(status_code=400, detail="chapter_index out of range")
    if not pipeline.approved:
        raise HTTPException(status_code=400, detail="Project settings are not approved")
    monitor_id = _task_key(req.task_id, f"regenerate_chapter_{req.chapter_index}")
    _set_task(
        monitor_id,
        project_id=req.task_id,
        task_type="chapter",
        label=f"重生成第{req.chapter_index + 1}章正文",
        stage="清理旧草稿并重新生成",
        progress=0.08,
        chapter_index=req.chapter_index,
    )
    try:
        generation_tasks[monitor_id].update({"stage": "正文生成、去AI痕迹与一致性检查", "progress": 0.35, "updated_at": _now_iso()})
        draft = await pipeline.regenerate_chapter(0, req.chapter_index, req.multi_version, guidance=req.guidance, target_words=req.target_words, auto_finalize=req.auto_finalize)
        _complete_task(monitor_id, stage="章节正文已重生成", chapter=draft.model_dump(), catalog=pipeline.get_chapter_catalog())
        return {"status": "success", "chapter": draft.model_dump(), "catalog": pipeline.get_chapter_catalog()}
    except Exception as e:
        try:
            pipeline.memory.clear_scene_context()
        except Exception:
            pass
        _fail_task(monitor_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chapter/continue")
async def continue_chapter(req: ContinueChapterRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        draft = await pipeline.continue_chapter(req.chapter_index, req.guidance, req.target_words)
        return {"status": "success", "chapter": draft.model_dump(), "catalog": pipeline.get_chapter_catalog()}
    except Exception as e:
        raise _normalize_api_error(e)


@app.post("/api/chapter/revise")
async def revise_chapter(req: ContinueChapterRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        draft = await pipeline.revise_chapter(req.chapter_index, req.guidance)
        return {"status": "success", "chapter": draft.model_dump(), "catalog": pipeline.get_chapter_catalog()}
    except Exception as e:
        raise _normalize_api_error(e)


@app.post("/api/chapter/revise-fragment")
async def revise_fragment(req: FragmentReviseRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        draft = await pipeline.revise_fragment(req.chapter_index, req.fragment, req.guidance)
        return {"status": "success", "chapter": draft.model_dump(), "catalog": pipeline.get_chapter_catalog()}
    except Exception as e:
        raise _normalize_api_error(e)


@app.get("/api/catalog/{task_id}")
async def get_catalog(task_id: str, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task_id,
        "pipeline": pipeline.get_status(),
        "catalog": pipeline.get_chapter_catalog(),
        "volume_name": pipeline.volume.volume if pipeline.volume else "第一卷",
        "output_dir": pipeline.get_output_dir(),
    }


@app.get("/api/projects")
async def list_projects(current_user: dict = Depends(get_current_user)):
    projects = []
    is_admin = current_user.get("role") == "admin"
    user_project_ids = None

    if not is_admin:
        with SessionLocal() as db:
            us = UserService(db)
            user_projects = us.get_user_projects(current_user["id"])
            user_project_ids = set(up.project_id for up in user_projects)
    
    db_projects = []
    try:
        with SessionLocal() as db:
            ps = ProjectService(db)
            for p in ps.get_all_projects():
                if user_project_ids is not None and p.id not in user_project_ids:
                    continue
                db_projects.append({
                    "task_id": p.id,
                    "title": (getattr(p, "title", "") or "").strip() or (pipeline.title if (pipeline := get_or_load_pipeline(p.id)) else (p.outline[:28])),
                    "outline": p.outline[:120],
                    "approved": p.approved,
                    "total_chapters": p.target_chapters,
                    "generated": ps.count_generated_chapters(p.id),
                    "output_dir": f"output/sessions/{p.id}",
                    "source": "database",
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                })
    except Exception as e:
        logger.warning(f"Failed to load DB projects: {e}")
    
    file_projects = []
    base_dir = PROJECT_ROOT / "data" / "sessions"
    if base_dir.exists():
        for state_path in base_dir.glob("*/project_state.json"):
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                session_id = state_path.parent.name
                if user_project_ids is not None and session_id not in user_project_ids:
                    continue
                if any(p["task_id"] == session_id for p in db_projects):
                    continue
                volume = state.get("volume") or {}
                chapters = volume.get("chapters") or []
                generated = state.get("generated_chapters") or []
                file_projects.append({
                    "task_id": session_id,
                    "title": state.get("title", state.get("outline", "")[:28]),
                    "outline": state.get("outline", "")[:120],
                    "approved": state.get("approved", False),
                    "total_chapters": len(chapters),
                    "generated": len(generated),
                    "output_dir": state.get("output_dir", f"output/sessions/{session_id}"),
                    "source": "filesystem",
                })
            except Exception as e:
                logger.warning(f"Failed to load project state {state_path}: {e}")
    
    projects = db_projects + file_projects
    projects.sort(key=lambda x: x.get("created_at") or x["task_id"], reverse=True)
    return {"projects": projects}


@app.get("/api/project/{task_id}")
async def get_project(task_id: str, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    return pipeline.get_project_data()


@app.get("/api/style-fingerprint/{task_id}")
async def get_style_fingerprint(task_id: str, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task_id,
        "style_fingerprint": pipeline.style_fingerprint or {},
    }


@app.post("/api/style-fingerprint/analyze")
async def analyze_style_fingerprint(req: StyleFingerprintAnalyzeRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        fingerprint = pipeline.analyze_style_fingerprint(req.sample_text)
        return {
            "task_id": req.task_id,
            "style_fingerprint": fingerprint,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/project")
async def update_project(req: ProjectUpdateRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        project = pipeline.update_project_data(req.outline, req.genre, req.style, req.target_chapters, req.words_per_chapter, req.world, req.characters, req.chapters)
        return {"status": "approved", "project": project, "catalog": pipeline.get_chapter_catalog()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/project/meta")
async def update_project_meta(req: ProjectMetadataRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        project = pipeline.update_project_metadata(req.title, req.outline, req.genre, req.style, req.target_chapters, req.words_per_chapter)
        return {"status": "updated", "project": project}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/project/import-txt")
async def import_project_txt(req: ImportNovelRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        chapters = pipeline.import_existing_novel(req.text)
        return {"status": "imported", "chapters": chapters, "catalog": pipeline.get_chapter_catalog(), "project": pipeline.get_project_data()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/project/regenerate/world")
async def regenerate_world(req: ProjectRegenerateRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    monitor_id = _task_key(req.task_id, "world")
    _set_task(monitor_id, project_id=req.task_id, task_type="world", label="重生成世界观", stage="生成世界规则、势力、历史与地点", progress=0.2)
    try:
        world = await pipeline.regenerate_world(req.prompt_hint)
        _complete_task(monitor_id, stage="世界观已生成", world=world)
        return {"status": "ok", "world": world, "project": pipeline.get_project_data()}
    except Exception as e:
        _fail_task(monitor_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/project/regenerate/characters")
async def regenerate_characters(req: ProjectRegenerateRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    monitor_id = _task_key(req.task_id, "characters")
    _set_task(monitor_id, project_id=req.task_id, task_type="characters", label="重生成角色", stage="生成角色表、关系和初始状态", progress=0.2)
    try:
        characters = await pipeline.regenerate_characters(req.prompt_hint)
        _complete_task(monitor_id, stage="角色设定已生成", characters=characters)
        return {"status": "ok", "characters": characters, "project": pipeline.get_project_data()}
    except Exception as e:
        _fail_task(monitor_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/project/regenerate/chapters")
async def regenerate_chapter_plan(req: ProjectRegenerateRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    monitor_id = _task_key(req.task_id, "chapters")
    _set_task(monitor_id, project_id=req.task_id, task_type="chapters", label="重生成章节规划", stage="规划近期阶段章节并拆分场景", progress=0.2)
    try:
        chapters = await pipeline.regenerate_chapter_plan(req.prompt_hint)
        _complete_task(monitor_id, stage="章节规划已生成", chapters=chapters, catalog=pipeline.get_chapter_catalog())
        return {"status": "ok", "chapters": chapters, "catalog": pipeline.get_chapter_catalog(), "project": pipeline.get_project_data()}
    except Exception as e:
        _fail_task(monitor_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chapter/finalize")
async def finalize_chapter(req: ChapterFinalizeRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    if req.chapter_index >= (len(pipeline.volume.chapters) if pipeline.volume else 0):
        raise HTTPException(status_code=400, detail="chapter_index out of range")
    result = await pipeline.finalize_chapter(req.chapter_index)
    return {"status": "finalized", "result": result, "catalog": pipeline.get_chapter_catalog()}


@app.post("/api/chapter/unfinalize")
async def unfinalize_chapter(req: ChapterFinalizeRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    if req.chapter_index >= (len(pipeline.volume.chapters) if pipeline.volume else 0):
        raise HTTPException(status_code=400, detail="chapter_index out of range")
    return {"status": "draft", "result": pipeline.unfinalize_chapter(req.chapter_index), "catalog": pipeline.get_chapter_catalog()}


@app.get("/api/export/{task_id}")
async def export_project(task_id: str, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")

    temp_dir = Path(tempfile.gettempdir()) / "longfiction_exports"
    temp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = temp_dir / f"{task_id}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        state_path = Path(pipeline.get_state_path())
        if state_path.exists():
            zf.write(state_path, arcname="project_state.json")

        output_dir = Path(pipeline.get_output_dir())
        if output_dir.exists():
            for file in output_dir.glob("*"):
                if file.is_file():
                    zf.write(file, arcname=f"chapters/{file.name}")

    return FileResponse(zip_path, filename=f"longfiction_{task_id}.zip", media_type="application/zip")


@app.get("/api/export/{task_id}/txt")
async def export_project_txt(task_id: str, finalized_only: bool = False, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")

    # P2 程序级修复：使用 pipeline.export_to_txt() 统一实现，便于测试和复用
    temp_dir = Path(tempfile.gettempdir()) / "longfiction_exports"
    try:
        txt_path = pipeline.export_to_txt(
            finalized_only=finalized_only,
            output_dir=str(temp_dir),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return FileResponse(
        txt_path,
        filename=f"longfiction_{task_id}{'_finalized' if finalized_only else ''}.txt",
        media_type="text/plain",
    )


@app.get("/api/export/{task_id}/epub")
async def export_project_epub(task_id: str, finalized_only: bool = False, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")

    chapters = sorted(pipeline.generated_chapters, key=lambda c: c.chapter_index)
    if finalized_only:
        chapters = [c for c in chapters if c.chapter_index in pipeline.finalized_chapters]
    if not chapters:
        raise HTTPException(status_code=400, detail="No chapters available for export")

    temp_dir = Path(tempfile.gettempdir()) / "longfiction_exports"
    temp_dir.mkdir(parents=True, exist_ok=True)
    epub_path = temp_dir / f"{task_id}{'_finalized' if finalized_only else ''}.epub"

    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", """<?xml version='1.0' encoding='utf-8'?>
<container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>
  <rootfiles>
    <rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/>
  </rootfiles>
</container>""")

        manifest_items = []
        spine_items = []
        nav_points = []
        for i, chapter in enumerate(chapters, start=1):
            chapter_file = f"chapter_{i:03d}.xhtml"
            chapter_id = f"chap{i}"
            manifest_items.append(f"<item id='{chapter_id}' href='{chapter_file}' media-type='application/xhtml+xml'/>")
            spine_items.append(f"<itemref idref='{chapter_id}'/>")
            nav_points.append(f"<li><a href='{chapter_file}'>{chapter.title}</a></li>")
            body = f"""<?xml version='1.0' encoding='utf-8'?>
<html xmlns='http://www.w3.org/1999/xhtml'>
  <head><title>{chapter.title}</title></head>
  <body><h1>{chapter.title}</h1><p>{chapter.content.replace(chr(10), '</p><p>')}</p></body>
</html>"""
            zf.writestr(f"OEBPS/{chapter_file}", body)

        nav = f"""<?xml version='1.0' encoding='utf-8'?>
<html xmlns='http://www.w3.org/1999/xhtml'>
  <head><title>目录</title></head>
  <body><nav epub:type='toc'><ol>{''.join(nav_points)}</ol></nav></body>
</html>"""
        zf.writestr("OEBPS/nav.xhtml", nav)
        manifest_items.append("<item id='nav' href='nav.xhtml' media-type='application/xhtml+xml' properties='nav'/>")

        opf = f"""<?xml version='1.0' encoding='utf-8'?>
<package xmlns='http://www.idpf.org/2007/opf' version='3.0' unique-identifier='bookid'>
  <metadata xmlns:dc='http://purl.org/dc/elements/1.1/'>
    <dc:identifier id='bookid'>{task_id}</dc:identifier>
    <dc:title>LongFiction Export {task_id}</dc:title>
    <dc:language>zh-CN</dc:language>
  </metadata>
  <manifest>{''.join(manifest_items)}</manifest>
  <spine>{''.join(spine_items)}</spine>
</package>"""
        zf.writestr("OEBPS/content.opf", opf)

    return FileResponse(epub_path, filename=f"longfiction_{task_id}{'_finalized' if finalized_only else ''}.epub", media_type="application/epub+zip")


@app.post("/api/generate")
async def generate_all(req: GenerateAllRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    """P1-3：超过 ABSOLUTE 上限直接 400 报错，不再静默 clamp。"""
    from core.config import settings as app_settings
    absolute_max = getattr(
        app_settings, "MAX_TARGET_CHAPTERS_ABSOLUTE", app_settings.MAX_TARGET_CHAPTERS
    )
    if req.target_chapters > absolute_max:
        raise HTTPException(
            status_code=400,
            detail=f"target_chapters 不能超过 {absolute_max}",
        )
    if req.target_chapters < 1:
        raise HTTPException(status_code=400, detail="target_chapters must be >= 1")
    task_id = str(uuid.uuid4())[:8]
    generation_tasks[task_id] = {"status": "running", "progress": 0, "chapters": [], "project_id": task_id}

    async def run_generation():
        pipeline = MainPipeline(session_id=task_id)
        pipelines[task_id] = pipeline
        request = GenerationRequest(
            outline=req.outline, genre=req.genre, style=req.style,
            target_chapters=req.target_chapters, words_per_chapter=req.words_per_chapter,
        )
        try:
            await pipeline.initialize(request)
            pipeline.approved = True
            pipeline.save_project_state()
            total = min(req.max_chapters, len(pipeline.volume.chapters)) if pipeline.volume else 0
            if total <= 0:
                generation_tasks[task_id]["status"] = "failed: no chapters planned"
                return
            for i in range(total):
                draft = await pipeline.generate_chapter(0, i)
                generation_tasks[task_id]["chapters"].append(draft.model_dump())
                generation_tasks[task_id]["catalog"] = pipeline.get_chapter_catalog()
                generation_tasks[task_id]["progress"] = (i + 1) / total
            generation_tasks[task_id]["status"] = "completed"
        except Exception as e:
            generation_tasks[task_id]["status"] = f"failed: {e}"
            logger.error(f"Generation failed: {e}")

    background_tasks.add_task(run_generation)
    return {"task_id": task_id, "status": "started"}


@app.post("/api/batch-generate")
async def batch_generate(req: BatchGenerateRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Project not found")
    if not pipeline.approved:
        raise HTTPException(status_code=400, detail="Project not approved yet")

    batch_id = f"batch_{req.task_id}_{uuid.uuid4().hex[:4]}"
    _set_task(
        batch_id,
        project_id=req.task_id,
        task_type="batch",
        label="批量推进正文",
        stage="排队启动批量生成",
        progress=0,
        chapters=[],
        start_chapter=req.start_chapter,
        end_chapter=req.end_chapter,
    )

    async def run_batch():
        try:
            generation_tasks[batch_id].update({"stage": "批量生成中：逐章写作、检查、保存", "updated_at": _now_iso()})
            batch_state = {"results": None}

            def _on_batch_progress(idx, end, result):
                results = result.get("results") if isinstance(result, dict) and result.get("results") else (batch_state.get("results") or {})
                actual_start = results.get("start_chapter", req.start_chapter)
                actual_end = results.get("end_chapter", end)
                actual_total = max(results.get("total", max(actual_end - actual_start, 1)), 1)
                completed = max(0, idx - actual_start + 1)
                generation_tasks[batch_id].update({
                    "progress": min(1.0, completed / actual_total),
                    "last_chapter": None if (isinstance(result, dict) and result.get("status") == "batch_ready") else result,
                    "stage": f"已处理第{idx + 1}章 / 目标第{actual_end}章",
                    "updated_at": _now_iso(),
                    "results": results,
                })

            results = await pipeline.batch_generate(
                start_chapter=req.start_chapter,
                end_chapter=req.end_chapter if req.end_chapter > 0 else None,
                consistency_threshold=req.consistency_threshold,
                auto_finalize=req.auto_finalize,
                max_retries=req.max_retries,
                on_progress=_on_batch_progress,
            )
            batch_state["results"] = results
            if results.get("failed", 0) > 0 and results.get("finalized", 0) < results.get("total", 0):
                generation_tasks[batch_id].update({
                    "status": "completed_with_issues",
                    "stage": "批量推进已停止，部分章节未完成",
                    "results": results,
                    "catalog": pipeline.get_chapter_catalog(),
                    "progress": min(1.0, (results.get("generated", 0) + results.get("skipped", 0)) / max(results.get("total", 1), 1)),
                    "updated_at": _now_iso(),
                })
            else:
                _complete_task(
                    batch_id,
                    stage="批量推进完成",
                    results=results,
                    catalog=pipeline.get_chapter_catalog(),
                    progress=1.0,
                )
        except Exception as e:
            _fail_task(batch_id, e)
            logger.error(f"Batch generation failed: {e}")

    background_tasks.add_task(run_batch)
    return {"batch_id": batch_id, "task_id": req.task_id, "status": "started"}


@app.get("/api/tasks/{project_id}")
async def get_project_tasks(project_id: str, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(project_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Project not found")
    tasks = _project_tasks(project_id)
    active = [task for task in tasks if str(task.get("status", "")).startswith("running")]
    return {
        "project_id": project_id,
        "active": active,
        "tasks": tasks[-20:],
        "pipeline": pipeline.get_status(),
    }


@app.get("/api/quality-flow/{project_id}")
async def get_quality_flow(project_id: str, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(project_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Project not found")
    active_tasks = _project_tasks(project_id)
    running = [task for task in active_tasks if str(task.get("status", "")).startswith("running")]
    latest_batch = next((task for task in running if task.get("type") == "batch"), None)
    latest_chapter = next((task for task in running if task.get("type") == "chapter"), None)
    status = pipeline.get_status()
    steps = [
        {"key": "init", "name": "设定确认", "done": bool(status.get("approved")), "note": "世界观、角色、章节规划先收束后再写正文"},
        {"key": "plan", "name": "写前规划", "done": bool(status.get("planned_chapters")), "note": f"当前已规划 {status.get('planned_chapters', 0)} 章"},
        {"key": "write", "name": "正文生成", "done": bool(status.get("generated")), "note": f"已生成 {status.get('generated', 0)} 章"},
        {"key": "polish", "name": "去AI与润色", "done": True, "note": "每章都会经过风格重写与去AI痕迹处理"},
        {"key": "check", "name": "一致性校验", "done": True, "note": "会检查人物状态、世界观、时间线和章节对齐"},
        {"key": "finalize", "name": "定稿沉淀", "done": bool(status.get("finalized")), "note": f"已定稿 {status.get('finalized', 0)} 章"},
        {"key": "evolution", "name": "阶段重规划", "done": status.get("finalized", 0) > 0, "note": "定稿后只调整后续未生成章节"},
        {"key": "batch", "name": "批量推进", "done": bool(latest_batch and str(latest_batch.get("status", "")).startswith("completed")), "note": latest_batch.get("stage") if latest_batch else "暂无批量任务"},
    ]
    return {
        "project_id": project_id,
        "status": status,
        "steps": steps,
        "running_tasks": running,
        "current_task": latest_batch or latest_chapter,
    }


@app.get("/api/status/{task_id}")
async def get_status(task_id: str, current_user: dict = Depends(get_current_user)):
    if task_id in generation_tasks:
        return generation_tasks[task_id]
    pipeline = get_or_load_pipeline(task_id)
    if pipeline:
        return {"status": "initialized", "pipeline": pipeline.get_status()}
    raise HTTPException(status_code=404, detail="Task not found")


@app.get("/api/chapters/{task_id}")
async def get_chapters(task_id: str, current_user: dict = Depends(get_current_user)):
    task = generation_tasks.get(task_id)
    if task:
        return {"chapters": task.get("chapters", [])}
    pipeline = get_or_load_pipeline(task_id)
    if pipeline:
        return {"chapters": [c.model_dump() for c in pipeline.generated_chapters]}
    raise HTTPException(status_code=404, detail="Task not found")


@app.get("/api/chapter/{task_id}/{chapter_index}")
async def get_chapter(task_id: str, chapter_index: int, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Task not found")
    for chapter in pipeline.generated_chapters:
        if chapter.chapter_index == chapter_index:
            return {"chapter": chapter.model_dump()}
    raise HTTPException(status_code=404, detail="Chapter not generated")


@app.on_event("startup")
async def startup_event():
    init_db()
    logger.info("Database initialized")

    admin_user = settings.ADMIN_USERNAME
    admin_pass = settings.ADMIN_PASSWORD
    if admin_user and admin_pass:
        try:
            with SessionLocal() as db:
                us = UserService(db)
                existing = us.get_user_by_username(admin_user)
                if existing:
                    us.update_user(
                        existing.id,
                        password_hash=hash_password(admin_pass),
                        role="admin",
                        is_active=True,
                    )
                    logger.info(f"Admin user '{admin_user}' already exists, credentials synced")
                else:
                    pw_hash = hash_password(admin_pass)
                    user = us.create_user(
                        username=admin_user,
                        password_hash=pw_hash,
                        nickname="Administrator",
                        role="admin",
                    )
                    logger.info(f"Admin user '{admin_user}' created with id={user.id}")
        except Exception as e:
            logger.warning(f"Admin account setup failed: {e}")


@app.get("/api/db/projects")
async def db_list_projects(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    ps = ProjectService(db)
    projects = ps.get_all_projects()
    return {
        "projects": [
            {
                "id": p.id,
                "title": (getattr(p, "title", "") or "").strip() or p.outline[:28],
                "outline": p.outline[:100],
                "genre": p.genre,
                "approved": p.approved,
                "target_chapters": p.target_chapters,
                "created_at": p.created_at.isoformat(),
            }
            for p in projects
        ]
    }


@app.get("/api/db/project/{project_id}")
async def db_get_project(project_id: str, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    ps = ProjectService(db)
    project = ps.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    cs = CharacterService(db)
    ws = WorldService(db)
    chs = ChapterService(db)
    
    characters = cs.get_project_characters(project_id)
    world = ws.get_world(project_id)
    chapters = chs.get_project_chapters(project_id)
    
    return {
        "project": {
            "id": project.id,
            "title": (getattr(project, "title", "") or "").strip() or project.outline[:28],
            "outline": project.outline,
            "genre": project.genre,
            "style": project.style,
            "target_chapters": project.target_chapters,
            "words_per_chapter": project.words_per_chapter,
            "approved": project.approved,
        },
        "world": ws.to_world_setting_model(world).model_dump() if world else None,
        "characters": [cs.to_character_sheet(c).model_dump() for c in characters],
        "chapters": [chs.to_chapter_outline(c).model_dump() for c in chapters],
    }


@app.delete("/api/db/project/{project_id}")
async def db_delete_project(project_id: str, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    import shutil
    us = UserService(db)
    is_admin = current_user.get("role") == "admin"
    if not is_admin and not us.has_project_access(current_user["id"], project_id):
        db_project = ProjectService(db).get_project(project_id)
        session_dir = PROJECT_ROOT / "data" / "sessions" / project_id
        if not db_project and not session_dir.exists():
            raise HTTPException(status_code=403, detail="无权限删除该项目")
    ps = ProjectService(db)
    ps.delete_project(project_id)
    if project_id in pipelines:
        pipeline = pipelines[project_id]
        if hasattr(pipeline, 'cleanup'):
            pipeline.cleanup()
        del pipelines[project_id]
    for bid in list(generation_tasks.keys()):
        if generation_tasks[bid].get("task_id") == project_id:
            del generation_tasks[bid]
    session_dir = PROJECT_ROOT / "data" / "sessions" / project_id
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)
    output_dir = PROJECT_ROOT / "output" / "sessions" / project_id
    if output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)
    return {"status": "deleted", "project_id": project_id}


@app.get("/api/db/project/{project_id}/chapters")
async def db_get_chapters(project_id: str, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    ps = ProjectService(db)
    if not ps.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    
    chs = ChapterService(db)
    chapters = chs.get_project_chapters(project_id)
    
    result = []
    for ch in chapters:
        latest = chs.get_latest_version(ch.id)
        result.append({
            "id": ch.id,
            "chapter_index": ch.chapter_index,
            "title": ch.title,
            "status": ch.status,
            "current_version": ch.current_version,
            "has_content": latest is not None,
            "word_count": latest.word_count if latest else 0,
        })
    return {"chapters": result}


@app.get("/api/db/chapter/{chapter_id}/versions")
async def db_get_versions(chapter_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    chs = ChapterService(db)
    chapter = chs.get_chapter(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    versions = chs.get_chapter_versions(chapter_id)
    return {
        "chapter_id": chapter_id,
        "title": chapter.title,
        "current_version": chapter.current_version,
        "versions": [
            {
                "version": v.version,
                "word_count": v.word_count,
                "consistency_score": v.consistency_score,
                "created_at": v.created_at.isoformat(),
                "content_preview": v.content[:300] if v.content else "",
            }
            for v in versions
        ]
    }


@app.get("/api/db/chapter/{chapter_id}/content/{version}")
async def db_get_chapter_content(chapter_id: int, version: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    chs = ChapterService(db)
    chapter = chs.get_chapter(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    for v in chs.get_chapter_versions(chapter_id):
        if v.version == version:
            return {
                "chapter_id": chapter_id,
                "version": version,
                "title": chapter.title,
                "content": v.content,
                "word_count": v.word_count,
                "consistency_score": v.consistency_score,
            }
    raise HTTPException(status_code=404, detail="Version not found")


@app.get("/api/db/project/{project_id}/timeline")
async def db_get_timeline(project_id: str, limit: int = 50, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    ps = ProjectService(db)
    if not ps.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    
    ts = TimelineService(db)
    events = ts.get_project_timeline(project_id, limit)
    return {
        "project_id": project_id,
        "timeline": [
            {
                "chapter_index": e.chapter_index,
                "event_type": e.event_type,
                "description": e.description,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ]
    }


class VersionCompareRequest(BaseModel):
    chapter_id: int
    version1: int
    version2: int


class SelectVersionRequest(BaseModel):
    chapter_id: int
    version: int


class FinalizeChapterRequest(BaseModel):
    project_id: str
    chapter_index: int


@app.post("/api/db/chapter/compare")
async def db_compare_versions(req: VersionCompareRequest, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    chs = ChapterService(db)
    chapter = chs.get_chapter(req.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    versions = {v.version: v for v in chs.get_chapter_versions(req.chapter_id)}
    v1 = versions.get(req.version1)
    v2 = versions.get(req.version2)
    
    if not v1 or not v2:
        raise HTTPException(status_code=404, detail="One or both versions not found")
    
    import difflib
    diff = list(difflib.unified_diff(
        v1.content.splitlines(keepends=True),
        v2.content.splitlines(keepends=True),
        fromfile=f"v{req.version1}",
        tofile=f"v{req.version2}",
        lineterm=""
    ))
    
    return {
        "chapter_id": req.chapter_id,
        "title": chapter.title,
        "version1": {
            "version": v1.version,
            "word_count": v1.word_count,
            "consistency_score": v1.consistency_score,
            "created_at": v1.created_at.isoformat(),
        },
        "version2": {
            "version": v2.version,
            "word_count": v2.word_count,
            "consistency_score": v2.consistency_score,
            "created_at": v2.created_at.isoformat(),
        },
        "diff": "".join(diff[:200]),
        "diff_lines": len(diff),
    }


@app.post("/api/db/chapter/select-version")
async def db_select_version(req: SelectVersionRequest, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    chs = ChapterService(db)
    chapter = chs.get_chapter(req.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    versions = {v.version: v for v in chs.get_chapter_versions(req.chapter_id)}
    target = versions.get(req.version)
    if not target:
        raise HTTPException(status_code=404, detail="Version not found")
    
    chapter.current_version = req.version
    chapter.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(chapter)

    pipeline = get_or_load_pipeline(chapter.project_id)
    if pipeline:
        try:
            pipeline.select_version_as_current(
                chapter.chapter_index,
                target.version,
                target.content,
                target.word_count,
                target.consistency_score,
            )
        except Exception as e:
            logger.warning(f"Pipeline select version sync failed: {e}")
    
    return {
        "status": "selected",
        "chapter_id": req.chapter_id,
        "current_version": chapter.current_version,
        "word_count": target.word_count,
        "content": target.content,
    }


@app.post("/api/db/chapter/finalize")
async def db_finalize_chapter(req: FinalizeChapterRequest, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    ps = ProjectService(db)
    project = ps.get_project(req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    chs = ChapterService(db)
    chapter = chs.get_chapter_by_index(req.project_id, req.chapter_index)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    if chapter.status == "finalized":
        return {"status": "already_finalized", "chapter_id": chapter.id}
    
    latest = chs.get_latest_version(chapter.id)
    if not latest:
        raise HTTPException(status_code=400, detail="No content to finalize")
    
    chapter.status = "finalized"
    chapter.updated_at = datetime.utcnow()
    
    ts = TimelineService(db)
    ts.add_event(
        project_id=req.project_id,
        chapter_index=req.chapter_index,
        event_type="chapter_finalized",
        description=f"章节《{chapter.title}》定稿，{latest.word_count}字"
    )
    
    db.commit()
    
    return {
        "status": "finalized",
        "chapter_id": chapter.id,
        "chapter_index": req.chapter_index,
        "title": chapter.title,
        "word_count": latest.word_count,
    }


@app.post("/api/db/chapter/unfinalize")
async def db_unfinalize_chapter(req: FinalizeChapterRequest, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    chs = ChapterService(db)
    chapter = chs.get_chapter_by_index(req.project_id, req.chapter_index)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    chapter.status = "draft"
    chapter.updated_at = datetime.utcnow()
    db.commit()
    
    return {"status": "unfinalized", "chapter_id": chapter.id}


from models.db_service import ForeshadowingService
from agents.style_rewriter import AIPatternDetector, DialogueAnalyzer, STYLE_LIBRARY


class ForeshadowPlantRequest(BaseModel):
    project_id: str
    description: str
    chapter_index: int
    foreshadow_type: str = "clue"
    trigger_keywords: list[str] = []
    payoff_condition: str = ""
    source_excerpt: str = ""
    close_by_chapter: int | None = None


class ForeshadowResolveRequest(BaseModel):
    foreshadow_id: int
    chapter_index: int
    description: str = ""


class AIDetectRequest(BaseModel):
    text: str
    chapter_title: str = ""
    recent_texts: list[str] = Field(default_factory=list)
    recent_titles: list[str] = Field(default_factory=list)
    is_final: bool = False


@app.post("/api/db/foreshadow/plant")
async def plant_foreshadow(req: ForeshadowPlantRequest, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    fs = ForeshadowingService(db)
    foreshadow = fs.plant(
        req.project_id,
        req.description,
        req.chapter_index,
        foreshadow_type=req.foreshadow_type,
        trigger_keywords=req.trigger_keywords,
        payoff_condition=req.payoff_condition,
        source_excerpt=req.source_excerpt,
        close_by_chapter=req.close_by_chapter,
    )
    return {
        "status": foreshadow.status,
        "foreshadow_id": foreshadow.id,
        "description": foreshadow.description,
        "planted_chapter": foreshadow.planted_chapter,
        "foreshadow_type": foreshadow.foreshadow_type,
        "trigger_keywords": foreshadow.trigger_keywords or [],
        "payoff_condition": foreshadow.payoff_condition,
        "source_excerpt": foreshadow.source_excerpt,
        "close_by_chapter": foreshadow.close_by_chapter,
    }


@app.post("/api/db/foreshadow/resolve")
async def resolve_foreshadow(req: ForeshadowResolveRequest, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    fs = ForeshadowingService(db)
    foreshadow = fs.resolve(req.foreshadow_id, req.chapter_index, req.description)
    if not foreshadow:
        raise HTTPException(status_code=404, detail="Foreshadow not found")
    return {
        "status": "resolved",
        "foreshadow_id": foreshadow.id,
        "resolved_chapter": foreshadow.resolved_chapter
    }


@app.get("/api/db/foreshadow/{project_id}")
async def get_foreshadows(project_id: str, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    fs = ForeshadowingService(db)
    all_foreshadows = fs.get_project_foreshadowing(project_id)
    unresolved = fs.get_unresolved(project_id)
    return {
        "project_id": project_id,
        "total": len(all_foreshadows),
        "unresolved_count": len(unresolved),
        "foreshadows": [
            {
                "id": f.id,
                "description": f.description,
                "foreshadow_type": getattr(f, "foreshadow_type", "clue") or "clue",
                "trigger_keywords": list(getattr(f, "trigger_keywords", []) or []),
                "payoff_condition": getattr(f, "payoff_condition", "") or "",
                "source_excerpt": getattr(f, "source_excerpt", "") or f.description,
                "planted_chapter": f.planted_chapter,
                "close_by_chapter": getattr(f, "close_by_chapter", None),
                "status": f.status,
                "resolved_chapter": f.resolved_chapter,
                "resolved_description": f.resolved_description,
            }
            for f in all_foreshadows
        ]
    }


@app.post("/api/ai-detect")
async def detect_ai_patterns(req: AIDetectRequest, current_user: dict = Depends(get_current_user)):
    detector = AIPatternDetector()
    report = detector.get_report(
        req.text,
        chapter_title=req.chapter_title,
        recent_texts=req.recent_texts,
        recent_titles=req.recent_titles,
        is_final=req.is_final,
    )
    return report


@app.post("/api/ai-detect/highlight")
async def detect_ai_patterns_highlighted(req: AIDetectRequest, current_user: dict = Depends(get_current_user)):
    detector = AIPatternDetector()
    result = detector.highlight_text(req.text)
    return result


@app.post("/api/dialogue-analyze")
async def analyze_dialogue(req: AIDetectRequest, current_user: dict = Depends(get_current_user)):
    analyzer = DialogueAnalyzer()
    result = analyzer.analyze(req.text)
    return result


@app.post("/api/style-rewrite")
async def style_rewrite_chapter(req: AIDetectRequest, current_user: dict = Depends(get_current_user)):
    from agents.style_rewriter import StyleRewriter as SR
    rewriter = SR()
    result = await rewriter.rewrite(req.text)
    return {"rewritten": result, "original_length": len(req.text), "rewritten_length": len(result)}


@app.get("/api/styles")
async def get_style_library():
    return {
        "styles": [
            {"id": k, "name": v["name"], "features": v["features"]}
            for k, v in STYLE_LIBRARY.items()
        ]}


class StyleLearnRequest(BaseModel):
    task_id: str
    texts: list[str]


@app.post("/api/style/learn")
async def learn_style_from_samples(req: StyleLearnRequest):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        return JSONResponse(content={"error": "Project not found"}, status_code=404)
    try:
        fingerprint = await pipeline.style_learner.learn_style(req.texts)
        pipeline.style_preserver.last_fingerprint = fingerprint
        fp_dict = {
            "sentence_length_dist": fingerprint.sentence_length_dist,
            "dialogue_density": fingerprint.dialogue_density,
            "rhetoric_frequency": fingerprint.rhetoric_frequency,
            "emotion_tone": fingerprint.emotion_tone,
            "rhythm_pattern": fingerprint.rhythm_pattern,
        }
        pipeline.style_fingerprint = fp_dict
        pipeline.save_project_state()
        return {
            "status": "ok",
            "fingerprint": fp_dict,
        }
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)
    except Exception as e:
        logger.exception("Style learning failed")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/templates")
async def get_templates():
    path = Path(__file__).resolve().parents[1] / "configs" / "templates.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"templates": []}


from agents.consistency_checker import ConsistencyGate, ConsistencyBlockError
from agents.character_state_machine import CharacterState, RelationType, StateTransitionBlockError


class MarkDeadRequest(BaseModel):
    task_id: str
    character_name: str
    chapter_index: int


class UpdatePowerRequest(BaseModel):
    task_id: str
    character_name: str
    new_level: int = Field(ge=1, le=100)
    chapter_index: int
    reason: str = ""


class ValidateActionRequest(BaseModel):
    task_id: str
    text: str
    chapter_index: int


class PreGenValidateRequest(BaseModel):
    task_id: str
    chapter_index: int
    plot_direction: str


class SetRelationRequest(BaseModel):
    task_id: str
    character1: str
    character2: str
    relation_type: str
    strength: int = Field(default=50, ge=0, le=100)


@app.get("/api/consistency-gate/{task_id}")
async def get_consistency_gate_state(task_id: str, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "task_id": task_id,
        "dead_characters": list(pipeline.consistency_gate.dead_characters),
        "character_power": pipeline.consistency_gate.character_power,
        "character_locations": pipeline.consistency_gate.character_locations,
        "score_threshold": pipeline.consistency_gate.score_threshold,
    }


@app.post("/api/consistency-gate/mark-dead")
async def mark_character_dead(req: MarkDeadRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Project not found")
    pipeline.consistency_gate.register_dead_character(req.character_name)
    pipeline.state_manager.mark_dead(req.character_name, req.chapter_index)
    pipeline.save_project_state()
    return {"status": "marked_dead", "character": req.character_name, "chapter": req.chapter_index}


@app.post("/api/consistency-gate/register-power")
async def register_character_power(req: UpdatePowerRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Project not found")
    pipeline.consistency_gate.register_character_power(req.character_name, req.new_level, req.chapter_index)
    success = pipeline.state_manager.update_character_power(req.character_name, req.new_level, req.chapter_index, req.reason)
    if not success:
        raise HTTPException(status_code=400, detail="Power update rejected - regression too large")
    pipeline.save_project_state()
    char = pipeline.state_manager.get_character(req.character_name)
    return {
        "status": "updated",
        "character": req.character_name,
        "power_level": req.new_level,
        "current_state": char.current_state.value if char else None,
        "progress": char.get_progress_percentage() if char else None,
    }


@app.post("/api/consistency-gate/validate-action")
async def validate_action(req: ValidateActionRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Project not found")
    violations = pipeline.state_manager.validate_action_for_text(req.text, req.chapter_index)
    dead_violations = pipeline.state_manager.check_dead_character_in_text(req.text, req.chapter_index)
    return {
        "action_violations": violations,
        "dead_character_violations": dead_violations,
        "has_hard_blocks": any(v.get("severity") == "hard" for v in violations + dead_violations),
    }


@app.post("/api/consistency-gate/pre-generation-validate")
async def pre_generation_validate(req: PreGenValidateRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Project not found")
    gate_blocks = pipeline.consistency_gate.pre_generation_validate(
        req.chapter_index, pipeline.characters, req.plot_direction
    )
    state_blocks = pipeline.state_manager.pre_generation_validate(req.chapter_index, req.plot_direction)
    all_blocks = gate_blocks + state_blocks
    hard_blocks = [b for b in all_blocks if b.startswith("HARD:")]
    return {
        "can_generate": len(hard_blocks) == 0,
        "all_blocks": all_blocks,
        "hard_blocks": [b.replace("HARD: ", "") for b in hard_blocks],
    }


@app.get("/api/character-state/{task_id}")
async def get_character_states(task_id: str, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Project not found")
    sm = pipeline.state_manager.to_dict()
    return {
        "task_id": task_id,
        "characters": sm["characters"],
        "relationships": sm.get("relationships", []),
        "dead_characters": list(pipeline.state_manager.dead_characters),
    }


@app.post("/api/character-state/set-relation")
async def set_character_relation(req: SetRelationRequest, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(req.task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        rel_type = RelationType(req.relation_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid relation type: {req.relation_type}")
    rel = pipeline.state_manager.set_relationship(req.character1, req.character2, rel_type, req.strength)
    pipeline.save_project_state()
    return {"status": "set", "relation": rel.to_dict()}


# ========== 用户管理API ==========

class UserRegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    email: str = Field(default="", max_length=128)
    nickname: str = Field(default="", max_length=64)


class UserLoginRequest(BaseModel):
    username: str
    password: str


class RechargeRequest(BaseModel):
    user_id: int
    amount: float = Field(gt=0)
    payment_method: str = "manual"
    description: str = ""


class UserUpdateRequest(BaseModel):
    nickname: str = Field(default="", max_length=64)
    email: str = Field(default="", max_length=128)


class AdminUserUpdateRequest(BaseModel):
    user_id: int
    role: str = Field(default="", max_length=32)
    is_active: bool = True
    nickname: str = Field(default="", max_length=64)


@app.post("/api/auth/register")
async def register(req: UserRegisterRequest, db: Session = Depends(get_db)):
    us = UserService(db)
    existing = us.get_user_by_username(req.username)
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")
    if req.email:
        existing_email = us.get_user_by_email(req.email)
        if existing_email:
            raise HTTPException(status_code=400, detail="邮箱已被注册")
    password_hash = hash_password(req.password)
    user = us.create_user(
        username=req.username,
        password_hash=password_hash,
        email=req.email or None,
        nickname=req.nickname or req.username,
    )
    token = create_access_token(user.id, user.username, user.role)
    return {
        "status": "registered",
        "user": us.user_to_dict(user),
        "token": token,
        "token_type": "bearer",
    }


@app.post("/api/auth/login")
async def login(req: UserLoginRequest, db: Session = Depends(get_db)):
    us = UserService(db)
    user = us.get_user_by_username(req.username)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    us.update_last_login(user.id)
    token = create_access_token(user.id, user.username, user.role)
    return {
        "status": "login_success",
        "user": us.user_to_dict(user),
        "token": token,
        "token_type": "bearer",
    }


@app.get("/api/auth/me")
async def get_me(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    us = UserService(db)
    user = us.get_user(current_user["id"])
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return us.user_to_dict(user)


@app.put("/api/auth/me")
async def update_me(req: UserUpdateRequest, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    us = UserService(db)
    updates = {}
    if req.nickname:
        updates["nickname"] = req.nickname
    if req.email:
        existing = us.get_user_by_email(req.email)
        if existing and existing.id != current_user["id"]:
            raise HTTPException(status_code=400, detail="邮箱已被其他用户使用")
        updates["email"] = req.email
    user = us.update_user(current_user["id"], **updates)
    return us.user_to_dict(user)


@app.get("/api/auth/balance")
async def get_balance(current_user: dict = Depends(get_current_user)):
    return {
        "user_id": current_user["id"],
        "balance": current_user["balance"],
    }


@app.get("/api/auth/recharge-history")
async def get_recharge_history(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    us = UserService(db)
    records = us.get_recharge_history(current_user["id"])
    return {
        "user_id": current_user["id"],
        "records": [
            {
                "id": r.id,
                "amount": r.amount,
                "payment_method": r.payment_method,
                "status": r.status,
                "description": r.description,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ]
    }


@app.get("/api/auth/consumption-history")
async def get_consumption_history(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    us = UserService(db)
    records = us.get_consumption_history(current_user["id"])
    return {
        "user_id": current_user["id"],
        "records": [
            {
                "id": r.id,
                "project_id": r.project_id,
                "amount": r.amount,
                "consumption_type": r.consumption_type,
                "description": r.description,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ]
    }


@app.get("/api/auth/projects")
async def get_my_projects(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    us = UserService(db)
    user_projects = us.get_user_projects(current_user["id"])
    result = []
    for up in user_projects:
        pipeline = get_or_load_pipeline(up.project_id)
        if pipeline:
            result.append({
                "project_id": up.project_id,
                "role": up.role,
                "outline": pipeline.outline[:100],
                "genre": pipeline.genre,
                "chapters_total": len(pipeline.volume.chapters) if pipeline.volume else 0,
                "chapters_generated": len(pipeline.generated_chapters),
                "chapters_finalized": len(pipeline.finalized_chapters),
            })
        else:
            result.append({"project_id": up.project_id, "role": up.role, "status": "not_loaded"})
    return {"user_id": current_user["id"], "projects": result}


# ========== 管理员API ==========

@app.post("/api/admin/recharge")
async def admin_recharge(req: RechargeRequest, current_user: dict = Depends(require_role("admin")), db: Session = Depends(get_db)):
    us = UserService(db)
    user = us.recharge(req.user_id, req.amount, req.payment_method, req.description)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {
        "status": "recharged",
        "user": us.user_to_dict(user),
        "recharged_amount": req.amount,
    }


@app.get("/api/admin/users")
async def admin_list_users(
    offset: int = 0,
    limit: int = 50,
    current_user: dict = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    us = UserService(db)
    users = us.list_users(offset, limit)
    return {
        "users": [us.user_to_dict(u) for u in users],
        "total": len(users),
    }


@app.put("/api/admin/user")
async def admin_update_user(req: AdminUserUpdateRequest, current_user: dict = Depends(require_role("admin")), db: Session = Depends(get_db)):
    us = UserService(db)
    updates = {}
    if req.role:
        updates["role"] = req.role
    updates["is_active"] = req.is_active
    if req.nickname:
        updates["nickname"] = req.nickname
    user = us.update_user(req.user_id, **updates)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"status": "updated", "user": us.user_to_dict(user)}


@app.delete("/api/admin/user/{user_id}")
async def admin_delete_user(user_id: int, current_user: dict = Depends(require_role("admin")), db: Session = Depends(get_db)):
    if user_id == current_user.get("id"):
        raise HTTPException(status_code=400, detail="不能删除当前登录的管理员账号")
    us = UserService(db)
    success = us.delete_user(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"status": "deleted", "user_id": user_id}


@app.get("/api/progress/{task_id}")
async def get_progress_panel(task_id: str, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline or not hasattr(pipeline, 'enhancement'):
        raise HTTPException(status_code=404, detail="Pipeline not found")
    summary = pipeline.enhancement.progress.get_progress_summary()
    return summary.model_dump()

@app.get("/api/info-gap/{task_id}")
async def get_info_gap_state(task_id: str, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline or not hasattr(pipeline, 'enhancement'):
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline.enhancement.info_gap.get_info_gap_state().model_dump()

@app.get("/api/suspense-arcs/{task_id}")
async def get_suspense_arcs(task_id: str, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline or not hasattr(pipeline, 'enhancement'):
        raise HTTPException(status_code=404, detail="Pipeline not found")
    arcs = pipeline.enhancement.suspense_arcs.arcs
    active = [a.model_dump() for a in arcs if not a.closed]
    closed = [a.model_dump() for a in arcs if a.closed]
    return {
        "arcs": active,
        "closed_count": len(closed),
        "total_count": len(arcs),
        "story_total_chapters": pipeline.target_chapters,
        "current_finalized_chapters": len(pipeline.finalized_chapters),
    }


@app.get("/api/quality-scores/{task_id}")
async def get_quality_scores(task_id: str, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline or not hasattr(pipeline, 'enhancement'):
        raise HTTPException(status_code=404, detail="Pipeline not found")
    history = pipeline.enhancement.quality_scores_history
    latest = history[-1] if history else None
    return {
        "history": history[-10:],
        "latest": latest,
        "total_scored": len(history),
    }


@app.get("/api/story-evolution/{task_id}")
async def get_story_evolution(task_id: str, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline.get_story_evolution()


@app.get("/api/chapter-observations/{task_id}")
async def get_chapter_observations(task_id: str, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    catalog = pipeline.get_chapter_catalog()
    return {
        "task_id": task_id,
        "chapters": [
            {
                "chapter_index": item["chapter_index"],
                "title": item["title"],
                "intent": item.get("intent") or {},
                "observations": item.get("observations") or {},
            }
            for item in catalog
            if item.get("generated")
        ],
    }


@app.post("/api/story-evolution/{task_id}/apply")
async def apply_story_evolution(task_id: str, current_user: dict = Depends(get_current_user)):
    pipeline = get_or_load_pipeline(task_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline.apply_story_evolution()
