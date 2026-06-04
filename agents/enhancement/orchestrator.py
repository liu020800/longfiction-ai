import json
import re
import logging
from .enhancement_config import EnhancementConfig
from .models import EnhancementState
from .readback_manager import ReadbackManager
from .anti_resolution import AntiResolutionBrake
from core.word_counter import count_chinese_words
from .event_matrix import EventMatrix
from .progress_manager import ProgressManager
from .structure_enforcer import StructureEnforcer
from .entry_mode_manager import EntryModeManager
from .info_gap_manager import InfoGapManager
from .suspense_arc_manager import SuspenseArcManager
from .rhythm_planner import RhythmPlanner
from .prompt_enhancer import PromptEnhancer
from .quality_scorer import QualityScorer
from .outline_adjuster import OutlineAdjuster
from .thread_pool import ThreadPool

logger = logging.getLogger(__name__)

# P1 修复：AI 痕迹密度监控
AI_TRACE_DENSITY_PHRASES = [
    "——不是", "，像是", "指节发白", "喉咙发干", "喉咙发紧",
    "瞳孔微缩", "瞳孔骤缩", "手心出汗", "手心冒汗", "表情很干净",
    "心中涌起", "心中升起", "一股暖流", "一股寒意",
    "倒吸一口凉气", "浑身一震", "不可思议", "难以置信",
    "值得注意的是", "显而易见", "众所周知",
    "脑子里某根弦", "后颈的毛发", "后颈一凉", "后颈发凉",
]
# 每千字 AI 痕迹上限
AI_TRACE_DENSITY_THRESHOLD = 2.0

REWRITE_DENSE_AI_TRACE_PROMPT = """请把以下段落改写得更加自然、更像真人写作，去除AI感。

【原始段落】
{paragraph}

【必须避免的AI痕迹词】
{forbidden}

【要求】
1. 保留原意、人物动作、情节、对话不变
2. 改写表达方式：把"——不是...是..."换成更自然的自我修正
3. 把抽象的"像是..."换成具体细节
4. 把重复的微动作（"喉咙发干"等）替换为不同表达
5. 字数与原文相近

请直接输出改写后的段落，不要解释："""

