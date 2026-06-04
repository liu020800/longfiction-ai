import json
import logging
import re
from core.llm_router import call_llm, TaskType
from core.config import settings
from core.models import VolumeOutline, ChapterOutline, SceneOutline

logger = logging.getLogger(__name__)

PLANNER_SYSTEM = """你是一个资深网文策划编辑，擅长将大纲拆解为可执行的章节计划。
你必须输出JSON格式，包含volume和chapters数组。每个chapter包含title、goal、conflict。
确保：
- chapters数组数量必须等于"本次需要规划的章节数"，不要一次性输出整部长篇
- 每章有明确目标和冲突
- 剧情节奏有起伏（紧张-缓和-高潮交替）
- 伏笔和回收合理
- 禁止出现"大结局""终局""最终决战""终章"等终局内容，除非已到达整书最后4章
- 本次规划只是全书的阶段性章节，不是完整故事
- 禁止在非第一章使用"序幕""前奏""序章"等结构性术语作为章节标题
- 章节标题必须具体反映本章核心事件（如"废墟中的救援""数据窃取"），禁止使用抽象的"前缀+后缀"组合（如"反制暗涌""深入逆转"）"""

PLANNER_PROMPT = """请将以下小说大纲拆解为详细的章节计划：

大纲：{outline}
类型：{genre}
核心人物：{characters}
整书目标章节数：{target_chapters}
本次需要规划的章节数：{plan_chapters}

要求：
- 只输出本次需要规划的章节，不要输出全部整书章节。
- 必须使用"核心人物"中的准确姓名，不要自创主角姓名或替换角色名。
- 当前章节规划只是第一阶段写作导航，后续会根据定稿内容阶段性重规划。
- 每章必须具体、可执行，避免"继续推进主线"这类空泛描述。
- 【重要】本次只规划前{plan_chapters}章（全书共{target_chapters}章），属于故事前期铺垫阶段。禁止出现大结局、终局、最终决战等内容。大结局只能在全书最后3-4章出现。

请输出JSON：
{{
  "volume": "卷名",
  "chapters": [
    {{
      "title": "章节标题",
      "goal": "本章目标",
      "conflict": "本章冲突"
    }}
  ]
}}"""

SCENE_SPLIT_PROMPT = """请将以下章节计划拆解为2-4个场景：

章节标题：{title}
章节目标：{goal}
章节冲突：{conflict}
当前人物：{characters}

请输出JSON数组：
[
  {{
    "description": "场景描述",
    "characters": ["出场人物"],
    "location": "场景地点",
    "mood": "场景氛围",
    "target_words": 2000
  }}
]"""


