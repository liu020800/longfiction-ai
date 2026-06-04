import logging
from core.llm_router import call_llm, TaskType

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """请为以下章节内容生成简洁摘要（100字以内），保留关键事件、人物变化、新信息：

{chapter_text}

只输出摘要文字。"""

FEEDBACK_PROMPT = """模拟读者阅读以下章节后的评论反应：

{chapter_text}

请输出JSON：
{{
  "excitement": 1-10评分,
  "boredom_points": ["无聊的部分"],
  "cool_points": ["爽点"],
  "suggestions": ["改进建议"],
  "want_continue": true/false,
  "simulated_comments": ["模拟读者评论1", "模拟读者评论2"]
}}"""


class CriticAgent:
    async def summarize(self, chapter_text: str) -> str:
        prompt = SUMMARY_PROMPT.format(chapter_text=chapter_text[:3000])
        summary = await call_llm(TaskType.CHECK, prompt, temperature=0.3, max_tokens=200)
        return summary.strip()

    async def simulate_feedback(self, chapter_text: str) -> dict:
        prompt = FEEDBACK_PROMPT.format(chapter_text=chapter_text[:3000])
        result = await call_llm(TaskType.CHECK, prompt, json_mode=True, temperature=0.7)
        return result

    async def select_best_version(self, versions: list[str]) -> int:
        if len(versions) <= 1:
            return 0
        preview = "\n\n---\n\n".join([f"版本{i+1}（前500字）：\n{v[:500]}" for i, v in enumerate(versions)])
        prompt = f"""以下是同一章节的{len(versions)}个版本，请选择最好的一个：

{preview}

请输出JSON：{{"best_version": 版本编号(1-{len(versions)}), "reason": "选择原因"}}"""
        try:
            result = await call_llm(TaskType.CHECK, prompt, json_mode=True, temperature=0.3)
            best = result.get("best_version", 1)
            return max(0, min(best - 1, len(versions) - 1))
        except Exception as e:
            logger.warning(f"Best version selection failed, using first version: {e}")
            return 0

    async def evaluate_pacing(self, chapter_text: str) -> dict:
        prompt = f"""评估以下章节的节奏质量：

{chapter_text[:2000]}

请输出JSON：
{{
  "conflict_density": "冲突密度(高/中/低)",
  "dialogue_ratio": "对话占比估计(0-1)",
  "cliff_hanger_score": "悬念评分(0-10)",
  "overall_pacing": "整体节奏评分(0-10)",
  "is_water": "是否水文(true/false)"
}}"""
        result = await call_llm(TaskType.CHECK, prompt, json_mode=True, temperature=0.3)
        return result
