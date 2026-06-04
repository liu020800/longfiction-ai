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
) -> str:
    from core.model_router import model_router
    temperature = clamp_temperature(task_type, temperature)
    model = model_router.select_model(task_type)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    if not settings.LLM_API_KEY:
        error_msg = "API key not configured. Set OPENAI_API_KEY in .env file"
        logger.error(error_msg)
        raise ValueError(error_msg)

    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "api_key": settings.LLM_API_KEY,
        "api_base": settings.LLM_API_BASE,
    }
    if json_mode and settings.LLM_USE_RESPONSE_FORMAT:
        kwargs["response_format"] = {"type": "json_object"}

    start_time = time.time()
    try:
        try:
            response = await asyncio.wait_for(litellm.acompletion(**kwargs), timeout=settings.LLM_TIMEOUT_SECONDS)
        except Exception as e:
            if "response_format" in kwargs:
                logger.warning(f"LLM response_format failed, retrying without it: {e}")
                kwargs.pop("response_format", None)
                response = await asyncio.wait_for(litellm.acompletion(**kwargs), timeout=settings.LLM_TIMEOUT_SECONDS)
            else:
                raise
        latency_ms = (time.time() - start_time) * 1000
        model_router.record_result(model, task_type, latency_ms=latency_ms)
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        model_router.record_result(model, task_type, latency_ms=latency_ms, error=True)
        raise

    content = response.choices[0].message.content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(item["text"])
            elif item:
                parts.append(str(item))
        content = "\n".join(parts)
    content = strip_reasoning_artifacts(content)
    if json_mode:
        return parse_json_response(content)
    return content


def route_model(task_type: TaskType) -> str:
    return normalize_model_id(MODEL_ROUTE.get(task_type, settings.LLM_WRITER_MODEL))
