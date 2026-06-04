import json
import logging
from core.llm_router import call_llm, TaskType
from core.models import PlotArc

logger = logging.getLogger(__name__)

PLOT_SYSTEM = """你是一个剧情推进引擎，负责控制故事节奏和逻辑连贯。
你需要确保：
- 剧情不跳跃、不断裂
- 冲突密度合理（每1000字至少一个冲突点）
- 主线和支线交替推进
- 伏笔有回收
- 节奏有起伏（紧张-舒缓-高潮）"""

PLOT_PROMPT = """根据以下信息，规划当前章节的剧情推进：

当前章节：{chapter_title}
章节目标：{chapter_goal}
章节冲突：{chapter_conflict}
主线进度：{main_arc}
活跃支线：{side_arcs}
最近剧情：{recent_summary}
当前人物状态：{characters_status}
故事控制信息：{story_control}

请输出JSON：
{{
  "main_progress": "主线推进内容",
  "side_progress": ["支线推进1"],
  "new_conflicts": ["新冲突1"],
  "foreshadowing": ["伏笔1"],
  "resolution": "本章解决的冲突",
  "hook": "章末钩子（悬念）",
  "pacing": "节奏（tight/normal/relax）"
}}"""


class PlotEngine:
    async def plan_chapter_plot(
        self,
        chapter_title: str,
        chapter_goal: str,
        chapter_conflict: str,
        main_arc: str,
        side_arcs: list[str],
        recent_summary: str,
        characters_status: str,
        story_control: str = "",
    ) -> dict:
        prompt = PLOT_PROMPT.format(
            chapter_title=chapter_title,
            chapter_goal=chapter_goal,
            chapter_conflict=chapter_conflict,
            main_arc=main_arc,
            side_arcs=", ".join(side_arcs) if side_arcs else "无",
            recent_summary=recent_summary[:1000] if recent_summary else "无",
            characters_status=characters_status[:500] if characters_status else "无",
            story_control=story_control[:1200] if story_control else "无",
        )
        try:
            result = await call_llm(TaskType.PLOT, prompt, system=PLOT_SYSTEM, json_mode=True, temperature=0.7)
        except Exception as e:
            logger.warning(f"Plot planning failed, using fallback: {e}")
            result = {}
        if not isinstance(result, dict):
            return {
                "main_progress": chapter_goal,
                "side_progress": [],
                "new_conflicts": [chapter_conflict] if chapter_conflict else [],
                "foreshadowing": [],
                "resolution": "保留部分悬念",
                "hook": "新的危机在暗处逼近。",
                "pacing": "normal",
            }
        return result

    async def check_pacing(self, chapter_text: str) -> dict:
        prompt = f"""分析以下章节的节奏和冲突密度：

{chapter_text[:3000]}

请输出JSON：
{{
  "conflict_count": 冲突数量,
  "dialogue_ratio": 对话占比(0-1),
  "pacing_score": 节奏评分(0-10),
  "is_too_slow": true/false,
  "suggestion": "改进建议"
}}"""
        result = await call_llm(TaskType.CHECK, prompt, json_mode=True, temperature=0.3)
        return result

    async def generate_hook(self, chapter_text: str, next_hint: str = "") -> str:
        prompt = f"""为以下章节结尾设计一个悬念钩子，让读者想继续阅读：

章节内容（末尾）：{chapter_text[-1000:]}
下一章提示：{next_hint}

只输出1-2句悬念钩子文字。"""
        hook = await call_llm(TaskType.WRITE, prompt, temperature=0.8, max_tokens=200)
        return hook.strip()
