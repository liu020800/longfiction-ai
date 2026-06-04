import logging
import json
import re
from .models import QualityScoreResult, Shortfall
from .enhancement_config import EnhancementConfig

logger = logging.getLogger(__name__)

QUALITY_DIMENSIONS = ["opening", "plot", "character", "dialogue", "suspense", "pacing", "show_dont_tell", "language", "coherence", "ai_naturalness"]

SCORING_PROMPT = """你是一位资深网文编辑，请对以下章节进行10维评分（每维0-10分）：

1. opening（开头吸引力）：开头是否抓人，是否使用强力开场技巧
2. plot（情节推进）：是否有实质进展，是否推进主线
3. character（人物塑造）：角色是否有深度，行为是否符合性格
4. dialogue（对话质量）：对话是否自然，是否有潜台词，角色是否有区分度
5. suspense（悬念设置）：是否有悬念/钩子，读者是否有翻页动力
6. pacing（节奏控制）：节奏是否合理，是否张弛有度
7. show_dont_tell（展示而非讲述）：是否用行动和细节代替抽象描述
8. language（语言质量）：是否自然流畅，无明显AI痕迹
9. coherence（连贯性）：与前文是否衔接自然，有无逻辑矛盾
10. ai_naturalness（AI痕迹程度）：文本是否有人味，是否使用了模板化句式，是否有多样化的表达。扣分项：频繁使用"——不是X，是Y"结构、"，像是"比喻、"指节发白"等套话、倒计时描写过多、情绪描写机械化（如"瞳孔微缩"反复出现）

请严格按JSON格式输出：
{"opening":X,"plot":X,"character":X,"dialogue":X,"suspense":X,"pacing":X,"show_dont_tell":X,"language":X,"coherence":X,"ai_naturalness":X}"""