class EnhancementOrchestrator:
    def __init__(self, config: EnhancementConfig = None, memory_system=None, llm_call=None):
        self.config = config or EnhancementConfig()
        self.llm_call = llm_call
        self.quality_scores_history: list[dict] = []

        self.readback = ReadbackManager(memory_system, self.config)
        self.brake = AntiResolutionBrake(self.config, llm_call)
        self.event_matrix = EventMatrix(self.config, llm_call)
        self.progress = ProgressManager(self.config)
        self.structure = StructureEnforcer(self.config)
        self.entry_mode = EntryModeManager(self.config)
        self.info_gap = InfoGapManager(self.config)
        self.suspense_arcs = SuspenseArcManager(self.config)
        self.rhythm = RhythmPlanner(self.config)
        self.prompt_enhancer = PromptEnhancer(self.config)
        self.quality_scorer = QualityScorer(self.config, llm_call)
        self.outline_adjuster = OutlineAdjuster(self.config, llm_call)
        self.thread_pool = ThreadPool(self.config)

    def pre_generation(self, chapter_index: int, total_chapters: int, task_id: str = "", target_words: int = 2000, pacing_label: str = "normal") -> dict:
        instructions = []

        # 线程合约强制任务（最高优先级，放在最前面）
        thread_snapshot = self.thread_pool.get_snapshot_text(chapter_index)
        if thread_snapshot and "当前无活跃线程" not in thread_snapshot:
            instructions.append(("线程合约", thread_snapshot))

        readback_result = self.readback.get_readback_context(chapter_index, task_id)
        if readback_result.context_text:
            instructions.append(("回读上下文", readback_result.context_text))

        brake_inst = self.brake.generate_brake_instruction(chapter_index, total_chapters)
        if brake_inst:
            instructions.append(("反向刹车", brake_inst))

        event_inst = self.event_matrix.generate_event_constraint(chapter_index)
        if event_inst:
            instructions.append(("事件约束", event_inst))

        structure_inst = self.structure.get_structure_instruction(target_words)
        if structure_inst:
            instructions.append(("章节结构", structure_inst))

        entry_inst = self.entry_mode.generate_entry_constraint(chapter_index)
        if entry_inst:
            instructions.append(("叙事入口", entry_inst))

        info_gap_inst = self.info_gap.generate_info_gap_instruction()
        if info_gap_inst:
            instructions.append(("信息差", info_gap_inst))

        arc_inst = self.suspense_arcs.generate_arc_instruction(chapter_index)
        if arc_inst:
            instructions.append(("悬念弧", arc_inst))

        rhythm_inst = self.rhythm.generate_rhythm_constraint(chapter_index, pacing_label)
        if rhythm_inst:
            instructions.append(("节奏约束", rhythm_inst))

        prompt_addition = self.prompt_enhancer.build_enhanced_system_prompt()
        if prompt_addition:
            instructions.append(("技巧库", prompt_addition))

        return {
            "instructions": instructions,
            "readback_context": readback_result.context_text,
            "combined_instruction": "\n".join(inst for _, inst in instructions),
        }

    def post_generation(self, chapter_text: str, chapter_index: int, total_chapters: int, context_tags: list[str] | None = None, previous_ending: str = "") -> dict:
        context_tags = context_tags or []
        results = {}

        brake_result = self.brake.check_and_intercept(chapter_text, chapter_index, total_chapters, context_tags=context_tags)
        results["brake"] = brake_result

        events = self.event_matrix.classify_events(chapter_text, chapter_index)
        cooldown_result = self.event_matrix.check_cooldown(chapter_index, context_tags=context_tags)
        results["cooldown_violations"] = cooldown_result.violations
        results["events"] = events

        structure_result = self.structure.check_structure(chapter_text, count_chinese_words(chapter_text))
        results["structure"] = structure_result

        # AI痕迹检测
        ai_trace_result = self._check_ai_traces(chapter_text)
        results["ai_traces"] = ai_trace_result
        # P1 修复：AI 痕迹密度（每千字）
        results["ai_trace_density"] = self.ai_trace_density(chapter_text)

        # 跨章衔接检查
        if previous_ending and chapter_index > 1:
            continuity_result = self._check_chapter_continuity(previous_ending, chapter_text, chapter_index)
            results["continuity"] = continuity_result
            if continuity_result.get("warnings"):
                logger.warning(f"  Chapter {chapter_index} continuity warnings: {continuity_result['warnings']}")

        self.event_matrix.update_cooldown_state(events)
        self.info_gap.update_after_chapter(chapter_text, chapter_index)
        self.suspense_arcs.update_after_chapter(chapter_text, chapter_index)

        # 线程池：规则化提取线程推进/闭合状态
        self._extract_thread_state_from_text(chapter_text, chapter_index)

        should_retry = brake_result.blocked or len(cooldown_result.violations) > 0
        results["should_retry"] = should_retry
        results["retry_reason"] = ""
        if brake_result.blocked:
            results["retry_reason"] = brake_result.reason
        elif cooldown_result.violations:
            results["retry_reason"] = f"事件冷却违规: {', '.join(cooldown_result.violations)}"

        # P2 程序级修复：AI 痕迹密度的标记和元信息保留在 results，但实际稀释由调用方（main_pipeline）显式调用
        # 因为 dilute_ai_traces 是 async 方法，不能在 sync 的 post_generation 中直接 await
        # 调用方应在 post_generation 之后用 `await enhancement.dilute_ai_traces(text, idx)` 取得稀释文本
        results["diluted_text"] = chapter_text  # 占位；调用方需替换
        results["text_was_diluted"] = False

        return results

    def _check_chapter_continuity(self, previous_ending: str, current_text: str, chapter_index: int) -> dict:
        """检查相邻章节的衔接连续性（规则检测，不调用LLM）。"""
        warnings = []
        prev_tail = previous_ending[-300:] if previous_ending else ""
        curr_head = current_text[:300] if current_text else ""

        if not prev_tail or not curr_head:
            return {"warnings": warnings}

        # 检测明显的场景跳转（前章结尾和本章开头的地点词不匹配）
        location_patterns = [
            (r'(?:地下室|地堡|隧道|管道)', "地下"),
            (r'(?:楼顶|天台|屋顶)', "高处"),
            (r'(?:医院|诊所)', "医疗"),
            (r'(?:酒吧|餐厅|饭店)', "餐饮"),
            (r'(?:森林|树林|树丛)', "野外"),
        ]
        prev_locations = {name for pat, name in location_patterns if re.search(pat, prev_tail)}
        curr_locations = {name for pat, name in location_patterns if re.search(pat, curr_head)}
        # 如果前章结尾和本章开头都有明确地点，但地点不同，可能是跳转
        if prev_locations and curr_locations and not (prev_locations & curr_locations):
            # 这不一定是问题（可能是有意的场景切换），只记录为 warning
            pass  # 不添加 warning，因为场景切换是正常的

        # 检测时间连续性：如果前章结尾是"夜晚/深夜"，本章开头是"清晨/早上"，需要有过渡
        time_end_patterns = {
            r'(?:深夜|半夜|凌晨|天黑)': "夜晚",
            r'(?:清晨|早上|天亮|黎明)': "清晨",
            r'(?:中午|正午|午后)': "白天",
        }
        prev_time = None
        curr_time = None
        for pat, label in time_end_patterns.items():
            if re.search(pat, prev_tail):
                prev_time = label
            if re.search(pat, curr_head):
                curr_time = label
        # 只在时间明显矛盾时警告（如深夜→中午没有过渡）
        if prev_time == "夜晚" and curr_time == "白天":
            # 这可能是正常的时间推移，不一定是问题
            pass

        return {"warnings": warnings}

    def _extract_thread_state_from_text(self, chapter_text: str, chapter_index: int):
        """规则化提取：检测章节中的线程推进和闭合。

        闭合判定：线程描述中的核心名词 + 强闭合关键词同时出现。
        推进判定：线程描述中的核心名词 + 弱推进关键词同时出现。
        避免单一关键词（如"真相"）导致误判。
        """
        if not chapter_text or not self.thread_pool.threads:
            return

        # 强闭合关键词（必须与线程描述词共现才算闭合）
        closure_keywords = ["真相大白", "水落石出", "终于明白", "彻底揭开",
                           "证实了", "承认了", "揭穿了", "坦白了", "暴露了"]
        # 弱推进关键词（单独出现不算推进，需要与线程描述词共现）
        advance_keywords = ["线索", "发现", "追查", "接触", "疑点", "暗示",
                           "回忆起", "提到", "提起", "旧事", "当年"]

        for thread in self.thread_pool.threads:
            if thread.status == "closed":
                continue
            # 提取线程描述中的核心名词（≥2字的中文词）
            desc_parts = re.split(r"[，。、；\s]+", thread.description)
            desc_keywords = {p for p in desc_parts if len(p) >= 2}
            if not desc_keywords:
                continue

            # 检查闭合：需要线程描述词 + 强闭合词同时出现
            for kw in desc_keywords:
                if kw in chapter_text:
                    for ck in closure_keywords:
                        if ck in chapter_text:
                            self.thread_pool.close(thread.thread_id, f"规则检测闭合（ch{chapter_index}）: {kw}+{ck}")
                            break
                    break  # 一个线程描述词命中就够了

            # 检查推进（如果线程未被闭合）
            if thread.status != "closed":
                for kw in desc_keywords:
                    if kw in chapter_text:
                        for ak in advance_keywords:
                            if ak in chapter_text:
                                self.thread_pool.advance(thread.thread_id, chapter_index, f"关键词命中: {kw}+{ak}")
                                break
                        break

    def _check_ai_traces(self, chapter_text: str) -> dict:
        """检测章节中的AI痕迹短语，返回超标情况。"""
        # 高频AI短语及其每章限制（只保留通用的写作模式，不含题材特定词汇）
        trace_phrases = {
            "——不是": 1,
            "，像是": 1,
            "指节发白": 0,
            "瞳孔微缩": 0,
            "瞳孔骤缩": 0,
            "手心出汗": 0,
            "手心冒汗": 0,
            "表情很干净": 0,
            "心中涌起": 0,
            "心中升起": 0,
            "一股暖流": 0,
            "一股寒意": 0,
            "倒吸一口凉气": 0,
            "浑身一震": 0,
            "不可思议": 0,
            "难以置信": 0,
            "值得注意的是": 0,
            "显而易见": 0,
            "众所周知": 0,
        }
        # 倒计时模式
        countdown_pattern = re.compile(r'还有\d+[分钟秒]')
        countdown_matches = countdown_pattern.findall(chapter_text)

        violations = []
        phrase_counts = {}
        for phrase, limit in trace_phrases.items():
            count = chapter_text.count(phrase)
            if count > 0:
                phrase_counts[phrase] = count
                if count > limit:
                    violations.append(f"「{phrase}」出现{count}次（限制{limit}次）")

        # 检查倒计时
        if len(countdown_matches) > 1:
            violations.append(f"倒计时描写出现{len(countdown_matches)}次（限制1次）")
        if countdown_matches:
            phrase_counts["倒计时"] = len(countdown_matches)

        # 检查"——不是X，是Y"结构
        dash_not_pattern = re.compile(r'——不是[^，。]+[，，]是[^。！？]+')
        dash_not_matches = dash_not_pattern.findall(chapter_text)
        if len(dash_not_matches) > 1:
            violations.append(f"「——不是X，是Y」结构出现{len(dash_not_matches)}次（限制1次）")
        if dash_not_matches:
            phrase_counts["——不是X，是Y"] = len(dash_not_matches)

        total_traces = sum(phrase_counts.values())

        # 动态词频检测：统计所有2-4字中文词的出现频率，标记过度重复的词
        word_freq = self._detect_word_repetition(chapter_text)
        word_violations = word_freq.get("violations", [])

        all_violations = violations + word_violations
        return {
            "phrase_counts": phrase_counts,
            "word_frequency": word_freq.get("top_words", {}),
            "violations": all_violations,
            "total_traces": total_traces,
            "has_violations": len(all_violations) > 0,
        }

    # P1 修复：AI 痕迹稀释
    def count_ai_traces(self, text: str) -> dict[str, int]:
        """统计指定文本中各 AI 痕迹短语的出现次数。"""
        if not text:
            return {}
        return {p: text.count(p) for p in AI_TRACE_DENSITY_PHRASES if text.count(p) > 0}

    def ai_trace_density(self, text: str) -> float:
        """计算每千字的 AI 痕迹密度"""
        total = count_chinese_words(text)
        if total == 0:
            return 0
        traces = self.count_ai_traces(text)
        return sum(traces.values()) / total * 1000

    async def dilute_ai_traces(self, text: str, chapter_idx: int) -> str:
        """P1 修复：AI 痕迹密度超标时调用 LLM 改写

        策略：找出 AI 痕迹最密集的段落，调用 LLM 改写（不改情节，只改表达）
        """
        if not text or len(text) < 200:
            return text
        if self.ai_trace_density(text) < AI_TRACE_DENSITY_THRESHOLD:
            return text
        if not self.llm_call:
            logger.debug(f"No LLM call available, skipping AI trace dilution for ch {chapter_idx}")
            return text

        # 找出 AI 痕迹最密集的段落（按段落切分）
        paragraphs = self._split_paragraphs(text)
        dense_indices = []
        for i, p in enumerate(paragraphs):
            if len(p) < 80:
                continue
            density = self.ai_trace_density(p)
            if density > AI_TRACE_DENSITY_THRESHOLD * 1.5:
                dense_indices.append((i, density))
        dense_indices.sort(key=lambda x: -x[1])

        # 一次最多改写 3 段
        rewritten_count = 0
        for idx, _ in dense_indices[:3]:
            original = paragraphs[idx]
            try:
                rewritten = await self.llm_call(
                    prompt=REWRITE_DENSE_AI_TRACE_PROMPT.format(
                        paragraph=original,
                        forbidden="、".join(list(AI_TRACE_DENSITY_PHRASES)[:5]),
                    ),
                    system="你是一个改写高手，专精把AI感浓厚的句子改成自然的人话。",
                    temperature=0.7,
                    max_tokens=len(original) * 2 + 100,
                )
                if rewritten and count_chinese_words(rewritten) >= count_chinese_words(original) * 0.7:
                    paragraphs[idx] = rewritten
                    rewritten_count += 1
            except Exception as e:
                logger.warning(f"AI trace rewrite failed for paragraph {idx} in ch {chapter_idx}: {e}")

        if rewritten_count > 0:
            logger.info(f"Diluted {rewritten_count} AI-trace-dense paragraphs in ch {chapter_idx}")
        return "\n".join(paragraphs)

    @staticmethod
    def _split_paragraphs(text: str) -> list[str]:
        """按双换行切分段落"""
        return [p for p in re.split(r'\n\n+', text) if p.strip()]

    def _detect_word_repetition(self, text: str) -> dict:
        """动态检测章节中过度重复的词（通用，不依赖固定词表）。

        使用统计方法：提取所有2-4字中文词频，标记超过阈值的词。
        阈值 = max(3, 中文字数 / 300)，即大约每300字允许出现1次。
        """
        if not text or len(text) < 50:
            return {"top_words": {}, "violations": []}

        # 计算纯中文字数（不含标点、空格、ASCII）
        chinese_char_count = len(re.findall(r'[一-鿿]', text))

        # 常见功能词（停用词），不参与重复检测
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
            "他的", "她的", "它的", "我的", "你的", "我们", "他们",
            "说道", "说道", "一个", "不了", "没有", "这个", "那个",
        }

        # 提取2-4字中文词（连续中文字符序列）
        words = re.findall(r'[一-鿿]{2,4}', text)
        freq: dict[str, int] = {}
        for w in words:
            if w in stopwords:
                continue
            freq[w] = freq.get(w, 0) + 1

        # 动态阈值：每300字允许1次，最低3次（基于中文字数，非总字符数）
        threshold = max(3, chinese_char_count // 300)
        top_words = {}
        violations = []
        for word, count in sorted(freq.items(), key=lambda x: -x[1]):
            if count < 3:
                break
            top_words[word] = count
            if count > threshold:
                violations.append(f"「{word}」出现{count}次（本章阈值{threshold}次）")

        return {"top_words": top_words, "violations": violations[:5]}

    async def extract_threads_with_llm(self, chapter_text: str, chapter_index: int) -> dict:
        """LLM 结构化提取线程状态（可选的深度提取，需要独立 LLM 调用）。"""
        if not self.llm_call:
            return {}
        active_threads = self.thread_pool.get_active()
        if not active_threads:
            return {}
        thread_list = "\n".join([f"- {t.thread_id}: 「{t.description}」(类型:{t.type}, 已沉默{t.urgency_score}章)" for t in active_threads[:10]])
        prompt = f"""分析以下小说章节，返回JSON格式的线程状态提取结果。

当前活跃线程：
{thread_list}

章节内容（前3000字）：
{chapter_text[:3000]}

请返回JSON（不要输出其他内容）：
{{
  "new_threads": [{{"type": "伏笔或悬念", "description": "新埋的伏笔/悬念描述", "resolution_hint": "回收方向提示"}}],
  "advanced_threads": [{{"thread_id": "推进的线程ID", "note": "推进摘要"}}],
  "closed_threads": ["已闭合的线程ID"],
  "info_reveals": ["本章揭示的信息"],
  "chapter_summary_100": "100字以内本章摘要"
}}"""
        try:
            from core.llm_router import call_llm, TaskType
            result = await call_llm(TaskType.CHECK, prompt, json_mode=True, temperature=0.3)
            if isinstance(result, dict):
                return result
        except Exception as e:
            logger.debug(f"LLM thread extraction failed, using rule-based fallback: {e}")
        return {}

    def apply_llm_extraction(self, extraction: dict, chapter_index: int):
        """应用 LLM 提取结果到线程池。"""
        if not extraction:
            return
        # 新线程
        for item in extraction.get("new_threads", []):
            desc = item.get("description", "").strip()
            if desc:
                self.thread_pool.plant(
                    description=desc,
                    planted_chapter=chapter_index,
                    thread_type=item.get("type", "伏笔"),
                    resolution_hint=item.get("resolution_hint", ""),
                    source="llm_extract",
                )
        # 推进
        for item in extraction.get("advanced_threads", []):
            tid = item.get("thread_id", "")
            note = item.get("note", "")
            if tid:
                self.thread_pool.advance(tid, chapter_index, note)
        # 闭合
        for tid in extraction.get("closed_threads", []):
            if tid:
                self.thread_pool.close(tid, f"LLM提取确认（ch{chapter_index}）")

    def record_quality_metrics(self, chapter_index: int, consistency_score: float, ai_score: float, issues: list[str], shortfalls: list[str] = None):
        """Record lightweight rule-based quality metrics (no LLM call)."""
        score = round(consistency_score * 10, 1)  # normalize to 0-10 scale
        entry = {
            "chapter_index": chapter_index,
            "composite_score": score,
            "ai_score": round(ai_score, 3),
            "consistency_score": round(consistency_score, 3),
            "dimension_scores": {
                "coherence": round(consistency_score * 10, 1),
                "language": round(ai_score * 10, 1),
            },
            "issues": issues[:5],
            "shortfalls_short": shortfalls or [],
        }
        self.quality_scores_history.append(entry)
        if len(self.quality_scores_history) > 30:
            self.quality_scores_history = self.quality_scores_history[-30:]

    async def post_critic(self, chapter_text: str, prev_summary: str = "", chapter_index: int = -1) -> dict:
        results = {}

        quality = await self.quality_scorer.score_chapter(chapter_text, prev_summary)
        results["quality"] = quality

        # 保存评分历史
        self.quality_scores_history.append({
            "chapter_index": chapter_index,
            "composite_score": quality.composite_score,
            "dimension_scores": dict(quality.dimension_scores),
            "shortfalls": [{"dimension": s.dimension, "score": s.score, "suggestion": s.suggestion} for s in quality.shortfalls],
        })
        if len(self.quality_scores_history) > 20:
            self.quality_scores_history = self.quality_scores_history[-20:]

        if quality.should_regenerate:
            results["should_regenerate"] = True
            results["regenerate_reason"] = f"综合评分{quality.composite_score}低于阈值{self.config.QUALITY_REGENERATE_THRESHOLD}"

        return results

    def get_state(self) -> dict:
        state = EnhancementState(
            unresolved_issues=self.brake.unresolved_issues,
            consecutive_zero_count=self.brake.consecutive_zero_count,
            cooldown_state=self.event_matrix.cooldown_state,
            anchors=self.progress.anchors,
            anchor_completions=self.progress.anchor_completions,
            info_gap_state=self.info_gap.state,
            suspense_arcs=self.suspense_arcs.arcs,
            quality_scores_history=self.quality_scores_history,
            thread_pool_threads=self.thread_pool.threads,
        ).model_dump()
        return state

    def restore_state(self, state: dict):
        try:
            es = EnhancementState(**state)
            self.brake.unresolved_issues = es.unresolved_issues
            self.brake.consecutive_zero_count = es.consecutive_zero_count
            self.event_matrix.cooldown_state = es.cooldown_state
            self.progress.anchors = es.anchors
            self.progress.anchor_completions = es.anchor_completions
            self.info_gap.state = es.info_gap_state
            self.suspense_arcs.arcs = es.suspense_arcs
            self.quality_scores_history = es.quality_scores_history
            self.thread_pool.threads = es.thread_pool_threads
        except Exception as e:
            logger.warning(f"恢复增强状态失败: {e}")
