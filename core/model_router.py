"""多模型路由。

按任务类型自动选择最适合的模型，支持主备切换、负载均衡。
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.config import settings
from core.models import TaskType
from core.retry import (
    ErrorType,
    RetryConfig,
    classify_error,
    is_retryable,
    calculate_delay,
)

logger = logging.getLogger(__name__)


class ModelRole(str, Enum):
    """模型角色。"""
    PLANNER = "planner"          # 规划（章节、大纲、世界观）
    WRITER = "writer"            # 写作（正文）
    STYLE = "style"              # 风格润色
    CHECK = "check"              # 一致性检查
    CREATIVE = "creative"        # 创意生成
    REASONING = "reasoning"      # 推理
    EMBEDDING = "embedding"      # 嵌入


# 任务类型 -> 模型角色
TASK_TO_ROLE: dict[TaskType, ModelRole] = {
    TaskType.PLAN: ModelRole.PLANNER,
    TaskType.WRITE: ModelRole.WRITER,
    TaskType.REWRITE: ModelRole.STYLE,
    TaskType.CHECK: ModelRole.CHECK,
    TaskType.WORLD: ModelRole.PLANNER,
    TaskType.CHARACTER: ModelRole.PLANNER,
    TaskType.PLOT: ModelRole.PLANNER,
}


@dataclass
class ModelConfig:
    """单个模型配置。"""
    name: str                          # LiteLLM 模型 ID
    api_key: str = ""                  # 可选独立 API Key
    api_base: str = ""                 # 可选独立 API base
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: int = 90
    weight: int = 1                    # 负载均衡权重
    enabled: bool = True


@dataclass
class RouteConfig:
    """路由配置。"""
    # 每个角色可用的模型列表（按优先级）
    models: dict[ModelRole, list[ModelConfig]] = field(default_factory=dict)
    # 失败切换的冷却时间（秒）
    cooldown_seconds: float = 60.0
    # 是否启用负载均衡
    enable_load_balance: bool = False
    # 全局超时倍数
    timeout_multiplier: float = 1.0

    def get_models(self, role: ModelRole) -> list[ModelConfig]:
        """获取指定角色的所有可用模型。"""
        return [m for m in self.models.get(role, []) if m.enabled]


class ModelState:
    """模型状态（用于失败冷却和负载均衡）。"""
    def __init__(self, name: str):
        self.name = name
        self.failure_count = 0
        self.last_failure_at: Optional[float] = None
        self.total_calls = 0
        self.total_failures = 0
        self.total_latency_ms = 0.0
        self.in_cooldown = False

    def record_success(self, latency_ms: float):
        self.total_calls += 1
        self.total_latency_ms += latency_ms
        # 成功后重置失败计数（指数衰减）
        if self.failure_count > 0:
            self.failure_count = max(0, self.failure_count - 1)

    def record_failure(self):
        self.failure_count += 1
        self.total_failures += 1
        self.last_failure_at = time.monotonic()

    def is_available(self, cooldown_seconds: float) -> bool:
        """检查是否可用。"""
        if self.failure_count == 0:
            return True
        if self.last_failure_at is None:
            return True
        elapsed = time.monotonic() - self.last_failure_at
        return elapsed >= cooldown_seconds

    @property
    def avg_latency_ms(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_latency_ms / self.total_calls

    @property
    def failure_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_failures / self.total_calls


class ModelRouter:
    """模型路由器。

    按任务类型选择模型，支持：
    - 主备自动切换
    - 失败冷却
    - 简单负载均衡
    - 统计监控
    """

    def __init__(self, config: Optional[RouteConfig] = None):
        self.config = config or self._default_config()
        self._states: dict[str, ModelState] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _default_config() -> RouteConfig:
        """从全局 settings 构造默认配置。"""
        return RouteConfig(models={
            ModelRole.PLANNER: [
                ModelConfig(
                    name=settings.LLM_PLANNER_MODEL or settings.LLM_DEFAULT_MODEL,
                    max_tokens=4096,
                    temperature=0.5,
                )
            ],
            ModelRole.WRITER: [
                ModelConfig(
                    name=settings.LLM_WRITER_MODEL or settings.LLM_DEFAULT_MODEL,
                    max_tokens=4096,
                    temperature=0.7,
                )
            ],
            ModelRole.STYLE: [
                ModelConfig(
                    name=settings.LLM_STYLE_MODEL or settings.LLM_DEFAULT_MODEL,
                    max_tokens=4096,
                    temperature=0.6,
                )
            ],
            ModelRole.CHECK: [
                ModelConfig(
                    name=settings.LLM_CHECK_MODEL or settings.LLM_DEFAULT_MODEL,
                    max_tokens=2048,
                    temperature=0.3,
                )
            ],
        })

    def _get_state(self, model_name: str) -> ModelState:
        if model_name not in self._states:
            self._states[model_name] = ModelState(model_name)
        return self._states[model_name]

    def select_model(self, role: ModelRole) -> Optional[ModelConfig]:
        """根据角色选择模型。

        策略：
        1. 过滤掉不可用（在冷却期）的模型
        2. 如果启用负载均衡，按权重随机选择
        3. 否则按列表顺序选择第一个
        """
        candidates = self.config.get_models(role)
        if not candidates:
            logger.error(f"No models configured for role {role}")
            return None

        # 过滤冷却中的
        available = [
            m for m in candidates
            if self._get_state(m.name).is_available(self.config.cooldown_seconds)
        ]
        if not available:
            logger.warning(
                f"All models for role {role} are in cooldown, "
                f"using first one anyway"
            )
            available = candidates

        if self.config.enable_load_balance and len(available) > 1:
            weights = [m.weight for m in available]
            return random.choices(available, weights=weights, k=1)[0]

        # 默认选第一个（最高优先级）
        return available[0]

    def get_fallback_models(self, role: ModelRole, exclude: str) -> list[ModelConfig]:
        """获取除指定模型外的备选模型。"""
        candidates = self.config.get_models(role)
        return [m for m in candidates if m.name != exclude]

    async def execute(
        self,
        role: ModelRole,
        call_func,
        *args,
        **kwargs,
    ):
        """使用指定角色执行 LLM 调用，自动处理主备切换。

        Args:
            role: 模型角色
            call_func: 实际调用 LLM 的函数，签名为
                       async (model_config, *args, **kwargs) -> result
            *args, **kwargs: 传递给 call_func 的参数

        Returns:
            call_func 的返回值

        Raises:
            所有模型都失败时抛出最后异常
        """
        tried: set[str] = set()
        last_exc: Optional[Exception] = None
        max_attempts = len(self.config.get_models(role))

        for attempt in range(max_attempts):
            model = self.select_model(role)
            if model is None or model.name in tried:
                # 试过的模型都失败 / 无可用模型
                break
            tried.add(model.name)
            state = self._get_state(model.name)
            start = time.monotonic()

            try:
                result = await call_func(model, *args, **kwargs)
                latency_ms = (time.monotonic() - start) * 1000
                state.record_success(latency_ms)
                return result
            except Exception as e:
                latency_ms = (time.monotonic() - start) * 1000
                state.record_failure()
                err_type = classify_error(e)
                last_exc = e
                logger.warning(
                    f"[{model.name}] call failed [{err_type.value}]: {e} "
                    f"(failure_count={state.failure_count}, "
                    f"avg_latency={state.avg_latency_ms:.0f}ms)"
                )
                # 不可重试的错误立即退出
                if not is_retryable(e, RetryConfig()):
                    logger.info(f"Error {err_type.value} not retryable, aborting")
                    break
                # 否则尝试下一个模型
                continue

        # 所有模型都失败
        if last_exc:
            raise last_exc
        raise RuntimeError(f"No models available for role {role}")

    def get_stats(self) -> dict:
        """获取所有模型的统计信息。"""
        return {
            name: {
                "total_calls": s.total_calls,
                "total_failures": s.total_failures,
                "failure_rate": round(s.failure_rate, 3),
                "avg_latency_ms": round(s.avg_latency_ms, 1),
                "current_failure_streak": s.failure_count,
                "in_cooldown": not s.is_available(self.config.cooldown_seconds),
            }
            for name, s in self._states.items()
        }

    def reset_stats(self):
        """重置所有统计。"""
        self._states.clear()


# 全局单例
_router: Optional[ModelRouter] = None


def get_router() -> ModelRouter:
    """获取全局路由器实例。"""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


def reset_router():
    """重置全局路由器（用于测试）。"""
    global _router
    _router = None


# ============================================================
# 向后兼容：旧 API 单例实例
# ============================================================

def _normalize_for_litellm(model_name: str) -> str:
    """为 LiteLLM 规范化模型名（按 `LLM_PROVIDER` 显式分支）。

    原则：
    1. 用户已写 `provider/model` 时不修改
    2. `provider=openai` 时不强制加前缀
    3. `provider=openai_compatible/newapi/oneapi/lmstudio` 加 `openai/`
    4. `provider=deepseek/qwen/ollama` 加对应 provider 前缀
    """
    if not model_name:
        return model_name
    if "/" in model_name:
        return model_name

    provider = getattr(settings, "LLM_PROVIDER", "openai_compatible").lower()

    if provider == "openai":
        return model_name

    if provider in {"openai_compatible", "newapi", "oneapi", "lmstudio"}:
        return f"openai/{model_name}"

    if provider == "deepseek":
        return model_name if model_name.startswith("deepseek/") else f"deepseek/{model_name}"

    if provider == "qwen":
        return model_name if model_name.startswith("dashscope/") else f"dashscope/{model_name}"

    if provider == "ollama":
        return model_name if model_name.startswith("ollama/") else f"ollama/{model_name}"

    return model_name


# 旧代码使用 model_router.select_model() 和 record_result()
class _CompatModelRouter:
    """旧 API 兼容层。"""

    def __init__(self, router: ModelRouter):
        self._router = router

    def select_model(self, task_type) -> str:
        """根据任务类型选择模型名（已规范化）。"""
        from core.models import TaskType
        if isinstance(task_type, str):
            try:
                task_type = TaskType(task_type)
            except ValueError:
                task_type = TaskType.WRITE
        role = TASK_TO_ROLE.get(task_type, ModelRole.WRITER)
        model = self._router.select_model(role)
        return _normalize_for_litellm(model.name) if model else ""

    def record_result(self, model: str, task_type, latency_ms: float, error: bool = False):
        """记录调用结果。"""
        from core.models import TaskType
        if isinstance(task_type, str):
            try:
                task_type = TaskType(task_type)
            except ValueError:
                task_type = TaskType.WRITE
        role = TASK_TO_ROLE.get(task_type, ModelRole.WRITER)
        # 旧 API 不区分 model，只更新全局统计
        # 这里简化处理：直接记录
        state = self._router._get_state(model)
        if error:
            state.record_failure()
        else:
            state.record_success(latency_ms)


# 全局兼容实例
model_router = _CompatModelRouter(get_router())
