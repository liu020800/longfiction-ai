from core.config import settings
from core.models import TaskType
from core.logging_util import Timer, log_llm_call
from core.retry import retry_with_backoff
import asyncio
import litellm
import json
import logging
import re
import time

logger = logging.getLogger(__name__)

litellm.api_key = settings.LLM_API_KEY
if settings.LLM_API_BASE:
    litellm.api_base = settings.LLM_API_BASE


MODEL_ROUTE = {
    TaskType.PLAN: settings.LLM_PLANNER_MODEL,
    TaskType.WRITE: settings.LLM_WRITER_MODEL,
    TaskType.REWRITE: settings.LLM_STYLE_MODEL,
    TaskType.CHECK: settings.LLM_CHECK_MODEL,
    TaskType.WORLD: settings.LLM_PLANNER_MODEL,
    TaskType.CHARACTER: settings.LLM_PLANNER_MODEL,
    TaskType.PLOT: settings.LLM_PLANNER_MODEL,
}

MODEL_FALLBACK_CHAIN = {
    TaskType.WRITE: [settings.LLM_WRITER_MODEL, settings.LLM_DEFAULT_MODEL],
    TaskType.PLAN: [settings.LLM_PLANNER_MODEL, settings.LLM_DEFAULT_MODEL],
    TaskType.REWRITE: [settings.LLM_STYLE_MODEL, settings.LLM_DEFAULT_MODEL],
    TaskType.CHECK: [settings.LLM_CHECK_MODEL, settings.LLM_DEFAULT_MODEL],
    TaskType.WORLD: [settings.LLM_PLANNER_MODEL, settings.LLM_DEFAULT_MODEL],
    TaskType.CHARACTER: [settings.LLM_PLANNER_MODEL, settings.LLM_DEFAULT_MODEL],
    TaskType.PLOT: [settings.LLM_PLANNER_MODEL, settings.LLM_DEFAULT_MODEL],
}

TASK_TEMPERATURE_RANGES = {
    TaskType.PLAN: (0.3, 0.5),
    TaskType.WRITE: (0.7, 0.95),
    TaskType.REWRITE: (0.5, 0.8),
    TaskType.CHECK: (0.3, 0.5),
    TaskType.WORLD: (0.3, 0.5),
    TaskType.CHARACTER: (0.3, 0.5),
    TaskType.PLOT: (0.3, 0.5),
}


def clamp_temperature(task_type: TaskType, temperature: float) -> float:
    temp_range = TASK_TEMPERATURE_RANGES.get(task_type)
    if temp_range is None:
        return temperature
    low, high = temp_range
    if temperature < low:
        logger.warning(f"Temperature {temperature} below range [{low},{high}] for {task_type.value}, clamped to {low}")
        return low
    if temperature > high:
        logger.warning(f"Temperature {temperature} above range [{low},{high}] for {task_type.value}, clamped to {high}")
        return high
    return temperature


_REASONING_PREFIXES = [
    "According to my analysis",
    "Based on my analysis",
    "Let me analyze",
    "Let me think",
    "I'll analyze",
    "As I reason through this",
    "My reasoning:",
    "Analysis:",
]


def strip_reasoning_artifacts(content: str) -> str:
    if not content:
        return ""
    text = str(content)
    text = re.sub(r"<reasoning\b[^>]*>.*?</reasoning>", "", text, flags=re.S | re.I)
    text = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.S | re.I)
    text = re.sub(r"<thinking\b[^>]*>.*?</thinking>", "", text, flags=re.S | re.I)
    text = re.sub(r"^```(?:thinking|reasoning)\s*.*?```", "", text, flags=re.S | re.I | re.M)
    for prefix in _REASONING_PREFIXES:
        if text.startswith(prefix):
            newline_pos = text.find("\n")
            if newline_pos != -1:
                text = text[newline_pos + 1:]
            else:
                text = ""
            break
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        skip = False
        for prefix in _REASONING_PREFIXES:
            if stripped.startswith(prefix):
                skip = True
                break
        if not skip:
            cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)
    return text.strip()


def normalize_model_id(model: str) -> str:
    if "/" in model:
        return model
    if settings.LLM_API_BASE and "api.openai.com" not in settings.LLM_API_BASE.lower():
        return f"openai/{model}"
    return model


def parse_json_response(content: str):
    if not content:
        raise ValueError("LLM returned empty JSON response")
    text = strip_reasoning_artifacts(content).strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start_candidates = [idx for idx in (text.find("{"), text.find("[")) if idx != -1]
        if not start_candidates:
            raise
        start = min(start_candidates)
        end = max(text.rfind("}"), text.rfind("]"))
        if end <= start:
            raise
        return json.loads(text[start:end + 1])


