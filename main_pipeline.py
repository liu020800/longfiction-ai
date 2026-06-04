import logging
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from core.models import (
    VolumeOutline, ChapterOutline, SceneOutline, WorldSetting,
    CharacterSheet, ChapterDraft, ConsistencyReport, GenerationRequest,
)
from core.config import settings
from core.word_counter import count_chinese_words, compute_deviation, allocate_scene_words, _rule_based_trim, CorrectionSnapshot, CorrectionHistory, CorrectionStrategy, evaluate_expand_quality, evaluate_trim_completeness, compute_style_drift, _repair_scene_boundaries
from memory.memory_system import MemorySystem
from rag.rag_engine import RAGEngine
from agents.planner_agent import PlannerAgent
from agents.world_builder import WorldBuilderAgent
from agents.character_engine import CharacterEngine
from agents.character_state_machine import CharacterStateManager, StateTransitionBlockError, RelationType
from agents.writer_agent import WriterAgent
from agents.style_rewriter import StyleRewriter, AIPatternDetector
from agents.style_controller import StyleLearner, StylePreserver
from agents.consistency_checker import ConsistencyChecker, ConsistencyGate, ConsistencyBlockError
from agents.critic_agent import CriticAgent
from agents.enhancement.orchestrator import EnhancementOrchestrator
from agents.enhancement.enhancement_config import EnhancementConfig
from agents.enhancement.models import AnchorCategory, AnchorDefinition, ArcLevel, SuspenseArc
from core.llm_router import call_llm
from core.models import TaskType
from core.validators import OutputValidationError  # P2 程序级修复：质量门异常
from memory.hierarchical_summary import HierarchicalSummaryManager
from models.db_models import Chapter, ChapterVersion, TimelineEvent
from models.db_models import Foreshadowing, PlotArcRecord

logger = logging.getLogger(__name__)

INITIAL_PLAN_CHAPTERS = 12
STAGE_PLAN_CHAPTERS = 12

PROJECT_BLUEPRINT_SYSTEM = """你是长篇网文总策划。请一次性完成世界观、人物和第一阶段章节规划。
只输出JSON，不要解释。输出必须能直接进入生产写作流程。"""

PROJECT_BLUEPRINT_PROMPT = """基于以下小说要求，一次性生成项目蓝图。

大纲：{outline}
类型：{genre}
整书目标章节数：{target_chapters}
本次规划章节数：{plan_chapters}

输出JSON格式：
{{
  "world": {{
    "cultivation_system": "力量/规则体系，含成长路径和代价",
    "factions": [{{"name":"势力名","type":"类型","description":"利益和冲突"}}],
    "rules": ["关键规则"],
    "history": ["重大历史或前史"],
    "locations": [{{"name":"地点","description":"地点作用"}}]
  }},
  "characters": [
    {{
      "name": "角色名",
      "goal": "核心目标",
      "personality": ["性格特征"],
      "appearance": "外貌/气质",
      "abilities": ["能力/资源"],
      "status": {{"stage": "初始状态"}},
      "relationships": [],
      "memory": []
    }}
  ],
  "volume": {{
    "volume": "第一卷",
    "chapters": [
      {{
        "title": "章节标题",
        "goal": "本章目标，必须具体可写",
        "conflict": "本章冲突，必须有阻力和代价",
        "scenes": [
          {{
            "description": "场景描述，包含行动、冲突、转折和结尾钩子",
            "characters": ["出场角色"],
            "location": "地点",
            "mood": "氛围",
            "target_words": {scene_target_words}
          }}
        ]
      }}
    ]
  }}
}}

要求：
- characters 生成3-5个核心角色，优先复用大纲里的明确姓名。
- chapters 数量必须等于 {plan_chapters}。
- 每章给1-2个高信息量场景即可，不要拆成很多碎场景。
- 章节规划只做第一阶段，不要一次规划完整长篇。
- 所有内容必须贴合大纲，不要输出“主角/盟友/宿敌”这类占位名。"""


