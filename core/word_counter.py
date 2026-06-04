import re
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

_CJK_RANGE = (
    (0x4E00, 0x9FFF),
    (0x3400, 0x4DBF),
)

_CHINESE_PUNCTS = set("，。！？；：""''《》（）【】{}—…·、～‖")

_MD_HEADING_RE = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)
_MD_BOLD_ITALIC_RE = re.compile(r"\*{1,2}([^*]+)\*{1,2}")
_MD_LIST_RE = re.compile(r"^[-*+]\s+", re.MULTILINE)
_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def count_chinese_words(text: str) -> int:
    if not text:
        return 0
    cleaned = _MD_HEADING_RE.sub("", text)
    cleaned = _MD_BOLD_ITALIC_RE.sub(r"\1", cleaned)
    cleaned = _MD_LIST_RE.sub("", cleaned)
    count = 0
    i = 0
    while i < len(cleaned):
        ch = cleaned[i]
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _CJK_RANGE):
            count += 1
            i += 1
            continue
        if ch.isalpha() or ch.isdigit():
            match = _ASCII_WORD_RE.match(cleaned, i)
            if match:
                token = match.group(0)
                count += max(1, len(token) // 2)
                i = match.end()
                continue
        i += 1
    return count


class DeviationLevel(Enum):
    SLIGHT = "slight"
    MODERATE = "moderate"
    SEVERE = "severe"


class CorrectionStrategy(Enum):
    NONE = "none"
    EXPAND = "expand"
    TRIM = "trim"


class AllocationMode(Enum):
    FULL = "full"
    UNIFORM = "uniform"
    STRUCTURAL = "structural"
    MERGED = "merged"


@dataclass
class StructureRatios:
    hook: float = 0.20
    development: float = 0.55
    climax: float = 0.17
    tail: float = 0.08


@dataclass
class WordCountReport:
    target_words: int
    actual_words: int
    deviation_rate: float
    deviation_level: DeviationLevel
    correction_strategy: CorrectionStrategy
    correction_attempts: int = 0
    final_words: int = 0
    is_within_tolerance: bool = False


def compute_deviation(actual: int, target: int) -> float:
    if target <= 0:
        return 0.0
    return abs(actual - target) / target * 100.0


def classify_deviation(
    deviation_rate: float, tolerance_pct: float = 15.0
) -> tuple[DeviationLevel, CorrectionStrategy]:
    if deviation_rate <= tolerance_pct:
        return (DeviationLevel.SLIGHT, CorrectionStrategy.NONE)
    if deviation_rate <= 30.0:
        return (DeviationLevel.MODERATE, CorrectionStrategy.EXPAND)
    return (DeviationLevel.SEVERE, CorrectionStrategy.EXPAND)


def _normalize_ratios(ratios: StructureRatios) -> StructureRatios:
    total = ratios.hook + ratios.development + ratios.climax + ratios.tail
    if any(v <= 0 for v in [ratios.hook, ratios.development, ratios.climax, ratios.tail]):
        logger.warning(f"StructureRatios contains non-positive value, using defaults")
        return StructureRatios()
    if abs(total - 1.0) <= 0.01:
        return ratios
    logger.info(f"StructureRatios auto-normalized, original sum={total:.3f}")
    return StructureRatios(
        hook=ratios.hook / total,
        development=ratios.development / total,
        climax=ratios.climax / total,
        tail=ratios.tail / total,
    )


def allocate_scene_words(
    words_per_chapter: int,
    scene_count: int,
    structure_ratios: StructureRatios | None = None,
    min_scene_words: int = 120,
) -> list[int]:
    if scene_count <= 0:
        logger.warning("Scene count <= 0, degrading to single scene")
        return [words_per_chapter]
    if scene_count > 20 and structure_ratios is not None:
        structure_ratios = _normalize_ratios(structure_ratios)
        dev_words = words_per_chapter * structure_ratios.development
        min_dev_scenes = max(1, int(-(-dev_words // min_scene_words)))
        merged_count = 3 + min_dev_scenes
        if merged_count < scene_count:
            logger.warning(f"Scene count {scene_count} > 20, merging to {merged_count} scenes")
            scene_count = merged_count
    if structure_ratios is not None and scene_count >= 2:
        structure_ratios = _normalize_ratios(structure_ratios)
        ratios = _distribute_ratios(scene_count, structure_ratios)
        raw = [words_per_chapter * r for r in ratios]
        floored = [int(v) for v in raw]
        remainders = [(raw[i] - floored[i], i) for i in range(scene_count)]
        remainders.sort(key=lambda x: x[0], reverse=True)
        remainder = words_per_chapter - sum(floored)
        for k in range(remainder):
            floored[remainders[k][1]] += 1
        result = floored
        logger.debug(f"Using structural allocation mode (scenes={scene_count})")
    else:
        base = words_per_chapter // scene_count
        remainder = words_per_chapter - base * scene_count
        result = []
        for i in range(scene_count):
            result.append(base + (1 if i < remainder else 0))
        logger.debug(f"Using uniform allocation mode (scenes={scene_count})")
    for i in range(len(result)):
        if result[i] < min_scene_words:
            result[i] = min_scene_words
    total = sum(result)
    if total != words_per_chapter:
        diff = total - words_per_chapter
        max_idx = result.index(max(result))
        adjustment = min(abs(diff), result[max_idx] - min_scene_words)
        if diff > 0:
            result[max_idx] -= adjustment
        else:
            result[max_idx] += adjustment
        remaining_diff = words_per_chapter - sum(result)
        if remaining_diff != 0:
            for i in range(len(result)):
                if i != max_idx and result[i] > min_scene_words:
                    can_adjust = min(abs(remaining_diff), result[i] - min_scene_words)
                    if remaining_diff > 0:
                        result[i] += can_adjust
                    else:
                        result[i] -= can_adjust
                    remaining_diff = words_per_chapter - sum(result)
                    if remaining_diff == 0:
                        break
    return result


def _distribute_ratios(scene_count: int, ratios: StructureRatios) -> list[float]:
    if scene_count == 1:
        return [1.0]
    if scene_count == 2:
        return [ratios.hook + ratios.development * 0.5, ratios.climax + ratios.tail + ratios.development * 0.5]
    if scene_count == 3:
        return [ratios.hook, ratios.development, ratios.climax + ratios.tail]
    if scene_count == 4:
        return [ratios.hook, ratios.development * 0.5, ratios.development * 0.5, ratios.climax + ratios.tail]
    dev_scenes = scene_count - 3
    dev_each = ratios.development / dev_scenes if dev_scenes > 0 else ratios.development
    result = [ratios.hook]
    for _ in range(dev_scenes):
        result.append(dev_each)
    result.append(ratios.climax)
    result.append(ratios.tail)
    return result


def _rule_based_trim(text: str, target_words: int) -> str:
    if count_chinese_words(text) <= target_words:
        return text
    target_units = max(1, target_words)
    cut_idx = len(text)
    units = 0
    i = 0
    while i < len(text):
        ch = text[i]
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _CJK_RANGE):
            units += 1
        elif ch.isalpha() or ch.isdigit():
            match = _ASCII_WORD_RE.match(text, i)
            if match:
                token = match.group(0)
                units += max(1, len(token) // 2)
                i = match.end() - 1
        if units >= target_units:
            cut_idx = i + 1
            break
        i += 1
    min_pos = max(0, int(cut_idx * 0.8))
    boundary = text.find("\n\n", cut_idx)
    if boundary != -1 and boundary <= min(len(text), cut_idx + 220) and boundary >= min_pos:
        return text[:boundary].rstrip()
    for i in range(min(cut_idx + 220, len(text) - 1), max(min_pos, 0), -1):
        if text[i] in ("。", "！", "？", "\n"):
            trimmed = text[: i + 1].rstrip()
            if count_chinese_words(trimmed) <= target_words * 1.05:
                return trimmed
    return text[:cut_idx].rstrip()


_NARRATIVE_PUSH_KEYWORDS = [
    "但", "却", "然而", "可是", "不过", "竟然", "居然",
    "发现", "意识到", "明白", "醒悟", "察觉", "看清",
    "冲", "抓", "跑", "跳", "挥", "撞", "扯",
    "秘密", "真相", "阴谋", "内幕", "证据",
    "危险", "威胁", "危机", "陷阱", "埋伏",
]

_HOLLOW_PATTERNS = [
    re.compile(r"(风景|景色|环境|氛围).{0,50}(美丽|壮阔|辽阔|苍茫|静谧)"),
    re.compile(r"(心中|内心|心底).{0,30}(涌起|升起|产生|泛起).{0,20}(感觉|情绪|念头)"),
    re.compile(r"(仿佛|宛如|犹如|恰似).{0,40}(一般|一样|似的)"),
]


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？；\n]", text)
    return [s.strip() for s in parts if len(s.strip()) > 5]


def evaluate_expand_quality(
    original_text: str, expanded_text: str, timeout_seconds: float = 5.0
) -> dict:
    start = time.monotonic()
    if not original_text or not expanded_text or count_chinese_words(original_text) < 50:
        return {"score": 0.7, "narrative_push": 0.7, "novelty": 0.7, "consistency": 0.7, "elapsed_ms": 0}
    new_content = expanded_text[len(original_text):] if expanded_text.startswith(original_text) else expanded_text
    new_words = count_chinese_words(new_content)
    if new_words == 0:
        return {"score": 0.5, "narrative_push": 0.5, "novelty": 0.5, "consistency": 0.7, "elapsed_ms": 0}
    push_count = sum(1 for kw in _NARRATIVE_PUSH_KEYWORDS if kw in new_content)
    expected_push = max(1, new_words / 200)
    narrative_push = min(1.0, push_count / expected_push)
    for pattern in _HOLLOW_PATTERNS:
        if pattern.search(new_content):
            narrative_push *= 0.7
            break
    orig_sentences = set(_split_sentences(original_text))
    new_sentences = _split_sentences(new_content)
    if new_sentences:
        duplicate_count = sum(1 for s in new_sentences if s in orig_sentences)
        novelty = 1.0 - duplicate_count / len(new_sentences)
    else:
        novelty = 0.7
    consistency = 0.8
    score = narrative_push * 0.4 + novelty * 0.3 + consistency * 0.3
    elapsed = (time.monotonic() - start) * 1000
    if elapsed > timeout_seconds * 1000:
        logger.warning(f"Expand quality eval took {elapsed:.0f}ms, exceeding {timeout_seconds}s limit")
    return {
        "score": round(score, 3),
        "narrative_push": round(narrative_push, 3),
        "novelty": round(novelty, 3),
        "consistency": consistency,
        "elapsed_ms": round(elapsed, 1),
    }


_CONFLICT_KEYWORDS = ["冲突", "矛盾", "对峙", "争", "吵", "战", "杀", "打"]
_TURNING_POINT_KEYWORDS = ["转折", "反转", "意外", "发现", "真相", "暴露", "揭露", "变"]
_SUSPENSE_KEYWORDS = ["悬念", "谜", "秘密", "究竟", "到底", "未知", "危险", "威胁", "陷阱"]
_MOTIVATION_KEYWORDS = ["动机", "目的", "为了", "因为", "缘故", "原因", "打算", "决心"]
_ALL_PLOT_KEYWORDS = _CONFLICT_KEYWORDS + _TURNING_POINT_KEYWORDS + _SUSPENSE_KEYWORDS + _MOTIVATION_KEYWORDS


def _check_scene_boundaries(original: str, trimmed: str) -> float:
    orig_paras = [p.strip() for p in original.split("\n\n") if p.strip()]
    trim_paras = [p.strip() for p in trimmed.split("\n\n") if p.strip()]
    if not orig_paras:
        return 1.0
    preserved = 0
    for para in orig_paras:
        first_10 = para[:10] if len(para) >= 10 else para
        last_10 = para[-10:] if len(para) >= 10 else para
        for tp in trim_paras:
            if first_10 in tp or last_10 in tp:
                preserved += 1
                break
    return preserved / len(orig_paras)


def evaluate_trim_completeness(
    original_text: str, trimmed_text: str, timeout_seconds: float = 5.0
) -> dict:
    start = time.monotonic()
    if not original_text or not trimmed_text or count_chinese_words(original_text) < 50:
        return {"score": 0.8, "keyword_retention": 0.8, "structure_integrity": 0.8, "boundary_integrity": 0.8, "elapsed_ms": 0}
    orig_keywords = [kw for kw in _ALL_PLOT_KEYWORDS if kw in original_text]
    if orig_keywords:
        retained = sum(1 for kw in orig_keywords if kw in trimmed_text)
        keyword_retention = retained / len(orig_keywords)
    else:
        keyword_retention = 1.0
    orig_paras = [p for p in original_text.split("\n\n") if p.strip()]
    trim_paras = [p for p in trimmed_text.split("\n\n") if p.strip()]
    if orig_paras:
        structure_integrity = min(1.0, len(trim_paras) / len(orig_paras))
        if len(trim_paras) < len(orig_paras) * 0.6:
            structure_integrity *= 0.7
    else:
        structure_integrity = 1.0
    boundary_integrity = _check_scene_boundaries(original_text, trimmed_text)
    score = keyword_retention * 0.5 + structure_integrity * 0.3 + boundary_integrity * 0.2
    elapsed = (time.monotonic() - start) * 1000
    return {
        "score": round(score, 3),
        "keyword_retention": round(keyword_retention, 3),
        "structure_integrity": round(structure_integrity, 3),
        "boundary_integrity": round(boundary_integrity, 3),
        "elapsed_ms": round(elapsed, 1),
    }


_DESCRIPTION_KEYWORDS = set("看望光暗风声思想想觉感听闻嗅触冷热温湿")


def _extract_style_features(text: str) -> dict:
    sentences = _split_sentences(text)
    if not sentences:
        return {"avg_sentence_length": 0.0, "dialogue_ratio": 0.0, "description_density": 0.0}
    lengths = [count_chinese_words(s) for s in sentences]
    avg_len = sum(lengths) / len(lengths) if lengths else 0.0
    dialogue_count = sum(1 for s in sentences if any(q in s for q in ['\u201c', '\u201d', '\u300c', '\u300d', '"']))
    dialogue_ratio = dialogue_count / len(sentences)
    desc_count = 0
    for s in sentences:
        has_dialogue = any(q in s for q in ['\u201c', '\u201d', '\u300c', '\u300d', '"'])
        has_desc = any(c in _DESCRIPTION_KEYWORDS for c in s)
        if not has_dialogue and has_desc:
            desc_count += 1
    description_density = desc_count / len(sentences)
    return {
        "avg_sentence_length": round(avg_len, 1),
        "dialogue_ratio": round(dialogue_ratio, 3),
        "description_density": round(description_density, 3),
    }


def _relative_change(old: float, new: float) -> float:
    if old == 0:
        return 0.0 if new == 0 else 1.0
    return min(1.0, abs(new - old) / old)


def compute_style_drift(baseline_text: str, current_text: str) -> dict:
    baseline = _extract_style_features(baseline_text)
    current = _extract_style_features(current_text)
    sl_drift = _relative_change(baseline["avg_sentence_length"], current["avg_sentence_length"])
    dr_drift = _relative_change(baseline["dialogue_ratio"], current["dialogue_ratio"])
    dd_drift = _relative_change(baseline["description_density"], current["description_density"])
    drift = sl_drift * 0.3 + dr_drift * 0.4 + dd_drift * 0.3
    return {
        "drift": round(drift, 3),
        "sentence_length_drift": round(sl_drift, 3),
        "dialogue_ratio_drift": round(dr_drift, 3),
        "description_density_drift": round(dd_drift, 3),
    }


@dataclass
class CorrectionSnapshot:
    text: str
    word_count: int
    quality_score: float
    strategy: CorrectionStrategy
    style_drift: float = 0.0
    timestamp: float = 0.0
    deviation: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.monotonic()


@dataclass
class CorrectionHistory:
    snapshots: list[CorrectionSnapshot] = field(default_factory=list)
    max_size: int = 6
    baseline_text: Optional[str] = None

    def save(self, snapshot: CorrectionSnapshot):
        if self.baseline_text is None:
            self.baseline_text = snapshot.text
        self.snapshots.append(snapshot)
        if len(self.snapshots) > self.max_size:
            self.snapshots.pop(0)

    def get_best_version(self, target_words: int) -> tuple[str, float]:
        if not self.snapshots:
            return ("", 100.0)
        tolerance_ok = [
            s for s in self.snapshots
            if compute_deviation(s.word_count, target_words) <= 15.0 and s.quality_score >= 0.7
        ]
        if tolerance_ok:
            best = min(tolerance_ok, key=lambda s: compute_deviation(s.word_count, target_words))
            return (best.text, compute_deviation(best.word_count, target_words))
        by_quality = sorted(self.snapshots, key=lambda s: s.quality_score, reverse=True)
        if by_quality:
            best = by_quality[0]
            return (best.text, compute_deviation(best.word_count, target_words))
        best = min(self.snapshots, key=lambda s: abs(s.word_count - target_words))
        return (best.text, compute_deviation(best.word_count, target_words))


_PROTECTED_NODE_KEYWORDS = _CONFLICT_KEYWORDS + _TURNING_POINT_KEYWORDS + _SUSPENSE_KEYWORDS


def _identify_protected_nodes(text: str) -> list[tuple[int, int]]:
    protected = []
    for match in re.finditer(r'[^\n。！？]+[。！？]', text):
        sentence = match.group()
        if any(kw in sentence for kw in _PROTECTED_NODE_KEYWORDS):
            protected.append((match.start(), match.end()))
    return protected


def _compute_compress_priority(paragraph: str) -> float:
    score = 0.0
    is_dialogue = any(q in paragraph for q in ['\u201c', '\u201d', '\u300c', '\u300d', '"'])
    has_env_desc = any(c in paragraph for c in "看望光暗风声色景山水天地日月星")
    has_transition = any(kw in paragraph for kw in ["于是", "然后", "接着", "随后", "之后", "后来"])
    has_greeting = any(kw in paragraph for kw in ["你好", "再见", "谢谢", "打扰", "请问", "辛苦"])
    has_conflict = any(kw in paragraph for kw in _CONFLICT_KEYWORDS)
    has_turning = any(kw in paragraph for kw in _TURNING_POINT_KEYWORDS)
    has_suspense = any(kw in paragraph for kw in _SUSPENSE_KEYWORDS)
    if has_env_desc and not has_conflict and not has_turning:
        score += 0.4
    if has_transition:
        score += 0.3
    if is_dialogue and has_greeting:
        score += 0.2
    if has_env_desc and not is_dialogue:
        score += 0.1
    if has_conflict or has_turning or has_suspense:
        score -= 0.5
    return max(0.0, min(1.0, score))


async def intelligent_trim(
    text: str,
    target_words: int,
    llm_call=None,
    style_drift_threshold: float = 0.3,
) -> str:
    current_words = count_chinese_words(text)
    if current_words <= target_words:
        return text
    tolerance = target_words * 0.15
    if current_words - target_words <= tolerance:
        return text

    protected_nodes = _identify_protected_nodes(text)
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return _rule_based_trim(text, target_words)

    priorities = [(i, _compute_compress_priority(p)) for i, p in enumerate(paragraphs)]
    priorities.sort(key=lambda x: x[1], reverse=True)

    result_paragraphs = list(paragraphs)
    words_to_cut = current_words - target_words

    for idx, priority in priorities:
        if words_to_cut <= 0:
            break
        para = result_paragraphs[idx]
        is_protected = any(
            ps <= sum(len(p) + 2 for p in result_paragraphs[:idx]) <= pe
            for ps, pe in protected_nodes
        )
        if is_protected and priority < 0.3:
            continue
        cut_ratio = min(0.4, priority * 0.5)
        para_words = count_chinese_words(para)
        cut_words = int(para_words * cut_ratio)
        if cut_words > 0 and para_words - cut_words > 20:
            trimmed_para = _rule_based_trim(para, para_words - cut_words)
            actual_cut = count_chinese_words(para) - count_chinese_words(trimmed_para)
            words_to_cut -= actual_cut
            result_paragraphs[idx] = trimmed_para

    result = "\n\n".join(result_paragraphs)
    remaining_words = count_chinese_words(result)

    if remaining_words > target_words * 1.15 and llm_call is not None:
        try:
            protected_desc = "保护以下内容不可删除：冲突、转折、悬念关键情节"
            prompt = (
                f"请将以下文本压缩到约{target_words}字（中文字数）。\n"
                f"要求：\n1. {protected_desc}\n"
                f"2. 保留核心情节和人物行为\n"
                f"3. 删除冗余环境描写和重复内容\n"
                f"4. 保持原文风格不变\n\n原文：\n{result}"
            )
            llm_result = await llm_call(prompt)
            if llm_result and count_chinese_words(llm_result) <= target_words * 1.1:
                result = llm_result
        except Exception as e:
            logger.warning(f"LLM intelligent trim failed, using rule-based result: {e}")

    if count_chinese_words(result) > target_words:
        result = _rule_based_trim(result, target_words)

    return result


_EXPAND_STRATEGIES = [
    ("dialogue_with_subtext", 0.35, ["潜台词", "言外之意", "话中有话"]),
    ("sensory_details", 0.30, ["感官", "视觉", "听觉", "嗅觉", "触觉"]),
    ("micro_actions", 0.20, ["微动作", "表情", "眼神", "手势"]),
    ("internal_thought", 0.15, ["内心", "思考", "犹豫", "抉择"]),
]


async def intelligent_expand(
    text: str,
    target_words: int,
    llm_call=None,
    style_drift_threshold: float = 0.3,
) -> str:
    current_words = count_chinese_words(text)
    if current_words >= target_words:
        return text
    words_needed = target_words - current_words
    if words_needed < 50:
        return text

    if llm_call is None:
        return text

    strategy_descriptions = []
    for name, weight, hints in _EXPAND_STRATEGIES:
        alloc = int(words_needed * weight)
        if alloc > 0:
            strategy_descriptions.append(
                f"- {name}：增加约{alloc}字，通过{'、'.join(hints)}丰富内容"
            )

    narrative_push_requirement = max(1, words_needed // 100)
    strategy_text = "\n".join(strategy_descriptions)

    prompt = (
        f"请将以下文本扩写到约{target_words}字（中文字数），当前约{current_words}字，需增加约{words_needed}字。\n\n"
        f"扩写策略（按优先级）：\n{strategy_text}\n\n"
        f"严格要求：\n"
        f"1. 每100字新增内容至少包含{narrative_push_requirement}个叙事推进元素（冲突/转折/悬念/发现）\n"
        f"2. 禁止空洞凑字和重复描写\n"
        f"3. 保持原文风格和语气\n"
        f"4. 直接输出修改后的完整正文——在原文段落之间或内部插入新内容，严禁重写开头、严禁在末尾追加重复段落\n"
        f"5. 新增内容必须推进情节或深化人物\n"
        f"6. 严禁改变原文中已出现的日期、时间、地点等事实信息\n\n"
        f"原文：\n{text}"
    )

    try:
        expanded = await llm_call(prompt)
        if not expanded:
            return text
        if count_chinese_words(expanded) < current_words:
            logger.warning("Expand produced shorter text, keeping original")
            return text
        quality = evaluate_expand_quality(text, expanded)
        if quality["score"] < 0.5:
            logger.warning(f"Expand quality too low ({quality['score']:.2f}), keeping original")
            return text
        return expanded
    except Exception as e:
        logger.warning(f"LLM intelligent expand failed: {e}")
        return text


def get_best_version_with_style_drift(
    history: CorrectionHistory,
    target_words: int,
    style_drift_threshold: float = 0.3,
) -> tuple[str, float]:
    if not history.snapshots:
        return ("", 100.0)
    candidates = []
    for s in history.snapshots:
        deviation = compute_deviation(s.word_count, target_words)
        if s.style_drift > style_drift_threshold:
            deviation += (s.style_drift - style_drift_threshold) * 50
        candidates.append((s, deviation))
    candidates.sort(key=lambda x: x[1])
    best_snap, best_dev = candidates[0]
    return (best_snap.text, compute_deviation(best_snap.word_count, target_words))


def _repair_scene_boundaries(original: str, trimmed: str) -> str:
    orig_paras = [p.strip() for p in original.split("\n\n") if p.strip()]
    trim_paras = [p.strip() for p in trimmed.split("\n\n") if p.strip()]
    if len(orig_paras) != len(trim_paras):
        return trimmed
    repaired = []
    for orig_p, trim_p in zip(orig_paras, trim_paras):
        orig_first = orig_p[:10] if len(orig_p) >= 10 else orig_p
        trim_first = trim_p[:10] if len(trim_p) >= 10 else trim_p
        if orig_first != trim_first and orig_first not in trim_p:
            trim_p = orig_p.split("。")[0] + "。" + trim_p
        orig_last = orig_p[-10:] if len(orig_p) >= 10 else orig_p
        trim_last = trim_p[-10:] if len(trim_p) >= 10 else trim_p
        if orig_last != trim_last and orig_last not in trim_p:
            trim_p = trim_p + orig_p.split("。")[-1]
        repaired.append(trim_p)
    return "\n\n".join(repaired)