@log_llm_call(logger)
async def call_llm(
    task_type: TaskType,
    prompt: str,
    system: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    json_mode: bool = False,
):
    """调用 LLM。

    行为：
    - 通过 `ModelRouter.execute()` 走主备模型切换
    - 单模型内部按 `LLM_MAX_RETRIES_PER_MODEL` 指数退避重试
    - 致命错误（401/403/404/context_too_long）不重试
    - JSON mode 不支持时自动降级到纯文本 + `parse_llm_json`
    """
    from core.model_router import get_router
    from core.llm_errors import classify_llm_exception
    from core.llm_json import parse_llm_json

    temperature = clamp_temperature(task_type, temperature)
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    router = get_router()
    role = _task_to_role(task_type)

    call_kwargs = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "json_mode": json_mode,
    }

    if settings.LLM_ROUTE_FALLBACK_ENABLED:
        return await router.execute(role, _single_llm_call, **call_kwargs)

    model = router.select_model(role)
    if not model:
        raise RuntimeError(f"No model configured for role {role}")
    return await _single_llm_call(model, **call_kwargs)


def _should_use_response_format(json_mode: bool) -> bool:
    """根据 `LLM_JSON_MODE_POLICY` 决定是否添加 `response_format`。

    - off: 永远不开
    - force: 强制开
    - auto: 只在已知支持 JSON mode 的 provider 下开
    """
    if not json_mode:
        return False
    if not settings.LLM_USE_RESPONSE_FORMAT and getattr(settings, "LLM_JSON_MODE_POLICY", "auto") == "auto":
        return False
    policy = getattr(settings, "LLM_JSON_MODE_POLICY", "auto").lower()
    if policy == "off":
        return False
    if policy == "force":
        return True
    provider = getattr(settings, "LLM_PROVIDER", "openai_compatible").lower()
    return provider in {
        "openai",
        "openai_compatible",
        "newapi",
        "oneapi",
        "deepseek",
        "qwen",
        "lmstudio",
    }


def _task_to_role(task_type: TaskType):
    """任务类型 -> 模型角色映射（避免循环 import）。"""
    from core.model_router import TASK_TO_ROLE, ModelRole
    return TASK_TO_ROLE.get(task_type, ModelRole.WRITER)


async def _single_llm_call(
    model_config,
    *,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    json_mode: bool,
):
    """单模型 LLM 调用 + 内部重试 + JSON mode 降级。

    由 `ModelRouter.execute()` 包装，自动处理主备切换。
    """
    from core.llm_errors import classify_llm_exception
    from core.llm_json import parse_llm_json

    model_name = model_config.name
    api_key = model_config.api_key or settings.LLM_API_KEY
    api_base = model_config.api_base or settings.LLM_API_BASE
    timeout = model_config.timeout or settings.LLM_TIMEOUT_SECONDS

    if not api_key:
        raise ValueError("API key not configured. Set OPENAI_API_KEY or LLM_API_KEY in .env file")

    use_format = _should_use_response_format(json_mode)
    max_attempts = max(1, settings.LLM_MAX_RETRIES_PER_MODEL)
    last_exc: Exception | None = None
    response_format_dropped = False

    for attempt in range(max_attempts):
        kwargs = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "api_key": api_key,
            "api_base": api_base,
        }
        if use_format and not response_format_dropped:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await asyncio.wait_for(
                litellm.acompletion(**kwargs),
                timeout=timeout,
            )
            content = _extract_content(response)
            content = strip_reasoning_artifacts(content)
            if json_mode:
                return parse_llm_json(content)
            return content

        except Exception as exc:
            last_exc = exc
            info = classify_llm_exception(exc)

            if use_format and not response_format_dropped and (
                "response_format" in str(exc)
                or "json" in str(exc).lower()
                or info.code in {"json_error", "unknown"}
            ):
                logger.warning(
                    "[%s] response_format 失败，自动降级到普通文本: %s",
                    model_name, exc,
                )
                response_format_dropped = True
                continue

            if info.fatal or not info.retryable:
                logger.error(
                    "[%s] 致命/不可重试错误 [%s]: %s",
                    model_name, info.code, exc,
                )
                raise

            if attempt < max_attempts - 1:
                delay = settings.LLM_RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "[%s] 第 %d 次失败 [%s]，%.1fs 后重试: %s",
                    model_name, attempt + 1, info.code, delay, exc,
                )
                await asyncio.sleep(delay)
                continue

            raise

    if last_exc:
        raise last_exc
    raise RuntimeError("LLM call failed without exception")


def _extract_content(response) -> str:
    """从 LiteLLM response 中提取文本内容。"""
    content = response.choices[0].message.content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(item["text"])
            elif item:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content or "")


def route_model(task_type: TaskType) -> str:
    return normalize_model_id(MODEL_ROUTE.get(task_type, settings.LLM_WRITER_MODEL))