class MainPipeline:
    def __init__(self, session_id: str = None):
        self.session_id = session_id
        self.memory = MemorySystem(session_id=session_id)
        self.rag = RAGEngine(self.memory.long_term)
        self.planner = PlannerAgent()
        self.world_builder = WorldBuilderAgent()
        self.character_engine = CharacterEngine()
        self.state_manager = CharacterStateManager()
        self.writer = WriterAgent()
        self.style_rewriter = StyleRewriter()
        self.style_learner = StyleLearner()
        self.style_preserver = StylePreserver()
        self.ai_detector = AIPatternDetector()
        self.consistency_checker = ConsistencyChecker()
        self.consistency_gate = ConsistencyGate(self.consistency_checker)
        self.critic = CriticAgent()
        self._enhancement_llm_call = lambda prompt: call_llm(TaskType.WRITE, prompt, temperature=0.3)
        self.enhancement = EnhancementOrchestrator(EnhancementConfig(), memory_system=self.memory, llm_call=self._enhancement_llm_call)
        self.consistency_checker.load_default_rules()

        self.hierarchical_summary = HierarchicalSummaryManager(
            project_id=session_id or "default",
            chapters_per_arc=10,
            recent_chapters=5,
        )

        self.outline: str = ""
        self.title: str = "未命名项目"
        self.genre: str = "urban_fantasy"
        self.style: str = "web_novel"
        self.target_chapters: int = 12
        self.words_per_chapter: int = 2000
        self.volume: Optional[VolumeOutline] = None
        self.world: Optional[WorldSetting] = None
        self.characters: list[CharacterSheet] = []
        self.generated_chapters: list[ChapterDraft] = []
        self.approved: bool = False
        self.finalized_chapters: list[int] = []
        self.pending_chapter_updates: dict[int, dict] = {}
        self.global_summary: str = ""
        self._previous_chapter_tail: str = ""
        self.evolution_state: dict = self._default_evolution_state()
        self.open_intents_ledger: dict = self._default_open_intents_ledger()
        self.consistency_gate_stats: dict = self._default_consistency_gate_stats()
        self.planning_window: int = STAGE_PLAN_CHAPTERS
        self.tail_repair_locked: bool = False
        self.style_fingerprint: dict = {}
        self._project_word_freq: dict[str, int] = {}  # 项目级词频追踪（跨章节累积）

    def _default_evolution_state(self) -> dict:
        return {
            "last_synced_chapter": -1,
            "history": [],
            "outline_memory": [],
            "world_memory": [],
            "strategy": "初始设定定方向，定稿记忆保连续，阶段性重规划贴合实际故事。",
        }

    def _default_open_intents_ledger(self) -> dict:
        return {
            "story_bible": {},
            "unresolved_payoffs": [],
            "continuity_debts": [],
            "closed_items": [],
        }

    def _default_consistency_gate_stats(self) -> dict:
        return {
            "pre_generation_calls": 0,
            "pre_generation_warnings": 0,
            "pre_generation_blocks": 0,
            "state_machine_warnings": 0,
            "state_machine_blocks": 0,
            "show_dont_tell_flags": 0,
            "last_issues": [],
        }

    def _normalize_evolution_state(self):
        base = self._default_evolution_state()
        if isinstance(self.evolution_state, dict):
            base.update(self.evolution_state)
        self.evolution_state = base

    def _normalize_consistency_gate_stats(self):
        base = self._default_consistency_gate_stats()
        if isinstance(self.consistency_gate_stats, dict):
            base.update(self.consistency_gate_stats)
        base["last_issues"] = list(base.get("last_issues", []) or [])[-20:]
        self.consistency_gate_stats = base

    def _normalize_open_intents_ledger(self):
        base = self._default_open_intents_ledger()
        if isinstance(self.open_intents_ledger, dict):
            base.update(self.open_intents_ledger)
        bible = base.get("story_bible") if isinstance(base.get("story_bible"), dict) else {}
        base["story_bible"] = {
            "core_promise": str(bible.get("core_promise", "") or ""),
            "ending_answer": str(bible.get("ending_answer", "") or ""),
            "main_conflict": str(bible.get("main_conflict", "") or ""),
            "world_constraints": self._dedupe_text_list(list(bible.get("world_constraints", []) or []), limit=8),
            "character_arcs": [
                item for item in (bible.get("character_arcs", []) or [])
                if isinstance(item, dict) and str(item.get("name", "") or "").strip()
            ][:8],
        }
        unresolved = []
        seen = set()
        for item in base.get("unresolved_payoffs", []) or []:
            if not isinstance(item, dict):
                continue
            desc = self._sanitize_chapter_outline_text(str(item.get("description", "") or "").strip())
            if not desc:
                continue
            key = re.sub(r"\s+", "", desc)
            if key in seen:
                continue
            seen.add(key)
            unresolved.append({
                "description": desc,
                "origin_chapter": max(0, int(item.get("origin_chapter", 0) or 0)),
                "deadline_hint": max(0, int(item.get("deadline_hint", 0) or 0)),
                "keywords": self._dedupe_text_list(list(item.get("keywords", []) or []) or self._extract_keywords(desc)[:6], limit=6),
                "status": str(item.get("status", "active") or "active"),
                "last_seen_chapter": max(0, int(item.get("last_seen_chapter", item.get("origin_chapter", 0)) or 0)),
            })
        base["unresolved_payoffs"] = unresolved
        debts = []
        debt_seen = set()
        for item in base.get("continuity_debts", []) or []:
            if not isinstance(item, dict):
                continue
            desc = self._sanitize_chapter_outline_text(str(item.get("description", "") or "").strip())
            if not desc:
                continue
            key = re.sub(r"\s+", "", desc)
            if key in debt_seen:
                continue
            debt_seen.add(key)
            debts.append({
                "description": desc,
                "kind": str(item.get("kind", "continuity") or "continuity"),
                "origin_chapter": max(0, int(item.get("origin_chapter", 0) or 0)),
                "deadline_hint": max(0, int(item.get("deadline_hint", 0) or 0)),
                "status": str(item.get("status", "active") or "active"),
                "keywords": self._dedupe_text_list(list(item.get("keywords", []) or []) or self._extract_keywords(desc)[:6], limit=6),
            })
        base["continuity_debts"] = debts[-30:]
        base["closed_items"] = list(base.get("closed_items", []) or [])[-50:]
        self.open_intents_ledger = base

    def _ensure_chapter_scenes_integrity(self) -> bool:
        if not self.volume:
            return False
        char_names = [c.name for c in self.characters] if self.characters else ["主角"]
        changed = False
        for chapter in self.volume.chapters:
            normalized_scenes = []
            for scene in chapter.scenes or []:
                if isinstance(scene, SceneOutline):
                    normalized_scenes.append(scene)
                elif isinstance(scene, dict):
                    try:
                        normalized_scenes.append(SceneOutline(**scene))
                    except Exception:
                        logger.warning(f"Failed to load scene from dict, skipping: {list(scene.keys())[:5]}")
            if not normalized_scenes:
                goal = (chapter.goal or "").strip()
                conflict = (chapter.conflict or "").strip()
                title = (chapter.title or "").strip()
                seed = goal or conflict or title or "围绕章节目标推进剧情"
                scene_chars = char_names[:min(3, len(char_names))]
                chars_text = "、".join(scene_chars)
                scene1_desc = (
                    f"{seed[:60]}。"
                    f"出场人物：{chars_text}。"
                    f"本段聚焦冲突的触发：{conflict[:60] if conflict else '面对新的阻碍'}，"
                    f"通过具体行动和对话推进，结尾出现第一个转折。"
                )
                scene2_desc = (
                    f"{seed[:60]}。"
                    f"出场人物：{chars_text}。"
                    f"本段聚焦冲突的升级与代价：{conflict[:60] if conflict else '选择带来代价'}，"
                    f"人物必须做出决定，结尾留下悬念钩子。"
                )
                normalized_scenes = [
                    SceneOutline(
                        description=scene1_desc,
                        characters=scene_chars,
                        target_words=max(800, self.words_per_chapter // 2),
                    ),
                    SceneOutline(
                        description=scene2_desc,
                        characters=scene_chars,
                        target_words=max(800, self.words_per_chapter // 2),
                    ),
                ]
                changed = True
            elif len(normalized_scenes) == 1 and self.words_per_chapter >= 1600:
                seed = normalized_scenes[0].description or chapter.goal or chapter.conflict or ""
                scene_chars = char_names[:min(3, len(char_names))]
                chars_text = "、".join(scene_chars)
                half = max(900, self.words_per_chapter // 2)
                normalized_scenes = [
                    SceneOutline(
                        description=f"{seed[:80]}。出场人物：{chars_text}。承接上文进入行动与冲突。",
                        characters=scene_chars,
                        target_words=half,
                    ),
                    SceneOutline(
                        description=f"{seed[:80]}。出场人物：{chars_text}。推动冲突变化并完成本章落点。",
                        characters=scene_chars,
                        target_words=max(half, self.words_per_chapter - half),
                    ),
                ]
                changed = True
            chapter.scenes = normalized_scenes
            for scene in chapter.scenes:
                expected_weight = self._infer_scene_tension_weight(scene)
                if abs(float(getattr(scene, "tension_weight", 1.0) or 1.0) - expected_weight) > 0.01:
                    scene.tension_weight = expected_weight
                    changed = True
                expected_sensory = self._infer_scene_sensory_focus(scene)
                if expected_sensory and getattr(scene, "sensory_focus", "") != expected_sensory:
                    scene.sensory_focus = expected_sensory
                    changed = True
        return changed

    def _extract_core_promise_local(self) -> str:
        text = re.sub(r"\s+", " ", self.outline or "").strip()
        if not text:
            return "主角必须完成最初承诺的核心目标，并承担选择后的后果"
        for sep in ["。", "；", ";", "！", "?", "？"]:
            if sep in text:
                first = text.split(sep)[0].strip()
                if len(first) >= 8:
                    return first[:120]
        return text[:120]

    def _initialize_story_bible(self, force: bool = False):
        self._normalize_open_intents_ledger()
        bible = self.open_intents_ledger.get("story_bible", {}) or {}
        if bible.get("core_promise") and not force:
            return
        world_constraints = []
        if self.world:
            world_constraints.extend([str(rule) for rule in (self.world.rules or [])[:5]])
            if self.world.cultivation_system:
                world_constraints.append(str(self.world.cultivation_system)[:120])
        character_arcs = []
        for char in self.characters[:6]:
            start_state = ""
            if isinstance(char.status, dict):
                start_state = str(char.status.get("stage") or char.status.get("level") or char.status)[:80]
            character_arcs.append({
                "name": char.name,
                "start": start_state or "初始状态待正文确认",
                "want": char.goal[:100] if char.goal else "目标待正文确认",
                "end_need": f"围绕“{char.goal[:40]}”给出选择、代价或归宿" if char.goal else "给出清晰归宿",
                "status": "active",
            })
        core = self._extract_core_promise_local()
        self.open_intents_ledger["story_bible"] = {
            "core_promise": core,
            "ending_answer": f"最终必须正面回答：{core}",
            "main_conflict": self.volume.chapters[0].conflict[:140] if self.volume and self.volume.chapters else core,
            "world_constraints": self._dedupe_text_list(world_constraints, limit=8),
            "character_arcs": character_arcs,
        }

    def _format_story_bible_context(self, chapter_idx: int) -> str:
        self._initialize_story_bible()
        bible = self.open_intents_ledger.get("story_bible", {}) or {}
        total = max(1, int(self.target_chapters or (len(self.volume.chapters) if self.volume else 0) or 1))
        parts = [
            "## 故事圣经",
            f"核心承诺：{bible.get('core_promise') or '按项目大纲完成主线'}",
            f"终局答案：{bible.get('ending_answer') or '最终章必须回答核心承诺'}",
            f"主冲突：{bible.get('main_conflict') or '主线冲突必须持续推进'}",
        ]
        constraints = bible.get("world_constraints") or []
        if constraints:
            parts.append("设定硬约束：" + "；".join(str(x) for x in constraints[:5]))
        arcs = []
        for item in bible.get("character_arcs", []) or []:
            if isinstance(item, dict):
                arcs.append(f"{item.get('name')}：目标={item.get('want','')}；结局需求={item.get('end_need','')}")
        if arcs:
            parts.append("人物弧线：" + "；".join(arcs[:5]))
        debts = self.open_intents_ledger.get("continuity_debts", []) or []
        if debts:
            closing = [
                d for d in debts
                if int(d.get("deadline_hint", 0) or 0) and chapter_idx + 1 >= int(d.get("deadline_hint", 0) or 0) - 1
            ]
            selected = closing or debts
            parts.append("剧情债务：" + "；".join(d.get("description", "") for d in selected[:5]))
        if chapter_idx >= max(0, total - 3):
            unresolved = [d.get("description", "") for d in (self.open_intents_ledger.get("unresolved_payoffs", []) or [])[:6]]
            if unresolved:
                parts.append("终局清账清单：" + "；".join(unresolved))
        return "\n".join([p for p in parts if p.strip()])

    def _add_continuity_debt(self, description: str, chapter_idx: int, kind: str = "continuity", deadline_hint: int | None = None):
        cleaned = self._sanitize_chapter_outline_text(str(description or "").strip(), chapter_idx=chapter_idx)
        if not cleaned:
            return
        self._normalize_open_intents_ledger()
        total = max(1, int(self.target_chapters or (len(self.volume.chapters) if self.volume else 0) or 1))
        deadline = deadline_hint or min(total, max(chapter_idx + 3, int(total * 0.85)))
        existing = self.open_intents_ledger.get("continuity_debts", []) or []
        key = re.sub(r"\s+", "", cleaned)
        for item in existing:
            if re.sub(r"\s+", "", str(item.get("description", ""))) == key:
                item["deadline_hint"] = max(int(item.get("deadline_hint", 0) or 0), deadline)
                return
        existing.append({
            "description": cleaned,
            "kind": kind,
            "origin_chapter": chapter_idx + 1,
            "deadline_hint": deadline,
            "status": "active",
            "keywords": self._extract_keywords(cleaned)[:6],
        })
        self.open_intents_ledger["continuity_debts"] = existing[-30:]

    def _resolve_continuity_debts(self, chapter_idx: int, content: str):
        self._normalize_open_intents_ledger()
        text = str(content or "")
        keywords = set(self._extract_keywords(text))
        remaining = []
        closed = list(self.open_intents_ledger.get("closed_items", []) or [])
        for item in self.open_intents_ledger.get("continuity_debts", []) or []:
            item_keywords = set(item.get("keywords", []) or self._extract_keywords(item.get("description", ""))[:6])
            if len(keywords.intersection(item_keywords)) >= 2:
                closed.append({
                    "description": item.get("description", ""),
                    "closed_chapter": chapter_idx + 1,
                    "kind": item.get("kind", "continuity"),
                })
                continue
            deadline = int(item.get("deadline_hint", 0) or 0)
            if deadline and chapter_idx + 1 >= deadline - 1:
                item["status"] = "closing"
            remaining.append(item)
        self.open_intents_ledger["continuity_debts"] = remaining[-30:]
        self.open_intents_ledger["closed_items"] = closed[-50:]

    async def _build_project_blueprint(self, request: GenerationRequest, plan_count: int) -> bool:
        if not settings.ENABLE_UNIFIED_PROJECT_BLUEPRINT:
            return False
        prompt = PROJECT_BLUEPRINT_PROMPT.format(
            outline=request.outline,
            genre=request.genre,
            target_chapters=request.target_chapters,
            plan_chapters=plan_count,
            scene_target_words=max(settings.SCENE_TARGET_WORDS, request.words_per_chapter // 2),
        )
        try:
            result = await call_llm(
                TaskType.PLAN,
                prompt,
                system=PROJECT_BLUEPRINT_SYSTEM,
                json_mode=True,
                temperature=0.6,
                max_tokens=min(18000, max(6000, plan_count * 900)),
            )
        except Exception as e:
            logger.warning(f"Unified project blueprint failed, falling back to staged setup: {e}")
            return False
        if not isinstance(result, dict):
            return False
        try:
            world_data = result.get("world") or {}
            if isinstance(world_data, dict) and isinstance(world_data.get("cultivation_system"), dict):
                cs = world_data.get("cultivation_system") or {}
                world_data["cultivation_system"] = "；".join(
                    str(v) for v in [cs.get("name"), cs.get("description"), cs.get("rules"), cs.get("cost")]
                    if v
                )
            self.world = WorldSetting(**world_data)
            raw_characters = result.get("characters") or []
            if isinstance(raw_characters, dict):
                raw_characters = [raw_characters]
            self.characters = [CharacterSheet(**item) for item in raw_characters if isinstance(item, dict)]
            volume_data = result.get("volume") or {}
            if not volume_data and result.get("chapters"):
                volume_data = {"volume": "第一卷", "chapters": result.get("chapters")}
            self.volume = VolumeOutline(**volume_data)
        except Exception as e:
            logger.warning(f"Unified project blueprint parse failed, falling back to staged setup: {e}")
            self.world = None
            self.characters = []
            self.volume = None
            return False
        if not self.world or not self.characters or not self.volume or not self.volume.chapters:
            logger.warning("Unified project blueprint incomplete, falling back to staged setup")
            return False
        if len(self.volume.chapters) < plan_count:
            self.volume.chapters.extend(self.planner._continuation_chapters(request.outline, self.volume.chapters, plan_count, request.target_chapters))
        if len(self.volume.chapters) > plan_count:
            self.volume.chapters = self.volume.chapters[:plan_count]
        self.volume.chapters = self.planner._repair_repeated_chapters(request.outline, self.volume.chapters, plan_count, request.target_chapters)
        self._ensure_chapter_scenes_integrity()
        self._canonicalize_chapter_character_names()
        return True

    def _infer_scene_tension_weight(self, scene: SceneOutline) -> float:
        text = " ".join([
            str(scene.description or ""),
            str(scene.mood or ""),
            str(scene.location or ""),
        ])
        score = 1.0
        if any(token in text for token in ["对峙", "追逐", "爆发", "枪", "血", "威胁", "崩溃", "真相", "摊牌", "失控", "冲突"]):
            score = 1.5
        elif any(token in text for token in ["转折", "异常", "发现", "试探", "逼问", "误导", "线索"]):
            score = 1.2
        elif any(token in text for token in ["过渡", "整理", "回程", "休整", "铺垫", "沉默", "观察"]):
            score = 0.85
        return round(score, 2)

    def _infer_scene_sensory_focus(self, scene: SceneOutline) -> str:
        text = " ".join([
            str(scene.description or ""),
            str(scene.mood or ""),
            str(scene.location or ""),
        ])
        if any(token in text for token in ["医院", "实验室", "消毒", "药", "血"]):
            return "强化气味、温度和器械声，不要只写看到什么。"
        if any(token in text for token in ["雨", "夜", "街", "风", "车库"]):
            return "强化声音、湿冷触感和空气压力感。"
        if any(token in text for token in ["家", "客厅", "卧室", "书桌"]):
            return "强化触感、呼吸声和细小生活气味。"
        return "至少补出一种非视觉感官细节，如声音、气味、触感、温度或味道。"

    def _allocate_weighted_scene_words(self, target_words: int, scenes: list[SceneOutline]) -> list[int]:
        if not scenes:
            return [target_words]
        weights = [max(0.6, float(getattr(scene, "tension_weight", 1.0) or 1.0)) for scene in scenes]
        total_weight = sum(weights) or float(len(scenes))
        raw = [target_words * (w / total_weight) for w in weights]
        floored = [max(120, int(value)) for value in raw]
        current_total = sum(floored)
        diff = target_words - current_total
        if diff != 0:
            # 按权重排序，优先调整高权重场景
            order = sorted(range(len(scenes)), key=lambda i: weights[i], reverse=(diff > 0))
            max_iterations = abs(diff) + len(scenes)  # 精确上限，不会振荡
            idx_ptr = 0
            while diff != 0 and idx_ptr < max_iterations:
                idx = order[idx_ptr % len(order)]
                if diff > 0:
                    floored[idx] += 1
                    diff -= 1
                else:
                    if floored[idx] > 120:
                        floored[idx] -= 1
                        diff += 1
                    else:
                        # 所有场景都已到下限，无法再减
                        break
                idx_ptr += 1
        return floored

    def _build_progress_anchors(self) -> list[AnchorDefinition]:
        if not self.volume or not self.volume.chapters:
            return []
        total = len(self.volume.chapters)
        milestone_indices = {
            0,
            max(0, total // 4),
            max(0, total // 2),
            max(0, (total * 3) // 4),
            max(0, total - 1),
        }
        anchors: list[AnchorDefinition] = []
        for idx, chapter in enumerate(self.volume.chapters):
            if idx in milestone_indices:
                category = AnchorCategory.A_CLASS
            elif idx % 3 == 1:
                category = AnchorCategory.B_CLASS
            else:
                category = AnchorCategory.C_CLASS
            desc = (chapter.goal or chapter.conflict or chapter.title or f"第{idx + 1}章关键推进").strip()
            anchors.append(
                AnchorDefinition(
                    chapter_index=idx,
                    category=category,
                    description=desc[:160],
                    completed=idx in self.finalized_chapters,
                )
            )
        return anchors

    def _classify_foreshadow_type(self, text: str) -> str:
        cleaned = text or ""
        if any(marker in cleaned for marker in ["戒指", "书签", "钥匙", "监控", "档案", "公式", "证据"]):
            return "clue"
        if any(marker in cleaned for marker in ["自己", "失忆", "真相", "假死", "凶手", "实验"]):
            return "reveal"
        if any(marker in cleaned for marker in ["关系", "对立", "合作", "怀疑", "侧写"]):
            return "relationship"
        return "mystery"

    def _build_foreshadow_payload(self, chapter_idx: int, cleaned: str) -> dict:
        keywords = self._extract_keywords(cleaned)[:6]
        total = max(1, int(self.target_chapters or (len(self.volume.chapters) if self.volume else 0) or 1))
        close_by = min(total, max(chapter_idx + 2, int(total * 0.85)))
        return {
            "description": f"第{chapter_idx + 1}章埋线：{cleaned[:60]}",
            "foreshadow_type": self._classify_foreshadow_type(cleaned),
            "trigger_keywords": keywords,
            "payoff_condition": f"当后文明确回应这些关键词时回收：{'、'.join(keywords[:4])}" if keywords else "后文明确解释或揭示时回收",
            "source_excerpt": cleaned[:120],
            "close_by_chapter": close_by,
            "status": "active",
        }

    def _derive_new_foreshadow_candidates(self, chapter_idx: int, chapter_outline: ChapterOutline, chapter_text: str = "") -> list[dict]:
        base_texts = [chapter_outline.goal, chapter_outline.conflict, chapter_outline.title]
        for scene in (chapter_outline.scenes or []):
            if hasattr(scene, "description") and scene.description:
                base_texts.append(scene.description)
        candidates: list[dict] = []
        seen: set[str] = set()
        for text in base_texts:
            if not text:
                continue
            parts = re.split(r"[。；;！？!?\n]", text)
            for part in parts:
                cleaned = re.sub(r"\s+", " ", (part or "").strip("：:，,、 "))
                if not self._is_foreshadow_candidate(cleaned):
                    continue
                if cleaned in seen:
                    continue
                seen.add(cleaned)
                candidates.append(self._build_foreshadow_payload(chapter_idx, cleaned))
                if len(candidates) >= 3:
                    return candidates
        if chapter_text:
            opening = chapter_text[:1500]
            ending = chapter_text[-1500:] if len(chapter_text) > 2000 else ""
            for chunk in [opening, ending]:
                if not chunk:
                    continue
                for sentence in re.split(r"[。！？!?\n]", chunk):
                    cleaned = re.sub(r"\s+", " ", (sentence or "").strip("：:，,、 "))
                    if len(cleaned) < 12 or len(cleaned) > 100:
                        continue
                    if not self._is_foreshadow_candidate(cleaned):
                        continue
                    if cleaned in seen:
                        continue
                    seen.add(cleaned)
                    candidates.append(self._build_foreshadow_payload(chapter_idx, cleaned))
                    if len(candidates) >= 3:
                        return candidates
        return candidates

    def _is_foreshadow_candidate(self, text: str) -> bool:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(cleaned) < 8:
            return False
        # 强标记词：包含即为伏笔候选
        strong_markers = [
            "真相", "秘密", "线索", "倒计时", "失忆", "实验", "戒指", "书签", "监控", "假死",
            "档案", "钥匙", "公式", "研究所", "匿名", "疑点", "空白期", "证据", "碎片", "校准",
            "身份", "来历", "身世", "过去", "前世", "预言", "诅咒", "封印", "传承", "血脉",
            "失踪", "死亡", "背叛", "阴谋", "陷阱", "圈套", "幕后", "黑手", "内鬼",
            "遗物", "遗产", "遗书", "遗言", "信物", "标记", "符号", "图案", "密码",
        ]
        # 弱标记词：需要两个以上才算伏笔候选
        weak_markers = [
            "隐藏", "未知", "神秘", "奇怪", "异常", "不对劲", "蹊跷", "古怪",
            "回忆", "想起", "忘记", "模糊", "不清楚", "不确定",
            "危险", "威胁", "警告", "注意", "小心",
            "承诺", "约定", "誓言", "保证",
        ]
        reject_words = ["完成", "对峙", "要求", "决定", "合作", "调查", "返回现场", "联合办案"]
        if any(marker in cleaned for marker in strong_markers):
            pass  # 强标记通过
        elif sum(1 for marker in weak_markers if marker in cleaned) >= 2:
            pass  # 两个以上弱标记通过
        else:
            return False
        if sum(1 for marker in reject_words if marker in cleaned) >= 2:
            return False
        return True

    def _detect_foreshadow_resolution_spans(self, content: str) -> set[str]:
        spans: set[str] = set()
        for sentence in re.split(r"[。！？!?\n]", content or ""):
            cleaned = re.sub(r"\s+", " ", sentence).strip("：:，,、 ")
            if len(cleaned) < 10:
                continue
            if any(marker in cleaned for marker in ["原来", "真相", "证实", "解释", "承认", "揭开", "发现", "回想", "终于明白", "这意味着", "就是"]):
                spans.update(self._extract_keywords(cleaned))
        return spans

    def _is_structural_foreshadow_noise(self, description: str) -> bool:
        text = re.sub(r"\s+", " ", str(description or "")).strip()
        if not text:
            return True
        markers = [
            "承接前序线索",
            "让主线进入",
            "余韵收束",
            "下一部或番外的可能性",
            "本章重点是",
            "终局开门",
            "最终抉择",
            "新路线成形",
        ]
        return sum(1 for marker in markers if marker in text) >= 2

    def _normalize_foreshadow_payload(self, item, chapter_idx: int | None = None) -> dict | None:
        if isinstance(item, dict):
            description = re.sub(r"\s+", " ", str(item.get("description", "") or "")).strip()
            if not description:
                return None
            source_excerpt = re.sub(r"\s+", " ", str(item.get("source_excerpt", "") or "")).strip()
            trigger_keywords = item.get("trigger_keywords") or self._extract_keywords(source_excerpt or description)[:6]
            foreshadow_type = str(item.get("foreshadow_type", "") or self._classify_foreshadow_type(source_excerpt or description))
            payoff_condition = re.sub(r"\s+", " ", str(item.get("payoff_condition", "") or "")).strip()
            if not payoff_condition:
                payoff_condition = f"当后文明确回应这些关键词时回收：{'、'.join(trigger_keywords[:4])}" if trigger_keywords else "后文明确解释或揭示时回收"
            return {
                "description": description,
                "foreshadow_type": foreshadow_type,
                "trigger_keywords": list(trigger_keywords)[:8],
                "payoff_condition": payoff_condition,
                "source_excerpt": (source_excerpt or description)[:160],
                "close_by_chapter": max(0, int(item.get("close_by_chapter", 0) or 0)) or None,
                "status": str(item.get("status", "active") or "active"),
            }
        cleaned = re.sub(r"\s+", " ", str(item or "")).strip()
        if not cleaned:
            return None
        return self._build_foreshadow_payload(chapter_idx or 0, cleaned)

    def _foreshadow_prompt_text(self, item) -> str:
        payload = self._normalize_foreshadow_payload(item)
        if not payload:
            return ""
        trigger = "、".join(payload.get("trigger_keywords") or []) or "待后文回应"
        payoff = payload.get("payoff_condition", "") or "后文明确解释或揭示时回收"
        return f"{payload['description']}；触发词：{trigger}；回收条件：{payoff}"

    def _persist_foreshadow_payload(self, service, payload, chapter_idx: int):
        normalized = self._normalize_foreshadow_payload(payload, chapter_idx=chapter_idx)
        if not normalized:
            return None
        if self._is_structural_foreshadow_noise(normalized["description"]):
            return None
        return service.plant(
            self.session_id,
            normalized["description"],
            chapter_idx,
            foreshadow_type=normalized["foreshadow_type"],
            trigger_keywords=normalized["trigger_keywords"],
            payoff_condition=normalized["payoff_condition"],
            source_excerpt=normalized["source_excerpt"],
            close_by_chapter=normalized.get("close_by_chapter"),
        )

    def _dirty_suspense_seed(self, description: str) -> bool:
        text = str(description or "").strip()
        if not text:
            return True
        dirty_markers = ["##", "【类型】", "短期悬念(第", "中期悬念(第", "长线悬念(第", "核心谜团", "终局谜题"]
        return any(marker in text for marker in dirty_markers)

    def _build_suspense_arc_description(self, payload: dict) -> str:
        description = re.sub(r"^第\d+章埋线：", "", str(payload.get("description", "") or "")).strip()
        description = re.sub(r"\s+", " ", description).strip("：:，,。 ")
        if not description:
            description = re.sub(r"\s+", " ", str(payload.get("source_excerpt", "") or "")).strip()
        payoff = re.sub(r"\s+", " ", str(payload.get("payoff_condition", "") or "")).strip()
        triggers = "、".join(payload.get("trigger_keywords") or [])[:40]
        base = description[:48] or "当前关键悬念"
        if payoff:
            return f"{base}。闭合条件：{payoff[:54]}"
        if triggers:
            return f"{base}。关注触发词：{triggers}"
        return f"{base}。需在后续章节得到明确回应"

    def _needs_suspense_rebuild(self) -> bool:
        arcs = getattr(self.enhancement.suspense_arcs, "arcs", []) or []
        if not arcs:
            return True
        total = max(1, int(self.target_chapters or (len(self.volume.chapters) if self.volume else 0) or 1))
        for arc in arcs:
            if self._dirty_suspense_seed(arc.description):
                return True
            if arc.target_close_chapter > total:
                return True
        return False

    def _rebuild_suspense_arcs_from_story(self, force: bool = False):
        if not self.volume:
            return
        if not force and not self._needs_suspense_rebuild():
            self.enhancement.suspense_arcs.set_story_horizon(max(1, int(self.target_chapters or len(self.volume.chapters) or 1)))
            return

        total_chapters = max(1, int(self.target_chapters or len(self.volume.chapters) or 1))
        current_chapter_no = max([idx + 1 for idx in self.finalized_chapters], default=0)
        unresolved_payloads: list[dict] = []
        if self.session_id:
            try:
                from core.database import SessionLocal
                from models.db_service import ForeshadowingService

                with SessionLocal() as db:
                    unresolved_items = ForeshadowingService(db).get_unresolved(self.session_id)
                    for item in unresolved_items:
                        if self._is_structural_foreshadow_noise(item.description):
                            continue
                        unresolved_payloads.append({
                            "description": item.description,
                            "foreshadow_type": getattr(item, "foreshadow_type", "clue") or "clue",
                            "trigger_keywords": list(getattr(item, "trigger_keywords", []) or []),
                            "payoff_condition": getattr(item, "payoff_condition", "") or "",
                            "source_excerpt": getattr(item, "source_excerpt", "") or item.description,
                            "planted_chapter": item.planted_chapter,
                        })
            except Exception as e:
                logger.warning(f"Suspense source load failed: {e}")

        if not unresolved_payloads:
            for chapter_idx in sorted(set(self.finalized_chapters))[-6:]:
                if 0 <= chapter_idx < len(self.volume.chapters):
                    chapter_outline = self.volume.chapters[chapter_idx]
                    chapter_text = ""
                    for draft in self.generated_chapters:
                        if draft.chapter_index == chapter_idx and draft.content:
                            chapter_text = draft.content
                            break
                    for item in self._derive_new_foreshadow_candidates(chapter_idx, chapter_outline, chapter_text=chapter_text)[:2]:
                        payload = dict(item)
                        payload["planted_chapter"] = chapter_idx
                        unresolved_payloads.append(payload)

        arcs: list[SuspenseArc] = []
        seen: set[tuple[str, int]] = set()
        self.enhancement.suspense_arcs.story_total_chapters = total_chapters
        for payload in unresolved_payloads:
            planted_no = int(payload.get("planted_chapter", 0)) + 1
            if planted_no <= 0 or planted_no > total_chapters:
                continue
            # Skip stale foreshadows that are too old (15+ chapters)
            foreshadow_age = max(0, current_chapter_no - planted_no)
            if foreshadow_age > 15:
                continue
            description = self._build_suspense_arc_description(payload)
            key = (description[:80], planted_no)
            if key in seen:
                continue
            seen.add(key)
            age = max(0, current_chapter_no - planted_no)
            ftype = payload.get("foreshadow_type", "mystery")
            if age >= 8 or ftype in {"reveal", "mystery"}:
                level = ArcLevel.LONG
            elif age >= 4 or ftype == "relationship":
                level = ArcLevel.MEDIUM
            else:
                level = ArcLevel.SHORT
            target = self.enhancement.suspense_arcs._bounded_target(level, planted_no)
            is_overdue = current_chapter_no > target
            # Skip arcs that are already overdue at creation time - they're stale
            if is_overdue:
                continue
            arcs.append(
                SuspenseArc(
                    arc_id=f"rebuilt-{planted_no}-{len(arcs)}",
                    level=level,
                    description=description,
                    planted_chapter=planted_no,
                    target_close_chapter=target,
                    current_chapter=max(current_chapter_no, planted_no),
                    closed=False,
                    overdue=False,
                )
            )
            if len(arcs) >= 8:
                break

        if not arcs:
            seed_chapter = min(max(current_chapter_no, 1), total_chapters)
            fallback = (self.outline or self.title or "当前主线").replace("\n", " ").strip()
            arcs = [
                SuspenseArc(
                    arc_id="rebuilt-short",
                    level=ArcLevel.SHORT,
                    description=f"{fallback[:36]}在近期章节将如何进一步失控？",
                    planted_chapter=seed_chapter,
                    target_close_chapter=self.enhancement.suspense_arcs._bounded_target(ArcLevel.SHORT, seed_chapter),
                    current_chapter=seed_chapter,
                ),
                SuspenseArc(
                    arc_id="rebuilt-medium",
                    level=ArcLevel.MEDIUM,
                    description=f"{fallback[:36]}背后的关键隐情究竟是什么？",
                    planted_chapter=seed_chapter,
                    target_close_chapter=self.enhancement.suspense_arcs._bounded_target(ArcLevel.MEDIUM, seed_chapter),
                    current_chapter=seed_chapter,
                ),
                SuspenseArc(
                    arc_id="rebuilt-long",
                    level=ArcLevel.LONG,
                    description=f"{fallback[:36]}最终将把人物推向怎样的结局？",
                    planted_chapter=seed_chapter,
                    target_close_chapter=self.enhancement.suspense_arcs._bounded_target(ArcLevel.LONG, seed_chapter),
                    current_chapter=seed_chapter,
                ),
            ]

        self.enhancement.suspense_arcs.arcs = arcs
        self.enhancement.suspense_arcs.set_story_horizon(total_chapters)
        # Force-close arcs that are significantly overdue (>5 chapters past target)
        for arc in self.enhancement.suspense_arcs.arcs:
            if not arc.closed and arc.target_close_chapter > 0 and current_chapter_no > arc.target_close_chapter + 5:
                arc.closed = True
                arc.resolved_chapter = current_chapter_no
                arc.resolved_reason = f"重建时强制闭合（目标ch{arc.target_close_chapter}，当前ch{current_chapter_no}）"
        self.enhancement.suspense_arcs.normalize_arcs()

    def _dedupe_text_list(self, items: list[str], limit: int | None = None) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in items:
            cleaned = re.sub(r"\s+", " ", str(item or "")).strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            result.append(cleaned)
            if limit and len(result) >= limit:
                break
        return result

    def _clean_plot_progress_text(self, text: str) -> str:
        cleaned = self._strip_evolution_wrappers(
            text,
            prefixes=["承接已定稿进展", "在不推翻初始方向的前提下推进", "延续已发生变化带来的新压力"],
        )
        cleaned = re.sub(r"^遵循阶段演进[：: ]*", "", cleaned).strip()
        cleaned = re.sub(r"^同时优先照看未回收伏笔[：: ]*", "", cleaned).strip()
        return cleaned

    def _sanitize_chapter_outline_text(self, text: str, chapter_idx: int | None = None) -> str:
        cleaned = self._clean_plot_progress_text(text or "")
        if not cleaned:
            return ""
        replacements = [
            (r"#\s*《[^》]+》", ""),
            (r"##\s*【[^】]+】", ""),
            (r"承接前序线索[“\"].*?[”\"]", ""),
            (r"本章重点是", ""),
            (r"让主线进入[“\"].*?[”\"]", ""),
            (r"并为后续埋下[“\"].*?[”\"]", ""),
            (r"不能再做普通过渡", ""),
            (r"必须让", ""),
            (r"必须在第\d+章内", ""),
        ]
        for pattern, repl in replacements:
            cleaned = re.sub(pattern, repl, cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip("：:，,、；; ")
        if len(cleaned) > 220:
            cleaned = cleaned[:220].rstrip("，,、；;。.") + "。"
        if chapter_idx is not None and (not cleaned or len(cleaned) < 12):
            if 0 <= chapter_idx < len(self.volume.chapters):
                title = self.volume.chapters[chapter_idx].title
            else:
                title = f"第{chapter_idx + 1}章"
            cleaned = f"围绕《{title}》推进核心事件，避免空泛规划描述。"
        return cleaned

    def _recent_chapter_texts(self, chapter_idx: int, limit: int = 3) -> tuple[list[str], list[str]]:
        previous = sorted(
            [draft for draft in self.generated_chapters if draft.chapter_index < chapter_idx],
            key=lambda draft: draft.chapter_index,
        )
        recent = previous[-limit:]
        return [draft.content or "" for draft in recent], [draft.title or "" for draft in recent]

    def _chapter_word_floor(self, chapter_idx: int, target_words: int) -> int:
        total = max(1, int(self.target_chapters or (len(self.volume.chapters) if self.volume else 0) or 1))
        tail_start = max(0, total - 5)
        ratio = 0.78 if chapter_idx >= tail_start else 0.70
        absolute_floor = min(1000, max(100, int(target_words * 0.65)))
        return max(absolute_floor, int(target_words * ratio))

    def _dynamic_target_words(self, chapter_idx: int) -> int:
        """根据章节在全书中的位置动态调整目标字数。

        P2 修复：让章节字数差异更明显（接近编辑审查建议的 3-5 倍）：
        - 开头 2 章：0.85 倍（铺垫期）
        - 早期（<30%）：0.95 倍
        - 中期（30-50%）：1.0 倍
        - 中后期（50-70%）：1.05 倍
        - 高潮段（70-90%）：1.15 倍
        - 收尾段（>90% 但非末章）：1.2 倍
        - 末章（最后一章）：1.4 倍（高潮章，需要更多空间）
        """
        base = self.words_per_chapter or 2000
        total = max(1, self.target_chapters or 1)
        progress = chapter_idx / total

        if chapter_idx <= 1:
            factor = 0.85
        elif chapter_idx == total - 1:
            factor = 1.4  # 末章高潮
        elif progress >= 0.9:
            factor = 1.2  # 收尾段
        elif progress >= 0.7:
            factor = 1.15  # 高潮段
        elif progress >= 0.5:
            factor = 1.05
        elif progress >= 0.3:
            factor = 1.0
        else:
            factor = 0.95

        return max(800, int(base * factor))

    def _strip_title_prefix(self, title: str) -> str:
        cleaned = re.sub(r"^第\s*\d+\s*章\s*", "", str(title or "")).strip()
        return cleaned or str(title or "").strip()

    def _should_strip_numeric_titles(self) -> bool:
        if not self.volume or not self.volume.chapters:
            return False
        sample = self.volume.chapters[: min(8, len(self.volume.chapters))]
        if not sample:
            return False
        prefixed = sum(1 for ch in sample if re.match(r"^第\s*\d+\s*章", ch.title or ""))
        return prefixed <= max(1, len(sample) // 3)

    def normalize_chapter_title_style(self) -> bool:
        if not self.volume or not self.volume.chapters:
            return False
        if not self._should_strip_numeric_titles():
            return False
        changed = False
        for chapter in self.volume.chapters:
            new_title = self._strip_title_prefix(chapter.title)
            if new_title != chapter.title:
                chapter.title = new_title
                changed = True
        for draft in self.generated_chapters:
            new_title = self._strip_title_prefix(draft.title)
            if new_title != draft.title:
                draft.title = new_title
                changed = True
        if changed and self.session_id:
            self._force_sync_chapter_range_to_db(0, len(self.volume.chapters))
            self.save_project_state()
        return changed

    def _dedupe_adjacent_paragraphs(self, text: str) -> str:
        paragraphs = [p.strip() for p in str(text or "").split("\n\n") if p.strip()]
        deduped: list[str] = []
        seen_recent: list[str] = []
        for para in paragraphs:
            norm = re.sub(r"\s+", "", para)
            if norm in seen_recent[-2:]:
                continue
            if deduped and norm == re.sub(r"\s+", "", deduped[-1]):
                continue
            deduped.append(para)
            seen_recent.append(norm)
        return "\n\n".join(deduped)

    def _is_placeholder_scene_text(self, text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return True
        markers = [
            "前段铺垫", "后段推进", "地点：，气氛：。", "地点：", "气氛：",
            "围绕章节目标推进剧情", "待分析", "待续写",
        ]
        if any(marker in raw for marker in markers):
            return True
        compact = re.sub(r"\s+", "", raw)
        if len(compact) <= 90 and ("（前段" in raw or "（后段" in raw):
            return True
        return False

    def _chapter_has_placeholder_scenes(self, chapter_outline: ChapterOutline) -> bool:
        scenes = chapter_outline.scenes or []
        if not scenes:
            return True
        return any(self._is_placeholder_scene_text(getattr(scene, "description", "")) for scene in scenes)

    def _paragraph_similarity(self, left: str, right: str) -> float:
        left_set = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{1,}", str(left or "")))
        right_set = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{1,}", str(right or "")))
        if not left_set or not right_set:
            return 0.0
        inter = len(left_set & right_set)
        union = len(left_set | right_set)
        return inter / max(1, union)

    def _has_repeated_paragraph_blocks(self, text: str) -> bool:
        paragraphs = [p.strip() for p in str(text or "").split("\n\n") if p.strip()]
        if len(paragraphs) < 2:
            return False
        normalized: list[str] = []
        for para in paragraphs:
            compact = re.sub(r"\s+", "", para)
            if compact in normalized[-2:]:
                return True
            normalized.append(compact)
        # 检查相邻段落相似度
        for idx in range(1, len(paragraphs)):
            if self._paragraph_similarity(paragraphs[idx - 1], paragraphs[idx]) >= 0.82:
                return True
        # 检查非相邻段落是否存在高度相似（多版本场景拼接的特征）
        if len(paragraphs) >= 4:
            for i in range(len(paragraphs)):
                for j in range(i + 2, min(i + 8, len(paragraphs))):
                    if self._paragraph_similarity(paragraphs[i], paragraphs[j]) >= 0.65:
                        return True
        return False

    def _detect_generation_red_flags(self, chapter_idx: int, chapter_outline: ChapterOutline, chapter_text: str) -> list[str]:
        issues: list[str] = []
        stripped = str(chapter_text or "").strip()
        if self._is_placeholder_scene_text(stripped):
            issues.append("正文仍是场景占位稿，没有真正写成小说内容")
        if self._has_repeated_paragraph_blocks(stripped):
            issues.append("正文存在明显重复段落或重复推进")
        if chapter_idx == 0 and "别回来了" in stripped[:160]:
            issues.append("第一章开篇过早直接打出核心短信，缺少情境铺垫，像硬拼信息点")
        if len(stripped) < 300:
            issues.append("正文异常过短，疑似生成失败")
        # 检测多版本开头：同一个"醒来"场景是否出现多次
        awakening_markers = ["睁开眼", "醒来", "撑起身", "从床上坐起", "从梦中醒", "睁开了眼"]
        awakening_count = sum(1 for m in awakening_markers if stripped.count(m) >= 2)
        if awakening_count >= 2:
            issues.append("正文出现多次角色醒来/睁眼场景，疑似多版本拼接——请只保留一个开场")
        # 检测时间线矛盾：提取日期模式，检查是否出现互相矛盾的日期
        date_conflicts = self._detect_date_conflicts(stripped)
        if date_conflicts:
            issues.append(f"正文中出现互相矛盾的日期：{date_conflicts}——请统一为章节规划中的日期")
        return issues

    def _detect_date_conflicts(self, text: str) -> str:
        """检测文本中是否出现多个互相矛盾的日期。"""
        import re
        # 匹配中文日期模式：X年X月X日、X月X日
        date_patterns = re.findall(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
        if len(date_patterns) <= 1:
            return ""
        # 检查是否所有日期一致
        unique_dates = set(date_patterns)
        if len(unique_dates) <= 1:
            return ""
        # 存在不同日期，检查是否跨度合理（同章内超过30天视为矛盾）
        from datetime import date
        parsed = []
        for y, m, d in unique_dates:
            try:
                parsed.append(date(int(y), int(m), int(d)))
            except ValueError:
                continue
        if len(parsed) >= 2:
            span = (max(parsed) - min(parsed)).days
            if span > 30:
                dates_str = "、".join(f"{y}年{m}月{d}日" for y, m, d in unique_dates)
                return dates_str
        return ""

    def _build_chapter_intent(self, chapter_idx: int, chapter_outline: ChapterOutline) -> dict:
        total = max(1, int(self.target_chapters or (len(self.volume.chapters) if self.volume else 0) or 1))
        self._initialize_story_bible()
        self._normalize_open_intents_ledger()
        unresolved = self._get_unresolved_foreshadow_notes()
        must_payoff = [item["description"] for item in unresolved[:2]]
        ledger_items = self.open_intents_ledger.get("unresolved_payoffs", []) or []
        overdue_items = [
            item for item in ledger_items
            if int(item.get("deadline_hint", 0) or 0) and chapter_idx + 1 >= int(item.get("deadline_hint", 0) or 0)
        ]
        active_items = overdue_items or ledger_items
        for item in active_items[:3]:
            desc = item.get("description", "")
            if desc and desc not in must_payoff:
                must_payoff.append(desc)
        debt_items = self.open_intents_ledger.get("continuity_debts", []) or []
        closing_debts = [
            item for item in debt_items
            if int(item.get("deadline_hint", 0) or 0) and chapter_idx + 1 >= int(item.get("deadline_hint", 0) or 0) - 1
        ]
        selected_debts = closing_debts or debt_items
        for item in selected_debts[:3]:
            desc = item.get("description", "")
            if desc and desc not in must_payoff:
                must_payoff.append(desc)
        # 线程池强制任务融入 must_payoff
        thread_mandates = self.enhancement.thread_pool.get_mandates(chapter_idx)
        for t in thread_mandates.get("critical", []):
            tag = f"[截止] {t.description}"
            if tag not in must_payoff and t.description not in must_payoff:
                must_payoff.append(tag)
        for t in thread_mandates.get("urgent", []):
            tag = f"[紧迫] {t.description}"
            if tag not in must_payoff and t.description not in must_payoff:
                must_payoff.append(tag)
        must_avoid = [
            "不要复述上一章同样的感官开场",
            "不要新增与本章主线无关的新谜题",
            "不要用规划语言代替具体剧情推进",
        ]
        if chapter_idx >= total - 1:
            must_avoid.append("不要开放式甩尾，不要把主冲突留到番外或下一部")
        intent = {
            "chapter_no": chapter_idx + 1,
            "title": chapter_outline.title,
            "must_advance": self._sanitize_chapter_outline_text(chapter_outline.goal, chapter_idx=chapter_idx),
            "must_confront": self._sanitize_chapter_outline_text(chapter_outline.conflict, chapter_idx=chapter_idx),
            "must_payoff": self._dedupe_text_list(must_payoff, limit=4),
            "must_track": self._dedupe_text_list([d.get("description", "") for d in selected_debts[:4]], limit=4),
            "must_avoid": must_avoid,
            "ending_mode": "closure" if chapter_idx >= total - 1 else ("endgame" if chapter_idx >= total - 5 else "progress"),
        }
        return intent

    def analyze_style_fingerprint(self, sample_text: str) -> dict:
        text = str(sample_text or "").strip()
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        sentences = [s.strip() for s in re.split(r"[。！？!?]", text) if s.strip()]
        dialogue_marks = text.count("“") + text.count("”") + text.count("\"")
        sentence_lengths = [len(re.sub(r"\s+", "", s)) for s in sentences[:200] if s.strip()]
        avg_sentence = round(sum(sentence_lengths) / max(len(sentence_lengths), 1), 2)
        short_ratio = round(sum(1 for n in sentence_lengths if n <= 18) / max(len(sentence_lengths), 1), 3)
        keywords = self._extract_keywords(text)
        rhythm_words = self._dedupe_text_list([kw for kw in keywords if 2 <= len(kw) <= 4], limit=12)
        fingerprint = {
            "avg_sentence_length": avg_sentence,
            "short_sentence_ratio": short_ratio,
            "paragraph_count": len(paragraphs),
            "dialogue_mark_density": round(dialogue_marks / max(len(text), 1), 4),
            "rhythm_keywords": rhythm_words,
            "style_hint": (
                f"平均句长约{avg_sentence}字，短句占比{short_ratio*100:.0f}%，"
                f"偏好关键词：{'、'.join(rhythm_words[:8]) or '无明显偏好'}。"
            ),
        }
        self.style_fingerprint = fingerprint
        self.save_project_state()
        return fingerprint

    def _style_fingerprint_instruction(self) -> str:
        fp = self.style_fingerprint or {}
        if not fp:
            return ""
        keywords = "、".join(fp.get("rhythm_keywords", [])[:8])
        return (
            "文风指纹约束："
            f"{fp.get('style_hint','')}"
            + (f" 写作时优先沿用这些常见节奏/意象词：{keywords}。" if keywords else "")
            + " 不要刻意模仿模板网文腔，要保持这一指纹的句长节奏和段落呼吸。"
        )

    def _format_chapter_intent(self, intent: dict) -> str:
        payoff = "；".join(intent.get("must_payoff") or []) or "本章至少推进一条既有悬念或关系线。"
        track = "；".join(intent.get("must_track") or [])
        avoid = "；".join(intent.get("must_avoid") or [])
        text = (
            f"本章意图：{intent.get('must_advance','')}\n"
            f"本章冲突：{intent.get('must_confront','')}\n"
            f"必须回应：{payoff}\n"
            f"必须避免：{avoid}"
        ).strip()
        if track:
            text += f"\n连续性债务：{track}"
        return text

    def _register_open_intents(self, chapter_idx: int, intent: dict):
        self._normalize_open_intents_ledger()
        total = max(1, int(self.target_chapters or (len(self.volume.chapters) if self.volume else 0) or 1))
        default_deadline = min(total, max(chapter_idx + 2, int(total * 0.85)))
        existing = self.open_intents_ledger.get("unresolved_payoffs", []) or []
        existing_map = {re.sub(r"\s+", "", str(item.get("description", ""))): item for item in existing if isinstance(item, dict)}
        for desc in intent.get("must_payoff", []) or []:
            cleaned = self._sanitize_chapter_outline_text(str(desc or "").strip(), chapter_idx=chapter_idx)
            if not cleaned:
                continue
            key = re.sub(r"\s+", "", cleaned)
            current = existing_map.get(key)
            if current:
                current["last_seen_chapter"] = chapter_idx + 1
                current["status"] = "closing" if current.get("deadline_hint", 0) and chapter_idx + 1 >= current.get("deadline_hint", 0) - 1 else current.get("status", "active")
                continue
            existing.append({
                "description": cleaned,
                "origin_chapter": chapter_idx + 1,
                "deadline_hint": default_deadline,
                "keywords": self._extract_keywords(cleaned)[:6],
                "status": "active",
                "last_seen_chapter": chapter_idx + 1,
            })
        self.open_intents_ledger["unresolved_payoffs"] = existing

    def _resolve_open_intents(self, chapter_idx: int, content: str):
        self._normalize_open_intents_ledger()
        text = str(content or "")
        if not text:
            return
        keywords = set(self._extract_keywords(text))
        resolved = []
        remaining = []
        for item in self.open_intents_ledger.get("unresolved_payoffs", []) or []:
            item_keywords = set(item.get("keywords", []) or self._extract_keywords(item.get("description", ""))[:6])
            desc = str(item.get("description", "") or "")
            direct_hit = desc and desc[: min(12, len(desc))] in text
            overlap = len(keywords.intersection(item_keywords))
            if direct_hit or overlap >= 2:
                resolved.append(desc)
                continue
            deadline_hint = int(item.get("deadline_hint", 0) or 0)
            if deadline_hint and chapter_idx + 1 >= deadline_hint - 1:
                item["status"] = "closing"
            remaining.append(item)
        if resolved:
            logger.info("Resolved open intent payoffs in chapter %s: %s", chapter_idx + 1, " | ".join(resolved[:4]))
        self.open_intents_ledger["unresolved_payoffs"] = remaining

    def _detect_show_dont_tell_issues(self, chapter_text: str) -> list[str]:
        text = str(chapter_text or "")
        if not text:
            return []
        patterns = [
            r"他感到[^，。！？]{1,12}",
            r"她感到[^，。！？]{1,12}",
            r"他觉得[^，。！？]{1,12}",
            r"她觉得[^，。！？]{1,12}",
            r"他意识到[^，。！？]{1,12}",
            r"她意识到[^，。！？]{1,12}",
            r"他很(?:愤怒|难过|伤心|紧张|害怕|高兴|失望|震惊)",
            r"她很(?:愤怒|难过|伤心|紧张|害怕|高兴|失望|震惊)",
        ]
        hits = []
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                snippet = match.group(0)[:30]
                if snippet not in hits:
                    hits.append(snippet)
                if len(hits) >= 3:
                    return hits
        return hits

    def _run_chapter_audit(self, chapter_idx: int, chapter_outline: ChapterOutline, chapter_text: str, context_tags: list[str], enhancement_post: dict | None = None) -> dict:
        if enhancement_post is None:
            enhancement_post = self.enhancement.post_generation(
                chapter_text=chapter_text,
                chapter_index=chapter_idx + 1,
                total_chapters=self.target_chapters,
                context_tags=context_tags,
            )
        recent_texts, recent_titles = self._recent_chapter_texts(chapter_idx, limit=3)
        is_final = chapter_idx >= max(0, self.target_chapters - 1)
        ai_report = self.ai_detector.get_report(
            chapter_text,
            chapter_title=chapter_outline.title,
            recent_texts=recent_texts,
            recent_titles=recent_titles,
            is_final=is_final,
        )
        severe_structure_flags = [
            flag for flag in (ai_report.get("structure_flags") or [])
            if any(marker in flag for marker in ["终章", "标题重复", "开场动作", "新增强钩子", "开新坑"])
        ]
        rule_result = self.consistency_gate.checker.rule_engine.validate_all(
            chapter_text, chapter_idx, self.characters
        )
        consistency_score = self._score_rule_consistency(rule_result)
        tail_audit = self._audit_tail_quality(chapter_idx, chapter_outline.title, chapter_text)
        show_tell_hits = self._detect_show_dont_tell_issues(chapter_text)
        issues = []
        severity = 0
        retry_reason = str(enhancement_post.get("retry_reason", "") or "").strip()
        if enhancement_post.get("should_retry") and retry_reason:
            issues.append(f"增强审计：{retry_reason}")
            severity += 3
        for flag in severe_structure_flags[:3]:
            issues.append(f"结构风险：{flag}")
            severity += 2
        if ai_report.get("ai_score", 1.0) < 0.8:
            issues.append(f"AI痕迹偏高：{ai_report.get('ai_score', 1.0):.2f}")
            severity += 2
        elif ai_report.get("patterns_found", 0) >= 3:
            issues.append(f"模板化模式偏多：{ai_report.get('patterns_found', 0)}处")
            severity += 1
        if not rule_result.get("is_valid", True):
            issues.extend([f"一致性：{issue}" for issue in (rule_result.get("issues", []) or [])[:3]])
            severity += 2
        if show_tell_hits:
            issues.extend([f"展示不足：{item}" for item in show_tell_hits[:2]])
            severity += 1
        if not tail_audit["ok"]:
            issues.extend([f"尾部质量：{flag}" for flag in tail_audit["flags"][:3]])
            severity += 2
            consistency_score = min(consistency_score, 0.72)
        self._normalize_consistency_gate_stats()
        self.consistency_gate_stats["show_dont_tell_flags"] = int(self.consistency_gate_stats.get("show_dont_tell_flags", 0) or 0) + len(show_tell_hits)
        self.consistency_gate_stats["last_issues"] = (self.consistency_gate_stats.get("last_issues", []) or []) + self._dedupe_text_list(issues, limit=6)
        should_rewrite = (not settings.FAST_TEST_MODE) and severity >= 3
        return {
            "enhancement_post": enhancement_post,
            "ai_report": ai_report,
            "rule_result": rule_result,
            "tail_audit": tail_audit,
            "show_tell_hits": show_tell_hits,
            "issues": self._dedupe_text_list(issues, limit=8),
            "severity": severity,
            "should_rewrite": should_rewrite,
            "consistency_score": consistency_score,
        }

    def _observe_chapter_facts(self, chapter_idx: int, chapter_title: str, chapter_text: str) -> dict:
        lines = [p.strip() for p in re.split(r"[。！？\n]+", chapter_text or "") if p.strip()]
        named_chars = [char.name for char in self.characters if char.name and char.name in chapter_text]
        location_keywords = [
            "客厅", "卧室", "书房", "厨房", "餐厅", "阳台", "走廊", "门口",
            "书桌", "茶几", "沙发", "床", "窗边",
            "档案馆", "实验室", "医院", "地下车库", "车库", "天台", "楼顶",
            "学校", "办公室", "会议室", "大厅", "大厅", "广场", "街道", "公园",
            "咖啡馆", "酒吧", "酒店", "车站", "机场", "码头",
            "森林", "山洞", "山谷", "河边", "湖边", "海边",
        ]
        locations = [kw for kw in location_keywords if kw in chapter_text]
        resource_keywords = [
            "书签", "戒指", "录音机", "档案", "监控", "白色SUV", "实验名单",
            "钥匙", "手机", "电脑", "信件", "照片", "日记", "地图",
            "药", "武器", "剑", "刀", "令牌", "玉佩", "符咒",
            "钱", "银行卡", "证件", "合同", "文件",
        ]
        resources = [kw for kw in resource_keywords if kw in chapter_text]
        hook_markers = [
            "原来", "真相", "同步率", "置换", "如果", "门外", "还没结束", "下一秒",
            "突然", "忽然", "没想到", "竟然", "居然", "意外", "发现", "意识到",
            "转身", "回头", "门外", "身后", "黑暗中", "电话响", "门铃",
            "决定", "选择", "答应", "拒绝", "离开", "回来",
        ]
        hooks = [line[:80] for line in lines if any(marker in line for marker in hook_markers)]
        # 摘要：取开头150字 + 结尾350字，覆盖起始场景和结尾状态
        opening = self._compact_text(chapter_text, 150)
        ending = self._compact_text(chapter_text[-800:], 350) if len(chapter_text) > 400 else ""
        summary = f"{opening}"
        if ending:
            summary += f"……{ending}"
        return {
            "chapter_index": chapter_idx,
            "title": chapter_title,
            "characters_on_stage": named_chars[:6],
            "locations": locations[:6],
            "resources_touched": resources[:6],
            "hook_movements": hooks[:6],
            "state_summary": summary[:500],
        }

    def _remove_output_artifacts(self, start_index: int, end_index: int | None = None):
        output_dir = Path(self.get_output_dir())
        if not output_dir.exists():
            return
        upper = (len(self.volume.chapters) if self.volume else self.target_chapters) if end_index is None else end_index
        for idx in range(max(0, start_index), max(0, upper)):
            for suffix in [".json", ".txt"]:
                path = output_dir / f"chapter_{idx + 1:03d}{suffix}"
                if path.exists():
                    path.unlink()

    def _prune_structured_memory_range(self, start_index: int):
        chapter_no = start_index + 1
        structured = self.memory.structured
        structured.timeline = [
            item for item in structured.timeline
            if int(item.get("chapter", item.get("chapter_index", 0)) or 0) < chapter_no
        ]
        structured.chapter_summaries = [
            item for item in structured.chapter_summaries
            if int(item.get("chapter", -1) or -1) < start_index
        ]
        def _clean_history_list(items: list[str]) -> list[str]:
            cleaned = []
            for item in items:
                text = str(item or "")
                match = re.search(r"第(\d+)章", text)
                if match and int(match.group(1)) >= chapter_no:
                    continue
                cleaned.append(item)
            return cleaned
        if self.world:
            self.world.history = _clean_history_list(list(self.world.history or []))
            structured.world = self.world
        for char in self.characters:
            char.memory = _clean_history_list(list(char.memory or []))
            structured.characters[char.name] = char
        structured.save()

    def _clear_long_term_memory(self):
        try:
            self.memory.long_term.clear()
        except Exception as e:
            logger.warning(f"Long-term memory clear failed: {e}")

    def _clear_all_generated_story_state(self):
        self.generated_chapters = []
        self.finalized_chapters = []
        self.pending_chapter_updates = {}
        self.memory.clear_story_state()
        self._clear_long_term_memory()
        self._reset_story_evolution_state()
        self._rebuild_suspense_arcs_from_story(force=True)
        self.global_summary = ""
        self._previous_chapter_tail = ""
        self._project_word_freq = {}
        # 重置增强系统内部状态
        from agents.enhancement.models import CooldownState
        self.enhancement.brake.unresolved_issues = []
        self.enhancement.brake.consecutive_zero_count = 0
        self.enhancement.thread_pool.threads = []
        self.enhancement.event_matrix.cooldown_state = CooldownState()

    async def _reindex_finalized_chapters(self, include_embeddings: bool = False):
        self._clear_long_term_memory()
        finalized = sorted(
            [draft for draft in self.generated_chapters if draft.chapter_index in set(self.finalized_chapters)],
            key=lambda draft: draft.chapter_index,
        )
        for draft in finalized:
            summary = self._compact_text(draft.content, 280)
            if include_embeddings:
                try:
                    await self.rag.index_chapter(draft.title, draft.content, summary)
                    continue
                except Exception as e:
                    logger.warning(f"RAG reindex failed for chapter {draft.chapter_index + 1}: {e}")
            self.memory.long_term.metadata.append({
                "type": "chapter",
                "title": draft.title,
                "text": f"【{draft.title}】{summary}",
            })
        self.memory.long_term._save()

    def _delete_chapter_range_from_db(self, start_index: int, end_index: int | None = None):
        if not self.session_id:
            return
        upper = (len(self.volume.chapters) if self.volume else self.target_chapters) if end_index is None else end_index
        try:
            from core.database import SessionLocal
            with SessionLocal() as db:
                chapters = db.query(Chapter).filter(
                    Chapter.project_id == self.session_id,
                    Chapter.chapter_index >= start_index,
                    Chapter.chapter_index < upper,
                ).all()
                chapter_ids = [ch.id for ch in chapters]
                if chapter_ids:
                    db.query(ChapterVersion).filter(ChapterVersion.chapter_id.in_(chapter_ids)).delete(synchronize_session=False)
                db.query(TimelineEvent).filter(
                    TimelineEvent.project_id == self.session_id,
                    TimelineEvent.chapter_index >= start_index,
                    TimelineEvent.chapter_index < upper,
                ).delete(synchronize_session=False)
                if start_index <= 0:
                    db.query(Foreshadowing).filter(
                        Foreshadowing.project_id == self.session_id,
                    ).delete(synchronize_session=False)
                    db.query(PlotArcRecord).filter(
                        PlotArcRecord.project_id == self.session_id,
                    ).delete(synchronize_session=False)
                for ch in chapters:
                    ch.status = "draft"
                    ch.current_version = 1
                    ch.guidance = ""
                db.commit()
        except Exception as e:
            logger.warning(f"DB cleanup failed for chapter range {start_index + 1}-{upper}: {e}")

    async def reset_chapter_range(self, start_index: int, end_index: int | None = None, *, clean_memory: bool = True) -> dict:
        if not self.volume:
            raise ValueError("Pipeline not initialized")
        upper = len(self.volume.chapters) if end_index is None else min(len(self.volume.chapters), end_index)
        if start_index < 0 or start_index >= upper:
            raise ValueError("Invalid chapter range")
        self.generated_chapters = [c for c in self.generated_chapters if not (start_index <= c.chapter_index < upper)]
        self.finalized_chapters = [idx for idx in self.finalized_chapters if not (start_index <= idx < upper)]
        self.pending_chapter_updates = {
            idx: value for idx, value in self.pending_chapter_updates.items()
            if not (start_index <= idx < upper)
        }
        self._delete_chapter_range_from_db(start_index, upper)
        self._remove_output_artifacts(start_index, upper)
        if clean_memory:
            self._prune_structured_memory_range(start_index)
            await self._reindex_finalized_chapters(include_embeddings=False)
        try:
            self._rebuild_story_evolution_from_finalized()
        except Exception as e:
            logger.warning(f"Story evolution rebuild failed during reset: {e}")
            self._reset_story_evolution_state()
        self._rebuild_suspense_arcs_from_story(force=True)
        self.save_project_state()
        return {
            "status": "reset",
            "start_chapter_no": start_index + 1,
            "end_chapter_no": upper,
            "remaining_finalized": len(self.finalized_chapters),
        }

    def _ending_closure_instruction(self, chapter_idx: int) -> str:
        total = max(1, int(self.target_chapters or (len(self.volume.chapters) if self.volume else 0) or 1))
        chapter_no = chapter_idx + 1
        chapters_left = total - chapter_no
        if chapters_left > 4:
            return ""
        if chapters_left == 4:
            return (
                "终局约束：故事已进入最后五章。禁止再引入新的主谜题或新的核心反派，"
                "本章必须开始实质回收既有伏笔，并明确终局战场、核心证据或最终关系裂口。"
            )
        if chapters_left == 3:
            return (
                "终局约束：故事已进入最后四章。必须推进至少一条核心伏笔的兑现，"
                "不能再用相似的痛感/闪回/感官模板反复开场，必须让局势发生不可逆变化。"
            )
        if chapters_left == 2:
            return (
                "终局约束：故事已进入最后三章。必须让主冲突见底，给出关键真相或决定性证据，"
                "禁止继续虚晃、禁止重复前章开场感官模板。"
            )
        if chapters_left == 1:
            return (
                "终局约束：这是倒数第二章。必须完成最终对决前的最后摊牌，"
                "把人物选择、代价与结局方向说透，不得再开启新主线。"
            )
        return (
            "终章约束：这是最终章。必须显式完成主冲突收束、关键伏笔回收、核心人物归宿交代与主题落点。"
            "结尾不允许再开启新的主谜题、下一部预告、番外钩子或“真正故事才开始”式收尾。"
            "最后必须补出2到3段明确善后：苏漾做出的最终选择、陆彦舟或温静宜留下的结果、循环日项目的处置去向。"
        )

    def _audit_tail_quality(self, chapter_idx: int, chapter_title: str, chapter_text: str) -> dict:
        recent_texts, recent_titles = self._recent_chapter_texts(chapter_idx, limit=3)
        total = max(1, int(self.target_chapters or (len(self.volume.chapters) if self.volume else 0) or 1))
        is_final = chapter_idx >= total - 1
        ai_report = self.ai_detector.get_report(
            chapter_text,
            chapter_title=chapter_title,
            recent_texts=recent_texts,
            recent_titles=recent_titles,
            is_final=is_final,
        )
        flags = list(ai_report.get("structure_flags") or [])
        if len(set(recent_titles + [chapter_title])) < len(recent_titles + [chapter_title]):
            flags.append("尾部章节标题重复，需要重规划")
        terminal_text = " ".join([line.strip() for line in chapter_text.splitlines() if line.strip()][-4:])
        if is_final and any(token in terminal_text for token in ["下一部", "番外", "更大的真相", "真正的故事才刚开始"]):
            flags.append("终章结尾仍在预告后续，而不是完成结局")
        return {
            "ok": not flags,
            "flags": self._dedupe_text_list(flags),
            "ai_report": ai_report,
        }

    def _repair_tail_plan(self, start_idx: int):
        if not self.volume:
            return
        total = min(len(self.volume.chapters), max(1, self.target_chapters))
        if start_idx >= total:
            return
        templates = [
            ("逼近真相", "锁定真相入口，迫使主要人物直面隐藏事实。", "线索即将闭环，但关键证词或证据仍可能被毁掉。"),
            ("证据成链", "让前文零散证据完成拼接，明确真正责任方。", "证据链一旦断裂，所有牺牲都将白费。"),
            ("代价摊牌", "把主角和核心关系推入必须付出代价的抉择。", "想得到答案，就必须承认并承担最不愿面对的那部分真相。"),
            ("终局对决", "完成主冲突正面对撞，逼出最终选择。", "任何迟疑都会让对手夺回主动权，旧伤和旧谎都将反噬。"),
            ("余震善后", "交代真相公开后的后果、人物归宿与新秩序。", "结局不是继续开新坑，而是让代价、关系与未来方向落地。"),
        ]
        tail_count = min(5, total - start_idx)
        selected = templates[-tail_count:]
        for offset, idx in enumerate(range(start_idx, total)):
            chapter = self.volume.chapters[idx]
            title_suffix, goal_seed, conflict_seed = selected[offset]
            chapter.title = f"第{idx + 1}章 {title_suffix}"
            chapter.goal = self._sanitize_chapter_outline_text(
                f"{goal_seed} 本章要承接既有正式剧情，优先回收已存在伏笔和悬念，避免重复模板化终局描写。",
                chapter_idx=idx,
            )
            chapter.conflict = self._sanitize_chapter_outline_text(conflict_seed, chapter_idx=idx)
            if chapter.scenes:
                for scene in chapter.scenes:
                    scene.description = self._sanitize_chapter_outline_text(scene.description, chapter_idx=idx)

    def _score_rule_consistency(self, rule_result: dict) -> float:
        issues = rule_result.get("issues", []) or []
        if not issues:
            return 0.96
        penalty = 0.0
        for issue in issues:
            text = str(issue or "")
            if any(marker in text for marker in ["硬阻断", "死亡", "复活", "章节错位", "设定冲突"]):
                penalty += 0.18
            elif any(marker in text for marker in ["状态", "地点", "称呼", "时间线"]):
                penalty += 0.10
            else:
                penalty += 0.06
        score = max(0.35, 0.96 - penalty)
        if not rule_result.get("is_valid", True):
            score = min(score, 0.75)
        return round(score, 3)

    def _strip_evolution_wrappers(self, text: str, prefixes: list[str]) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""
        cleaned = re.sub(r"^（第\d+章《[^》]+》(?:；第\d+章《[^》]+》)*）[，,、 ]*", "", cleaned)
        cleaned = re.sub(r"^承接已定稿进展（[^）]+）[，,、 ]*", "", cleaned)
        cleaned = re.sub(r"^在不推翻初始方向的前提下推进[：: ]*", "", cleaned)
        cleaned = re.sub(r"^延续已发生变化带来的新压力[：: ]*", "", cleaned)
        changed = True
        while changed:
            changed = False
            for prefix in prefixes:
                if cleaned.startswith(prefix):
                    cleaned = cleaned[len(prefix):].strip("：:；，, ")
                    changed = True
        for marker in ["；遵循阶段演进：", "；同时优先照看未回收伏笔："]:
            if marker in cleaned:
                cleaned = cleaned.split(marker, 1)[0].rstrip("；，, ")
        return cleaned.strip()

    def _sync_thread_pool(self):
        """从 DB foreshadowing + open_intents_ledger 同步活跃线程到线程池。"""
        tp = self.enhancement.thread_pool
        # 从 DB foreshadowing 同步
        if self.session_id:
            try:
                from core.database import SessionLocal
                from models.db_service import ForeshadowingService
                with SessionLocal() as db:
                    unresolved = ForeshadowingService(db).get_unresolved(self.session_id)
                    if unresolved:
                        tp.sync_from_db(unresolved)
            except Exception as e:
                logger.debug(f"Thread pool DB sync skipped: {e}")
        # 从 open_intents_ledger 同步
        self._normalize_open_intents_ledger()
        tp.sync_from_ledger(self.open_intents_ledger)

    def _thread_aware_replan(self, finalized_chapter_idx: int):
        """定稿后线程感知重规划：将线程截止日期映射到未来章节 goal/conflict。"""
        if not self.volume:
            return
        tp = self.enhancement.thread_pool
        active = tp.get_active()
        if not active:
            return
        # 获取未来未生成的章节
        future_start = finalized_chapter_idx + 1
        future_chapters = self.volume.chapters[future_start:]
        if not future_chapters:
            return
        # 将线程截止日期映射到未来章节
        for thread in active:
            if thread.must_resolve_by <= 0:
                continue
            target_idx = thread.must_resolve_by - 1  # 0-based
            if target_idx < future_start or target_idx >= len(self.volume.chapters):
                continue
            chapter = self.volume.chapters[target_idx]
            # 检查是否已有该线程的回收任务
            goal_text = chapter.goal or ""
            conflict_text = chapter.conflict or ""
            if thread.description[:10] in goal_text or thread.description[:10] in conflict_text:
                continue  # 已包含，跳过
            # 注入线程回收任务到 goal
            tag = f"（回收线索：{thread.description[:30]}）"
            if len(chapter.goal or "") < 200:
                chapter.goal = (chapter.goal or "") + tag
                logger.info(f"Thread-aware replan: injected {thread.thread_id} into ch{target_idx+1} goal")

    def _backfill_foreshadowing_if_empty(self):
        if not self.session_id or not self.volume or not self.finalized_chapters:
            return
        try:
            from core.database import SessionLocal
            from models.db_service import ForeshadowingService

            with SessionLocal() as db:
                fs = ForeshadowingService(db)
                existing = fs.get_project_foreshadowing(self.session_id)
                if existing:
                    return
                planted = 0
                for chapter_idx in sorted(self.finalized_chapters):
                    if chapter_idx < 0 or chapter_idx >= len(self.volume.chapters):
                        continue
                    chapter_outline = self.volume.chapters[chapter_idx]
                    chapter_text = ""
                    for draft in self.generated_chapters:
                        if draft.chapter_index == chapter_idx and draft.content:
                            chapter_text = draft.content
                            break
                    for item in self._derive_new_foreshadow_candidates(chapter_idx, chapter_outline, chapter_text=chapter_text)[:2]:
                        if item:
                            self._persist_foreshadow_payload(fs, item, chapter_idx)
                            planted += 1
                if planted:
                    logger.info("Backfilled %s foreshadowing records for project %s", planted, self.session_id)
        except Exception as e:
            logger.warning(f"Foreshadowing backfill failed: {e}")

    def repair_project_integrity(self) -> dict:
        if not self.volume:
            raise ValueError("Project not loaded")
        self._canonicalize_chapter_character_names()
        self._ensure_chapter_scenes_integrity()
        self._refresh_enhancement_baseline(force=True)

        repaired = {
            "characters_rebuilt": False,
            "foreshadowing_deduped": 0,
            "foreshadowing_rebuilt": 0,
            "suspense_arcs_trimmed": 0,
            "chapter_plans_sanitized": 0,
            "timeline_sanitized": 0,
            "plot_arcs_sanitized": 0,
        }

        generic_names = {"主角", "盟友", "宿敌", "反派", "配角"}
        if any((char.name or "").strip() in generic_names for char in self.characters):
            try:
                import asyncio
                world_summary = self.memory.structured.get_world_text()
                new_chars = asyncio.run(self.character_engine.create_characters(self.outline, world_summary, self.genre))
                if new_chars:
                    self.characters = new_chars
                    self.memory = MemorySystem(session_id=self.session_id)
                    if self.world:
                        self.memory.update_world(self.world)
                    self.state_manager = CharacterStateManager()
                    for char in self.characters:
                        self.memory.update_character(char)
                        self.state_manager.register_character(char.name, initial_power=1)
                    self.memory.sync_relationships_from_characters(chapter=0)
                    repaired["characters_rebuilt"] = True
            except Exception as e:
                logger.warning(f"Character repair failed: {e}")

        if self.session_id:
            try:
                from core.database import SessionLocal
                from models.db_service import ForeshadowingService

                with SessionLocal() as db:
                    fs = ForeshadowingService(db)
                    items = fs.get_project_foreshadowing(self.session_id)
                    seen = set()
                    deleted = 0
                    for item in items:
                        key = (item.description, item.planted_chapter, item.status)
                        if key in seen:
                            db.delete(item)
                            deleted += 1
                        else:
                            seen.add(key)
                    if deleted:
                        db.commit()
                    repaired["foreshadowing_deduped"] = deleted
            except Exception as e:
                logger.warning(f"Foreshadow dedupe failed: {e}")

        before_arc_count = len(self.enhancement.suspense_arcs.arcs)
        self.enhancement.suspense_arcs.normalize_arcs()
        repaired["suspense_arcs_trimmed"] = max(0, before_arc_count - len(self.enhancement.suspense_arcs.arcs))

        for idx, chapter in enumerate(self.volume.chapters):
            old_goal = chapter.goal
            old_conflict = chapter.conflict
            chapter.goal = self._clean_plot_progress_text(
                chapter.goal,
            ) or old_goal
            chapter.conflict = self._clean_plot_progress_text(chapter.conflict) or old_conflict
            if chapter.goal != old_goal or chapter.conflict != old_conflict:
                repaired["chapter_plans_sanitized"] += 1

        sanitized_timeline = []
        for event in self.memory.structured.timeline or []:
            normalized = dict(event)
            original_progress = str(normalized.get("plot_progress", "") or "")
            cleaned_progress = self._clean_plot_progress_text(original_progress)
            if cleaned_progress and cleaned_progress != original_progress:
                normalized["plot_progress"] = cleaned_progress
                repaired["timeline_sanitized"] += 1
            sanitized_timeline.append(normalized)
        self.memory.structured.timeline = sanitized_timeline

        sanitized_plot_arcs = []
        for arc in self.memory.structured.plot_arcs or []:
            normalized = dict(arc)
            original_desc = str(normalized.get("description", "") or "")
            cleaned_desc = self._clean_plot_progress_text(original_desc)
            if cleaned_desc and cleaned_desc != original_desc:
                normalized["description"] = cleaned_desc
                repaired["plot_arcs_sanitized"] += 1
            sanitized_plot_arcs.append(normalized)
        self.memory.structured.plot_arcs = sanitized_plot_arcs
        self.memory.structured.save()

        if self.session_id:
            try:
                from core.database import SessionLocal
                from models.db_service import ForeshadowingService

                with SessionLocal() as db:
                    fs = ForeshadowingService(db)
                    for item in fs.get_project_foreshadowing(self.session_id):
                        db.delete(item)
                    db.commit()
                    rebuilt = 0
                    for chapter_idx in sorted(set(self.finalized_chapters)):
                        if 0 <= chapter_idx < len(self.volume.chapters):
                            chapter_outline = self.volume.chapters[chapter_idx]
                            chapter_text = ""
                            for draft in self.generated_chapters:
                                if draft.chapter_index == chapter_idx and draft.content:
                                    chapter_text = draft.content
                                    break
                            for item in self._derive_new_foreshadow_candidates(chapter_idx, chapter_outline, chapter_text=chapter_text)[:2]:
                                if item:
                                    self._persist_foreshadow_payload(fs, item, chapter_idx)
                                    rebuilt += 1
                    repaired["foreshadowing_rebuilt"] = rebuilt
            except Exception as e:
                logger.warning(f"Foreshadow rebuild failed: {e}")

        self._rebuild_suspense_arcs_from_story(force=True)
        self._sync_project_to_db()
        self.save_project_state()
        return repaired

    def _refresh_enhancement_baseline(self, force: bool = False):
        self._ensure_chapter_scenes_integrity()
        if self.volume:
            self.enhancement.suspense_arcs.set_story_horizon(max(1, int(self.target_chapters or len(self.volume.chapters) or 1)))
        if self.world or self.characters:
            state = self.enhancement.info_gap.get_info_gap_state()
            if force or (not state.reader_knows and not state.character_knows and not state.reader_wants_to_know):
                self.enhancement.info_gap.initialize_from_setting(
                    self.world.model_dump() if self.world else {},
                    [c.model_dump() for c in self.characters],
                )
        # 从已定稿章节中补充信息差条目
        if self.finalized_chapters and self.generated_chapters:
            self._enrich_info_gap_from_finalized()
        if self.volume and (force or not self.enhancement.progress.anchors):
            self.enhancement.progress.set_anchors(self._build_progress_anchors())
        for idx in self.finalized_chapters:
            self.enhancement.progress.update_anchor_completion(idx, completed=True)
        self._backfill_foreshadowing_if_empty()
        self._rebuild_suspense_arcs_from_story(force=force)
        # 同步线程池：从 DB foreshadowing + open_intents_ledger 同步活跃线程
        self._sync_thread_pool()

    def _enrich_info_gap_from_finalized(self):
        """从已定稿章节的内容中补充信息差条目，让面板展示更丰富。"""
        from core.word_counter import count_chinese_words
        ig = self.enhancement.info_gap
        existing_knows = set(ig.state.reader_knows)
        existing_wants = set(ig.state.reader_wants_to_know)
        new_knows = []
        new_wants = []
        for draft in self.generated_chapters:
            if draft.chapter_index not in self.finalized_chapters:
                continue
            content = draft.content or ""
            if len(content) < 50:
                continue
            # 从章节内容中提取关键信息
            summary = self._compact_text(content, 80)
            knows_entry = f"第{draft.chapter_index + 1}章《{draft.title}》: {summary}"
            if knows_entry not in existing_knows and len(new_knows) < 4:
                new_knows.append(knows_entry)
            # 检测悬念/秘密关键词
            suspense_kws = ["秘密", "真相", "阴谋", "隐藏", "未知", "谜团", "可疑", "背叛"]
            for kw in suspense_kws:
                if kw in content:
                    want_entry = f"第{draft.chapter_index + 1}章中关于「{kw}」的线索"
                    if want_entry not in existing_wants and len(new_wants) < 3:
                        new_wants.append(want_entry)
                        existing_wants.add(want_entry)
                    break
        ig.state.reader_knows.extend(new_knows)
        ig.state.reader_wants_to_know.extend(new_wants)
        # 限制总条目数
        ig.state.reader_knows = ig.state.reader_knows[-15:]
        ig.state.reader_wants_to_know = ig.state.reader_wants_to_know[-10:]

    def _word_target_bounds(self, target_words: int) -> tuple[int, int]:
        lower = max(100, int(target_words * settings.WC_LOWER_TOLERANCE))
        upper = max(lower + 50, int(target_words * settings.WC_UPPER_TOLERANCE))
        return lower, upper

    def get_session_dir(self) -> str:
        if self.session_id:
            return os.path.join("data", "sessions", self.session_id)
        return "data"

    def get_output_dir(self) -> str:
        if self.session_id:
            return os.path.join("output", "sessions", self.session_id)
        return "output"

    def get_state_path(self) -> str:
        return os.path.join(self.get_session_dir(), "project_state.json")

    def save_project_state(self):
        os.makedirs(self.get_session_dir(), exist_ok=True)
        data = {
            "session_id": self.session_id,
            "outline": self.outline,
            "title": self.title,
            "genre": self.genre,
            "style": self.style,
            "target_chapters": self.target_chapters,
            "planned_chapters": len(self.volume.chapters) if self.volume else 0,
            "planning_window": self.planning_window,
            "words_per_chapter": self.words_per_chapter,
            "world": self.world.model_dump() if self.world else {},
            "characters": [c.model_dump() for c in self.characters],
            "volume": self.volume.model_dump() if self.volume else None,
            "generated_chapters": [c.model_dump() for c in self.generated_chapters],
            "approved": self.approved,
            "finalized_chapters": self.finalized_chapters,
            "pending_chapter_updates": self.pending_chapter_updates,
            "evolution_state": self.evolution_state,
            "open_intents_ledger": self.open_intents_ledger,
            "consistency_gate_stats": self.consistency_gate_stats,
            "planning_window": self.planning_window,
            "character_state_manager": self.state_manager.to_dict(),
            "consistency_gate": {
                "dead_characters": list(self.consistency_gate.dead_characters),
                "character_power": self.consistency_gate.character_power,
                "character_locations": self.consistency_gate.character_locations,
            },
            "output_dir": self.get_output_dir(),
            "enhancement_state": self.enhancement.get_state(),
            "global_summary": self.global_summary,
            "_previous_chapter_tail": self._previous_chapter_tail,
            "hierarchical_summary": {
                "chapters_per_arc": self.hierarchical_summary.chapters_per_arc,
                "recent_chapters": self.hierarchical_summary.recent_chapters,
            },
            "tail_repair_locked": self.tail_repair_locked,
            "style_fingerprint": self.style_fingerprint,
        }
        with open(self.get_state_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def ensure_project_in_database(self):
        if not self.outline or not self.world or not self.volume:
            raise ValueError("Cannot persist incomplete project to database")
        from core.database import SessionLocal
        from models.db_service import ProjectService, CharacterService, WorldService, ChapterService, SceneService

        with SessionLocal() as db:
            ps = ProjectService(db)
            existing = ps.get_project(self.session_id) if self.session_id else None
            if existing:
                return existing.id

            project = ps.create_project(
                title=self.title,
                outline=self.outline,
                genre=self.genre,
                style=self.style,
                target_chapters=self.target_chapters,
                words_per_chapter=self.words_per_chapter,
            )

            old_id = self.session_id
            self.session_id = project.id

            ws = WorldService(db)
            ws.create_world(project.id, self.world)

            cs = CharacterService(db)
            for char in self.characters:
                cs.create_character(project.id, char)

            chs = ChapterService(db)
            ss = SceneService(db)
            for idx, ch_outline in enumerate(self.volume.chapters):
                chapter = chs.create_chapter(project.id, idx, ch_outline.title, ch_outline.goal, ch_outline.conflict)
                for s_idx, scene in enumerate(ch_outline.scenes):
                    ss.create_scene(chapter.id, s_idx, scene.description, scene.characters, scene.location, scene.mood, scene.target_words)

            if old_id and old_id != self.session_id:
                import shutil
                old_dir = os.path.join("data", "sessions", old_id)
                new_dir = os.path.join("data", "sessions", self.session_id)
                if os.path.exists(old_dir):
                    shutil.move(old_dir, new_dir)
                # 同时迁移分层摘要缓存
                old_cache = Path("cache/coherence") / f"{old_id}_arc_summaries.json"
                new_cache = Path("cache/coherence") / f"{self.session_id}_arc_summaries.json"
                if old_cache.exists() and not new_cache.exists():
                    shutil.move(str(old_cache), str(new_cache))
                self.hierarchical_summary = HierarchicalSummaryManager(
                    project_id=self.session_id,
                    chapters_per_arc=10,
                    recent_chapters=5,
                )
                self.memory = MemorySystem(session_id=self.session_id)
                self.rag = RAGEngine(self.memory.long_term)
                self.memory.update_world(self.world)
                for char in self.characters:
                    self.memory.update_character(char)

            return project.id

    def _require_database_project(self):
        if not self.session_id:
            raise ValueError("Project session_id is missing")
        from core.database import SessionLocal
        from models.db_service import ProjectService
        with SessionLocal() as db:
            project = ProjectService(db).get_project(self.session_id)
            if not project:
                raise ValueError(f"Database project not found: {self.session_id}")
            return project

    def _sync_project_to_db(self):
        if not self.session_id or not self.volume or not self.world:
            return
        try:
            from core.database import SessionLocal
            from models.db_service import ProjectService, CharacterService, WorldService, ChapterService, SceneService

            with SessionLocal() as db:
                ps = ProjectService(db)
                cs = CharacterService(db)
                ws = WorldService(db)
                chs = ChapterService(db)
                ss = SceneService(db)

                project = ps.get_project(self.session_id)
                if not project:
                    return

                ps.update_project(
                    self.session_id,
                    title=self.title,
                    outline=self.outline,
                    genre=self.genre,
                    style=self.style,
                    target_chapters=self.target_chapters,
                    words_per_chapter=self.words_per_chapter,
                    approved=self.approved,
                )

                cs.delete_project_characters(self.session_id)
                for char in self.characters:
                    cs.create_character(self.session_id, char)

                ws.replace_world(self.session_id, self.world)

                # 增量更新 chapters：只更新有变化的，保留版本历史
                existing_chapters = chs.get_project_chapters(self.session_id)
                existing_by_index = {c.chapter_index: c for c in existing_chapters}

                for idx, ch_outline in enumerate(self.volume.chapters):
                    existing = existing_by_index.get(idx)
                    if existing:
                        # 只更新 outline 字段，不删除 scenes 和版本历史
                        needs_update = (
                            existing.title != ch_outline.title
                            or existing.goal != ch_outline.goal
                            or existing.conflict != ch_outline.conflict
                        )
                        if needs_update:
                            chs.update_chapter(
                                existing.id,
                                title=ch_outline.title,
                                goal=ch_outline.goal,
                                conflict=ch_outline.conflict,
                            )
                        # 同步 scenes（仅当 outline 有 scene 变化时）
                        ss.delete_chapter_scenes(existing.id)
                        for s_idx, scene in enumerate(ch_outline.scenes):
                            ss.create_scene(
                                existing.id,
                                s_idx,
                                scene.description,
                                scene.characters,
                                scene.location,
                                scene.mood,
                                scene.target_words,
                            )
                    else:
                        chapter = chs.create_chapter(
                            self.session_id,
                            idx,
                            ch_outline.title,
                            ch_outline.goal,
                            ch_outline.conflict,
                        )
                        for s_idx, scene in enumerate(ch_outline.scenes):
                            ss.create_scene(
                                chapter.id,
                                s_idx,
                                scene.description,
                                scene.characters,
                                scene.location,
                                scene.mood,
                                scene.target_words,
                            )

                # 删除 DB 中多余的不在 volume 中的 chapters
                for existing in existing_chapters:
                    if existing.chapter_index >= len(self.volume.chapters):
                        ss.delete_chapter_scenes(existing.id)
                        chs.delete_chapter(existing.id)
        except Exception as e:
            import traceback
            logger.warning(f"Project DB sync failed: {e}\n{traceback.format_exc()}")

    def _sync_characters_to_db(self):
        if not self.session_id:
            return
        try:
            from core.database import SessionLocal
            from models.db_service import CharacterService

            with SessionLocal() as db:
                cs = CharacterService(db)
                cs.delete_project_characters(self.session_id)
                for char in self.characters:
                    cs.create_character(self.session_id, char)
        except Exception as e:
            logger.warning(f"Character DB sync failed: {e}")

    def _sync_world_to_db(self):
        if not self.session_id or not self.world:
            return
        try:
            from core.database import SessionLocal
            from models.db_service import WorldService

            with SessionLocal() as db:
                ws = WorldService(db)
                if ws.get_world(self.session_id):
                    ws.update_world(self.session_id, self.world)
                else:
                    ws.create_world(self.session_id, self.world)
        except Exception as e:
            logger.warning(f"World DB sync failed: {e}")

    def _sync_future_chapter_outlines_to_db(self, start_index: int, include_generated_drafts: bool = False):
        if not self.session_id or not self.volume:
            return
        try:
            from core.database import SessionLocal
            from models.db_service import ChapterService, SceneService

            generated_indices = {c.chapter_index for c in self.generated_chapters}
            finalized_indices = set(self.finalized_chapters)
            with SessionLocal() as db:
                chs = ChapterService(db)
                ss = SceneService(db)
                for idx, ch_outline in enumerate(self.volume.chapters):
                    if idx < start_index or idx in finalized_indices:
                        continue
                    if idx in generated_indices and not include_generated_drafts:
                        continue
                    chapter = chs.get_chapter_by_index(self.session_id, idx)
                    if chapter:
                        chs.update_chapter(
                            chapter.id,
                            title=ch_outline.title,
                            goal=ch_outline.goal,
                            conflict=ch_outline.conflict,
                        )
                    else:
                        chapter = chs.create_chapter(
                            self.session_id,
                            idx,
                            ch_outline.title,
                            ch_outline.goal,
                            ch_outline.conflict,
                        )
                    ss.delete_chapter_scenes(chapter.id)
                    for s_idx, scene in enumerate(ch_outline.scenes):
                        ss.create_scene(
                            chapter.id,
                            s_idx,
                            scene.description,
                            scene.characters,
                            scene.location,
                            scene.mood,
                            scene.target_words,
                        )
        except Exception as e:
            logger.warning(f"Future chapter outline DB sync failed: {e}")

    def _force_sync_chapter_range_to_db(self, start_index: int, end_index: int | None = None):
        if not self.session_id or not self.volume:
            return
        try:
            from core.database import SessionLocal
            from models.db_service import ChapterService, SceneService

            upper = len(self.volume.chapters) if end_index is None else min(len(self.volume.chapters), end_index)
            with SessionLocal() as db:
                chs = ChapterService(db)
                ss = SceneService(db)
                for idx in range(max(0, start_index), upper):
                    ch_outline = self.volume.chapters[idx]
                    chapter = chs.get_chapter_by_index(self.session_id, idx)
                    if chapter:
                        chs.update_chapter(
                            chapter.id,
                            title=ch_outline.title,
                            goal=ch_outline.goal,
                            conflict=ch_outline.conflict,
                        )
                    else:
                        chapter = chs.create_chapter(
                            self.session_id,
                            idx,
                            ch_outline.title,
                            ch_outline.goal,
                            ch_outline.conflict,
                        )
                    ss.delete_chapter_scenes(chapter.id)
                    for s_idx, scene in enumerate(ch_outline.scenes or []):
                        ss.create_scene(
                            chapter.id,
                            s_idx,
                            scene.description,
                            scene.characters,
                            scene.location,
                            scene.mood,
                            scene.target_words,
                        )
        except Exception as e:
            logger.warning(f"Forced chapter outline DB sync failed: {e}")

    def _save_chapter_version_to_db(self, draft: ChapterDraft, guidance: str = ""):
        if not self.session_id:
            return
        try:
            from core.database import SessionLocal
            from models.db_service import ChapterService

            with SessionLocal() as db:
                chs = ChapterService(db)
                chapter = chs.get_chapter_by_index(self.session_id, draft.chapter_index)
                if not chapter:
                    return
                if guidance:
                    chs.update_chapter(chapter.id, guidance=guidance)
                chs.add_chapter_version(
                    chapter.id,
                    draft.content,
                    word_count=draft.word_count,
                    consistency_score=draft.consistency_score,
                )
        except Exception as e:
            logger.warning(f"Chapter version DB save failed: {e}")

    def _extract_keywords(self, text: str) -> list[str]:
        if not text:
            return []
        text = text.replace("\n", " ")
        words = []
        current = []
        for ch in text:
            if ch.isalnum() or '\u4e00' <= ch <= '\u9fff':
                current.append(ch)
            else:
                if len(current) >= 2:
                    words.append("".join(current))
                current = []
        if len(current) >= 2:
            words.append("".join(current))
        words = [w for w in words if len(w) >= 2 and len(w) <= 12]
        return words[:40]

    def _canonicalize_chapter_character_names(self) -> bool:
        if not self.volume or not self.characters:
            return False
        character_names = [c.name for c in self.characters if c.name]
        if not character_names:
            return False
        known = set(character_names)
        primary = character_names[0]
        if len(primary) < 2:
            return False

        aliases: set[str] = set()
        texts: list[str] = []
        for chapter in self.volume.chapters:
            texts.extend([chapter.title or "", chapter.goal or "", chapter.conflict or ""])
            for scene in chapter.scenes or []:
                texts.extend([scene.description or "", scene.location or "", scene.mood or ""])
                texts.extend(scene.characters or [])
        combined = "\n".join(texts)
        for pattern in [
            r"主角([\u4e00-\u9fff]{2,3})",
            r"([\u4e00-\u9fff]{2,3})(?:开始|决定|通过|利用|负责|发现|试图|邀请|回到|必须|被迫|与)",
        ]:
            for candidate in re.findall(pattern, combined):
                if candidate not in known and candidate.startswith(primary[0]) and len(candidate) == len(primary):
                    aliases.add(candidate)
        if not aliases:
            return False

        def replace_text(value: str) -> str:
            new_value = value or ""
            for alias in aliases:
                new_value = new_value.replace(alias, primary)
            return new_value

        changed = False
        for chapter in self.volume.chapters:
            old_fields = (chapter.title, chapter.goal, chapter.conflict)
            chapter.title = replace_text(chapter.title)
            chapter.goal = replace_text(chapter.goal)
            chapter.conflict = replace_text(chapter.conflict)
            changed = changed or old_fields != (chapter.title, chapter.goal, chapter.conflict)
            for scene in chapter.scenes or []:
                old_scene = (scene.description, tuple(scene.characters or []), scene.location, scene.mood)
                scene.description = replace_text(scene.description)
                scene.characters = [replace_text(name) for name in (scene.characters or [])]
                scene.location = replace_text(scene.location)
                scene.mood = replace_text(scene.mood)
                changed = changed or old_scene != (scene.description, tuple(scene.characters or []), scene.location, scene.mood)
        if changed:
            logger.warning("Canonicalized chapter character aliases: %s -> %s", sorted(aliases), primary)
        return changed

    def _auto_resolve_foreshadowing(self, chapter_idx: int, content: str):
        if not self.session_id:
            return
        try:
            from core.database import SessionLocal
            from models.db_service import ForeshadowingService

            keywords = set(self._extract_keywords(content))
            if not keywords:
                return
            with SessionLocal() as db:
                fs = ForeshadowingService(db)
                unresolved = fs.get_unresolved(self.session_id)
                resolution_spans = self._detect_foreshadow_resolution_spans(content)
                for item in unresolved:
                    if item.planted_chapter >= chapter_idx:
                        continue
                    item_keywords = set(getattr(item, "trigger_keywords", None) or [])
                    if not item_keywords:
                        item_keywords = set(self._extract_keywords(getattr(item, "source_excerpt", "") or item.description))
                    if not item_keywords:
                        item_keywords = set(self._extract_keywords(item.description))
                    # 补充：从 description 中也提取关键词扩大匹配面
                    desc_keywords = set(self._extract_keywords(item.description)) if item.description else set()
                    all_item_keywords = item_keywords | desc_keywords
                    overlap = keywords.intersection(all_item_keywords)
                    strong_markers = [kw for kw in ["真相", "原来", "证实", "发现", "承认", "解释", "回收", "回应", "就是", "凶手", "实验", "暴露", "揭穿", "坦白", "领悟", "明白"] if kw in content]
                    span_overlap = resolution_spans.intersection(all_item_keywords)
                    payoff_condition = str(getattr(item, "payoff_condition", "") or "")
                    payoff_hit = any(token in content for token in self._extract_keywords(payoff_condition)[:4]) if payoff_condition else False
                    # 年龄自动闭合：伏笔已存在 8+ 章且有 1+ 关键词匹配
                    foreshadow_age = chapter_idx - (item.planted_chapter or 0)
                    age_auto_close = foreshadow_age >= 8 and len(overlap) >= 1
                    # 强制闭合：伏笔已存在 15+ 章，无论是否有关键词匹配
                    force_age_close = foreshadow_age >= 15
                    if len(overlap) >= 1 or len(span_overlap) >= 1 or (overlap and strong_markers) or (payoff_hit and overlap) or age_auto_close or force_age_close:
                        reason_bits = sorted(list(span_overlap or overlap))[:4] or strong_markers[:4]
                        if force_age_close and not reason_bits:
                            reason_bits = ["长期未回收"]
                        age_note = f"（伏笔已存在{foreshadow_age}章）" if age_auto_close or force_age_close else ""
                        fs.resolve(item.id, chapter_idx, f"自动检测到在本章得到回应：{', '.join(reason_bits)}{age_note}")
                        continue
                    close_by = getattr(item, "close_by_chapter", None)
                    if close_by and chapter_idx + 1 >= int(close_by) - 1 and getattr(item, "status", "active") == "active":
                        item.status = "closing"
                db.commit()
        except Exception as e:
            logger.warning(f"Auto foreshadow resolution failed: {e}")

    def _get_character_state_context(self) -> str:
        """构建角色状态上下文
        参考幻城科技 CharacterTracker.get_character_summary_for_context()
        """
        try:
            parts = ["## 角色当前状态"]
            for char in self.characters:
                name = char.name
                goal = char.goal or ""
                personality = ", ".join(char.personality or []) if isinstance(char.personality, list) else (char.personality or "")
                status = char.status or {}
                location = status.get("location", "") if isinstance(status, dict) else ""
                mood = status.get("mood", "") if isinstance(status, dict) else ""
                level = status.get("level", "") if isinstance(status, dict) else ""

                # 角色状态机数据
                machine_state = ""
                try:
                    machine = self.state_manager.get_character(name)
                    if machine:
                        machine_state = f"修炼阶段:{machine.current_state} 等级:{machine.power_level}"
                except Exception:
                    pass

                line = f"- {name}"
                if personality:
                    line += f" 性格:{personality}"
                if location:
                    line += f" 位置:{location}"
                if mood:
                    line += f" 情绪:{mood}"
                if level:
                    line += f" 修为:{level}"
                if goal:
                    line += f" 目标:{goal[:60]}"
                if machine_state:
                    line += f" [{machine_state}]"

                # 人际关系
                if char.relationships:
                    rels = char.relationships[:3] if isinstance(char.relationships, list) else []
                    if rels:
                        rel_text = "; ".join([f"{r.get('name','')}:{r.get('relationship','')}" for r in rels])
                        line += f" 关系:{rel_text[:80]}"

                parts.append(line)

            return "\n".join(parts) if len(parts) > 1 else ""
        except Exception as e:
            logger.warning(f"Character state context build failed: {e}")
            return ""

    def _get_story_control_context(self) -> str:
        if not self.session_id:
            return ""
        try:
            from core.database import SessionLocal
            from models.db_service import TimelineService, ForeshadowingService, ChapterService

            with SessionLocal() as db:
                ts = TimelineService(db)
                fs = ForeshadowingService(db)
                chs = ChapterService(db)

                timeline = ts.get_project_timeline(self.session_id, limit=8)
                unresolved = fs.get_unresolved(self.session_id)[:8]
                finalized = [c for c in chs.get_project_chapters(self.session_id) if c.status == "finalized"][-3:]

                parts = []
                if finalized:
                    finalized_lines = []
                    for chapter in finalized:
                        draft = chs.to_chapter_draft(chapter)
                        if draft:
                            finalized_lines.append(f"- 第{chapter.chapter_index + 1}章《{chapter.title}》摘要：{draft.content[:180]}")
                    if finalized_lines:
                        parts.append("## 最近定稿章节\n" + "\n".join(finalized_lines))

                if timeline:
                    parts.append("## 正式时间线\n" + "\n".join([f"- 第{e.chapter_index + 1}章 [{e.event_type}] {e.description}" for e in timeline]))

                if unresolved:
                    parts.append("## 未回收伏笔\n" + "\n".join([f"- 埋设于第{f.planted_chapter + 1}章：{f.description}" for f in unresolved]))
                    old_unresolved = [f for f in unresolved if hasattr(f, 'planted_chapter') and self.volume and (len(self.finalized_chapters) - f.planted_chapter) >= 3]
                    if old_unresolved:
                        parts.append("## 伏笔提醒\n以下伏笔已悬置多章，优先考虑推进或回收：\n" + "\n".join([f"- {f.description}" for f in old_unresolved[:5]]))

                self._normalize_evolution_state()
                outline_memory = self.evolution_state.get("outline_memory", [])[-5:]
                world_memory = self.evolution_state.get("world_memory", [])[-5:]
                if outline_memory:
                    parts.append("## 阶段性重规划记忆\n" + "\n".join([f"- {item}" for item in outline_memory]))
                if world_memory:
                    parts.append("## 世界观增量记忆\n" + "\n".join([f"- {item}" for item in world_memory]))

                return "\n\n".join(parts)
        except Exception as e:
            logger.warning(f"Story control context load failed: {e}")
            return ""

    def _enrich_context(self, context: str, chapter_idx: int) -> str:
        """使用分层摘要系统构建上下文，注入角色状态、剧情线和伏笔"""
        chapter_num = chapter_idx + 1

        parts = []
        if context:
            parts.append(context)

        # 1. 分层摘要（核心）
        finalized = [
            {
                "chapter_index": c.chapter_index,
                "title": c.title,
                "content": c.content,
                "summary": getattr(c, "summary", c.content[:300]),
            }
            for c in self.generated_chapters
            if c.chapter_index in self.finalized_chapters
        ]
        finalized.sort(key=lambda x: x["chapter_index"])
        arc_context = self.hierarchical_summary.get_context_for_chapter(
            chapter_num=chapter_num,
            all_chapters=finalized,
            prev_chapter_tail_chars=800,
        )
        if arc_context:
            parts.append(arc_context)

        # 2. 全局摘要（保留旧格式兼容）
        if self.global_summary:
            parts.append("## 全局故事进展\n" + self.global_summary[:800])

        # 3. 项目级过度重复词反馈（通用，不依赖固定词表）
        overused = self._get_overused_words(top_n=8)
        if overused:
            word_list = "、".join(f"「{w}」({c}次)" for w, c in overused)
            parts.append(f"## 已过度重复的词（本章必须避免高频使用）\n{word_list}")

        # 4. 角色出场均衡提示
        if self.characters and chapter_num > 3:
            char_absence = self._get_character_absence(chapter_idx)
            if char_absence:
                absence_text = "、".join(f"「{name}」(已{absent}章未出场)" for name, absent in char_absence)
                parts.append(f"## 已长期未出场的角色（本章应适当提及或出场）\n{absence_text}")

        return "\n\n".join(parts)

    def _get_character_absence(self, current_chapter_idx: int, max_absence: int = 8) -> list[tuple[str, int]]:
        """返回已超过 max_absence 章未出场的主要角色。"""
        if not self.characters:
            return []
        result = []
        finalized_set = set(self.finalized_chapters)
        for char in self.characters:
            if not char.name:
                continue
            last_seen = -1
            for draft in self.generated_chapters:
                if draft.chapter_index in finalized_set and draft.content and char.name in draft.content:
                    last_seen = max(last_seen, draft.chapter_index)
            absence = current_chapter_idx - last_seen if last_seen >= 0 else current_chapter_idx + 1
            if absence > max_absence:
                result.append((char.name, absence))
        # 只返回最久未出场的前5个
        result.sort(key=lambda x: -x[1])
        return result[:5]

    def _update_project_word_freq(self, chapter_text: str):
        """从章节正文中提取词频，累积到项目级词频表。"""
        if not chapter_text:
            return
        stopwords = {
            "一个", "我们", "你们", "他们", "她们", "它们", "自己", "什么", "怎么",
            "这个", "那个", "这里", "那里", "这些", "那些", "这样", "那样",
            "没有", "不是", "可以", "已经", "可能", "应该", "需要", "就是",
            "但是", "而且", "或者", "因为", "所以", "如果", "虽然", "不过",
            "只是", "一直", "一下", "一些", "一样", "一切", "一种",
            "起来", "出来", "下去", "上来", "过来", "过去", "进入",
            "知道", "看到", "听到", "感到", "觉得", "认为", "希望",
            "时候", "现在", "然后", "最后", "开始", "继续", "突然",
            "之间", "之后", "之前", "以上", "以下", "以后", "前面", "后面",
            "他的", "她的", "它的", "我的", "你的",
            "说道", "不了",
        }
        words = re.findall(r'[一-鿿]{2,4}', chapter_text)
        for w in words:
            if w not in stopwords:
                self._project_word_freq[w] = self._project_word_freq.get(w, 0) + 1

    def _get_overused_words(self, top_n: int = 10) -> list[tuple[str, int]]:
        """返回项目中出现频率最高的词（按总频次排序）。"""
        if not self._project_word_freq:
            return []
        # 只返回出现次数足够多的词（至少5次）
        candidates = [(w, c) for w, c in self._project_word_freq.items() if c >= 5]
        candidates.sort(key=lambda x: -x[1])
        return candidates[:top_n]

    def _get_previous_chapter_ending(self, chapter_idx: int) -> str:
        """获取前一章的结尾1500字，用于跨章衔接。"""
        if chapter_idx <= 0:
            return ""
        # 先查已生成的章节
        for ch in reversed(self.generated_chapters):
            if ch.chapter_index == chapter_idx - 1 and ch.content:
                return ch.content[-1500:]
        # 再查缓存的上一章尾部
        if hasattr(self, '_previous_chapter_tail') and self._previous_chapter_tail:
            return self._previous_chapter_tail
        return ""

    def _build_chapter_bridge(self, chapter_idx: int) -> str:
        """构建结构化的跨章衔接信息，帮助LLM理解上章发生了什么并自然续写。"""
        if chapter_idx <= 0:
            return ""

        parts = []

        # 1. 上章摘要（从structured_memory获取）
        prev_summary = self.memory.structured.get_chapter_summary(chapter_idx - 1)
        if prev_summary:
            parts.append(f"上一章摘要：{prev_summary[:300]}")

        # 2. 上章结尾原文（1500字，衔接文风和场景）
        ending = self._get_previous_chapter_ending(chapter_idx)
        if ending:
            parts.append(f"上一章结尾原文（从这里自然续写）：\n...{ending}")

        # 3. 当前角色状态快照（谁在场、情绪、位置）
        observations = self.memory.structured.get_chapter_observations(chapter_idx - 1)
        if observations:
            chars_on_stage = observations.get("characters_on_stage", [])
            if chars_on_stage:
                parts.append(f"上章结尾在场角色：{'、'.join(chars_on_stage)}")
            emotional_state = observations.get("emotional_state", "")
            if emotional_state:
                parts.append(f"上章结尾情绪基调：{emotional_state}")
            hook = observations.get("chapter_end_hook", "")
            if hook:
                parts.append(f"上章结尾钩子：{hook}")

        # 4. 未闭合伏笔提醒
        unresolved = self.memory.structured.get_unresolved_foreshadowing()
        if unresolved:
            hints = [f.get("description", "")[:60] for f in unresolved[:3] if f.get("description")]
            if hints:
                parts.append(f"待回收伏笔：{'；'.join(hints)}")

        return "\n".join(parts)

    def _set_db_chapter_status(self, chapter_index: int, status: str):
        if not self.session_id:
            return
        try:
            from core.database import SessionLocal
            from models.db_service import ChapterService

            with SessionLocal() as db:
                chs = ChapterService(db)
                chapter = chs.get_chapter_by_index(self.session_id, chapter_index)
                if chapter:
                    chs.update_chapter(chapter.id, status=status)
        except Exception as e:
            logger.warning(f"Chapter DB status sync failed: {e}")

    def _mark_chapter_as_draft(self, chapter_idx: int):
        self.finalized_chapters = [idx for idx in self.finalized_chapters if idx != chapter_idx]
        self._set_db_chapter_status(chapter_idx, "draft")

    def _replace_generated_chapter(self, updated: ChapterDraft, pending_plot_progress: str):
        chapter_idx = updated.chapter_index
        if self.volume and 0 <= chapter_idx < len(self.volume.chapters):
            updated.title = self.volume.chapters[chapter_idx].title
        self.generated_chapters = [c for c in self.generated_chapters if c.chapter_index != chapter_idx] + [updated]
        self._mark_chapter_as_draft(chapter_idx)
        self.pending_chapter_updates[chapter_idx] = {
            "title": updated.title,
            "content": updated.content,
            "summary": updated.content[:300],
            "plot_progress": pending_plot_progress,
            "intent": getattr(updated, "intent", {}) or {},
            "observations": getattr(updated, "observations", {}) or {},
        }
        self.save_chapter(updated)
        self.save_project_state()

    def load_project_state(self) -> bool:
        path = self.get_state_path()
        if not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.outline = data.get("outline", "")
        self.title = data.get("title", self._derive_project_title(self.outline))
        self.genre = data.get("genre", "urban_fantasy")
        self.style = data.get("style", "web_novel")
        self.target_chapters = data.get("target_chapters", 12)
        self.words_per_chapter = data.get("words_per_chapter", 2000)
        self.world = WorldSetting(**data.get("world", {})) if data.get("world") else None
        self.characters = [CharacterSheet(**c) for c in data.get("characters", [])]
        if data.get("volume"):
            vol_data = data["volume"]
            chapters_data = vol_data.get("chapters", [])
            chapters = []
            for ch_data in chapters_data:
                scenes_data = ch_data.get("scenes", [])
                scenes = []
                for s in scenes_data:
                    if isinstance(s, dict):
                        try:
                            scenes.append(SceneOutline(**s))
                        except Exception:
                            logger.warning(f"Failed to load scene from JSON, using default: {list(s.keys())[:5]}")
                            scenes.append(SceneOutline(description=s.get("description", ""), characters=s.get("characters", [])))
                    else:
                        scenes.append(s)
                ch_dict = {**ch_data, "scenes": scenes}
                chapters.append(ChapterOutline(**ch_dict))
            self.volume = VolumeOutline(volume=vol_data.get("volume", "第一卷"), chapters=chapters)
        else:
            self.volume = None
        self.generated_chapters = [ChapterDraft(**c) for c in data.get("generated_chapters", [])]
        self.approved = data.get("approved", False)
        self.finalized_chapters = data.get("finalized_chapters", [])
        raw_pending = data.get("pending_chapter_updates", {})
        self.pending_chapter_updates = {int(k): v for k, v in raw_pending.items()}
        self.evolution_state = data.get("evolution_state", {"last_synced_chapter": -1, "history": []})
        self._normalize_evolution_state()
        self.open_intents_ledger = data.get("open_intents_ledger", self._default_open_intents_ledger())
        self._normalize_open_intents_ledger()
        self.consistency_gate_stats = data.get("consistency_gate_stats", self._default_consistency_gate_stats())
        self._normalize_consistency_gate_stats()
        self.planning_window = data.get("planning_window", STAGE_PLAN_CHAPTERS)
        self.tail_repair_locked = data.get("tail_repair_locked", False)
        self.style_fingerprint = data.get("style_fingerprint", {}) or {}
        self.state_manager = CharacterStateManager.from_dict(data.get("character_state_manager", {}))
        gate_data = data.get("consistency_gate", {})
        if gate_data:
            self.consistency_gate.dead_characters = set(gate_data.get("dead_characters", []))
            self.consistency_gate.character_power = gate_data.get("character_power", {})
            self.consistency_gate.character_locations = gate_data.get("character_locations", {})
        self.state_manager.dead_characters = set(data.get("character_state_manager", {}).get("dead_characters", []))
        if "enhancement_state" in data:
            self.enhancement.restore_state(data["enhancement_state"])
        self.global_summary = data.get("global_summary", "")
        self._previous_chapter_tail = data.get("_previous_chapter_tail", "")
        self._canonicalize_chapter_character_names()
        self._refresh_enhancement_baseline()
        # 重建项目级词频表
        self._project_word_freq = {}
        finalized_set = set(self.finalized_chapters)
        for draft in self.generated_chapters:
            if draft.chapter_index in finalized_set and draft.content:
                self._update_project_word_freq(draft.content)
        return True

    def load_from_database(self) -> bool:
        if not self.session_id:
            return False
        try:
            from core.database import SessionLocal
            from models.db_service import ProjectService, CharacterService, WorldService, ChapterService

            with SessionLocal() as db:
                ps = ProjectService(db)
                cs = CharacterService(db)
                ws = WorldService(db)
                chs = ChapterService(db)

                project = ps.get_project(self.session_id)
                if not project:
                    return False

                self.outline = project.outline
                self.title = project.title.strip() if getattr(project, "title", "") and project.title.strip() else self._derive_project_title(project.outline)
                self.genre = project.genre
                self.style = project.style
                self.target_chapters = project.target_chapters
                self.words_per_chapter = project.words_per_chapter
                world = ws.get_world(self.session_id)
                self.world = ws.to_world_setting_model(world) if world else None
                self.characters = [cs.to_character_sheet(c) for c in cs.get_project_characters(self.session_id)]
                chapters = chs.get_project_chapters(self.session_id)
                self.volume = VolumeOutline(
                    volume="第一卷",
                    chapters=[chs.to_chapter_outline(ch) for ch in chapters],
                )
                # 如果 DB 中 chapters 没有 scenes，尝试从 JSON 状态恢复
                has_any_scenes = any(ch.scenes for ch in self.volume.chapters)
                if not has_any_scenes and os.path.exists(self.get_state_path()):
                    try:
                        with open(self.get_state_path(), "r", encoding="utf-8") as f:
                            state_data = json.load(f)
                        if state_data.get("volume"):
                            vol_data = state_data["volume"]
                            chapters_data = vol_data.get("chapters", [])
                            for i, ch_data in enumerate(chapters_data):
                                if i < len(self.volume.chapters) and ch_data.get("scenes"):
                                    scenes_data = ch_data["scenes"]
                                    scenes = []
                                    for s in scenes_data:
                                        if isinstance(s, dict):
                                            scenes.append(SceneOutline(**s))
                                        else:
                                            scenes.append(s)
                                    self.volume.chapters[i].scenes = scenes
                    except Exception as e:
                        logger.warning(f"Failed to restore scenes from JSON: {e}")
                self.generated_chapters = []
                finalized_indices = []
                for ch in chapters:
                    draft = chs.to_chapter_draft(ch)
                    if draft:
                        self.generated_chapters.append(draft)
                        if ch.status == "finalized":
                            finalized_indices.append(ch.chapter_index)
                    elif ch.status == "finalized":
                        chs.update_chapter(ch.id, status="draft")
                self.approved = project.approved
                self.finalized_chapters = finalized_indices
                self.pending_chapter_updates = {}
                self.evolution_state = self._default_evolution_state()
                if os.path.exists(self.get_state_path()):
                    try:
                        with open(self.get_state_path(), "r", encoding="utf-8") as f:
                            state_data = json.load(f)
                            self.evolution_state = state_data.get("evolution_state", self.evolution_state)
                            self.planning_window = state_data.get("planning_window", STAGE_PLAN_CHAPTERS)
                            if state_data.get("enhancement_state"):
                                self.enhancement.restore_state(state_data["enhancement_state"])
                            self.global_summary = state_data.get("global_summary", "")
                            self._previous_chapter_tail = state_data.get("_previous_chapter_tail", "")
                    except Exception as e:
                        logger.warning(f"Evolution state load failed: {e}")
                self._normalize_evolution_state()
                self.state_manager = CharacterStateManager()
                for char in self.characters:
                    self.state_manager.register_character(char.name, initial_power=1)

                self.memory = MemorySystem(session_id=self.session_id)
                self.rag = RAGEngine(self.memory.long_term)
                if self.world:
                    self.memory.update_world(self.world)
                for char in self.characters:
                    self.memory.update_character(char)
                self.memory.sync_relationships_from_characters(chapter=0)
                for draft in self.generated_chapters[-settings.MEMORY_SHORT_TERM_SIZE:]:
                    summary = draft.content[:300]
                    self.memory.add_chapter_to_memory(draft.title, draft.content, summary)

                self._canonicalize_chapter_character_names()
                self._refresh_enhancement_baseline()
                # 重建项目级词频表
                self._project_word_freq = {}
                finalized_set = set(self.finalized_chapters)
                for draft in self.generated_chapters:
                    if draft.chapter_index in finalized_set and draft.content:
                        self._update_project_word_freq(draft.content)
                self.save_project_state()
                return True
        except Exception as e:
            logger.warning(f"Database project load failed: {e}")
            return False

    def save_chapter(self, draft: ChapterDraft):
        output_dir = self.get_output_dir()
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"chapter_{draft.chapter_index + 1:03d}.txt")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"# {draft.title}\n\n{draft.content}")
        draft_path = os.path.join(output_dir, f"chapter_{draft.chapter_index + 1:03d}.json")
        with open(draft_path, "w", encoding="utf-8") as f:
            json.dump(draft.model_dump(), f, ensure_ascii=False, indent=2)
        return output_path

    def export_to_txt(self, finalized_only: bool = False, output_dir: Optional[str] = None) -> str:
        """P2 程序级修复：将已生成章节导出为单个 .txt 文件。

        行为：
        - 按 chapter_index 排序所有章节
        - 如 finalized_only=True，只导出 finalized_chapters 中的章节
        - 自动去除 content 开头已包含的标题行（避免连续重复）
        - 自动跳过连续相同标题
        - 返回导出文件的绝对路径

        Args:
            finalized_only: 是否仅导出已定稿章节
            output_dir: 自定义输出目录；默认使用 self.get_output_dir() / session_id.txt

        Returns:
            导出文件的绝对路径

        Raises:
            ValueError: 当没有可用章节时
        """
        chapters = sorted(self.generated_chapters, key=lambda c: c.chapter_index)
        if finalized_only:
            chapters = [c for c in chapters if c.chapter_index in self.finalized_chapters]
        if not chapters:
            raise ValueError("No chapters available for export")

        if output_dir is None:
            base_dir = Path(self.get_output_dir())
        else:
            base_dir = Path(output_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        suffix = "_finalized" if finalized_only else ""
        txt_path = base_dir / f"{self.session_id}{suffix}.txt"

        with open(txt_path, "w", encoding="utf-8") as f:
            prev_title = None
            for ch in chapters:
                content = ch.content or ""
                title_line = f"# {ch.title}"
                # P2 修复：去除 content 开头已包含的标题行
                stripped = content.lstrip()
                if stripped.startswith(title_line):
                    idx = stripped.find("\n")
                    if idx >= 0:
                        rest = stripped[idx + 1:].lstrip("\n").lstrip()
                        content = rest
                # 连续相同标题也跳过
                if title_line == prev_title:
                    f.write(f"{content}\n\n")
                else:
                    f.write(f"{title_line}\n\n{content}\n\n")
                    prev_title = title_line

        return str(txt_path)

    def _get_finalized_drafts_after_sync(self) -> list[ChapterDraft]:
        self._normalize_evolution_state()
        last_synced = int(self.evolution_state.get("last_synced_chapter", -1))
        finalized = set(self.finalized_chapters)
        drafts = [
            chapter for chapter in self.generated_chapters
            if chapter.chapter_index in finalized and chapter.chapter_index > last_synced
        ]
        return sorted(drafts, key=lambda chapter: chapter.chapter_index)

    def _compact_text(self, text: str, limit: int = 220) -> str:
        text = " ".join((text or "").split())
        if len(text) <= limit:
            return text
        truncated = text[:limit]
        # 向后查找最近的句子结束标点，避免截断中文句子
        for punct in ["。", "！", "？", "!", "?", "；", "，"]:
            idx = truncated.rfind(punct)
            if idx > limit * 0.5:  # 至少保留一半内容
                return truncated[: idx + 1].rstrip()
        return truncated.rstrip() + "..."

    def _chapter_contract_text(self, chapter_idx: int, chapter_outline: ChapterOutline, plot_direction: str = "") -> str:
        goal = self._sanitize_chapter_outline_text(chapter_outline.goal, chapter_idx=chapter_idx)
        conflict = self._sanitize_chapter_outline_text(chapter_outline.conflict, chapter_idx=chapter_idx)
        plot_direction = self._sanitize_chapter_outline_text(plot_direction or goal, chapter_idx=chapter_idx)
        scenes = "\n".join(
            [
                f"- 场景{idx + 1}：{self._sanitize_chapter_outline_text(scene.description, chapter_idx=chapter_idx)}；人物：{'、'.join(scene.characters or []) or '按章节需要'}；地点：{scene.location or '按章节需要'}"
                for idx, scene in enumerate(chapter_outline.scenes or [])
            ]
        ) or "- 暂无场景拆分，必须围绕章节目标和冲突展开。"
        contract = (
            f"当前必须生成：第{chapter_idx + 1}章《{chapter_outline.title}》\n"
            f"章节目标：{goal}\n"
            f"章节冲突：{conflict}\n"
            f"剧情推进：{plot_direction or goal}\n"
            f"场景要求：\n{scenes}\n"
            "硬性边界：不得改写为其他章节，不得自创第X章标题，不得偏离本章目标和冲突。"
        )
        ending_instruction = self._ending_closure_instruction(chapter_idx)
        if ending_instruction:
            contract += "\n" + ending_instruction
        story_bible_context = self._format_story_bible_context(chapter_idx)
        if story_bible_context:
            contract += "\n" + story_bible_context
        return contract

    def _strip_generated_heading(self, text: str, expected_title: str) -> str:
        text = (text or "").lstrip()
        lines = text.splitlines()
        removed = False
        while lines:
            while lines and not lines[0].strip():
                lines.pop(0)
            if not lines:
                break
            first = lines[0].strip()
            heading_pattern = r"^(#{1,6}\s*)?(第[0-9一二三四五六七八九十百千]+章|章节\s*[0-9]+|Chapter\s+\d+)([：:\s].*)?$"
            if re.match(heading_pattern, first, flags=re.I) or first in {expected_title, f"《{expected_title}》"}:
                lines.pop(0)
                removed = True
                continue
            break
        if removed:
            return "\n".join(lines).lstrip()
        if not lines:
            return text.strip()
        return text.strip()

    def _validate_chapter_alignment(self, chapter_idx: int, chapter_outline: ChapterOutline, chapter_text: str):
        first_line = next((line.strip() for line in (chapter_text or "").splitlines() if line.strip()), "")
        if re.match(r"^(#{1,6}\s*)?第[0-9一二三四五六七八九十百千]+章", first_line):
            raise ConsistencyBlockError(
                [f"正文开头出现自创章节标题“{first_line[:40]}”，可能与目录第{chapter_idx + 1}章《{chapter_outline.title}》错位"],
                category="chapter_alignment",
            )
        anchors = self._extract_keywords(f"{chapter_outline.title} {chapter_outline.goal} {chapter_outline.conflict}")[:12]
        if anchors:
            hit_count = sum(1 for word in anchors if word and word in chapter_text)
            if hit_count == 0:
                logger.warning(
                    "Chapter alignment weak signal: no keyword hit for chapter %s《%s》",
                    chapter_idx + 1,
                    chapter_outline.title,
                )

    def _chapter_change_summary(self, draft: ChapterDraft) -> dict:
        keywords = self._extract_keywords(draft.content)[:10]
        return {
            "chapter_index": draft.chapter_index,
            "chapter_no": draft.chapter_index + 1,
            "title": draft.title,
            "summary": self._compact_text(draft.content, 260),
            "keywords": keywords,
            "word_count": draft.word_count or len(draft.content or ""),
        }

    def _get_unresolved_foreshadow_notes(self) -> list[dict]:
        if not self.session_id:
            return []
        try:
            from core.database import SessionLocal
            from models.db_service import ForeshadowingService

            with SessionLocal() as db:
                items = ForeshadowingService(db).get_unresolved(self.session_id)[:8]
                return [
                    {
                        "description": item.description,
                        "foreshadow_type": getattr(item, "foreshadow_type", "clue") or "clue",
                        "trigger_keywords": list(getattr(item, "trigger_keywords", []) or []),
                        "payoff_condition": getattr(item, "payoff_condition", "") or "",
                        "planted_chapter": item.planted_chapter + 1,
                        "age": max(0, len(self.finalized_chapters) - item.planted_chapter),
                    }
                    for item in items
                    if not self._is_structural_foreshadow_noise(item.description)
                ]
        except Exception as e:
            logger.warning(f"Unresolved foreshadow load failed: {e}")
            return []

    def _sync_foreshadows_to_info_gap(self, chapter_idx: int):
        """将 DB 中未解伏笔同步到信息差管理器的 reader_wants_to_know。"""
        if not hasattr(self, 'enhancement') or not self.enhancement:
            return
        ig = self.enhancement.info_gap
        unresolved = self._get_unresolved_foreshadow_notes()
        for note in unresolved[:5]:
            cleaned = str(note or "").strip()
            if not cleaned:
                continue
            # 避免重复
            if cleaned not in ig.state.reader_wants_to_know:
                ig.state.reader_wants_to_know.append(cleaned)
        # 确保至少有基础悬念
        if not ig.state.reader_wants_to_know:
            ig.state.reader_wants_to_know.append(f"第{chapter_idx}章后的核心悬念")

    def _auto_detect_relationships(self, chapter_idx: int, chapter_text: str):
        """从章节文本中自动检测角色共现，推断关系。"""
        if not self.characters or not self.state_manager:
            return
        character_names = [c.name for c in self.characters if c.name]
        if len(character_names) < 2:
            return
        # 将文本按段落分割，检测角色共现
        paragraphs = re.split(r"[\n]", chapter_text)
        co_occurrence: dict[tuple[str, str], int] = {}
        for para in paragraphs:
            present = [name for name in character_names if name in para]
            # 去重：如果 A 出现多次只计一次
            present = list(set(present))
            for i in range(len(present)):
                for j in range(i + 1, len(present)):
                    pair = tuple(sorted([present[i], present[j]]))
                    co_occurrence[pair] = co_occurrence.get(pair, 0) + 1
        # 根据共现次数设置关系强度
        for (c1, c2), count in co_occurrence.items():
            if count >= 5:
                strength = min(90, 50 + count * 3)
                rel_type = RelationType.ALLY  # 高频共现默认为盟友
            elif count >= 3:
                strength = min(70, 40 + count * 5)
                rel_type = RelationType.NEUTRAL
            else:
                strength = min(50, 20 + count * 10)
                rel_type = RelationType.NEUTRAL
            # 检查是否有敌对关键词
            enemy_keywords = ["敌", "打", "杀", "恨", "怒", "仇", "骂", "斥", "威胁", "对抗"]
            friend_keywords = ["帮", "救", "保护", "合作", "信任", "爱", "朋友", "伙伴", "感激"]
            enemy_count = sum(1 for kw in enemy_keywords if kw in chapter_text and c1 in chapter_text and c2 in chapter_text)
            friend_count = sum(1 for kw in friend_keywords if kw in chapter_text and c1 in chapter_text and c2 in chapter_text)
            if enemy_count > friend_count and enemy_count >= 2:
                rel_type = RelationType.ENEMY
                strength = min(80, 40 + enemy_count * 10)
            elif friend_count > enemy_count and friend_count >= 2:
                rel_type = RelationType.ALLY
                strength = min(90, 50 + friend_count * 8)
            self.state_manager.set_relationship(c1, c2, rel_type, strength)

    def _settle_story_completion_state(self):
        if not self.volume or not self.generated_chapters:
            return
        if len(self.finalized_chapters) < self.target_chapters:
            return
        last_idx = self.target_chapters - 1
        final_draft = next((c for c in self.generated_chapters if c.chapter_index == last_idx), None)
        final_text = final_draft.content if final_draft else ""
        closure_gaps = self._story_closure_gaps(final_text)
        if closure_gaps:
            logger.warning("Story completion has unresolved gaps: %s", "；".join(closure_gaps[:8]))
        final_summary = self._compact_text(final_text, 160) if final_text else ""
        try:
            from core.database import SessionLocal
            from models.db_service import ForeshadowingService

            with SessionLocal() as db:
                fs = ForeshadowingService(db)
                unresolved = fs.get_unresolved(self.session_id)
                for item in unresolved:
                    desc = item.description or ""
                    if self._is_structural_foreshadow_noise(desc):
                        fs.resolve(item.id, last_idx, "终局清理：章节规划噪声，不再视为真实伏笔")
                        continue
                    item_keywords = set(getattr(item, "trigger_keywords", None) or [])
                    if not item_keywords:
                        item_keywords = set(self._extract_keywords(getattr(item, "source_excerpt", "") or desc))
                    overlap = [kw for kw in item_keywords if kw and kw in final_text]
                    if overlap or any(marker in final_text for marker in ["真相", "原来", "终于", "结束", "收束", "交代", "归宿"]):
                        fs.resolve(item.id, last_idx, f"终局回收：第{last_idx + 1}章完成收束")
        except Exception as e:
            logger.warning(f"Story completion settlement failed: {e}")

        self.enhancement.suspense_arcs.settle_at_story_end(last_idx + 1, reason="故事完结，悬念弧自动结算")
        self.enhancement.info_gap.settle_at_story_end(final_summary=final_summary)

    def _story_closure_gaps(self, final_text: str = "") -> list[str]:
        self._normalize_open_intents_ledger()
        gaps = []
        text = str(final_text or "")
        prior_text = "\n".join(
            c.content or ""
            for c in sorted(self.generated_chapters, key=lambda item: item.chapter_index)
            if c.chapter_index < max(0, self.target_chapters - 1)
        )
        corpus = (prior_text + "\n" + text).strip()
        corpus_keywords = set(self._extract_keywords(corpus))

        def closure_terms(desc: str, keywords: list[str] | None = None) -> list[str]:
            raw = re.sub(r"^第\d+章埋线：", "", str(desc or ""))
            terms = list(keywords or []) + self._extract_keywords(raw)
            important = [
                "林岫", "周砚", "赵丰年", "陈竞洋", "铜铃", "潮位", "旧城区", "档案",
                "沉船", "台风", "预警", "密钥", "拆迁", "栈桥", "真相", "父亲",
            ]
            terms.extend([term for term in important if term in raw])
            compact = re.sub(r"\s+", "", raw)
            for size in (2, 3, 4):
                for idx in range(0, max(0, len(compact) - size + 1)):
                    piece = compact[idx:idx + size]
                    if any(ch in piece for ch in "的了和与在是为把被"):
                        continue
                    if piece in important or piece in corpus:
                        terms.append(piece)
            return self._dedupe_text_list([t for t in terms if 2 <= len(str(t)) <= 12], limit=12)

        def covered(desc: str, keywords: list[str] | None = None, min_hits: int = 1) -> bool:
            kws = closure_terms(desc, keywords)
            if not corpus:
                return False
            if desc and desc[: min(12, len(desc))] in corpus:
                return True
            hits = [kw for kw in kws if kw in corpus or kw in corpus_keywords]
            return len(hits) >= min_hits

        bible = self.open_intents_ledger.get("story_bible", {}) or {}
        core_text = f"{bible.get('core_promise','')} {bible.get('ending_answer','')} {bible.get('main_conflict','')}"
        core_terms = closure_terms(core_text)
        core_hits = [kw for kw in core_terms if kw in corpus or kw in corpus_keywords]
        if corpus and core_terms and len(core_hits) < min(3, len(core_terms)):
            gaps.append("整部正文没有明显回应故事圣经的核心承诺")
        for item in (self.open_intents_ledger.get("unresolved_payoffs", []) or [])[:8]:
            desc = item.get("description", "")
            kws = item.get("keywords", []) or self._extract_keywords(desc)[:6]
            if not covered(desc, kws, min_hits=1):
                gaps.append(f"未清伏笔：{desc}")
        for item in (self.open_intents_ledger.get("continuity_debts", []) or [])[:8]:
            desc = item.get("description", "")
            kws = item.get("keywords", []) or self._extract_keywords(desc)[:6]
            if not covered(desc, kws, min_hits=1):
                gaps.append(f"未清剧情债务：{desc}")
        for arc in (bible.get("character_arcs", []) or [])[:6]:
            if not isinstance(arc, dict):
                continue
            name = arc.get("name", "")
            if name and text and name not in text:
                gaps.append(f"主要人物缺少终局归宿：{name}")
        return self._dedupe_text_list(gaps, limit=12)

    def get_story_evolution(self) -> dict:
        self._normalize_evolution_state()
        self._ensure_planned_chapter_count()
        drafts = self._get_finalized_drafts_after_sync()
        next_start = (max(self.finalized_chapters) + 1) if self.finalized_chapters else 0
        future_count = len(self.volume.chapters[next_start:]) if self.volume else 0
        synced_to = int(self.evolution_state.get("last_synced_chapter", -1))
        finalized_summaries = [self._chapter_change_summary(draft) for draft in drafts]
        character_updates = self._build_character_evolution_notes(drafts)
        world_updates = self._build_world_evolution_notes(drafts)
        outline_updates = self._build_outline_evolution_notes(drafts)
        unresolved_threads = self._get_unresolved_foreshadow_notes()
        plan_updates = self._build_chapter_evolution_notes(
            drafts,
            next_start,
            outline_updates=outline_updates,
            unresolved_threads=unresolved_threads,
        )
        drift_report = self._build_plan_drift_report(
            drafts,
            next_start,
            outline_updates=outline_updates,
            unresolved_threads=unresolved_threads,
            plan_updates=plan_updates,
        )
        # 同步 last_synced_chapter，避免下次调用仍返回相同数据
        if drafts:
            latest_draft_idx = max(d.chapter_index for d in drafts)
            self.evolution_state["last_synced_chapter"] = latest_draft_idx
        return {
            "status": "ready" if drafts else "up_to_date",
            "strategy": self.evolution_state.get("strategy", ""),
            "sync_policy": {
                "initial_setting": "只作为方向锚点，不会被自动推翻。",
                "finalized_memory": "只吸收已定稿章节，草稿不会进入正式演进。",
                "stage_replan": "只调整未来未生成章节，已生成或已定稿章节不被改写。",
            },
            "last_synced_chapter": synced_to,
            "pending_finalized_count": len(drafts),
            "pending_range": [
                drafts[0].chapter_index + 1,
                drafts[-1].chapter_index + 1,
            ] if drafts else [],
            "future_start_chapter": next_start + 1 if self.volume and next_start < len(self.volume.chapters) else None,
            "future_chapter_count": future_count,
            "finalized_summaries": finalized_summaries,
            "character_updates": character_updates,
            "world_updates": world_updates,
            "outline_updates": outline_updates,
            "unresolved_threads": unresolved_threads,
            "chapter_plan_updates": plan_updates,
            "plan_drift_report": drift_report,
            "outline_memory": self.evolution_state.get("outline_memory", [])[-8:],
            "world_memory": self.evolution_state.get("world_memory", [])[-8:],
            "history": self.evolution_state.get("history", [])[-8:],
        }

    def _build_character_evolution_notes(self, drafts: list[ChapterDraft]) -> list[dict]:
        if not drafts:
            return []
        notes = []
        for char in self.characters:
            hits = []
            keyword_hits = set()
            for draft in drafts:
                if char.name and char.name in draft.content:
                    summary = self._compact_text(draft.content, 120)
                    hits.append(f"第{draft.chapter_index + 1}章《{draft.title}》参与了已定稿剧情：{summary}")
                    keyword_hits.update(self._extract_keywords(draft.content)[:5])
            if hits:
                status_patch = {
                    "last_seen_chapter": drafts[-1].chapter_index + 1,
                    "continuity_keywords": sorted(keyword_hits)[:8],
                }
                notes.append({
                    "name": char.name,
                    "status": char.status,
                    "status_patch": status_patch,
                    "rationale": "角色在定稿章节中出现，后续写作需要继承其经历、位置与情绪状态。",
                    "memory_additions": hits[-3:],
                })
        return notes

    def _build_world_evolution_notes(self, drafts: list[ChapterDraft]) -> list[dict]:
        notes = []
        keywords = ["规则", "势力", "地点", "禁忌", "能力", "境界", "组织", "城市", "学院", "家族", "契约", "代价", "传说", "遗迹"]
        for draft in drafts:
            matched = [keyword for keyword in keywords if keyword in draft.content]
            if matched:
                notes.append({
                    "chapter": draft.chapter_index + 1,
                    "title": draft.title,
                    "type": "world_delta",
                    "summary": f"出现可能影响世界观、势力关系或规则体系的新事实：{self._compact_text(draft.content, 160)}",
                    "keywords": matched[:6],
                })
        return notes[-8:]

    def _build_outline_evolution_notes(self, drafts: list[ChapterDraft]) -> list[str]:
        if not drafts:
            return []
        notes = []
        for draft in drafts:
            obs = getattr(draft, "observations", {}) or {}
            focus = []
            if obs.get("characters_on_stage"):
                focus.append("人物:" + "、".join(obs["characters_on_stage"][:3]))
            if obs.get("resources_touched"):
                focus.append("资源:" + "、".join(obs["resources_touched"][:3]))
            if obs.get("hook_movements"):
                focus.append("钩子:" + " / ".join(obs["hook_movements"][:2]))
            notes.append(
                f"第{draft.chapter_index + 1}章《{draft.title}》已成为正式剧情基础，后续主线必须承接：{self._compact_text(draft.content, 140)}"
                + (f"；观察摘要：{'；'.join(focus)}" if focus else "")
            )
        return notes[-6:]

    def _build_chapter_evolution_notes(
        self,
        drafts: list[ChapterDraft],
        next_start: int,
        outline_updates: list[str] | None = None,
        unresolved_threads: list[dict] | None = None,
    ) -> list[dict]:
        if not self.volume or not drafts:
            return []
        recent = "；".join([f"第{d.chapter_index + 1}章《{d.title}》" for d in drafts[-3:]])
        unresolved_threads = unresolved_threads or []
        total = min(self.target_chapters or len(self.volume.chapters), len(self.volume.chapters))
        thread_hint = ""
        if unresolved_threads:
            deduped_threads = self._dedupe_text_list([item["description"] for item in unresolved_threads], limit=3)
            if deduped_threads:
                thread_hint = "；同时优先照看未回收伏笔：" + "、".join([item[:28] for item in deduped_threads])
        outline_hint = ""
        if outline_updates:
            compact_outline_updates = self._dedupe_text_list([item[:60] for item in outline_updates], limit=2)
            if compact_outline_updates:
                outline_hint = "；遵循阶段演进：" + " / ".join(compact_outline_updates)
        updates = []
        generated_indices = {c.chapter_index for c in self.generated_chapters}
        stage_size = 12
        for idx, chapter in enumerate(self.volume.chapters[next_start:next_start + stage_size], start=next_start):
            if idx in generated_indices:
                continue
            old_goal = self._clean_plot_progress_text(chapter.goal) or chapter.goal
            old_conflict = self._clean_plot_progress_text(chapter.conflict) or chapter.conflict
            chapters_left = total - idx
            if chapters_left <= min(4, total):
                progress_note = f"承接已定稿进展（{recent}），当前已进入终局倒计时，必须在第{total}章内完成主冲突闭合、关键伏笔回收与人物结局落点：{old_goal}"
            else:
                progress_note = f"承接已定稿进展（{recent}），保持既定方向推进：{old_goal}"
            if outline_hint:
                progress_note += outline_hint
            if thread_hint:
                progress_note += thread_hint
            updates.append({
                "chapter_index": idx,
                "chapter_no": idx + 1,
                "title": chapter.title,
                "before_goal": old_goal,
                "before_conflict": old_conflict,
                "goal": old_goal,
                "conflict": old_conflict,
                "plot_progress": progress_note,
                "reason": "阶段性重规划：让后续章节吃到定稿剧情的真实变化。",
            })
        return updates

    def _build_plan_drift_report(
        self,
        drafts: list[ChapterDraft],
        next_start: int,
        outline_updates: list[str],
        unresolved_threads: list[dict],
        plan_updates: list[dict],
    ) -> dict:
        finalized_count = len(self.finalized_chapters)
        if finalized_count < 5 or finalized_count % 5 != 0:
            return {
                "checked": False,
                "recommended": False,
                "reason": "未达到5章检查节点",
                "severity": "none",
                "signals": [],
            }
        signals = []
        severity_score = 0
        if len(outline_updates) >= 3:
            signals.append(f"近5章产生了{len(outline_updates)}条主线演进信号")
            severity_score += 1
        closing_threads = [item for item in unresolved_threads if item.get("age", 0) >= 5]
        if closing_threads:
            signals.append(f"存在{len(closing_threads)}条长期未回收伏线")
            severity_score += 1
        if plan_updates:
            altered = sum(1 for item in plan_updates if str(item.get("plot_progress", "")) != str(item.get("before_goal", "")))
            if altered >= 3:
                signals.append(f"未来章节中至少{altered}章需要承接新的正式剧情")
                severity_score += 1
        if drafts:
            recent_keywords = set()
            for draft in drafts[-5:]:
                recent_keywords.update(self._extract_keywords(draft.content)[:12])
            future_keywords = set()
            if self.volume:
                for chapter in self.volume.chapters[next_start:next_start + 5]:
                    future_keywords.update(self._extract_keywords(" ".join([chapter.title or "", chapter.goal or "", chapter.conflict or ""]))[:10])
            if recent_keywords and future_keywords:
                overlap_ratio = len(recent_keywords.intersection(future_keywords)) / max(len(future_keywords), 1)
                if overlap_ratio < 0.18:
                    signals.append("近期正式剧情与未来规划关键词重叠偏低")
                    severity_score += 2
        recommended = severity_score >= 2
        severity = "high" if severity_score >= 3 else ("medium" if severity_score >= 2 else "low")
        reason = "建议对未来未生成章节做阶段性重规划" if recommended else "当前规划仍可继续承接，仅需观察"
        return {
            "checked": True,
            "recommended": recommended,
            "reason": reason,
            "severity": severity,
            "signals": signals[:6],
            "checked_at_finalized": finalized_count,
            "future_start_chapter": next_start + 1 if self.volume and next_start < len(self.volume.chapters) else None,
        }

    def apply_story_evolution(self) -> dict:
        self._normalize_evolution_state()
        self._ensure_planned_chapter_count()
        evolution = self.get_story_evolution()
        drafts = self._get_finalized_drafts_after_sync()
        if not drafts:
            return {"status": "up_to_date", "evolution": evolution}

        for note in evolution["character_updates"]:
            for char in self.characters:
                if char.name != note["name"]:
                    continue
                memory = list(char.memory or [])
                for item in note["memory_additions"]:
                    if item not in memory:
                        memory.append(item)
                char.memory = memory[-50:]
                current_status = dict(char.status or {})
                current_status.update(note.get("status_patch") or {})
                current_status["last_synced_chapter"] = drafts[-1].chapter_index + 1
                char.status = current_status
                self.memory.update_character(char)

        world_memory = list(self.evolution_state.get("world_memory", []))
        for note in evolution["world_updates"]:
            text = note.get("summary", "") if isinstance(note, dict) else str(note)
            if text and text not in world_memory:
                world_memory.append(text)
            if self.world and text and text not in self.world.history:
                self.world.history.append(text)
        if self.world:
            self.world.history = self.world.history[-80:]
            self.memory.update_world(self.world)

        next_start = max(self.finalized_chapters) + 1 if self.finalized_chapters else 0
        if self.volume:
            for update in evolution["chapter_plan_updates"]:
                idx = update["chapter_index"]
                if 0 <= idx < len(self.volume.chapters):
                    chapter = self.volume.chapters[idx]
                    chapter.goal = self._clean_plot_progress_text(update["goal"]) or chapter.goal
                    chapter.conflict = self._clean_plot_progress_text(update["conflict"]) or chapter.conflict
                    if not chapter.scenes:
                        chapter.scenes = [
                            SceneOutline(
                                description=chapter.goal,
                                target_words=self.words_per_chapter,
                            )
                        ]

        synced_to = drafts[-1].chapter_index
        outline_memory = list(self.evolution_state.get("outline_memory", []))
        for item in evolution.get("outline_updates", []):
            if item not in outline_memory:
                outline_memory.append(item)
        history_item = {
            "synced_to_chapter": synced_to + 1,
            "pending_count": len(drafts),
            "character_updates": len(evolution["character_updates"]),
            "world_updates": len(evolution["world_updates"]),
            "outline_updates": len(evolution.get("outline_updates", [])),
            "chapter_plan_updates": len(evolution["chapter_plan_updates"]),
            "applied_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        history = list(self.evolution_state.get("history", []))
        history.append(history_item)
        self.evolution_state = {
            "last_synced_chapter": synced_to,
            "outline_memory": outline_memory[-40:],
            "world_memory": world_memory[-40:],
            "history": history[-20:],
            "strategy": self._default_evolution_state()["strategy"],
        }
        self._rebuild_suspense_arcs_from_story(force=True)
        self._sync_characters_to_db()
        self._sync_world_to_db()
        self._sync_future_chapter_outlines_to_db(next_start)
        self.save_project_state()
        return {"status": "applied", "evolution": self.get_story_evolution(), "applied": history_item}

    def _reset_story_evolution_state(self):
        self.evolution_state = self._default_evolution_state()
        self._normalize_evolution_state()

    def _rebuild_story_evolution_from_finalized(self) -> dict:
        self._reset_story_evolution_state()
        return self.apply_story_evolution()

    def _ensure_planned_chapter_count(self):
        self._ensure_future_planning_window()

    def _initial_plan_count(self) -> int:
        return max(1, min(self.target_chapters or INITIAL_PLAN_CHAPTERS, INITIAL_PLAN_CHAPTERS))

    def _desired_planned_count(self) -> int:
        finalized_next = (max(self.finalized_chapters) + 1) if self.finalized_chapters else 0
        current_count = len(self.volume.chapters) if self.volume else 0
        # 只往前看 planning_window 章，不要一次性规划到 target_chapters
        desired = max(finalized_next + self.planning_window, self._initial_plan_count())
        result = min(desired, self.target_chapters, current_count + self.planning_window)
        # 当已规划超过80%目标时，强制扩展到目标章节数，确保故事能完整收尾
        if result < self.target_chapters and current_count >= int(self.target_chapters * 0.8):
            result = self.target_chapters
        logger.info(f"  _desired_planned_count: finalized_next={finalized_next}, current={current_count}, desired={desired}, target={self.target_chapters}, window={self.planning_window} → {result}")
        return result

    def _ensure_planned_to(self, chapter_index: int) -> bool:
        if not self.volume:
            return False
        if chapter_index < 0 or chapter_index >= self.target_chapters:
            raise IndexError(f"chapter_idx out of range: {chapter_index}")

        # 计算合理的规划上限：已定稿的下一章 + planning_window，不超过 target_chapters
        finalized_next = (max(self.finalized_chapters) + 1) if self.finalized_chapters else 0
        planning_ceiling = min(self.target_chapters, finalized_next + self.planning_window)
        target_count = min(planning_ceiling, max(chapter_index + 1, self._desired_planned_count()))
        logger.info(f"  _ensure_planned_to({chapter_index}): ceiling={planning_ceiling}, target={target_count}, current={len(self.volume.chapters)}")

        # 如果已存在的章节数超过规划上限（模板膨胀），裁剪掉多余的垃圾章节
        if len(self.volume.chapters) > planning_ceiling:
            trimmed = len(self.volume.chapters) - planning_ceiling
            logger.info(f"  Trimming {trimmed} excess template chapters beyond planning window ({len(self.volume.chapters)} -> {planning_ceiling})")
            self.volume.chapters = self.volume.chapters[:planning_ceiling]
            self.save_project_state()
            return True

        if len(self.volume.chapters) >= target_count:
            repaired = self._repair_repeated_future_chapter_plan()
            canonicalized = self._canonicalize_chapter_character_names()
            self._refresh_enhancement_baseline(force=True)
            if canonicalized:
                self._sync_future_chapter_outlines_to_db(0, include_generated_drafts=True)
                self.save_project_state()
            return repaired or canonicalized
        start_index = len(self.volume.chapters)
        extra = self.planner._continuation_chapters(self.outline, self.volume.chapters, target_count, self.target_chapters)
        self.volume.chapters.extend(extra)
        # P2 增量修复：扩展完后立即对所有规划章节跑一次 uniqueness 修复
        # 防止同 stage 桶坍缩导致连续 N 章标题完全相同
        self.volume.chapters = self.planner._repair_repeated_chapters(
            self.outline, self.volume.chapters, len(self.volume.chapters), self.target_chapters
        )
        self._repair_repeated_future_chapter_plan()
        self._canonicalize_chapter_character_names()
        self._refresh_enhancement_baseline(force=True)
        self._sync_future_chapter_outlines_to_db(start_index)
        self.save_project_state()
        return True

    def _ensure_future_planning_window(self) -> bool:
        if not self.volume:
            return False
        target_count = self._desired_planned_count()
        logger.info(f"  _ensure_future_planning_window: target={target_count}, current={len(self.volume.chapters)}")
        if target_count <= len(self.volume.chapters):
            repaired = self._repair_repeated_future_chapter_plan()
            endgame = self._apply_endgame_constraints()
            canonicalized = self._canonicalize_chapter_character_names()
            self._refresh_enhancement_baseline(force=True)
            if canonicalized:
                self._sync_future_chapter_outlines_to_db(0, include_generated_drafts=True)
                self.save_project_state()
            return repaired or canonicalized or endgame
        return self._ensure_planned_to(target_count - 1)

    def repair_tail_planning(self, start_chapter: int | None = None) -> dict:
        if not self.volume:
            raise ValueError("Pipeline not initialized")
        total = min(len(self.volume.chapters), max(1, self.target_chapters))
        if total <= 0:
            raise ValueError("No planned chapters")
        default_start = max(0, total - 5)
        start_idx = default_start if start_chapter is None else max(0, min(start_chapter, total - 1))
        self._repair_tail_plan(start_idx)
        self._force_sync_chapter_range_to_db(start_idx, total)
        self.save_project_state()
        return {
            "status": "repaired",
            "start_chapter": start_idx,
            "start_chapter_no": start_idx + 1,
            "end_chapter_no": total,
            "titles": [self.volume.chapters[idx].title for idx in range(start_idx, total)],
        }

    async def repair_tail_chain(self, start_chapter: int | None = None) -> dict:
        if not self.volume:
            raise ValueError("Pipeline not initialized")
        total = min(len(self.volume.chapters), max(1, self.target_chapters))
        start_idx = max(0, total - 5) if start_chapter is None else max(0, min(start_chapter, total - 1))
        self.tail_repair_locked = True
        planning = self.repair_tail_planning(start_idx)
        reset = await self.reset_chapter_range(start_idx, total, clean_memory=True)
        self.save_project_state()
        return {
            "status": "tail_chain_repaired",
            "planning": planning,
            "reset": reset,
        }

    def _repair_repeated_future_chapter_plan(self) -> bool:
        if not self.volume or len(self.volume.chapters) < 6:
            return False
        protected_indices = set(self.finalized_chapters)
        # Only check chapters that have generated content (not empty planning templates)
        generated_indices = {c.chapter_index for c in self.generated_chapters}
        checkable_indices = protected_indices | generated_indices
        seen: set[tuple[str, str]] = set()
        first_bad: int | None = None
        bad_count = 0
        generic_count = 0
        for idx, chapter in enumerate(self.volume.chapters):
            if idx in protected_indices:
                seen.add(self.planner._chapter_signature(chapter))
                continue
            # Skip chapters that haven't been generated yet (planning templates)
            if idx not in generated_indices:
                continue
            signature = self.planner._chapter_signature(chapter)
            is_generic = self.planner._is_generic_chapter(chapter)
            is_bad = signature in seen or is_generic
            if is_bad:
                bad_count += 1
                if is_generic:
                    generic_count += 1
                if first_bad is None:
                    first_bad = idx
            seen.add(signature)
        if first_bad is None or (bad_count < 3 and generic_count == 0):
            logger.info(f"  _repair_repeated_future_chapter_plan: OK (first_bad={first_bad}, bad={bad_count}, generic={generic_count})")
            return False

        # 裁剪策略：砍掉所有模板垃圾章节，只保留到第一个坏章节之前
        # 不再用模板重新生成（模板只会产生同样的垃圾）
        trim_count = len(self.volume.chapters) - first_bad
        logger.info(f"  Repair: trimming {trim_count} template chapters (first bad at index {first_bad}, {bad_count} bad, {generic_count} generic)")
        self.volume.chapters = self.volume.chapters[:first_bad]
        self._refresh_enhancement_baseline(force=True)
        self.save_project_state()
        return True

    def _apply_endgame_constraints(self) -> bool:
        if not self.volume or not self.target_chapters:
            return False
        if self.tail_repair_locked:
            return False
        if len(self.volume.chapters) < self.target_chapters:
            return False
        total = min(self.target_chapters, len(self.volume.chapters))
        if total <= 0:
            return False
        protected_indices = set(self.finalized_chapters)
        start_idx = max(0, total - min(4, total))
        anchors = self.volume.chapters[:start_idx]
        rebuilt = self.planner._continuation_chapters(self.outline, anchors, total, self.target_chapters)
        changed = False
        for idx in range(start_idx, total):
            if idx in protected_indices:
                continue
            replacement = rebuilt[idx - start_idx]
            current = self.volume.chapters[idx]
            if current.model_dump() != replacement.model_dump():
                self.volume.chapters[idx] = replacement
                changed = True
        if changed:
            self._refresh_enhancement_baseline(force=True)
            self._sync_future_chapter_outlines_to_db(start_idx, include_generated_drafts=True)
            self.save_project_state()
        return changed

    def _needs_tail_replan(self, chapter: ChapterOutline) -> bool:
        text = " ".join([(chapter.title or ""), (chapter.goal or ""), (chapter.conflict or "")])
        markers = ["收束战后影响", "余韵收束", "下一部或番外的可能性", "战后清点、告别、重建和远方新信号形成尾声"]
        return sum(1 for marker in markers if marker in text) >= 2

    def repair_tail_drifted_plan(self) -> bool:
        if not self.volume or len(self.volume.chapters) < 8:
            return False
        if self.tail_repair_locked:
            return False
        protected_indices = set(self.finalized_chapters)
        first_bad = None
        consecutive_bad = 0
        for idx, chapter in enumerate(self.volume.chapters):
            if idx in protected_indices:
                consecutive_bad = 0
                continue
            if self._needs_tail_replan(chapter):
                consecutive_bad += 1
                if first_bad is None:
                    first_bad = idx
            else:
                consecutive_bad = 0
            if consecutive_bad >= 3:
                break
        if first_bad is None or consecutive_bad < 3:
            return False
        anchors = self.volume.chapters[:first_bad]
        repaired_tail = self.planner._continuation_chapters(self.outline, anchors, len(self.volume.chapters), self.target_chapters)
        for offset, replacement in enumerate(repaired_tail, start=first_bad):
            if offset in protected_indices:
                continue
            self.volume.chapters[offset] = replacement
        self._refresh_enhancement_baseline(force=True)
        self._sync_future_chapter_outlines_to_db(first_bad, include_generated_drafts=True)
        self.save_project_state()
        tail_changed = True
        return self._apply_endgame_constraints() or tail_changed

    def _derive_project_title(self, outline: str) -> str:
        if not outline:
            return "未命名项目"
        text = outline.strip().replace("\n", " ")
        if ("电子生命" in text or "机器生命" in text or "智慧意识" in text) and ("2355" in text or "宇宙" in text):
            return "硅基纪元"
        if "系统" in text and ("都市" in text or "逆袭" in text):
            return "系统逆袭"
        if "修仙" in text or "飞升" in text:
            return "修仙长路"
        if "废柴" in text or "崛起" in text:
            return "废柴崛起"
        for sep in ["。", "！", "？", ".", "!", "?"]:
            if sep in text:
                text = text.split(sep)[0]
                break
        text = text[:12].strip()
        return text or "未命名项目"

    async def initialize(self, request: GenerationRequest):
        import uuid
        if not self.session_id:
            self.session_id = str(uuid.uuid4())[:8]

        logger.info(f"Initializing pipeline for: {request.outline[:100]}")
        logger.info(f"Session ID: {self.session_id}")
        self.outline = request.outline
        self.title = self._derive_project_title(request.outline)
        self.genre = request.genre
        self.style = request.style
        self.target_chapters = request.target_chapters
        self.words_per_chapter = request.words_per_chapter

        plan_count = self._initial_plan_count()
        logger.info(f"Step 1: Building unified project blueprint ({plan_count}/{request.target_chapters})...")
        blueprint_ok = await self._build_project_blueprint(request, plan_count)
        if not blueprint_ok:
            logger.info("Step 1a: Building world...")
            self.world = await self.world_builder.build(request.outline, request.genre)
            self.memory.update_world(self.world)

            logger.info("Step 1b: Creating characters...")
            world_summary = self.memory.structured.get_world_text()
            self.characters = await self.character_engine.create_characters(request.outline, world_summary, request.genre)

            logger.info(f"Step 1c: Planning first stage chapters ({plan_count}/{request.target_chapters})...")
            char_names = [c.name for c in self.characters]
            self.volume = await self.planner.plan(
                request.outline,
                request.genre,
                request.target_chapters,
                plan_chapters=plan_count,
                character_names=char_names,
            )
            self._canonicalize_chapter_character_names()

            logger.info("Step 1d: Preparing first-stage scenes...")
            if settings.ENABLE_LLM_SCENE_SPLIT:
                for i in range(len(self.volume.chapters)):
                    self.volume.chapters[i] = await self.planner.split_into_scenes(self.volume.chapters[i], char_names)
            else:
                self._ensure_chapter_scenes_integrity()
        self._canonicalize_chapter_character_names()
        self._refresh_enhancement_baseline(force=True)
        self.memory.update_world(self.world)
        for char in self.characters:
            self.memory.update_character(char)

        # 不缩减 target_chapters：初始 LLM 规划可能只返回部分章节，
        # 保留原始目标让 _ensure_planned_to() 增量扩展到完整章节数
        actual_planned = len(self.volume.chapters) if self.volume else 0
        if actual_planned > 0 and actual_planned < self.target_chapters:
            logger.info(f"  Initial plan has {actual_planned} chapters, target is {self.target_chapters}. Will expand incrementally.")

        logger.info("Step 2: Saving to database...")
        try:
            from core.database import SessionLocal
            from models.db_service import ProjectService, CharacterService, WorldService, ChapterService, SceneService
            
            with SessionLocal() as db:
                ps = ProjectService(db)
                project = ps.create_project(
                    outline=request.outline,
                    genre=request.genre,
                    style=request.style,
                    target_chapters=request.target_chapters,
                    words_per_chapter=request.words_per_chapter
                )
                old_id = self.session_id
                self.session_id = project.id
                
                ws = WorldService(db)
                ws.create_world(project.id, self.world)
                
                cs = CharacterService(db)
                for char in self.characters:
                    cs.create_character(project.id, char)
                
                chs = ChapterService(db)
                ss = SceneService(db)
                for idx, ch_outline in enumerate(self.volume.chapters):
                    chapter = chs.create_chapter(
                        project.id, idx, ch_outline.title,
                        ch_outline.goal, ch_outline.conflict
                    )
                    for s_idx, scene in enumerate(ch_outline.scenes):
                        ss.create_scene(
                            chapter.id, s_idx, scene.description,
                            scene.characters, scene.location, scene.mood, scene.target_words
                        )
                
                if old_id != self.session_id:
                    import shutil
                    old_dir = os.path.join("data", "sessions", old_id)
                    new_dir = os.path.join("data", "sessions", self.session_id)
                    if os.path.exists(old_dir) and old_id != self.session_id:
                        shutil.move(old_dir, new_dir)
                        self.memory = MemorySystem(session_id=self.session_id)
                        self.rag = RAGEngine(self.memory.long_term)
                        self.memory.update_world(self.world)
                        for char in self.characters:
                            self.memory.update_character(char)
                self._require_database_project()
            logger.info(f"Project saved to database: {self.session_id}")
        except Exception as e:
            logger.error(f"Failed to save to database: {e}")
            raise

        logger.info(f"Pipeline initialized: {len(self.volume.chapters)} chapters planned, {len(self.characters)} characters created")
        self.approved = False
        self.save_project_state()
        return {
            "task_id": self.session_id,
            "title": self.title,
            "outline": self.outline,
            "genre": self.genre,
            "style": self.style,
            "target_chapters": self.target_chapters,
            "planned_chapters": len(self.volume.chapters) if self.volume else 0,
            "planning_window": self.planning_window,
            "words_per_chapter": self.words_per_chapter,
            "world": self.world.model_dump(),
            "characters": [c.model_dump() for c in self.characters],
            "chapters": [
                ch.model_dump()
                for ch in self.volume.chapters
            ],
            "approved": self.approved,
        }

    def get_project_data(self) -> dict:
        repaired = self._repair_repeated_future_chapter_plan()
        canonicalized = self._canonicalize_chapter_character_names()
        if repaired or canonicalized:
            self._sync_future_chapter_outlines_to_db(0, include_generated_drafts=True)
            self.save_project_state()
        return {
            "outline": self.outline,
            "title": self.title,
            "genre": self.genre,
            "style": self.style,
            "target_chapters": self.target_chapters,
            "planned_chapters": len(self.volume.chapters) if self.volume else 0,
            "planning_window": self.planning_window,
            "words_per_chapter": self.words_per_chapter,
            "world": self.world.model_dump() if self.world else {},
            "characters": [c.model_dump() for c in self.characters],
            "chapters": [c.model_dump() for c in self.volume.chapters] if self.volume else [],
            "generated_chapters": [c.model_dump() for c in self.generated_chapters],
            "approved": self.approved,
            "character_state_manager": self.state_manager.to_dict(),
            "style_fingerprint": self.style_fingerprint,
        }

    def update_project_data(self, outline: str, genre: str, style: str, target_chapters: int, words_per_chapter: int, world: dict, characters: list[dict], chapters: list[dict]):
        previous_outline = self.outline
        previous_title = (self.title or "").strip()
        incoming_world = WorldSetting(**(world or {}))
        incoming_characters = [CharacterSheet(**c) for c in (characters or [])]
        incoming_volume = VolumeOutline(volume=self.volume.volume if self.volume else "第一卷", chapters=[ChapterOutline(**c) for c in (chapters or [])])

        planning_changed = False
        if self.world and incoming_world.model_dump() != self.world.model_dump():
            planning_changed = True
        if [c.model_dump() for c in incoming_characters] != [c.model_dump() for c in self.characters]:
            planning_changed = True
        if self.volume and incoming_volume.model_dump() != self.volume.model_dump():
            planning_changed = True

        if self.generated_chapters and planning_changed:
            logger.warning(f"Updating project planning after {len(self.generated_chapters)} chapters generated - clearing generated chapters")
            self.generated_chapters = []
            self.finalized_chapters = []
            self.pending_chapter_updates = {}
        self.outline = outline
        auto_previous_title = self._derive_project_title(previous_outline)
        if previous_title and previous_title != auto_previous_title:
            self.title = previous_title
        else:
            self.title = self._derive_project_title(outline)
        self.genre = genre
        self.style = style
        self.target_chapters = target_chapters
        self.words_per_chapter = words_per_chapter
        self.world = incoming_world
        self.characters = incoming_characters
        self.volume = incoming_volume
        self._canonicalize_chapter_character_names()
        self._refresh_enhancement_baseline(force=True)
        self.memory.update_world(self.world)
        self.state_manager = CharacterStateManager()
        for char in self.characters:
            self.memory.update_character(char)
            self.state_manager.register_character(char.name, initial_power=1)
        self.approved = True
        self.save_project_state()
        self._sync_project_to_db()
        return self.get_project_data()

    def update_project_metadata(self, title: str, outline: str, genre: str, style: str, target_chapters: int, words_per_chapter: int):
        self.outline = outline
        self.title = title.strip() if title and title.strip() else self._derive_project_title(outline)
        self.genre = genre
        self.style = style
        self.target_chapters = target_chapters
        self.words_per_chapter = words_per_chapter
        self._refresh_enhancement_baseline(force=True)
        self.approved = False
        self.save_project_state()
        self._sync_project_to_db()
        return self.get_project_data()

    def import_existing_novel(self, text: str):
        import re
        if not text.strip():
            raise ValueError("导入内容为空")
        parts = re.split(r'(?=第[0-9一二三四五六七八九十百千]+章)', text)
        chapters = []
        for idx, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            lines = part.splitlines()
            title = lines[0].strip()[:60] if lines else f"第{idx + 1}章"
            body = "\n".join(lines[1:]).strip() if len(lines) > 1 else part
            chapters.append(ChapterOutline(
                title=title,
                goal="导入章节，待续写",
                conflict="待分析",
                scenes=[SceneOutline(description=body[:120] or title, target_words=self.words_per_chapter)],
            ))
        if not chapters:
            chapters = [ChapterOutline(title="第1章", goal="导入章节，待续写", conflict="待分析", scenes=[SceneOutline(description=text[:120], target_words=self.words_per_chapter)])]
        self.volume = VolumeOutline(volume=self.volume.volume if self.volume else "第一卷", chapters=chapters)
        self.target_chapters = len(chapters)
        self._refresh_enhancement_baseline(force=True)
        self.approved = False
        self.generated_chapters = []
        self.finalized_chapters = []
        self.pending_chapter_updates = {}
        self._sync_project_to_db()
        self.save_project_state()
        return [c.model_dump() for c in self.volume.chapters]

    async def regenerate_world(self, prompt_hint: str = "") -> dict:
        combined_outline = self.outline if not prompt_hint else f"{self.outline}\n\n补充要求：{prompt_hint}"
        self.world = await self.world_builder.build(combined_outline, self.genre)
        self.memory.update_world(self.world)

        # 世界观变更后，重置一致性检查门控（旧世界观规则不再适用）
        self.consistency_gate = ConsistencyGate(self.consistency_checker)
        self.consistency_gate_stats = self._default_consistency_gate_stats()

        self._refresh_enhancement_baseline(force=True)
        self.approved = False
        self._sync_project_to_db()
        self.save_project_state()
        return self.world.model_dump()

    async def regenerate_characters(self, prompt_hint: str = "") -> list[dict]:
        world_summary = self.memory.structured.get_world_text()
        combined_outline = self.outline if not prompt_hint else f"{self.outline}\n\n角色补充要求：{prompt_hint}"
        self.characters = await self.character_engine.create_characters(combined_outline, world_summary, self.genre)

        # 重置角色相关的内部状态，避免旧角色数据残留
        self.state_manager = CharacterStateManager()
        for char in self.characters:
            self.state_manager.register_character(char.name, initial_power=1)

        # 清理旧的角色关系图谱并从新角色重建
        self.memory.relationship_graph.clear()

        # 重置一致性检查门控（旧角色的死亡/位置/战力追踪）
        self.consistency_gate = ConsistencyGate(self.consistency_checker)
        self.consistency_gate_stats = self._default_consistency_gate_stats()

        # 清理结构化记忆中的旧角色数据并写入新角色
        self.memory.structured.characters = {}
        for char in self.characters:
            self.memory.update_character(char)

        # 从新角色关系描述同步到关系图谱
        self.memory.sync_relationships_from_characters(chapter=0)

        self._refresh_enhancement_baseline(force=True)
        self.approved = False
        self._sync_project_to_db()
        self.save_project_state()
        return [c.model_dump() for c in self.characters]

    async def regenerate_chapter_plan(self, prompt_hint: str = "") -> list[dict]:
        # 清理DB中所有章节（不仅是volume中的，还包括DB中多出的旧规划）
        try:
            from core.database import SessionLocal
            from models.db_service import ChapterService, SceneService
            with SessionLocal() as db:
                chs = ChapterService(db)
                ss = SceneService(db)
                existing = chs.get_project_chapters(self.session_id)
                for ch in existing:
                    ss.delete_chapter_scenes(ch.id)
                    chs.delete_chapter(ch.id)
        except Exception as e:
            logger.warning(f"Failed to clear DB chapters: {e}")

        old_total = len(self.volume.chapters) if self.volume else 0
        if old_total > 0:
            self._remove_output_artifacts(0, old_total)
        self._clear_all_generated_story_state()

        # 重置角色状态机（新的章节规划可能改变角色定位）
        self.state_manager = CharacterStateManager()
        for char in self.characters:
            self.state_manager.register_character(char.name, initial_power=1)

        target_chapters = self.target_chapters or (len(self.volume.chapters) if self.volume else 10)
        generated_next = (max([chapter.chapter_index for chapter in self.generated_chapters]) + 1) if self.generated_chapters else 0
        finalized_window = (max(self.finalized_chapters) + self.planning_window + 1) if self.finalized_chapters else 0
        plan_count = min(target_chapters, max(self._initial_plan_count(), generated_next, finalized_window))
        combined_outline = self.outline if not prompt_hint else f"{self.outline}\n\n章节规划补充要求：{prompt_hint}"
        char_names = [c.name for c in self.characters]
        self.volume = await self.planner.plan(
            combined_outline,
            self.genre,
            target_chapters,
            plan_chapters=plan_count,
            character_names=char_names,
        )
        self._canonicalize_chapter_character_names()
        if settings.ENABLE_LLM_SCENE_SPLIT:
            for i in range(len(self.volume.chapters)):
                self.volume.chapters[i] = await self.planner.split_into_scenes(self.volume.chapters[i], char_names)
        else:
            self._ensure_chapter_scenes_integrity()
        self._canonicalize_chapter_character_names()
        self._refresh_enhancement_baseline(force=True)
        self.approved = False
        self._sync_project_to_db()
        self.save_project_state()
        return [c.model_dump() for c in self.volume.chapters]

    def _is_last_chapter(self, chapter_idx: int) -> bool:
        """P2 程序级修复：判断当前章是否为最后一章。

        用于：
        - 触发 _post_generation_recovery 的 95% 字数阈值
        - 触发 OutputValidator 的末章字数下限
        """
        return chapter_idx >= self.target_chapters - 1

    async def _final_quality_gate(
        self,
        chapter_idx: int,
        title: str,
        content: str,
        *,
        target_words: int,
        previous_ending: str,
        previous_titles: list[str] | None = None,
    ) -> None:
        """P2 程序级修复：最终质量门——在产物即将落盘前做只读检查。

        检查项：
        - 标题脏词（复用 PlannerAgent.DIRTY_TITLE_PATTERNS）
        - 标题唯一性（与历史章节对比：精确重复 / 前缀坍缩）—— P2 增量修复
        - 字数下限（普通章 85%，末章 95%）
        - 截断检测（复用 WriterAgent._is_truncated_ending）
        - AI 痕迹短语 + 密度
        - 跨章相似度（复用 WriterAgent._is_too_similar）

        失败时抛 OutputValidationError，由 generate_chapter 的重试循环捕获。
        当 STRICT_QUALITY_GATES=False 时只 WARN 不抛。
        """
        if not settings.STRICT_QUALITY_GATES:
            logger.debug(f"Quality gate disabled (chapter {chapter_idx}); skipping")
            return
        from core.validators import OutputValidator
        validator = OutputValidator(
            ai_trace_phrases=settings.AI_TRACE_PHRASES,
            ai_trace_max=settings.AI_TRACE_MAX_PER_CHAPTER,
            ai_trace_density_limit=settings.AI_TRACE_DENSITY_LIMIT,
            word_count_lower_pct=settings.WC_LOWER_TOLERANCE,
            word_count_lower_pct_last=settings.WC_LOWER_TOLERANCE_LAST,
            word_count_absolute_min=settings.WORD_COUNT_ABSOLUTE_MIN,
        )
        is_last = self._is_last_chapter(chapter_idx)
        validator.validate_all(
            title=title,
            content=content,
            target_words=target_words,
            is_last_chapter=is_last,
            previous_ending=previous_ending,
            previous_titles=previous_titles,
        )

    async def generate_chapter(self, volume_idx: int, chapter_idx: int, multi_version: bool = True, guidance: str = "", target_words: int | None = None, auto_finalize: bool = True) -> ChapterDraft:
        if not self.volume:
            raise ValueError("Pipeline is not initialized. Call initialize() before generate_chapter().")
        if not self.approved:
            raise ValueError("Project settings are not approved. Save and confirm world, characters, and chapter plan first.")
        if chapter_idx < 0 or chapter_idx >= self.target_chapters:
            raise IndexError(f"chapter_idx out of range: {chapter_idx}")
        # 顺序生成检查：第N章的前N-1章必须已生成（保证上下文连续性）
        if chapter_idx > 0:
            generated_indices = {c.chapter_index for c in self.generated_chapters}
            missing = [i for i in range(chapter_idx) if i not in generated_indices]
            if missing:
                missing_str = ", ".join(str(i+1) for i in missing)
                raise ValueError(f"顺序生成：第{chapter_idx+1}章的前置章节尚未生成（缺第{missing_str}章），请先按顺序生成前面的章节。")
        self._refresh_enhancement_baseline()
        self._ensure_planned_to(chapter_idx)
        self.normalize_chapter_title_style()
        chapter_outline = self.volume.chapters[chapter_idx]
        chapter_intent = self._build_chapter_intent(chapter_idx, chapter_outline)
        chapter_outline.goal = self._sanitize_chapter_outline_text(chapter_outline.goal, chapter_idx=chapter_idx)
        chapter_outline.conflict = self._sanitize_chapter_outline_text(chapter_outline.conflict, chapter_idx=chapter_idx)
        if chapter_outline.scenes:
            for scene in chapter_outline.scenes:
                scene.description = self._sanitize_chapter_outline_text(scene.description, chapter_idx=chapter_idx)
        logger.info(f"Generating Chapter {chapter_idx+1}: {chapter_outline.title}")

        char_status = self.memory.structured.get_character_profiles_text()
        context = self.memory.retrieve_context()
        control_context = self._get_story_control_context()
        state_context = self._get_character_state_context()
        if control_context:
            context = context + "\n\n" + control_context if context else control_context
        if state_context:
            context = context + "\n\n" + state_context if context else state_context
        context = self._enrich_context(context, chapter_idx)

        logger.info("  Step 1: Preparing plot direction (derived, no LLM)...")
        # 从章节大纲推导剧情推进方向，不再使用独立LLM调用
        unresolved_foreshadowing = self.memory.structured.get_unresolved_foreshadowing()
        foreshadowing_hints = self._dedupe_text_list([self._foreshadow_prompt_text(f) for f in unresolved_foreshadowing[:3]]) if unresolved_foreshadowing else []
        new_foreshadowing = [
            item for item in [
                self._normalize_foreshadow_payload(candidate, chapter_idx=chapter_idx)
                for candidate in self._derive_new_foreshadow_candidates(chapter_idx, chapter_outline)[:2]
            ] if item
        ]
        recent_summary = self.memory.short_term.get_recent_summaries()
        main_arc = f"当前进度：第{chapter_idx+1}章，已生成{len(self.generated_chapters)}章。\n核心设定：{self.outline[:200]}"
        plot_plan = {
            "main_progress": chapter_outline.goal,
            "side_progress": [arc.get("description", "") for arc in self.memory.structured.plot_arcs[:2]],
            "new_conflicts": [chapter_outline.conflict] if chapter_outline.conflict else [],
            "foreshadowing": new_foreshadowing,
            "foreshadowing_hints": foreshadowing_hints,
            "resolution": "保留部分悬念",
            "hook": "",
            "pacing": "normal",
        }

        # 增强系统：写前注入
        enhancement_pre = self.enhancement.pre_generation(
            chapter_index=chapter_idx + 1,
            total_chapters=self.target_chapters,
            task_id=self.session_id,
            target_words=target_words or self.words_per_chapter,
            pacing_label=plot_plan.get("pacing", "normal") if isinstance(plot_plan, dict) else "normal",
        )
        enhancement_context = enhancement_pre.get("combined_instruction", "")

        plot_direction = self._sanitize_chapter_outline_text(plot_plan.get("main_progress") or chapter_outline.goal, chapter_idx=chapter_idx)
        chapter_contract = self._chapter_contract_text(chapter_idx, chapter_outline, plot_direction)
        chapter_contract = chapter_contract + "\n" + self._format_chapter_intent(chapter_intent)
        style_instruction = self._style_fingerprint_instruction()
        if style_instruction:
            chapter_contract = chapter_contract + "\n" + style_instruction
        self._register_open_intents(chapter_idx, chapter_intent)
        if plot_plan.get("new_conflicts"):
            self.memory.structured.add_plot_arc({
                "arc_type": "side",
                "description": plot_plan["new_conflicts"][0],
                "progress": 0.0,
            })

        self.memory.add_scene_context(chapter_contract)
        if guidance:
            self.memory.add_scene_context(f"用户本章指导：{guidance}")
        if style_instruction:
            self.memory.add_scene_context(style_instruction)

        logger.info("  Step 1.5: Pre-generation consistency gate...")
        if not settings.FAST_TEST_MODE:
            self._normalize_consistency_gate_stats()
            self.consistency_gate_stats["pre_generation_calls"] = int(self.consistency_gate_stats.get("pre_generation_calls", 0) or 0) + 1
            try:
                gate_warnings = self.consistency_gate.pre_generation_block(
                    chapter_idx, self.characters, plot_direction
                )
                for warning in gate_warnings:
                    logger.warning(f"  Consistency-gate warning: {warning}")
                    self.memory.add_scene_context(f"一致性提示：{warning}")
                self.consistency_gate_stats["pre_generation_warnings"] = int(self.consistency_gate_stats.get("pre_generation_warnings", 0) or 0) + len(gate_warnings)
            except ConsistencyBlockError as e:
                logger.error(f"  HARD BLOCK before generation: {e}")
                self.consistency_gate_stats["pre_generation_blocks"] = int(self.consistency_gate_stats.get("pre_generation_blocks", 0) or 0) + 1
                self.consistency_gate_stats["last_issues"] = (self.consistency_gate_stats.get("last_issues", []) or []) + list(e.issues or [])
                self.memory.clear_scene_context()
                raise

            state_blocks = self.state_manager.pre_generation_validate(chapter_idx, plot_direction)
            state_warnings = [b for b in state_blocks if b.startswith("WARN:")]
            for warning in state_warnings:
                logger.warning(f"  State-machine warning: {warning.replace('WARN: ', '')}")
                self.memory.add_scene_context(f"状态机提示：{warning.replace('WARN: ', '')}")
            self.consistency_gate_stats["state_machine_warnings"] = int(self.consistency_gate_stats.get("state_machine_warnings", 0) or 0) + len(state_warnings)
            hard_state_blocks = [b for b in state_blocks if b.startswith("HARD:")]
            if hard_state_blocks:
                # 检查是否是合理提及（回忆、幻境、传说等）
                reasonable_keywords = ["回忆", "幻境", "梦境", "传说", "提及", "听说", "记载", "历史"]
                truly_hard = []
                for block in hard_state_blocks:
                    block_text = block.replace("HARD: ", "")
                    is_reasonable = any(kw in block_text for kw in reasonable_keywords)
                    if is_reasonable:
                        logger.warning(f"  State-machine HARD block overridden (reasonable mention): {block_text}")
                        self.memory.add_scene_context(f"状态机提示：{block_text}")
                    else:
                        truly_hard.append(block)
                if truly_hard:
                    from agents.consistency_checker import ConsistencyBlockError as CBE
                    self.consistency_gate_stats["state_machine_blocks"] = int(self.consistency_gate_stats.get("state_machine_blocks", 0) or 0) + len(truly_hard)
                    self.consistency_gate_stats["last_issues"] = (self.consistency_gate_stats.get("last_issues", []) or []) + [b.replace("HARD: ", "") for b in truly_hard]
                    self.memory.clear_scene_context()
                    raise CBE(
                        issues=[b.replace("HARD: ", "") for b in truly_hard],
                        category="state_machine"
                    )

        logger.info("  Step 2: Writing scenes...")
        if not chapter_outline.scenes:
            if settings.ENABLE_LLM_SCENE_SPLIT:
                chapter_outline = await self.planner.split_into_scenes(chapter_outline, [c.name for c in self.characters])
            else:
                self._ensure_chapter_scenes_integrity()
                chapter_outline = self.volume.chapters[chapter_idx]
        elif self._chapter_has_placeholder_scenes(chapter_outline):
            logger.warning("  Placeholder scenes detected, rebuilding scene breakdown before writing")
            if settings.ENABLE_LLM_SCENE_SPLIT:
                chapter_outline = await self.planner.split_into_scenes(chapter_outline, [c.name for c in self.characters])
            else:
                chapter_outline.scenes = []
                self._ensure_chapter_scenes_integrity()
                chapter_outline = self.volume.chapters[chapter_idx]
        if target_words and target_words > 0:
            self._ensure_chapter_scenes_integrity()
            scene_words_list = self._allocate_weighted_scene_words(target_words, chapter_outline.scenes)
            if len(scene_words_list) < len(chapter_outline.scenes):
                last_valid_idx = len(scene_words_list) - 1
                for j in range(len(scene_words_list), len(chapter_outline.scenes)):
                    merge_desc = chapter_outline.scenes[j].description
                    chapter_outline.scenes[last_valid_idx].description += f"\n（合并场景：{merge_desc}）"
                chapter_outline.scenes = chapter_outline.scenes[:len(scene_words_list)]
                logger.warning(f"Merged scenes: {len(chapter_outline.scenes) + (len(chapter_outline.scenes) - len(scene_words_list))} -> {len(scene_words_list)}")
            for i, scene in enumerate(chapter_outline.scenes):
                scene.target_words = scene_words_list[i]
        if enhancement_context:
            context = context + "\n\n" + enhancement_context if context else enhancement_context

        previous_ending = self._build_chapter_bridge(chapter_idx)

        if multi_version and settings.MULTI_VERSION_COUNT > 1:
            versions = []
            for v in range(settings.MULTI_VERSION_COUNT):
                chapter_text = await self.writer.generate_chapter(
                    chapter_outline.scenes, plot_direction, char_status, context, chapter_contract=chapter_contract, previous_ending=previous_ending,
                    is_last_chapter=self._is_last_chapter(chapter_idx),  # P2 程序级修复
                )
                versions.append(chapter_text)
            best_idx = await self.critic.select_best_version(versions)
            chapter_text = versions[best_idx]
            version_num = best_idx + 1
        else:
            chapter_text = await self.writer.generate_chapter(
                chapter_outline.scenes, plot_direction, char_status, context, chapter_contract=chapter_contract, previous_ending=previous_ending,
                is_last_chapter=self._is_last_chapter(chapter_idx),  # P2 程序级修复
            )
            version_num = 1

        # 检测特殊上下文（回忆/梦境/幻境/传说）→ 传递给增强系统用于白名单
        _special_context_keywords = {
            "dream": ["梦境", "梦中", "梦里", "梦到"],
            "flashback": ["回忆", "回想", "想起", "记得", "闪回", "往事", "从前"],
            "illusion": ["幻境", "幻象", "幻觉", "幻想", "心魔"],
            "legend": ["传说", "传说中", "据说", "上古", "远古", "神话"],
            "memory": ["前世", "记忆", "印象"],
        }
        _all_special_context_text = f"{chapter_contract} {plot_direction or ''} {guidance or ''}"
        context_tags = [
            tag for tag, kws in _special_context_keywords.items()
            if any(kw in _all_special_context_text for kw in kws)
        ]

        # 增强系统：默认只做写后检查；需要深度修复时再打开重试开关。
        max_enhancement_retries = 2 if settings.ENABLE_GENERATION_RETRY else 0
        for retry_attempt in range(max_enhancement_retries + 1):
            # 重试时重置事件冷却状态，避免第一次检查的状态污染第二次
            if retry_attempt > 0:
                from agents.enhancement.models import CooldownState
                self.enhancement.event_matrix.cooldown_state = CooldownState()
            enhancement_post = self.enhancement.post_generation(
                chapter_text=chapter_text,
                chapter_index=chapter_idx + 1,
                total_chapters=self.target_chapters,
                context_tags=context_tags,
                previous_ending=previous_ending,
            )
            if enhancement_post.get("should_retry") and retry_attempt < max_enhancement_retries:
                retry_reason = enhancement_post.get("retry_reason", "未知原因")
                logger.warning(f"增强系统拦截 (attempt {retry_attempt+1}/{max_enhancement_retries}): {retry_reason}")
                # 将拦截原因注入 context 后重新生成
                retry_instruction = f"\n\n【增强系统反馈】{retry_reason}\n请避免上述问题，重新生成本章。"
                chapter_contract = chapter_contract + retry_instruction
                context = context + retry_instruction if context else retry_instruction
                chapter_text = await self.writer.generate_chapter(
                    chapter_outline.scenes, plot_direction, char_status, context, chapter_contract=chapter_contract, previous_ending=previous_ending,
                    is_last_chapter=self._is_last_chapter(chapter_idx),  # P2 程序级修复
                )
                version_num = 1
            else:
                if enhancement_post.get("should_retry"):
                    logger.warning(f"增强系统拦截: {enhancement_post.get('retry_reason')} (已达最大重试次数，使用当前版本)")
                break

        # P2 程序级修复：实际执行 AI 痕迹稀释（之前是孤立代码，定义但从不调用）
        # 在 enhancement 后做一次密度检查；超阈值则用 LLM 改写密集段落
        if enhancement_post is not None and not enhancement_post.get("should_retry", True):
            try:
                density = enhancement_post.get("ai_trace_density", 0.0)
                if density > settings.AI_TRACE_DENSITY_LIMIT:
                    logger.info(f"  AI trace density {density:.2f}/k chars > {settings.AI_TRACE_DENSITY_LIMIT}, running dilution")
                    diluted_text = await self.enhancement.dilute_ai_traces(chapter_text, chapter_idx + 1)
                    if diluted_text and diluted_text != chapter_text:
                        logger.info(f"  AI trace dilution applied to chapter {chapter_idx+1}")
                        chapter_text = diluted_text
            except Exception as e:
                logger.warning(f"  AI trace dilution failed: {e}")

        logger.info("  Step 3: Chapter audit (single-pass)...")
        audit = self._run_chapter_audit(chapter_idx, chapter_outline, chapter_text, context_tags, enhancement_post=enhancement_post)
        if settings.ENABLE_GENERATION_REWRITE and audit["should_rewrite"]:
            logger.info("  Unified audit requested rewrite: %s", "；".join(audit["issues"][:3]) or "综合质量问题")
            pre_rewrite_words = count_chinese_words(chapter_text)
            try:
                chapter_text = await self.style_rewriter.rewrite(chapter_text)
                post_rewrite_words = count_chinese_words(chapter_text)
                rewrite_deviation = compute_deviation(post_rewrite_words, pre_rewrite_words)
                if rewrite_deviation > settings.WC_TOLERANCE_PCT:
                    logger.warning(f"  Style rewrite changed word count significantly: {pre_rewrite_words} -> {post_rewrite_words} (deviation {rewrite_deviation:.1f}%), Step 4.5 will correct")
            except Exception as e:
                logger.warning(f"  Style rewriting failed, using raw chapter text: {e}")
        elif audit["ai_report"].get("ai_score", 1.0) >= 0.85:
            logger.info(f"  Style rewriting skipped: AI score {audit['ai_report'].get('ai_score', 1.0):.2f} >= 0.85")

        chapter_text = self._dedupe_adjacent_paragraphs(chapter_text)
        chapter_text = self._strip_generated_heading(chapter_text, chapter_outline.title)
        red_flags = self._detect_generation_red_flags(chapter_idx, chapter_outline, chapter_text)
        if red_flags:
            logger.warning("  Generation red flags detected: %s", "；".join(red_flags))
            retry_instruction = "\n\n【硬性修正】" + "；".join(red_flags) + "。请重新生成完整正文，禁止输出占位稿、重复段落、剧情摘要或场景标签。"
            chapter_contract = chapter_contract + retry_instruction
            context = context + retry_instruction if context else retry_instruction
            chapter_text = await self.writer.generate_chapter(
                chapter_outline.scenes, plot_direction, char_status, context, chapter_contract=chapter_contract, previous_ending=previous_ending,
                is_last_chapter=self._is_last_chapter(chapter_idx),  # P2 程序级修复
            )
            chapter_text = self._dedupe_adjacent_paragraphs(chapter_text)
            chapter_text = self._strip_generated_heading(chapter_text, chapter_outline.title)
            red_flags = self._detect_generation_red_flags(chapter_idx, chapter_outline, chapter_text)
            if red_flags:
                raise ValueError("章节生成失败：" + "；".join(red_flags))
        if chapter_idx >= self.target_chapters - 1:
            closure_gaps = self._story_closure_gaps(chapter_text)
            if closure_gaps:
                raise ConsistencyBlockError(
                    ["终章闭环不完整：" + "；".join(closure_gaps[:6])],
                    category="story_closure",
                )
        # 章节对齐检查：仅警告，不阻断（避免LLM生成的正常章节标题被误判）
        try:
            self._validate_chapter_alignment(chapter_idx, chapter_outline, chapter_text)
        except ConsistencyBlockError as e:
            logger.warning(f"  Chapter alignment warning (non-fatal): {e}")

        logger.info("  Step 4: Lightweight consistency (rule-based, no LLM)...")
        audit = self._run_chapter_audit(chapter_idx, chapter_outline, chapter_text, context_tags, enhancement_post=enhancement_post)
        rule_result = audit["rule_result"]
        consistency_score = audit["consistency_score"]
        # Record quality metrics for enhancement panel display
        try:
            ai_score = audit.get("ai_report", {}).get("ai_score", 1.0)
            self.enhancement.record_quality_metrics(
                chapter_index=chapter_idx,
                consistency_score=consistency_score,
                ai_score=ai_score,
                issues=audit.get("issues", []),
                shortfalls=[s for s in audit.get("show_tell_hits", [])[:3]],
            )
        except Exception as e:
            logger.debug(f"Quality metrics recording skipped: {e}")
        report = ConsistencyReport(
            is_consistent=rule_result.get("is_valid", True),
            issues=audit["issues"],
            score=consistency_score,
        )
        tail_audit = audit["tail_audit"]
        if not tail_audit["ok"]:
            logger.warning(f"  Tail quality flags for chapter {chapter_idx + 1}: {tail_audit['flags']}")
            report.issues.extend([f"尾部质量风险：{flag}" for flag in tail_audit["flags"][:4]])
            report.score = min(report.score, 0.72)
        if not rule_result.get("is_valid", True):
            logger.warning(f"  Rule-based consistency issues: {rule_result.get('issues')}")
        outline_keywords = set(self._extract_keywords(f"{chapter_outline.title} {chapter_outline.goal} {chapter_outline.conflict}")[:12])
        chapter_keywords = set(self._extract_keywords(chapter_text))
        if outline_keywords:
            matched_keywords = outline_keywords.intersection(chapter_keywords)
            self.enhancement.progress.update_anchor_completion(chapter_idx, completed=len(matched_keywords) >= 1)

        logger.info("  Step 4.5: Word count verification and correction...")
        target = target_words or self.words_per_chapter
        lower_bound, upper_bound = self._word_target_bounds(target)
        correction_history = CorrectionHistory(max_size=settings.WC_MAX_CORRECTION_HISTORY)
        expand_terminated = False
        trim_terminated = False
        for attempt in range(settings.WC_MAX_CORRECTION_ATTEMPTS):
            actual = count_chinese_words(chapter_text)
            deviation = compute_deviation(actual, target)
            chapter_floor = self._chapter_word_floor(chapter_idx, target)
            if deviation <= settings.WC_TOLERANCE_PCT and actual >= chapter_floor:
                logger.info(f"  Word count OK: {actual} vs target {target} (deviation {deviation:.1f}%)")
                break
            if actual < lower_bound and not expand_terminated:
                if not settings.ENABLE_GENERATION_RETRY:
                    logger.info(f"  Word count low but retry disabled: {actual} vs target {target}; accepting fast path")
                    break
                if deviation > settings.WC_SEVERE_DEVIATION_PCT:
                    logger.warning(f"  Word count severely low: {actual} vs target {target} (deviation {deviation:.1f}%, attempt {attempt+1})")
                else:
                    logger.info(f"  Word count moderately low: {actual} vs {target} (deviation {deviation:.1f}%, attempt {attempt+1})")
                correction_history.save(CorrectionSnapshot(
                    text=chapter_text, word_count=actual, quality_score=1.0,
                    strategy=CorrectionStrategy.EXPAND, deviation=deviation,
                ))
                try:
                    pre_expand_text = chapter_text
                    chapter_text = await self.writer.expand(chapter_text, target)
                    post_expand_words = count_chinese_words(chapter_text)
                    if post_expand_words < actual:
                        logger.warning(f"  Expand produced shorter text ({post_expand_words} < {actual}), reverting")
                        chapter_text = pre_expand_text
                        expand_terminated = True
                        continue
                    expand_quality = evaluate_expand_quality(
                        pre_expand_text, chapter_text,
                        timeout_seconds=settings.WC_EVAL_TIMEOUT_SECONDS,
                    )
                    logger.info(f"  Expand quality: {expand_quality['score']:.2f} (push={expand_quality['narrative_push']:.2f}, novelty={expand_quality['novelty']:.2f})")
                    if expand_quality["score"] < settings.WC_EXPAND_QUALITY_THRESHOLD:
                        logger.warning(f"  Expand quality below threshold ({expand_quality['score']:.2f} < {settings.WC_EXPAND_QUALITY_THRESHOLD}), reverting")
                        chapter_text = pre_expand_text
                        expand_terminated = True
                        continue
                    if correction_history.baseline_text:
                        style_drift = compute_style_drift(correction_history.baseline_text, chapter_text)
                        if style_drift["drift"] > settings.WC_STYLE_DRIFT_THRESHOLD:
                            logger.warning(f"  Style drift exceeded ({style_drift['drift']:.2f} > {settings.WC_STYLE_DRIFT_THRESHOLD}), reverting")
                            chapter_text = pre_expand_text
                            expand_terminated = True
                            continue
                    if post_expand_words > upper_bound:
                        logger.warning(f"  Expand overshot target ({post_expand_words} > upper bound {upper_bound}), trimming back")
                        chapter_text = _rule_based_trim(chapter_text, target)
                        post_expand_words = count_chinese_words(chapter_text)
                    new_deviation = compute_deviation(post_expand_words, target)
                    logger.info(f"  After expand: {post_expand_words} words (deviation {new_deviation:.1f}%)")
                except Exception as e:
                    logger.warning(f"  Auto-expand failed: {e}, using current text")
                    expand_terminated = True
                    continue
            elif actual > upper_bound and not trim_terminated:
                pre_trim_text = chapter_text
                correction_history.save(CorrectionSnapshot(
                    text=chapter_text, word_count=actual, quality_score=1.0,
                    strategy=CorrectionStrategy.TRIM, deviation=deviation,
                ))
                if not settings.ENABLE_GENERATION_RETRY:
                    logger.info(f"  Word count high but retry disabled: {actual} vs target {target}; rule-based trim fast path")
                    chapter_text = _rule_based_trim(chapter_text, target)
                    trim_terminated = True
                    continue
                if deviation > settings.WC_SEVERE_DEVIATION_PCT:
                    logger.warning(f"  Word count severely high: {actual} vs target {target} (deviation {deviation:.1f}%, attempt {attempt+1})")
                    try:
                        chapter_text = await self.writer.trim(chapter_text, target)
                    except Exception as e:
                        logger.warning(f"  Auto-trim failed: {e}, attempting rule-based trim")
                        chapter_text = _rule_based_trim(chapter_text, target)
                else:
                    logger.info(f"  Word count moderately high: {actual} vs {target} (deviation {deviation:.1f}%), trimming")
                    chapter_text = _rule_based_trim(chapter_text, target)
                trim_completeness = evaluate_trim_completeness(
                    pre_trim_text, chapter_text,
                    timeout_seconds=settings.WC_EVAL_TIMEOUT_SECONDS,
                )
                logger.info(f"  Trim completeness: {trim_completeness['score']:.2f} (keywords={trim_completeness['keyword_retention']:.2f}, structure={trim_completeness['structure_integrity']:.2f}, boundary={trim_completeness['boundary_integrity']:.2f})")
                if trim_completeness["score"] < settings.WC_TRIM_COMPLETENESS_THRESHOLD:
                    logger.warning(f"  Trim completeness below threshold ({trim_completeness['score']:.2f} < {settings.WC_TRIM_COMPLETENESS_THRESHOLD}), reverting and trying rule-based trim")
                    chapter_text = _rule_based_trim(pre_trim_text, target)
                    trim_terminated = True
                    continue
                if trim_completeness["boundary_integrity"] < 0.5:
                    logger.warning(f"  Boundary integrity low ({trim_completeness['boundary_integrity']:.2f}), repairing")
                    chapter_text = _repair_scene_boundaries(pre_trim_text, chapter_text)
            else:
                if actual < chapter_floor and not expand_terminated and settings.ENABLE_GENERATION_RETRY:
                    logger.info(f"  Word count inside tolerance but below chapter floor: {actual} < {chapter_floor}, continuing expansion")
                    try:
                        pre_expand_text = chapter_text
                        chapter_text = await self.writer.expand(chapter_text, target)
                        post_expand_words = count_chinese_words(chapter_text)
                        if post_expand_words <= actual:
                            chapter_text = pre_expand_text
                            expand_terminated = True
                    except Exception as e:
                        logger.warning(f"  Chapter floor expansion failed: {e}")
                        expand_terminated = True
                    continue
                if actual < chapter_floor and expand_terminated:
                    logger.warning(f"  Word count below chapter floor ({actual} < {chapter_floor}) but expansion exhausted, accepting best effort")
                logger.info(f"  Word count accepted inside hard bounds: {actual} vs target {target}")
                break
        final_words = count_chinese_words(chapter_text)
        final_deviation = compute_deviation(final_words, target)
        logger.info(f"  Final word count: {final_words} vs target {target} (deviation {final_deviation:.1f}%)")

        logger.info("  Step 5: Observation and summary...")
        observations = self._observe_chapter_facts(chapter_idx, chapter_outline.title, chapter_text)
        self._resolve_open_intents(chapter_idx, chapter_text)
        self._resolve_continuity_debts(chapter_idx, chapter_text)
        summary = observations.get("state_summary", "") or chapter_text[:300]

        # P2 程序级修复：最终质量门——在产物即将落盘前做只读检查
        # 失败时抛 OutputValidationError，由 API 层捕获并向用户返回明确错误
        # 先做软修复（用 outline 标题替换脏标题），再走硬质量门
        sanitized_title = await self.writer._validate_and_fix_title(
            chapter_outline.title, chapter_outline.title
        )
        if settings.STRICT_QUALITY_GATES:
            try:
                # P2 增量修复：把已生成章节的标题传入质量门，触发跨章唯一性检查
                previous_titles = [
                    c.title for c in self.generated_chapters if c.title
                ]
                self._final_quality_gate(
                    chapter_idx=chapter_idx,
                    title=sanitized_title,
                    content=chapter_text,
                    target_words=target,
                    previous_ending=previous_ending,
                    previous_titles=previous_titles,
                )
            except OutputValidationError as e:
                logger.error(
                    f"  Final quality gate FAILED for chapter {chapter_idx+1}: "
                    f"category={e.category}, violations={'；'.join(e.violations)}"
                )
                # 抛出到上层，让调用方决定如何处理（重试整章 / 报错给用户）
                raise

        self.memory.clear_scene_context()

        draft = ChapterDraft(
            volume_index=volume_idx,
            chapter_index=chapter_idx,
            title=sanitized_title,  # P2 程序级修复：使用软修复后的标题
            content=chapter_text,
            word_count=count_chinese_words(chapter_text),
            consistency_score=report.score,
            version=version_num,
            intent=chapter_intent,
            observations=observations,
        )
        self._replace_generated_chapter(draft, plot_direction)
        self.pending_chapter_updates[chapter_idx]["foreshadowing"] = plot_plan.get("foreshadowing", [])
        self._save_chapter_version_to_db(draft, guidance=guidance)
        logger.info(f"  Chapter {chapter_idx+1} done: {draft.word_count} words, consistency={report.score:.2f}")
        draft.finalized = False
        finalize_errors = []
        if auto_finalize:
            try:
                hard_floor = self._chapter_word_floor(chapter_idx, target)
                if draft.word_count < hard_floor:
                    raise ValueError(f"章节字数过低，未自动定稿：{draft.word_count} < {hard_floor}")
                finalize_result = await self.finalize_chapter(chapter_idx)
                self._previous_chapter_tail = chapter_text[-1500:]
                self.global_summary = self.global_summary + "\n" + (summary[:300] if summary else chapter_text[:200])
                if len(self.global_summary) > 3000:
                    self.global_summary = self.global_summary[-3000:]
                draft.finalized = True
                logger.info(f"  Auto-finalized chapter {chapter_idx+1}")
            except Exception as e:
                err_msg = str(e)
                finalize_errors.append(err_msg)
                logger.warning(f"  Auto-finalize failed (non-fatal): {err_msg}")
                # 定稿失败时仍然更新基本上下文，保证后续章节的连续性
                self._previous_chapter_tail = chapter_text[-1500:]
                if len(self.global_summary) > 3000:
                    self.global_summary = self.global_summary[-3000:]
        else:
            logger.info(f"  Manual finalize mode: chapter {chapter_idx+1} saved as draft (not finalized)")
            # 手动模式下仍然更新基本上下文，保证后续章节的连续性
            self._previous_chapter_tail = chapter_text[-1500:]
            if len(self.global_summary) > 3000:
                self.global_summary = self.global_summary[-3000:]
        draft.finalize_errors = finalize_errors
        return draft

    async def regenerate_chapter(self, volume_idx: int, chapter_idx: int, multi_version: bool = False, guidance: str = "", target_words: int | None = None, auto_finalize: bool = True) -> ChapterDraft:
        self.generated_chapters = [c for c in self.generated_chapters if c.chapter_index != chapter_idx]
        self.pending_chapter_updates.pop(chapter_idx, None)
        self._mark_chapter_as_draft(chapter_idx)
        return await self.generate_chapter(volume_idx, chapter_idx, multi_version=multi_version, guidance=guidance, target_words=target_words, auto_finalize=auto_finalize)

    async def continue_chapter(self, chapter_idx: int, guidance: str = "", target_words: int = 800) -> ChapterDraft:
        existing = next((c for c in self.generated_chapters if c.chapter_index == chapter_idx), None)
        if not existing:
            raise ValueError("Chapter not generated yet")
        context = self.memory.retrieve_context()
        control_context = self._get_story_control_context()
        state_context = self._get_character_state_context()
        if control_context:
            context = context + "\n\n" + control_context if context else control_context
        if state_context:
            context = context + "\n\n" + state_context if context else state_context
        title = existing.title
        new_content = await self.writer.continue_chapter(title, existing.content, guidance, context, target_words=target_words)
        combined = existing.content.rstrip() + "\n\n" + new_content.lstrip()
        combined_words = count_chinese_words(combined)
        chapter_target = self.words_per_chapter
        if combined_words > chapter_target * settings.WC_UPPER_TOLERANCE:
            target_chars = int(chapter_target * 1.15)
            if len(combined) > target_chars:
                for i in range(target_chars, int(target_chars * 0.8), -1):
                    if combined[i:i+2] == "\n\n":
                        combined = combined[:i].rstrip()
                        break
                else:
                    combined = combined[:target_chars].rstrip()
            combined_words = count_chinese_words(combined)
            logger.info(f"  Continue chapter trimmed: {combined_words} words (target {chapter_target})")
        updated = ChapterDraft(
            volume_index=existing.volume_index,
            chapter_index=existing.chapter_index,
            title=existing.title,
            content=combined,
            word_count=count_chinese_words(combined),
            consistency_score=existing.consistency_score,
            version=existing.version + 1,
        )
        self._replace_generated_chapter(updated, "continued")
        self._save_chapter_version_to_db(updated, guidance=guidance)
        return updated

    async def revise_chapter(self, chapter_idx: int, guidance: str = "") -> ChapterDraft:
        existing = next((c for c in self.generated_chapters if c.chapter_index == chapter_idx), None)
        if not existing:
            raise ValueError("Chapter not generated yet")
        revised_content = await self.writer.revise_chapter(existing.title, existing.content, guidance)
        revised_words = count_chinese_words(revised_content)
        chapter_target = self.words_per_chapter
        revised_deviation = compute_deviation(revised_words, chapter_target)
        if revised_deviation > settings.WC_TOLERANCE_PCT:
            if revised_words < chapter_target:
                logger.info(f"  Revise chapter word count low: {revised_words} vs {chapter_target}, Step 4.5 will correct")
            elif revised_words > chapter_target * 1.3:
                logger.info(f"  Revise chapter word count high: {revised_words} vs {chapter_target}, trimming")
                revised_content = _rule_based_trim(revised_content, chapter_target)
        updated = ChapterDraft(
            volume_index=existing.volume_index,
            chapter_index=existing.chapter_index,
            title=existing.title,
            content=revised_content,
            word_count=count_chinese_words(revised_content),
            consistency_score=existing.consistency_score,
            version=existing.version + 1,
        )
        self._replace_generated_chapter(updated, "revised")
        self._save_chapter_version_to_db(updated, guidance=guidance)
        return updated

    async def revise_fragment(self, chapter_idx: int, fragment: str, guidance: str = "") -> ChapterDraft:
        existing = next((c for c in self.generated_chapters if c.chapter_index == chapter_idx), None)
        if not existing:
            raise ValueError("Chapter not generated yet")
        revised_content = await self.writer.revise_fragment(existing.title, existing.content, fragment, guidance)
        revised_words = count_chinese_words(revised_content)
        chapter_target = self.words_per_chapter
        if revised_words > chapter_target * 1.3:
            logger.info(f"  Fragment revise word count high: {revised_words} vs {chapter_target}, trimming")
            revised_content = _rule_based_trim(revised_content, chapter_target)
        updated = ChapterDraft(
            volume_index=existing.volume_index,
            chapter_index=existing.chapter_index,
            title=existing.title,
            content=revised_content,
            word_count=count_chinese_words(revised_content),
            consistency_score=existing.consistency_score,
            version=existing.version + 1,
        )
        self._replace_generated_chapter(updated, "fragment_revised")
        self._save_chapter_version_to_db(updated, guidance=guidance)
        return updated

    async def finalize_chapter(self, chapter_idx: int) -> dict:
        if chapter_idx not in self.finalized_chapters:
            self.finalized_chapters.append(chapter_idx)
            self.finalized_chapters.sort()
        for draft in self.generated_chapters:
            if draft.chapter_index == chapter_idx:
                draft.finalized = True
                self.save_chapter(draft)
                break
        pending = self.pending_chapter_updates.get(chapter_idx)
        # Fallback: if pending is None (pipeline loaded from state), reconstruct from generated chapter
        if not pending:
            for draft in self.generated_chapters:
                if draft.chapter_index == chapter_idx and draft.content:
                    pending = {
                        "title": draft.title,
                        "content": draft.content,
                        "summary": draft.summary if hasattr(draft, 'summary') and draft.summary else draft.content[:300],
                        "observations": {},
                        "foreshadowing": [],
                        "plot_progress": "",
                    }
                    break
        evolution_result = {"status": "skipped", "reason": "no_new_finalized_content"}
        if pending:
            # 更新项目级词频追踪
            self._update_project_word_freq(pending.get("content", ""))
            self.memory.add_chapter_to_memory(pending["title"], pending["content"], pending["summary"])
            try:
                await self.memory.consolidate_chapter(
                    pending["content"], pending["title"], chapter_idx,
                    context=pending.get("observations"),
                )
            except Exception as e:
                logger.warning(f"Memory consolidation failed for chapter {chapter_idx}: {e}")
            observations = pending.get("observations") or {}
            self.memory.structured.upsert_chapter_summary(
                chapter_idx,
                pending["title"],
                pending["summary"],
                observations=observations,
            )
            updated_chars = []
            for char in self.characters:
                updated = char
                if not settings.FAST_TEST_MODE and settings.ENABLE_LLM_CHARACTER_UPDATE:
                    try:
                        updated = await self.character_engine.update_character(char, pending["summary"])
                    except Exception as e:
                        logger.warning(f"Character update failed for {char.name}: {e}")
                self.memory.update_character(updated)
                updated_chars.append(updated)
                try:
                    if not self.state_manager.get_character(updated.name):
                        self.state_manager.register_character(updated.name, initial_power=1)
                    machine = self.state_manager.get_character(updated.name)
                    level_text = str(updated.status.get("level", "")) if isinstance(updated.status, dict) else ""
                    power = machine.power_level if machine else 1
                    # 从等级文本推断战力
                    if any(token in level_text for token in ["初始", "觉醒", "F"]):
                        power = max(power, 5)
                    elif any(token in level_text for token in ["E", "见习", "成长"]):
                        power = max(power, 15)
                    elif any(token in level_text for token in ["D", "掌控", "强"]):
                        power = max(power, 30)
                    elif any(token in level_text for token in ["C", "B", "A", "金丹", "元婴", "化神"]):
                        power = max(power, 60)
                    # 从章节进度推断成长：角色随剧情推进自然提升
                    progress_ratio = (chapter_idx + 1) / max(1, self.target_chapters or 12)
                    progress_power = max(1, int(progress_ratio * 50) + 5)
                    power = max(power, progress_power)
                    # 本章出场角色额外加分
                    chapter_content = pending.get("content", "")
                    if updated.name and updated.name in chapter_content:
                        power = min(100, power + 3)
                    if machine:
                        machine.update_power(power, chapter_idx + 1, reason=pending["summary"][:60])
                except Exception as e:
                    logger.warning(f"State manager update failed for {updated.name}: {e}")
            self.characters = updated_chars
            self.memory.sync_relationships_from_characters(chapter=chapter_idx)
            try:
                char_names = [c.name for c in self.characters if c.name]
                self.memory.relationship_graph.extract_relationships_from_content(
                    pending["content"], char_names, chapter=chapter_idx
                )
            except Exception as e:
                logger.warning(f"Relationship extraction from content failed: {e}")
            self.memory.structured.add_timeline_event({
                "chapter": chapter_idx + 1,
                "title": pending["title"],
                "summary": pending["summary"],
                "plot_progress": pending["plot_progress"],
                "characters": observations.get("characters_on_stage", []),
                "locations": observations.get("locations", []),
                "resources": observations.get("resources_touched", []),
            })
            try:
                from core.database import SessionLocal
                from models.db_service import TimelineService, ForeshadowingService
                with SessionLocal() as db:
                    TimelineService(db).add_event(
                        project_id=self.session_id,
                        chapter_index=chapter_idx,
                        event_type="chapter_finalized",
                        description=f"《{pending['title']}》定稿：{pending['summary'][:120]}",
                    )
                    for item in pending.get("foreshadowing", [])[:5]:
                        if item:
                            self._persist_foreshadow_payload(ForeshadowingService(db), item, chapter_idx)
                    if chapter_idx < len(self.volume.chapters):
                        chapter_outline = self.volume.chapters[chapter_idx]
                        content_candidates = self._derive_new_foreshadow_candidates(chapter_idx, chapter_outline, chapter_text=pending["content"])
                        existing_descs = {item.get("description", "") for item in pending.get("foreshadowing", []) if item}
                        for cand in content_candidates:
                            if cand and cand.get("description", "") not in existing_descs:
                                self._persist_foreshadow_payload(ForeshadowingService(db), cand, chapter_idx)
            except Exception as e:
                logger.warning(f"Finalize DB timeline/foreshadow sync failed: {e}")
            self._auto_resolve_foreshadowing(chapter_idx, pending["content"])
            # 同步未解伏笔到信息差管理器的 reader_wants_to_know
            try:
                self._sync_foreshadows_to_info_gap(chapter_idx)
            except Exception as e:
                logger.debug(f"Info gap foreshadow sync skipped: {e}")
            self._resolve_continuity_debts(chapter_idx, pending["content"])
            for hook in observations.get("hook_movements", [])[:3]:
                self._add_continuity_debt(hook, chapter_idx, kind="hook")
            for resource in observations.get("resources_touched", [])[:4]:
                self._add_continuity_debt(f"{resource}的用途或后果需要后文确认", chapter_idx, kind="resource")
            self._rebuild_suspense_arcs_from_story(force=True)
            # 线程感知重规划：将线程截止日期映射到未来章节规划
            try:
                self._thread_aware_replan(chapter_idx)
            except Exception as e:
                logger.debug(f"Thread-aware replan skipped: {e}")
            # LLM 结构化线程提取（深度提取，失败则忽略，规则提取已在 post_generation 中完成）
            try:
                extraction = await self.enhancement.extract_threads_with_llm(pending["content"], chapter_idx + 1)
                if extraction:
                    self.enhancement.apply_llm_extraction(extraction, chapter_idx + 1)
            except Exception as e:
                logger.debug(f"LLM thread extraction skipped: {e}")
            try:
                await self.rag.index_chapter(pending["title"], pending["content"], pending["summary"])
            except Exception as e:
                logger.warning(f"RAG indexing failed on finalize: {e}")
            self.pending_chapter_updates.pop(chapter_idx, None)
        # 如果完成了一卷（每10章），生成卷摘要
        chapter_num = chapter_idx + 1
        if self.hierarchical_summary.should_generate_arc_summary(chapter_num):
            arc_id = self.hierarchical_summary.get_arc_id(chapter_num)
            arc_chapters = self.hierarchical_summary.get_arc_chapters(arc_id, [
                {
                    "chapter_index": c.chapter_index,
                    "title": c.title,
                    "content": c.content,
                    "summary": getattr(c, "summary", c.content[:300]),
                }
                for c in self.generated_chapters
            ])
            summaries = [ch.get("summary", "")[:200] for ch in arc_chapters if ch.get("summary")]
            if summaries:
                import re
                arc_summary = " → ".join(summaries)
                if len(arc_summary) > 500:
                    arc_summary = arc_summary[:500]
                self.hierarchical_summary.update_arc_summary(
                    arc_id=arc_id,
                    summary=arc_summary,
                    main_events=summaries[:5],
                    character_changes=[],
                    foreshadowing=pending.get("foreshadowing", []) if pending else [],
                )

        self._set_db_chapter_status(chapter_idx, "finalized")
        # 自动检测角色关系（从定稿文本中提取共现和互动关键词）
        try:
            self._auto_detect_relationships(chapter_idx, pending.get("content", ""))
        except Exception as e:
            logger.debug(f"Auto relationship detection skipped: {e}")
        self._settle_story_completion_state()
        try:
            evolution_result = self.apply_story_evolution()
        except Exception as e:
            logger.warning(f"Auto story evolution apply failed after finalize: {e}")
            evolution_result = {"status": "failed", "error": str(e)}
        self._ensure_future_planning_window()
        self.save_project_state()
        return {"chapter_index": chapter_idx, "finalized": True, "story_evolution": evolution_result}

    def unfinalize_chapter(self, chapter_idx: int) -> dict:
        self._mark_chapter_as_draft(chapter_idx)
        evolution_result = {"status": "up_to_date"}
        last_synced = int(self.evolution_state.get("last_synced_chapter", -1)) if isinstance(self.evolution_state, dict) else -1
        if chapter_idx <= last_synced:
            try:
                evolution_result = self._rebuild_story_evolution_from_finalized()
            except Exception as e:
                logger.warning(f"Story evolution rebuild failed after unfinalize: {e}")
                self._reset_story_evolution_state()
                evolution_result = {"status": "failed", "error": str(e)}
        self.save_project_state()
        return {"chapter_index": chapter_idx, "finalized": False, "story_evolution": evolution_result}

    def select_version_as_current(self, chapter_idx: int, version: int, content: str, word_count: int, consistency_score: float) -> ChapterDraft:
        existing = next((c for c in self.generated_chapters if c.chapter_index == chapter_idx), None)
        if not existing:
            raise ValueError("Chapter not generated yet")
        updated = ChapterDraft(
            volume_index=existing.volume_index,
            chapter_index=existing.chapter_index,
            title=existing.title,
            content=content,
            word_count=word_count,
            consistency_score=consistency_score,
            version=version,
        )
        self._replace_generated_chapter(updated, "selected_version")
        return updated

    async def generate_all(self, request: GenerationRequest, max_chapters: int = None) -> list[ChapterDraft]:
        init_result = await self.initialize(request)
        total = len(self.volume.chapters)
        if max_chapters:
            total = min(total, max_chapters)

        for i in range(total):
            draft = await self.generate_chapter(0, i)
            output_path = self.save_chapter(draft)
            logger.info(f"Saved: {output_path}")

        return self.generated_chapters

    async def batch_generate(
        self,
        start_chapter: int = 0,
        end_chapter: int = None,
        consistency_threshold: float = 0.4,
        auto_finalize: bool = True,
        max_retries: int = 1,
        on_progress=None,
    ) -> dict:
        if not self.volume:
            raise ValueError("Pipeline not initialized")
        if not self.approved:
            raise ValueError("Project not approved")
        if not auto_finalize:
            raise ValueError("批量推进为保证长篇连续性，必须开启自动定稿。请先开启“自动定稿”再执行。")

        start_chapter = max(0, int(start_chapter or 0))
        if start_chapter >= self.target_chapters:
            raise ValueError(f"项目总章节数上限是第{self.target_chapters}章，当前起始章节已越界。")
        if end_chapter is not None:
            end_chapter = max(0, int(end_chapter))
        if end_chapter is None:
            end_chapter = len(self.volume.chapters)
        else:
            if end_chapter == 0:
                end_chapter = len(self.volume.chapters)
            else:
                end_chapter = min(end_chapter, self.target_chapters)
                if end_chapter > len(self.volume.chapters):
                    self._ensure_planned_to(end_chapter - 1)
        total_chapters = len(self.volume.chapters)
        end_chapter = min(end_chapter, total_chapters)
        start_chapter = min(start_chapter, end_chapter)
        finalized_cursor = 0
        finalized_set = set(self.finalized_chapters)
        while finalized_cursor in finalized_set:
            finalized_cursor += 1
        broken_finalized = sorted(idx for idx in finalized_set if idx > finalized_cursor)
        if broken_finalized:
            first_broken = broken_finalized[0]
            raise ValueError(
                f"检测到定稿链断裂：第{finalized_cursor + 1}章之前仍有缺口，但第{first_broken + 1}章已经定稿。请先修复前面的章节连续性，再批量推进。"
            )

        requested_start = start_chapter
        if start_chapter < finalized_cursor:
            logger.warning(
                "Batch start adjusted for continuity: requested=%s actual=%s",
                start_chapter + 1,
                finalized_cursor + 1,
            )
            start_chapter = finalized_cursor
        if start_chapter >= end_chapter:
            raise ValueError(
                f"当前可连续推进的位置是第{finalized_cursor + 1}章，目标范围内没有可安全批量生成的章节。"
            )

        results = {
            "total": end_chapter - start_chapter,
            "generated": 0,
            "finalized": 0,
            "failed": 0,
            "skipped": 0,
            "stopped_early": False,
            "stop_reason": "",
            "requested_start_chapter": requested_start,
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "requested_start_chapter_no": requested_start + 1,
            "start_chapter_no": start_chapter + 1,
            "end_chapter_no": end_chapter,
            "planned_chapters": len(self.volume.chapters),
            "target_chapters": self.target_chapters,
            "mode": "contiguous_finalize_first",
            "chapters": [],
        }

        if on_progress:
            try:
                on_progress(start_chapter - 1, end_chapter, {"status": "batch_ready", "chapter_index": start_chapter, "results": results})
            except Exception:
                pass

        chapter_idx = start_chapter
        while chapter_idx < end_chapter:
            expected_idx = 0
            current_finalized = set(self.finalized_chapters)
            while expected_idx in current_finalized:
                expected_idx += 1
            if chapter_idx != expected_idx:
                logger.warning(
                    "Batch generation stopped because continuity cursor moved: expected=%s current=%s",
                    expected_idx + 1,
                    chapter_idx + 1,
                )
                results["failed"] += 1
                results["chapters"].append({
                    "chapter_index": chapter_idx,
                    "status": "blocked_non_contiguous",
                    "error": f"必须从第{expected_idx + 1}章连续推进，不能跳到第{chapter_idx + 1}章。",
                })
                results["stopped_early"] = True
                results["stop_reason"] = f"第{chapter_idx + 1}章无法开始：必须从第{expected_idx + 1}章连续推进。"
                break
            existing = next((c for c in self.generated_chapters if c.chapter_index == chapter_idx), None)
            if existing and chapter_idx in self.finalized_chapters:
                results["skipped"] += 1
                results["chapters"].append({
                    "chapter_index": chapter_idx,
                    "status": "skipped_already_finalized",
                    "title": existing.title,
                    "word_count": existing.word_count,
                    "consistency_score": existing.consistency_score,
                })
                chapter_idx += 1
                continue

            draft = None
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    draft = await self.generate_chapter(0, chapter_idx, auto_finalize=False)
                    break
                except ConsistencyBlockError as e:
                    self.memory.clear_scene_context()
                    last_error = str(e)
                    logger.error(f"Chapter {chapter_idx + 1} blocked: {e}")
                    if attempt == max_retries:
                        break
                    logger.info(f"Retrying chapter {chapter_idx + 1} (attempt {attempt + 2})")
                except StateTransitionBlockError as e:
                    self.memory.clear_scene_context()
                    last_error = str(e)
                    logger.error(f"Chapter {chapter_idx + 1} state transition blocked: {e}")
                    break
                except Exception as e:
                    self.memory.clear_scene_context()
                    err_str = str(e)
                    if "Inappropriate" in err_str or "content_policy" in err_str or "safety" in err_str.lower():
                        last_error = f"第{chapter_idx + 1}章被LLM内容安全过滤器拒绝。建议：1)检查前几章是否有敏感内容；2)尝试修改大纲方向后重试。"
                    else:
                        last_error = f"第{chapter_idx + 1}章生成失败：{err_str[:200]}"
                    logger.error(f"Chapter {chapter_idx + 1} generation failed: {e}")
                    break

            # Detect empty/near-empty chapters (title only, no real content)
            if draft and count_chinese_words(draft.content or "") < 100:
                logger.error(f"Chapter {chapter_idx + 1} generated with near-empty content ({draft.word_count} words)")
                draft = None
                last_error = f"第{chapter_idx + 1}章生成内容为空（不足100字），需要重新生成。"

            if draft is None:
                results["failed"] += 1
                results["chapters"].append({
                    "chapter_index": chapter_idx,
                    "status": "failed",
                    "error": last_error,
                })
                results["stopped_early"] = True
                results["stop_reason"] = last_error or f"第{chapter_idx + 1}章生成失败"
                break

            results["generated"] += 1
            chapter_result = {
                "chapter_index": chapter_idx,
                "status": "generated",
                "title": draft.title,
                "word_count": draft.word_count,
                "consistency_score": draft.consistency_score,
            }

            if auto_finalize and draft.consistency_score >= consistency_threshold:
                try:
                    chapter_target_words = self._dynamic_target_words(chapter_idx)
                    hard_floor = self._chapter_word_floor(chapter_idx, chapter_target_words)
                    # Retry if word count is below hard floor (up to 2 extra attempts)
                    wc_retry = 0
                    while draft.word_count < hard_floor and wc_retry < 2:
                        wc_retry += 1
                        logger.warning(f"Chapter {chapter_idx + 1} word count {draft.word_count} < hard floor {hard_floor}, regenerating (attempt {wc_retry})")
                        self.memory.clear_scene_context()
                        try:
                            draft = await self.generate_chapter(0, chapter_idx, auto_finalize=False, target_words=chapter_target_words + 200 * wc_retry)
                        except Exception as wc_e:
                            logger.error(f"Word count retry failed: {wc_e}")
                            break
                        chapter_result["word_count"] = draft.word_count
                        chapter_result["title"] = draft.title
                    if draft.word_count < hard_floor:
                        chapter_result["status"] = "generated_below_word_threshold"
                        chapter_result["note"] = f"word_count {draft.word_count} < hard floor {hard_floor} (after {wc_retry} retries)"
                        results["failed"] += 1
                        results["chapters"].append(chapter_result)
                        results["stopped_early"] = True
                        results["stop_reason"] = chapter_result["note"]
                        break
                    # Fix truncated endings before finalize
                    if self.writer._is_truncated_ending(draft.content):
                        try:
                            fixed = await self.writer._fix_truncated_ending(draft.content, chapter_target_words)
                            if count_chinese_words(fixed) > count_chinese_words(draft.content):
                                draft.content = fixed
                                draft.word_count = count_chinese_words(fixed)
                                chapter_result["word_count"] = draft.word_count
                        except Exception as fix_e:
                            logger.warning(f"Truncated ending fix failed: {fix_e}")
                    finalize_result = await self.finalize_chapter(chapter_idx)
                    results["finalized"] += 1
                    chapter_result["status"] = "finalized"
                except Exception as e:
                    err_msg = str(e)
                    logger.warning(f"Auto-finalize failed for chapter {chapter_idx + 1}: {err_msg}")
                    chapter_result["status"] = "generated_not_finalized"
                    chapter_result["finalize_error"] = err_msg
                    if draft.finalize_errors:
                        chapter_result["finalize_errors"] = draft.finalize_errors
                    results["failed"] += 1
                    results["chapters"].append(chapter_result)
                    results["stopped_early"] = True
                    results["stop_reason"] = err_msg
                    break
            elif draft.consistency_score < consistency_threshold:
                chapter_result["status"] = "generated_below_threshold"
                chapter_result["note"] = f"consistency_score {draft.consistency_score:.2f} < threshold {consistency_threshold}"
                results["failed"] += 1
                results["chapters"].append(chapter_result)
                results["stopped_early"] = True
                results["stop_reason"] = chapter_result["note"]
                break

            results["chapters"].append(chapter_result)

            # Expand end_chapter if planning window added new chapters
            logger.info(f"  Batch loop: chapter_idx={chapter_idx}, end_chapter={end_chapter}, volume={len(self.volume.chapters)}, target={self.target_chapters}")
            if len(self.volume.chapters) > end_chapter:
                end_chapter = min(len(self.volume.chapters), self.target_chapters)
                results["end_chapter"] = end_chapter
                results["total"] = end_chapter - start_chapter

            if on_progress:
                try:
                    on_progress(chapter_idx, end_chapter, chapter_result)
                except Exception:
                    pass

            chapter_idx += 1

            self.save_project_state()

        return results

    async def _generate_hook_and_summary(self, chapter_text: str, next_hint: str) -> dict:
        prompt = f"""请分析以下章节内容，输出两样东西：

1. 章节结尾钩子（hook）- 1-2句话，制造悬念，吸引读者继续看下一章
2. 章节摘要（summary）- 3-5句话，概括本章核心情节发展

章节内容：
{chapter_text[:3000]}

{"下一章标题：" + next_hint if next_hint else ""}

请输出JSON格式：
{{
  "hook": "结尾钩子文本",
  "summary": "章节摘要文本"
}}"""
        from core.llm_router import call_llm, TaskType
        result = await call_llm(TaskType.PLAN, prompt, temperature=0.7, json_mode=True)
        return result if isinstance(result, dict) else {"hook": "", "summary": chapter_text[:300]}

    def get_status(self) -> dict:
        return {
            "total_chapters": self.target_chapters,
            "planned_chapters": len(self.volume.chapters) if self.volume else 0,
            "planning_window": self.planning_window,
            "generated": len(self.generated_chapters),
            "characters": len(self.characters),
            "world_set": self.world is not None,
            "approved": self.approved,
            "finalized": len(self.finalized_chapters),
        }

    def get_chapter_catalog(self) -> list[dict]:
        if not self.volume:
            return []
        generated_map = {chapter.chapter_index: chapter for chapter in self.generated_chapters}
        catalog = []
        for idx, chapter in enumerate(self.volume.chapters):
            draft = generated_map.get(idx)
            catalog.append({
                "chapter_index": idx,
                "title": draft.title if draft else chapter.title,
                "goal": chapter.goal,
                "conflict": chapter.conflict,
                "scene_count": len(chapter.scenes),
                "generated": draft is not None,
                "finalized": idx in self.finalized_chapters,
                "word_count": draft.word_count if draft else 0,
                "consistency_score": draft.consistency_score if draft else None,
                "intent": getattr(draft, "intent", {}) if draft else {},
                "observations": getattr(draft, "observations", {}) if draft else {},
                "output_file": os.path.join(self.get_output_dir(), f"chapter_{idx + 1:03d}.txt") if draft else None,
            })
        return catalog
