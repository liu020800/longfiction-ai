import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from core.config import settings
from core.models import TaskType

logger = logging.getLogger(__name__)


@dataclass
class ModelPerformance:
    total_calls: int = 0
    total_errors: int = 0
    avg_quality_score: float = 0.0
    avg_latency_ms: float = 0.0
    last_error_time: float = 0.0
    _quality_scores: list = field(default_factory=list)

    def record_call(self, quality_score: float = None, latency_ms: float = 0, error: bool = False):
        self.total_calls += 1
        if error:
            self.total_errors += 1
            self.last_error_time = time.time()
        if quality_score is not None:
            self._quality_scores.append(quality_score)
            if len(self._quality_scores) > 50:
                self._quality_scores = self._quality_scores[-50:]
            self.avg_quality_score = sum(self._quality_scores) / len(self._quality_scores)
        if latency_ms > 0:
            if self.avg_latency_ms == 0:
                self.avg_latency_ms = latency_ms
            else:
                self.avg_latency_ms = self.avg_latency_ms * 0.8 + latency_ms * 0.2

    @property
    def error_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_errors / self.total_calls

    @property
    def is_healthy(self) -> bool:
        if self.total_calls < 3:
            return True
        if self.error_rate > 0.5:
            cooldown = 300
            if time.time() - self.last_error_time < cooldown:
                return False
        return True


MODEL_CAPABILITIES = {
    "creative_writing": {"weight": 1.0, "preferred_tasks": [TaskType.WRITE, TaskType.REWRITE]},
    "reasoning": {"weight": 1.0, "preferred_tasks": [TaskType.CHECK, TaskType.PLAN]},
    "structured_output": {"weight": 0.8, "preferred_tasks": [TaskType.WORLD, TaskType.CHARACTER]},
    "speed": {"weight": 0.5, "preferred_tasks": [TaskType.PLOT]},
}

TASK_COMPLEXITY = {
    TaskType.WRITE: "high",
    TaskType.REWRITE: "medium",
    TaskType.CHECK: "medium",
    TaskType.PLAN: "high",
    TaskType.WORLD: "medium",
    TaskType.CHARACTER: "medium",
    TaskType.PLOT: "low",
}


class ModelRouter:
    def __init__(self):
        self._performance: dict[str, dict[str, ModelPerformance]] = defaultdict(
            lambda: defaultdict(ModelPerformance)
        )
        self._override_models: dict[str, str] = {}

    def select_model(self, task_type: TaskType, complexity_hint: str = None) -> str:
        from core.llm_router import MODEL_ROUTE, MODEL_FALLBACK_CHAIN, normalize_model_id

        if task_type.value in self._override_models:
            return normalize_model_id(self._override_models[task_type.value])

        primary = MODEL_ROUTE.get(task_type, settings.LLM_DEFAULT_MODEL)
        perf = self._performance[primary].get(task_type.value)

        if perf and not perf.is_healthy:
            fallback_chain = MODEL_FALLBACK_CHAIN.get(task_type, [])
            for fallback in fallback_chain:
                if fallback == primary:
                    continue
                fb_perf = self._performance[fallback].get(task_type.value)
                if fb_perf is None or fb_perf.is_healthy:
                    logger.info(f"ModelRouter: {primary} unhealthy for {task_type.value}, using fallback {fallback}")
                    return normalize_model_id(fallback)

        return normalize_model_id(primary)

    def record_result(self, model: str, task_type: TaskType, quality_score: float = None, latency_ms: float = 0, error: bool = False):
        self._performance[model][task_type.value].record_call(
            quality_score=quality_score,
            latency_ms=latency_ms,
            error=error,
        )

    def set_override(self, task_type: str, model: str):
        self._override_models[task_type] = model

    def clear_override(self, task_type: str):
        self._override_models.pop(task_type, None)

    def get_stats(self) -> dict:
        stats = {}
        for model, tasks in self._performance.items():
            stats[model] = {}
            for task, perf in tasks.items():
                stats[model][task] = {
                    "total_calls": perf.total_calls,
                    "error_rate": round(perf.error_rate, 3),
                    "avg_quality": round(perf.avg_quality_score, 2),
                    "avg_latency_ms": round(perf.avg_latency_ms, 1),
                    "is_healthy": perf.is_healthy,
                }
        return stats

    def get_recommendation(self, task_type: TaskType) -> dict:
        best_model = None
        best_score = -1

        from core.llm_router import MODEL_FALLBACK_CHAIN
        candidates = MODEL_FALLBACK_CHAIN.get(task_type, [settings.LLM_DEFAULT_MODEL])

        for model in candidates:
            perf = self._performance[model].get(task_type.value)
            if perf is None:
                score = 0.5
            elif not perf.is_healthy:
                continue
            else:
                quality_factor = perf.avg_quality_score / 10.0 if perf.avg_quality_score > 0 else 0.5
                reliability_factor = 1.0 - perf.error_rate
                score = quality_factor * 0.7 + reliability_factor * 0.3
            if score > best_score:
                best_score = score
                best_model = model

        return {
            "task_type": task_type.value,
            "recommended_model": best_model or settings.LLM_DEFAULT_MODEL,
            "confidence": round(best_score, 2),
            "candidates": candidates,
        }


model_router = ModelRouter()
