"""运行时日志系统：文件日志+控制台+LLM追踪+API请求日志"""

import logging
import logging.handlers
import sys
import os
import time
import functools
import traceback
from pathlib import Path
from typing import Callable, Any

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5


def setup_logging(debug: bool = False, log_level: str = "DEBUG") -> None:
    """初始化日志系统：控制台(INFO)+文件(DEBUG)+错误文件(ERROR)"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    level_map = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR}
    file_level = level_map.get(log_level.upper(), logging.DEBUG)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # 根设DEBUG，handler各自过滤

    # 清除已有handlers避免重复
    for h in list(root.handlers):
        root.removeHandler(h)

    # 控制台handler: INFO及以上
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "[%(levelname)s] %(name)s: %(message)s",
    ))
    root.addHandler(console)

    # 详细日志文件: file_level及以上（默认DEBUG），滚动10MB
    detail_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "detail.log", maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    detail_handler.setLevel(file_level)
    detail_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)-30s %(lineno)4d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(detail_handler)

    # 错误日志文件: ERROR及以上，含堆栈
    error_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "error.log", maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s %(lineno)d\n%(message)s\n",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(error_handler)

    # 抑制litellm自身的DEBUG噪音
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    logging.getLogger("litellm").setLevel(logging.WARNING)
    logging.getLogger("LiteLLM Router").setLevel(logging.WARNING)

    # LLM追踪日志文件: 独立文件避免被滚动淹没
    llm_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "llm.log", maxBytes=LOG_MAX_BYTES * 2, backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    llm_handler.setLevel(logging.DEBUG)
    llm_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    llm_logger = logging.getLogger("llm_trace")
    llm_logger.propagate = False
    for h in list(llm_logger.handlers):
        llm_logger.removeHandler(h)
    llm_logger.addHandler(llm_handler)
    llm_logger.setLevel(logging.DEBUG)

    root.info(f"日志系统初始化完成: 级别={'DEBUG' if debug else 'INFO'}, 目录={LOG_DIR}")


class Timer:
    """简易计时器"""
    def __init__(self):
        self.start = time.time()

    @property
    def elapsed_ms(self) -> int:
        return int((time.time() - self.start) * 1000)

    @property
    def elapsed_sec(self) -> float:
        return round(time.time() - self.start, 2)


def log_llm_call(logger: logging.Logger):
    """装饰器：记录LLM调用的入参、耗时和结果"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            timer = Timer()
            prompt = kwargs.get("prompt", "")
            system = kwargs.get("system", "")
            task_type = kwargs.get("task_type", None)
            max_tokens = kwargs.get("max_tokens", 4096)
            temperature = kwargs.get("temperature", 0.7)
            json_mode = kwargs.get("json_mode", False)

            # 截断prompt/system预览（避免刷屏）
            prompt_preview = (prompt[:300] + "...") if len(prompt) > 300 else prompt
            system_preview = (system[:200] + "...") if len(system) > 200 else system

            logger.info(
                "LLM调用开始 | type=%s model_token=%d temp=%.1f json=%s",
                task_type, max_tokens, temperature, json_mode,
            )
            llm_trace = logging.getLogger("llm_trace")
            llm_trace.info(
                ">>> LLM CALL type=%s tokens=%d temp=%.1f json=%s\n"
                "  system: %s\n"
                "  prompt: %s",
                task_type, max_tokens, temperature, json_mode,
                system_preview, prompt_preview,
            )

            try:
                result = await func(*args, **kwargs)
                elapsed = timer.elapsed_ms

                result_preview = ""
                if isinstance(result, str):
                    result_preview = (result[:300] + "...") if len(result) > 300 else result
                elif isinstance(result, dict):
                    result_str = str(result)
                    result_preview = (result_str[:300] + "...") if len(result_str) > 300 else result_str
                else:
                    result_preview = str(result)[:300]

                logger.info("LLM调用成功 | type=%s 耗时=%dms", task_type, elapsed)
                llm_trace.info(
                    "<<< LLM OK type=%s elapsed=%dms\n"
                    "  result: %s",
                    task_type, elapsed, result_preview,
                )
                return result
            except Exception as e:
                elapsed = timer.elapsed_ms
                tb = traceback.format_exc()
                logger.error("LLM调用失败 | type=%s 耗时=%dms  error=%s", task_type, elapsed, e)
                llm_trace.error(
                    "<<< LLM FAIL type=%s elapsed=%dms error=%s\n%s",
                    task_type, elapsed, e, tb,
                )
                raise
        return wrapper
    return decorator


def log_api_call(logger: logging.Logger):
    """装饰器：记录API调用的方法和路径"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            timer = Timer()
            request = kwargs.get("request") or kwargs.get("req")
            path = getattr(request, "url", None)
            method = getattr(request, "method", "?")
            path_str = str(path) if path else "?"
            try:
                result = await func(*args, **kwargs)
                elapsed = timer.elapsed_ms
                status = getattr(result, "status_code", 200) if hasattr(result, "status_code") else 200
                logger.info("API %s %s → %d (%dms)", method, path_str, status, elapsed)
                return result
            except Exception as e:
                elapsed = timer.elapsed_ms
                tb = traceback.format_exc()
                logger.error("API %s %s 失败 (%dms): %s\n%s", method, path_str, elapsed, e, tb)
                raise
        return wrapper
    return decorator


class PipelineLogger:
    """流水线步骤日志工具，方便追踪每章的生成过程"""
    def __init__(self, chapter_idx: int, total_steps: int = 8):
        self.chapter_idx = chapter_idx
        self.total_steps = total_steps
        self.current_step = 0
        self.timer = Timer()
        self.step_timers: dict[str, Timer] = {}
        self.logger = logging.getLogger("main_pipeline")

    def step(self, name: str, detail: str = ""):
        self.current_step += 1
        self.step_timers[name] = Timer()
        self.logger.info(
            "  [%d/%d] %s %s",
            self.current_step, self.total_steps, name, detail,
        )

    def step_done(self, name: str, detail: str = ""):
        t = self.step_timers.pop(name, None)
        elapsed = f"({t.elapsed_ms}ms)" if t else ""
        self.logger.info(
            "  [%d/%d] ✓ %s %s %s",
            self.current_step, self.total_steps, name, elapsed, detail,
        )

    def step_warn(self, name: str, detail: str = ""):
        self.logger.warning("  [%d/%d] ⚠ %s: %s", self.current_step, self.total_steps, name, detail)

    def step_error(self, name: str, detail: str = ""):
        self.logger.error("  [%d/%d] ✗ %s: %s", self.current_step, self.total_steps, name, detail)

    @property
    def elapsed(self) -> int:
        return self.timer.elapsed_ms

    def summary(self):
        self.logger.info(
            "第%d章生成完成: 总耗时=%dms",
            self.chapter_idx + 1, self.elapsed,
        )