class QualityScorer:
    def __init__(self, config: EnhancementConfig, llm_call=None):
        self.config = config
        self.llm_call = llm_call

    async def score_chapter(self, chapter_text: str, prev_summary: str = "") -> QualityScoreResult:
        scores = await self._llm_score(chapter_text, prev_summary)
        scores = self._cross_validate(scores, chapter_text)
        composite = self.calculate_composite(scores)
        shortfalls = self.detect_shortfalls(scores)
        should_regen = self.should_regenerate(composite)
        readability = self.analyze_readability(chapter_text)
        return QualityScoreResult(
            dimension_scores=scores,
            composite_score=composite,
            shortfalls=shortfalls,
            should_regenerate=should_regen,
        )

    def _cross_validate(self, scores: dict[str, float], text: str) -> dict[str, float]:
        adjusted = dict(scores)

        dialogue_count = sum(1 for _ in re.finditer(r'[「」""\u201c\u201d]', text))
        total_chars = max(1, len(text))
        dialogue_ratio = (dialogue_count * 15) / total_chars

        if dialogue_ratio < 0.05 and adjusted.get("dialogue", 0) > 8.0:
            adjusted["dialogue"] = 7.0

        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        max_consecutive_narrative = 0
        current_streak = 0
        for p in paragraphs:
            has_dlg = bool(re.search(r'[「」""\u201c\u201d]', p))
            if not has_dlg:
                current_streak += 1
                max_consecutive_narrative = max(max_consecutive_narrative, current_streak)
            else:
                current_streak = 0
        if max_consecutive_narrative >= 3 and adjusted.get("pacing", 0) > 8.0:
            adjusted["pacing"] = min(adjusted["pacing"], 7.0)

        sentences = re.split(r'[。！？]', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 3]
        if sentences:
            avg_len = sum(len(s) for s in sentences) / len(sentences)
            if avg_len > 50 and adjusted.get("language", 0) > 8.0:
                adjusted["language"] = 7.5

        all_perfect = all(v >= 9.9 for v in scores.values())
        if all_perfect:
            for d in adjusted:
                adjusted[d] = min(9.0, adjusted[d])

        return adjusted

    def analyze_readability(self, text: str) -> dict:
        sentences = re.split(r'[。！？；]', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 3]

        avg_sentence_length = 0.0
        if sentences:
            avg_sentence_length = round(sum(len(s) for s in sentences) / len(sentences), 1)

        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        para_lengths = [len(p) for p in paragraphs]
        paragraph_length_dist = {}
        if para_lengths:
            bins = [(0, 50), (50, 150), (150, 300), (300, float('inf'))]
            labels = ["短段", "中段", "长段", "超长段"]
            for (lo, hi), label in zip(bins, labels):
                count = sum(1 for l in para_lengths if lo <= l < hi)
                paragraph_length_dist[label] = count

        dialogue_chars = sum(len(m.group()) for m in re.finditer(r'[「」""\u201c\u201d][^「」""\u201c\u201d]+[「」""\u201c\u201d]', text))
        dialogue_ratio = round(dialogue_chars / max(1, len(text)), 3)

        max_consecutive_narrative = 0
        current_streak = 0
        for p in paragraphs:
            has_dlg = bool(re.search(r'[「」""\u201c\u201d]', p))
            if not has_dlg:
                current_streak += 1
                max_consecutive_narrative = max(max_consecutive_narrative, current_streak)
            else:
                current_streak = 0

        narrative_density = round(
            sum(1 for p in paragraphs if not re.search(r'[「」""\u201c\u201d]', p)) / max(1, len(paragraphs)),
            3
        )

        return {
            "avg_sentence_length": avg_sentence_length,
            "paragraph_length_dist": paragraph_length_dist,
            "dialogue_ratio": dialogue_ratio,
            "narrative_density": narrative_density,
            "has_long_narrative_streak": max_consecutive_narrative >= 3,
            "max_consecutive_narrative": max_consecutive_narrative,
        }

    async def _llm_score(self, chapter_text: str, prev_summary: str) -> dict[str, float]:
        if not self.llm_call:
            return {d: 7.0 for d in QUALITY_DIMENSIONS}
        try:
            context = f"上一章摘要：{prev_summary}\n\n" if prev_summary else ""
            result = await self.llm_call(f"{SCORING_PROMPT}\n\n{context}---\n{chapter_text[:3000]}")
            match = re.search(r'\{[^}]+\}', result)
            if match:
                raw = json.loads(match.group())
                scores = {}
                for d in QUALITY_DIMENSIONS:
                    v = raw.get(d, 7.0)
                    scores[d] = max(0.0, min(10.0, float(v)))
                return scores
        except Exception as e:
            logger.warning(f"10维评分LLM调用失败: {e}，使用默认分数")
        return {d: 7.0 for d in QUALITY_DIMENSIONS}

    def calculate_composite(self, scores: dict[str, float]) -> float:
        weights = self.config.QUALITY_WEIGHTS
        total_weight = sum(weights.get(d, 1.0) for d in scores)
        weighted_sum = sum(scores.get(d, 0) * weights.get(d, 1.0) for d in scores)
        return round(weighted_sum / max(total_weight, 0.01), 2)

    def detect_shortfalls(self, scores: dict[str, float]) -> list[Shortfall]:
        shortfalls = []
        threshold = self.config.QUALITY_SHORTFALL_THRESHOLD
        suggestions = {
            "opening": "尝试使用行动中开场/悬念预置/震撼对话等强力开场技巧",
            "plot": "确保本章推进主线剧情，引入新的冲突或转折",
            "character": "通过行动和选择展示角色性格，而非直接描述",
            "dialogue": "增加对话潜台词，让不同角色有区分度",
            "suspense": "在章末设置悬念钩子，引入未解之谜",
            "pacing": "调整节奏波形，高密度与低密度段落交替",
            "show_dont_tell": "用具体行动和细节替代抽象情感描述",
            "language": "消除AI高频词和模式化表达，增加语言多样性",
            "coherence": "确保与前文衔接自然，检查设定一致性",
            "ai_naturalness": "消除模板化句式（——不是X是Y、，像是等），增加表达多样性，用独特细节替代套话",
        }
        for d, s in scores.items():
            if s < threshold:
                shortfalls.append(Shortfall(dimension=d, score=s, suggestion=suggestions.get(d, "")))
        return shortfalls

    def should_regenerate(self, composite_score: float) -> bool:
        return composite_score < self.config.QUALITY_REGENERATE_THRESHOLD

    def get_state(self) -> dict:
        return {}

    def restore_state(self, state: dict):
        pass