class PlannerAgent:
    def _sanitize_story_text(self, text: str, limit: int = 80) -> str:
        cleaned = " ".join((text or "").split())
        cleaned = re.sub(r"#+", " ", cleaned)
        cleaned = re.sub(r"【[^】]{0,20}】", " ", cleaned)
        cleaned = re.sub(r"(类型|题材|风格|设定工作区|项目骨架)[：:]\s*[^#]+", " ", cleaned)
        cleaned = re.sub(r"[《》]", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ：:，,。;；-")
        return cleaned[:limit].strip()

    async def plan(
        self,
        outline: str,
        genre: str = "urban_fantasy",
        target_chapters: int = 100,
        plan_chapters: int | None = None,
        character_names: list[str] | None = None,
    ) -> VolumeOutline:
        count = max(1, min(plan_chapters or target_chapters or 1, target_chapters or plan_chapters or 1))
        # 故事总长度用于大结局检测，批次大小用于截断
        story_total = max(target_chapters, count)
        prompt = PLANNER_PROMPT.format(
            outline=outline,
            genre=genre,
            characters="、".join(character_names or []) or "未指定",
            target_chapters=target_chapters,
            plan_chapters=count,
        )
        try:
            result = await call_llm(TaskType.PLAN, prompt, system=PLANNER_SYSTEM, json_mode=True, temperature=0.7)
        except Exception as e:
            logger.warning(f"Chapter planning failed, using fallback: {e}")
            return VolumeOutline(volume="第一卷", chapters=self._fallback_chapters(outline, count, story_total))
        try:
            volume = VolumeOutline(**result)
        except Exception:
            chapters = []
            if not isinstance(result, dict):
                result = {}
            raw_chapters = result.get("chapters", [])
            if isinstance(raw_chapters, dict):
                raw_chapters = [raw_chapters]
            for ch in raw_chapters:
                if not isinstance(ch, dict):
                    continue
                chapters.append(ChapterOutline(
                    title=ch.get("title", "未命名"),
                    goal=ch.get("goal", ""),
                    conflict=ch.get("conflict", ""),
                ))
            volume = VolumeOutline(volume=result.get("volume", "第一卷"), chapters=chapters)
        if not volume.chapters:
            volume.chapters = self._fallback_chapters(outline, count, story_total)
        if len(volume.chapters) < count:
            volume.chapters.extend(self._continuation_chapters(outline, volume.chapters, count, story_total))
        if len(volume.chapters) > count:
            volume.chapters = volume.chapters[:count]
        volume.chapters = self._repair_repeated_chapters(outline, volume.chapters, count, story_total)
        return volume

    def _fallback_chapters(self, outline: str, target_chapters: int, story_total: int = 0) -> list[ChapterOutline]:
        count = max(1, target_chapters or 1)
        total = max(story_total or 0, count)
        chapters = []
        for i in range(count):
            chapters.append(self._make_progressive_chapter(outline, chapters, i, total))
        return chapters

    def _continuation_chapters(self, outline: str, existing: list[ChapterOutline], target_chapters: int, story_total: int = 0) -> list[ChapterOutline]:
        start = len(existing)
        total = max(story_total or 0, target_chapters)
        chapters = []
        for i in range(start, target_chapters):
            chapters.append(self._make_progressive_chapter(outline, existing + chapters, i, total))
        return chapters

    def _repair_repeated_chapters(self, outline: str, chapters: list[ChapterOutline], target_chapters: int, story_total: int = 0) -> list[ChapterOutline]:
        total = max(story_total or 0, target_chapters)
        fixed: list[ChapterOutline] = []
        seen: set[tuple[str, str]] = set()
        seen_titles: set[str] = set()
        for idx, chapter in enumerate(chapters[:target_chapters]):
            signature = self._chapter_signature(chapter)
            title = (chapter.title or "").strip()
            needs_regen = False
            if idx > 0 and (signature in seen or self._is_generic_chapter(chapter)):
                needs_regen = True
            if title in seen_titles:
                needs_regen = True
            if needs_regen:
                chapter = self._make_progressive_chapter(outline, fixed, idx, total)
                signature = self._chapter_signature(chapter)
            fixed.append(chapter)
            seen.add(signature)
            seen_titles.add((chapter.title or "").strip())
        return fixed

    def _chapter_signature(self, chapter: ChapterOutline) -> tuple[str, str]:
        return ((chapter.goal or "").strip(), (chapter.conflict or "").strip())

    def _is_generic_chapter(self, chapter: ChapterOutline) -> bool:
        goal = chapter.goal or ""
        conflict = chapter.conflict or ""
        title = chapter.title or ""
        generic_goal = "承接前文继续推进主线" in goal and len(goal) < 140
        generic_conflict = conflict.strip() in {
            "新的阻碍升级，主角必须做出选择并推动下一阶段剧情",
            "主角遭遇新的阻碍并被迫做出选择",
        }
        # 检测模板生成的阶段章节（stage/beat 模式）— 只检测旧的前缀+后缀组合
        stage_markers = ["燃点暗涌", "燃点爆发", "余波", "远行初现", "远行暗涌", "远行试探", "远行失控",
                         "新生初现", "新生暗涌", "新生试探", "新生失控",
                         "反制暗涌", "反制试探", "反制失控", "真相暗涌", "真相试探",
                         "败局暗涌", "败局试探", "重构暗涌", "深入暗涌", "燃点代价"]
        is_stage_template = any(marker in title for marker in stage_markers)
        # P0 修复：检测策划阶段标签作为标题（f8e1ca1d 的核心问题）
        is_dirty_title = self._is_dirty_title(title)
        # 终局章节有专门的生成逻辑（_make_endgame_chapter），不算 generic
        # 只有当 goal 和 conflict 都很泛泛时才算 generic
        return generic_goal or generic_conflict or is_stage_template or is_dirty_title

    def _make_progressive_chapter(
        self,
        outline: str,
        existing: list[ChapterOutline],
        chapter_index: int,
        total_chapters: int,
    ) -> ChapterOutline:
        remaining = total_chapters - chapter_index
        # 大结局只在全书最后4章触发，且不能在前60%章节中出现
        if total_chapters >= 4 and remaining <= min(4, total_chapters) and chapter_index >= total_chapters * 0.6:
            return self._make_endgame_chapter(outline, existing, chapter_index, total_chapters)
        stage = self._stage_for(chapter_index, total_chapters)
        beat = self._beat_for(chapter_index)
        anchor = self._anchor_text(outline, existing)
        title_text = self._extract_title_from_goal(stage['goal'], beat['goal_focus'], chapter_index)
        # P0 修复：如果标题仍是脏词，尝试同步多章一次性 LLM 重生成（节省 token）
        if self._is_dirty_title(title_text):
            new_title = self._llm_title_for_batch([(stage['goal'], beat['goal_focus'], chapter_index, total_chapters)], existing)
            if new_title and not self._is_dirty_title(new_title):
                title_text = new_title
        # P2 增量修复：用 beat 后缀打破"同 stage 桶 → 同一标题"坍缩
        # 例：第13章 扩大组织·初现、第14章 扩大组织·暗涌、第15章 扩大组织·试探
        # 这样同 stage 内的连续章节标题天然不同，避免 _extract_title_from_goal 的前缀重复
        beat_suffix = beat.get('title_suffix', '').strip()
        if beat_suffix and not title_text.endswith(beat_suffix):
            title_text = f"{title_text}·{beat_suffix}"
        title = f"第{chapter_index + 1}章 {title_text}"
        goal = (
            f"{stage['goal']}。承接前序线索“{anchor}”，本章重点是{beat['goal_focus']}，"
            f"让主线进入“{stage['turning_point']}”。"
        )
        conflict = (
            f"{stage['pressure']}；{beat['conflict_focus']}，主角必须付出代价或调整策略，"
            f"并为后续埋下“{stage['hook']}”。"
        )
        return ChapterOutline(
            title=title,
            goal=goal,
            conflict=conflict,
            scenes=[
                SceneOutline(
                    description=f"{stage['scene']}：{beat['scene_focus']}，结尾留下明确转折。",
                    target_words=settings.SCENE_TARGET_WORDS,
                )
            ],
        )

    def _make_endgame_chapter(
        self,
        outline: str,
        existing: list[ChapterOutline],
        chapter_index: int,
        total_chapters: int,
    ) -> ChapterOutline:
        remaining = total_chapters - chapter_index
        anchor = self._anchor_text(outline, existing)
        core = self._extract_core_promise(outline)
        unresolved = self._extract_unresolved_from_existing(existing)
        if remaining == 4:
            title = f"第{chapter_index + 1}章 终局收网"
            goal = f"把前文主线与关键伏笔统一收束，明确终局战场与最后目标。承接“{anchor}”，必须让{core}进入不可回头的收网阶段，并点亮待回收问题：{unresolved}。"
            conflict = "敌方开始主动封口或毁灭证据，主角如果此刻判断失误，前文积累的全部线索都会断裂；必须在有限时间内锁定真正终局切口。"
            scene = "多线信息汇合、旧线索交叉印证、关键人物重新站队，章节结尾明确最终行动方案。"
        elif remaining == 3:
            title = f"第{chapter_index + 1}章 终局逼近"
            goal = f"推动主角真正逼近核心真相或最终对手，让前文最大悬念得到关键回应。承接“{anchor}”，本章必须实际回收至少一条重要伏笔，并把{core}推到最后抉择前夜。"
            conflict = "真相的代价高于预期，核心关系、身份或世界规则遭遇反噬；主角必须在保全自我、保护同伴和完成主线之间做痛苦取舍。"
            scene = "潜入、对质、回忆拼接或证据落位交替推进，让读者确认最终对决已不可避免。"
        elif remaining == 2:
            title = f"第{chapter_index + 1}章 最终抉择"
            goal = f"完成整部小说的核心对决与主题抉择，正面回答“{core}”这一主问题。承接“{anchor}”，本章必须推动主要矛盾真正见底，不能再做普通过渡。"
            conflict = "任何选择都伴随牺牲或失去，敌方最后反扑会逼主角暴露底牌；若不能承担代价，就无法换来真正的解决。"
            scene = "主战场高潮、人物底牌揭示、关键牺牲或反转连锁发生，把全书张力推到峰值。"
        else:
            title = f"第{chapter_index + 1}章 大结局"
            goal = f"完成最终回收与结局落地，交代核心人物归宿、主线结果与世界新秩序，明确回答“{core}”的最终后果。承接“{anchor}”，本章必须形成真正闭环，而不是留下主冲突未解。"
            conflict = "胜利后的残局、代价与余震仍需面对；必须处理前文最重要的情感和设定后果，避免用空泛尾声跳过真正善后。"
            scene = "终局余震、关系落点、关键伏笔最后回收和世界状态确认依次完成，最后一段给出完整而克制的收束。"
        return ChapterOutline(
            title=title,
            goal=goal,
            conflict=conflict,
            scenes=[
                SceneOutline(
                    description=scene,
                    target_words=settings.SCENE_TARGET_WORDS,
                )
            ],
        )

    def _stage_for(self, chapter_index: int, total_chapters: int) -> dict[str, str]:
        stages = [
            {
                "title_prefix": "余波",
                "goal": "处理上一阶段事件的直接后果，明确主角新的短期目标",
                "pressure": "敌方开始试探，盟友内部出现不同意见",
                "turning_point": "被迫行动",
                "hook": "更深层的监控痕迹",
                "scene": "从危机余波切入，展示代价与新目标",
            },
            {
                "title_prefix": "裂痕",
                "goal": "扩大组织、亲情或信念层面的矛盾，让主角第一次意识到胜利并不纯粹",
                "pressure": "同伴立场分化，旧计划暴露明显缺陷",
                "turning_point": "内部选择",
                "hook": "被隐藏的背叛线索",
                "scene": "以争执、审问或秘密会议推进关系张力",
            },
            {
                "title_prefix": "远行",
                "goal": "让主角离开安全区，接触更广阔的世界和新的势力",
                "pressure": "陌生环境带来生存风险，新势力要求交换代价",
                "turning_point": "外部世界展开",
                "hook": "未知坐标或古老遗物",
                "scene": "路途、废墟、据点或边境冲突交替推进",
            },
            {
                "title_prefix": "反制",
                "goal": "敌方主动升级压迫，逼迫主角从防守转向反击",
                "pressure": "敌人掌握主角弱点，并以人质、资源或真相施压",
                "turning_point": "第一次反击",
                "hook": "敌方核心系统的破绽",
                "scene": "行动计划、潜入、追逃或局部战斗形成节奏峰值",
            },
            {
                "title_prefix": "真相",
                "goal": "揭开一层关键真相，但同时制造更大的疑问",
                "pressure": "真相动摇主角阵营的正当性，旧认知被迫重估",
                "turning_point": "认知反转",
                "hook": "更高层级的幕后存在",
                "scene": "调查、连接、档案读取或幸存者证词构成信息高潮",
            },
            {
                "title_prefix": "败局",
                "goal": "安排中段重大失败，让主角失去重要依靠或安全据点",
                "pressure": "计划失败、据点暴露、关键人物受损或阵营瓦解",
                "turning_point": "跌入低谷",
                "hook": "绝境中的唯一线索",
                "scene": "围剿、撤离、牺牲和临时决断压缩在同一章内",
            },
            {
                "title_prefix": "重构",
                "goal": "主角从失败中重建路线，重新定义胜利条件",
                "pressure": "资源不足、信任破裂，主角必须说服或整合残余力量",
                "turning_point": "新路线成形",
                "hook": "反攻所需的最后拼图",
                "scene": "疗伤、复盘、谈判和小规模验证行动穿插推进",
            },
            {
                "title_prefix": "深入",
                "goal": "进入敌方或核心秘密区域，推动主线接近最终答案",
                "pressure": "每推进一步都会触发更高等级防御和心理诱惑",
                "turning_point": "核心逼近",
                "hook": "最终选择的道德代价",
                "scene": "潜入核心、意识对抗、机械封锁或虚实切换形成压迫",
            },
            {
                "title_prefix": "燃点",
                "goal": "把长期伏笔集中引爆，让主要人物完成关键站队",
                "pressure": "敌我双方都要求主角立刻做出不可逆选择",
                "turning_point": "终局开门",
                "hook": "最后战场的位置或规则",
                "scene": "多线会合、伏笔回收和阵营摊牌同步发生",
            },
            {
                "title_prefix": "终局",
                "goal": "推动最终对决，解决核心矛盾并完成主题表达",
                "pressure": "胜利会伴随牺牲，错误选择会导致世界秩序崩塌",
                "turning_point": "最终抉择",
                "hook": "新秩序的隐患",
                "scene": "终极对抗、牺牲、反转和结果落地构成高潮",
            },
            {
                "title_prefix": "新生",
                "goal": "收束战后影响，交代人物归宿和新世界规则",
                "pressure": "旧问题并未完全消失，新秩序需要被选择和守护",
                "turning_point": "余韵收束",
                "hook": "下一部或番外的可能性",
                "scene": "战后清点、告别、重建和远方新信号形成尾声",
            },
        ]
        if total_chapters <= 1:
            return stages[0]
        progress = chapter_index / max(total_chapters - 1, 1)
        idx = min(int(progress * len(stages)), len(stages) - 1)
        return stages[idx]

    def _beat_for(self, chapter_index: int) -> dict[str, str]:
        beats = [
            {"title_suffix": "初现", "goal_focus": "确认异常来源", "conflict_focus": "线索被截断或伪造", "scene_focus": "发现异常并快速验证"},
            {"title_suffix": "暗涌", "goal_focus": "追踪隐藏线索", "conflict_focus": "追踪过程暴露位置", "scene_focus": "追踪、误导和反追踪"},
            {"title_suffix": "试探", "goal_focus": "与关键人物或势力接触", "conflict_focus": "对方提出难以接受的条件", "scene_focus": "谈判与试探交锋"},
            {"title_suffix": "失控", "goal_focus": "处理突发危机", "conflict_focus": "计划被打乱，局面超出预期", "scene_focus": "突发事件打断原计划"},
            {"title_suffix": "代价", "goal_focus": "完成一次冒险交换", "conflict_focus": "必须在保护个人和推进大局间取舍", "scene_focus": "选择、牺牲与后果"},
            {"title_suffix": "裂口", "goal_focus": "撕开敌方防线的一角", "conflict_focus": "敌方以更高权限或武力压制", "scene_focus": "局部突破和反扑"},
            {"title_suffix": "回声", "goal_focus": "让旧伏笔产生回应", "conflict_focus": "伏笔答案带来新的不安", "scene_focus": "旧线索回收并产生反转"},
            {"title_suffix": "逆转", "goal_focus": "利用新信息扭转局面", "conflict_focus": "胜利不完整，隐藏更大风险", "scene_focus": "反击、反转和新钩子"},
        ]
        return beats[chapter_index % len(beats)]

    def _extract_title_from_goal(self, goal: str, focus: str, chapter_index: int) -> str:
        """Extract a short meaningful title from the chapter goal instead of template prefix+suffix.

        策略：从 goal 中提取核心名词短语（2-4字），优先取第一个逗号前的核心概念。
        P0 修复：递归剥除所有可能的前缀，剔除脏词
        """
        parts = re.split(r'[，,；;。]', goal)
        first_part = (parts[0] if parts else goal).strip()

        # P0 修复：扩展动词前缀列表，覆盖所有 stage goal 模板
        verb_prefixes = [
            # 多字前缀（先匹配长的）
            "处理上一阶段", "把前文主线", "把长期伏笔", "把整部小说",
            "进入敌方或", "进入核心", "进入最终",
            "主角收束", "主角离开", "主角从", "主角必须",
            "敌方主动", "敌方或核心", "敌方开始",
            "揭开一层", "揭开真相", "揭开",
            "安排中段", "安排一次", "安排",
            "真相揭开", "败局安排", "重构让", "深入进入", "燃点把",
            "终局推动", "新生收束",
            "余波处理", "裂痕扩大", "远行让",
            "推动", "让主角", "让", "把前文", "把长期", "把", "收束",
            "进入", "主角", "敌方", "处理", "完成", "回收", "引爆",
            "主线推进", "从", "在", "通过", "围绕", "聚焦", "揭示",
        ]
        # 递归剥除（最多 3 次，处理"让主角离开"这种多层）
        for _ in range(3):
            stripped = False
            for prefix in verb_prefixes:
                if first_part.startswith(prefix):
                    first_part = first_part[len(prefix):]
                    stripped = True
                    break
            if not stripped:
                break

        # 去掉"的""与""和"开头
        first_part = first_part.lstrip("的与和")

        # P0 修复：如果还是脏词，尝试从 focus 取
        title_text = first_part[:5].strip()
        if self._is_dirty_title(title_text) or len(title_text) < 2 or title_text in {"事件", "情况", "问题", "局面", "真相", "对手", "结果", "目标"}:
            title_text = (focus or "")[:5].strip()
        if self._is_dirty_title(title_text) or len(title_text) < 2:
            # 终极兜底：用 chapter_index
            title_text = f"第{chapter_index + 1}节"

        return title_text

    # P0 修复：脏词标题判定
    DIRTY_TITLE_PATTERNS = [
        "主角", "中段", "长期", "战后", "终局", "一层", "敌方", "从失败",
        "燃点", "反制", "败局", "远行", "重构", "深入", "新生", "余波",
        "裂痕", "本章", "大结局",
        "主动升级", "主动升",
        "最终对决", "最终抉",
        "层次", "阶段", "事件", "情况", "问题", "局面",
        "目标", "压力", "代价", "节点",
        "承接前序", "前序线索",
    ]

    def _is_dirty_title(self, title: str) -> bool:
        """检测标题是否仍包含策划阶段词/抽象词"""
        if not title:
            return True
        # 短标题（<=2字）几乎一定是脏词
        if len(title) <= 2:
            return True
        for pat in self.DIRTY_TITLE_PATTERNS:
            if pat in title:
                return True
        return False

    def _llm_title_for_batch(self, batch: list[tuple[str, str, int, int]], existing: list[ChapterOutline]) -> str:
        """P0 修复：批量调用 LLM 生成有意义标题（同步一次生成多章，节省 token）

        Args:
            batch: list of (goal, focus, chapter_index, total_chapters)
            existing: 已有的章节大纲（用于上下文）
        """
        import asyncio
        if not batch:
            return ""
        # 构造 prompt
        items = []
        for goal, focus, idx, total in batch:
            items.append(f"第{idx+1}章（{idx+1}/{total}）\n目标：{goal[:80]}\n冲突：{focus[:60]}")
        recent_titles = [c.title for c in existing[-6:]]
        prompt = f"""请为以下网络小说章节生成具体的2-5字中文标题，要求：
1. 直接反映本章核心事件/转折/新角色
2. 禁止使用抽象阶段词（禁止：主角、中段、长期、战后、终局、一层、敌方、从失败、燃点、反制、败局、远行、重构、深入、新生、余波、裂痕）
3. 标题必须与最近章节不重复
4. 只输出标题本身，不要序号不要标点不要引号

最近章节标题：{', '.join(recent_titles) if recent_titles else '无'}

待命名章节：
{chr(10).join(items)}

按顺序输出 N 行标题（每行一个，对应一个章节）："""
        try:
            result = call_llm(TaskType.PLAN, prompt, system="你是一个网文编辑，专精章节命名。", temperature=0.6)
            lines = [l.strip() for l in result.split('\n') if l.strip()]
            if lines:
                # 取第一个标题（调用方只取第一个）
                return self._sanitize_story_text(lines[0], 12).strip()
        except Exception as e:
            logger.warning(f"LLM title generation failed: {e}")
        return ""

    def _llm_title_for_chapter(self, goal: str, focus: str, chapter_index: int, total: int, existing: list[ChapterOutline] = None) -> str:
        """P0 修复：单章 LLM 标题生成（保留旧接口以兼容）"""
        return self._llm_title_for_batch([(goal, focus, chapter_index, total)], existing or [])

    def _anchor_text(self, outline: str, existing: list[ChapterOutline]) -> str:
        for chapter in reversed(existing[-6:]):
            if any(marker in (chapter.title or "") for marker in ["终局", "最终", "大结局"]):
                text = (chapter.title or chapter.conflict or "").strip()
            else:
                text = (chapter.goal or chapter.conflict or chapter.title or "").strip()
            if "承接前序线索" in text:
                text = (chapter.title or chapter.conflict or "").strip()
            if text:
                return self._sanitize_story_text(text, 42)
        return self._sanitize_story_text(outline or "核心设定", 42)

    def _extract_core_promise(self, outline: str) -> str:
        text = " ".join((outline or "").split())
        if not text:
            return "主角能否完成最初承诺"
        for sep in ["。", "！", "？", "\n"]:
            if sep in text:
                text = text.split(sep, 1)[0]
                break
        text = self._sanitize_story_text(text, 36)
        if any(marker in text for marker in ["悬疑", "轻科幻", "心理惊悚", "/"]) or len(text) < 8:
            return "主角能否揭开真相并完成自我救赎"
        return text or "主角能否完成最初承诺"

    def _extract_unresolved_from_existing(self, existing: list[ChapterOutline]) -> str:
        for chapter in reversed(existing[-6:]):
            text = " ".join([chapter.goal or "", chapter.conflict or "", chapter.title or ""]).strip()
            if text:
                text = text.replace("承接前序线索", "").replace("本章重点是", "")
                text = self._sanitize_story_text(text, 30)
                if text:
                    return text
        return "前文埋下的关键真相与关系裂口"

    async def split_into_scenes(self, chapter: ChapterOutline, character_names: list[str] = None) -> ChapterOutline:
        prompt = SCENE_SPLIT_PROMPT.format(
            title=chapter.title,
            goal=chapter.goal,
            conflict=chapter.conflict,
            characters=", ".join(character_names or []),
        )
        try:
            result = await call_llm(TaskType.PLAN, prompt, system="输出JSON数组", json_mode=True, temperature=0.5)
        except Exception as e:
            logger.warning(f"Scene split failed, using default: {e}")
            chapter.scenes = [SceneOutline(description=chapter.goal, target_words=max(settings.CHAPTER_MIN_WORDS, settings.SCENE_TARGET_WORDS))]
            return chapter
        try:
            if isinstance(result, dict):
                result = result.get("scenes", result.get("data", []))
            scenes = [SceneOutline(**s) for s in result]
            chapter.scenes = scenes
        except Exception as e:
            logger.warning(f"Scene split failed, using default: {e}")
            chapter.scenes = [SceneOutline(description=chapter.goal, target_words=max(settings.CHAPTER_MIN_WORDS, settings.SCENE_TARGET_WORDS))]
        return chapter
