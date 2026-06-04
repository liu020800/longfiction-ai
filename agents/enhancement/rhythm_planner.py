import logging
from .models import EmotionCurve, DensityCheckResult, RhythmDeviationResult
from .enhancement_config import EnhancementConfig

logger = logging.getLogger(__name__)

class RhythmPlanner:
    def __init__(self, config: EnhancementConfig):
        self.config = config
        self._preset_curves: dict[int, EmotionCurve] = {}
    
    def plan_emotion_curve(self, chapter_index: int, pacing_label: str = "normal") -> EmotionCurve:
        if chapter_index in self._preset_curves:
            return self._preset_curves[chapter_index]
        return self._get_default_curve(pacing_label)
    
    def set_preset_curve(self, chapter_index: int, curve: EmotionCurve):
        self._preset_curves[chapter_index] = curve
    
    def generate_rhythm_constraint(self, chapter_index: int, pacing_label: str = "normal") -> str:
        curve = self.plan_emotion_curve(chapter_index, pacing_label)
        return (
            f"\n【节奏约束】\n"
            f"1. 情绪曲线：起点{curve.start_intensity}→峰值{curve.peak_intensity}→终点{curve.end_intensity}（1-10分）\n"
            f"2. 信息密度波浪：高密度(动作/对话/揭示)与低密度(沉淀/描写/内心)交替\n"
            f"3. 禁止连续{self.config.DENSITY_MAX_CONSECUTIVE}段同密度\n"
            f"4. 长短句交替，短句制造紧迫感，长句铺陈氛围\n"
        )
    
    def check_density_alternation(self, chapter_text: str) -> DensityCheckResult:
        paragraphs = [p.strip() for p in chapter_text.split("\n\n") if p.strip()]
        if len(paragraphs) < 3:
            return DensityCheckResult(compliant=True)
        
        densities = [self._classify_paragraph_density(p) for p in paragraphs]
        violations = []
        consecutive = 1
        for i in range(1, len(densities)):
            if densities[i] == densities[i-1]:
                consecutive += 1
                if consecutive >= self.config.DENSITY_MAX_CONSECUTIVE:
                    violations.append(f"第{i+1}段: 连续{consecutive}段{densities[i]}密度")
            else:
                consecutive = 1
        
        return DensityCheckResult(compliant=len(violations) == 0, violations=violations)
    
    def detect_rhythm_deviation(self, chapter_text: str, target_curve: EmotionCurve) -> RhythmDeviationResult:
        paragraphs = [p.strip() for p in chapter_text.split("\n\n") if p.strip()]
        if len(paragraphs) < 3:
            return RhythmDeviationResult(deviation=0.0, warning="")
        
        n = len(paragraphs)
        actual_start = self._estimate_intensity(paragraphs[0])
        actual_peak = max(self._estimate_intensity(p) for p in paragraphs)
        actual_end = self._estimate_intensity(paragraphs[-1])
        
        start_diff = abs(actual_start - target_curve.start_intensity) / 10
        peak_diff = abs(actual_peak - target_curve.peak_intensity) / 10
        end_diff = abs(actual_end - target_curve.end_intensity) / 10
        deviation = (start_diff + peak_diff + end_diff) / 3
        
        warning = ""
        if deviation > self.config.RHYTHM_DEVIATION_THRESHOLD:
            warning = f"节奏偏差{deviation*100:.0f}%：开头{actual_start}→峰值{actual_peak}→结尾{actual_end}，与目标曲线偏差较大"
        
        return RhythmDeviationResult(deviation=round(deviation, 3), warning=warning)
    
    def _classify_paragraph_density(self, paragraph: str) -> str:
        action_words = ["打", "冲", "跑", "喊", "跳", "抓", "斩", "挡", "闪", "击"]
        emotion_words = ["想", "感", "叹", "忆", "思", "念", "望", "悲", "喜", "怒"]
        action_count = sum(paragraph.count(w) for w in action_words)
        emotion_count = sum(paragraph.count(w) for w in emotion_words)
        dialogue_count = paragraph.count('"') + paragraph.count('"') + paragraph.count('「')
        
        if action_count + dialogue_count > emotion_count + 3:
            return "高"
        return "低"
    
    def _estimate_intensity(self, paragraph: str) -> float:
        intensity_words = {"！": 0.5, "？": 0.3, "杀": 1.0, "死": 1.0, "战": 0.8, "怒": 0.7, "惊": 0.6, "险": 0.7, "危": 0.8}
        score = 3.0
        for w, s in intensity_words.items():
            score += paragraph.count(w) * s
        return min(score, 10.0)
    
    def _get_default_curve(self, pacing_label: str) -> EmotionCurve:
        defaults = {
            "fast": EmotionCurve(start_intensity=5.0, peak_intensity=9.0, end_intensity=7.0),
            "normal": EmotionCurve(start_intensity=4.0, peak_intensity=7.0, end_intensity=5.0),
            "slow": EmotionCurve(start_intensity=3.0, peak_intensity=5.0, end_intensity=4.0),
        }
        return defaults.get(pacing_label, EmotionCurve())
    
    def get_state(self) -> dict:
        return {"preset_curves": {str(k): v.model_dump() for k, v in self._preset_curves.items()}}

    def restore_state(self, state: dict):
        self._preset_curves = {int(k): EmotionCurve(**v) for k, v in state.get("preset_curves", {}).items()}

    def compute_act_structure(self, total_chapters: int) -> dict:
        if total_chapters <= 0:
            return {"act1": [], "act2": [], "act3": []}
        act1_end = max(1, int(total_chapters * 0.30))
        act3_start = min(total_chapters, int(total_chapters * 0.85) + 1)
        return {
            "act1": list(range(1, act1_end + 1)),
            "act2": list(range(act1_end + 1, act3_start)),
            "act3": list(range(act3_start, total_chapters + 1)),
        }

    def get_act_label(self, chapter_index: int, total_chapters: int) -> str:
        structure = self.compute_act_structure(total_chapters)
        if chapter_index in structure["act1"]:
            return "开端"
        elif chapter_index in structure["act3"]:
            return "结尾"
        else:
            return "对抗"

    def generate_conflict_curve(self, total_chapters: int) -> list[float]:
        if total_chapters <= 0:
            return []
        curve = []
        for i in range(1, total_chapters + 1):
            progress = i / total_chapters
            if progress <= 0.30:
                intensity = 0.3 + 0.4 * (progress / 0.30)
            elif progress <= 0.85:
                mid = 0.575
                base = 0.7
                amplitude = 0.25
                intensity = base + amplitude * __import__("math").sin(
                    (progress - 0.30) / 0.55 * 3 * __import__("math").pi
                )
                intensity += 0.1 * (progress - 0.30) / 0.55
            else:
                intensity = 0.6 - 0.4 * ((progress - 0.85) / 0.15)
            curve.append(round(max(0.1, min(1.0, intensity)), 3))
        return curve

    def get_expected_conflict(self, chapter_index: int, total_chapters: int) -> float:
        curve = self.generate_conflict_curve(total_chapters)
        if 0 < chapter_index <= len(curve):
            return curve[chapter_index - 1]
        return 0.5

    def generate_conflict_constraint(self, chapter_index: int, total_chapters: int) -> str:
        expected = self.get_expected_conflict(chapter_index, total_chapters)
        act_label = self.get_act_label(chapter_index, total_chapters)
        if expected > 0.7:
            return f"【冲突约束】当前处于{act_label}幕，预期冲突强度{expected:.1f}，本章应包含高强度冲突或转折事件"
        elif expected > 0.4:
            return f"【冲突约束】当前处于{act_label}幕，预期冲突强度{expected:.1f}，保持适度冲突推进"
        else:
            return f"【冲突约束】当前处于{act_label}幕，预期冲突强度{expected:.1f}，侧重收束和情感沉淀"
