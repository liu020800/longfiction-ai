import math
import random
import re
import logging
from dataclasses import dataclass, field
from typing import Optional
from core.llm_router import call_llm, TaskType
from core.word_counter import count_chinese_words, _split_sentences
from core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class StyleFingerprint:
    sentence_length_dist: list[float] = field(default_factory=lambda: [0.2, 0.5, 0.2, 0.1])
    dialogue_density: float = 0.3
    rhetoric_frequency: float = 0.1
    emotion_tone: list[float] = field(default_factory=lambda: [0.5, 0.3, 0.2])
    rhythm_pattern: list[float] = field(default_factory=list)
    template_id: str = ""
    template_name: str = ""


class StyleLearner:
    def __init__(self):
        self.fingerprint: Optional[StyleFingerprint] = None
        self._min_chars = getattr(settings, 'STYLE_SAMPLE_MIN_CHARS', 500)

    async def learn_style(self, texts: list[str]) -> StyleFingerprint:
        if not texts:
            raise ValueError("No texts provided for style learning")
        total_chars = sum(count_chinese_words(t) for t in texts)
        if total_chars < self._min_chars:
            raise ValueError(f"Total chars {total_chars} below minimum {self._min_chars}")

        all_sentences = []
        for text in texts:
            all_sentences.extend(_split_sentences(text))

        if not all_sentences:
            raise ValueError("No sentences found in texts")

        lengths = [count_chinese_words(s) for s in all_sentences]
        bins = [0, 10, 25, 50]
        bin_counts = [0] * (len(bins))
        for l in lengths:
            placed = False
            for i in range(len(bins) - 1):
                if bins[i] <= l < bins[i + 1]:
                    bin_counts[i] += 1
                    placed = True
                    break
            if not placed:
                bin_counts[-1] += 1
        total = sum(bin_counts) or 1
        sentence_length_dist = [c / total for c in bin_counts]

        dialogue_count = sum(
            1 for s in all_sentences
            if any(q in s for q in ['\u201c', '\u201d', '\u300c', '\u300d', '"'])
        )
        dialogue_density = dialogue_count / len(all_sentences)

        rhetoric_patterns = [
            r"像|如|似|般", r"不.{1,5}而", r"既.{1,5}又",
            r"一.{1,3}就", r"越.{1,5}越",
        ]
        rhetoric_count = 0
        for s in all_sentences:
            for p in rhetoric_patterns:
                if re.search(p, s):
                    rhetoric_count += 1
                    break
        rhetoric_frequency = rhetoric_count / len(all_sentences)

        emotion_positive = sum(1 for s in all_sentences if any(kw in s for kw in ["喜", "乐", "笑", "欢", "爱", "温暖"]))
        emotion_negative = sum(1 for s in all_sentences if any(kw in s for kw in ["怒", "悲", "哭", "恨", "惧", "冷"]))
        emotion_neutral = len(all_sentences) - emotion_positive - emotion_negative
        emotion_total = len(all_sentences) or 1
        emotion_tone = [
            emotion_positive / emotion_total,
            emotion_negative / emotion_total,
            emotion_neutral / emotion_total,
        ]

        para_lengths = []
        for text in texts:
            paras = [p.strip() for p in text.split("\n\n") if p.strip()]
            para_lengths.extend([count_chinese_words(p) for p in paras])
        rhythm_pattern = []
        if para_lengths:
            avg = sum(para_lengths) / len(para_lengths)
            rhythm_pattern = [round(l / (avg or 1), 2) for l in para_lengths[:20]]

        self.fingerprint = StyleFingerprint(
            sentence_length_dist=sentence_length_dist,
            dialogue_density=round(dialogue_density, 3),
            rhetoric_frequency=round(rhetoric_frequency, 3),
            emotion_tone=[round(e, 3) for e in emotion_tone],
            rhythm_pattern=rhythm_pattern,
        )
        return self.fingerprint

    def compute_similarity(self, other: StyleFingerprint) -> float:
        if not self.fingerprint:
            return 0.0
        fp1 = self.fingerprint
        fp2 = other
        sl1, sl2 = fp1.sentence_length_dist, fp2.sentence_length_dist
        min_len = min(len(sl1), len(sl2))
        sl_dot = sum(sl1[i] * sl2[i] for i in range(min_len))
        sl_norm1 = math.sqrt(sum(x ** 2 for x in sl1))
        sl_norm2 = math.sqrt(sum(x ** 2 for x in sl2))
        sl_sim = sl_dot / (sl_norm1 * sl_norm2 + 1e-8)

        dd_diff = abs(fp1.dialogue_density - fp2.dialogue_density)
        dd_sim = 1.0 - min(1.0, dd_diff * 2)

        return sl_sim * 0.6 + dd_sim * 0.4


class StylePreserver:
    def __init__(self, perturbation_rate: float = None):
        self.perturbation_rate = perturbation_rate or getattr(settings, 'STYLE_PERTURBATION_RATE', 0.3)
        self.last_fingerprint: Optional[StyleFingerprint] = None

    def apply_perturbation(self, fingerprint: StyleFingerprint) -> StyleFingerprint:
        perturbed = StyleFingerprint(
            template_id=fingerprint.template_id,
            template_name=fingerprint.template_name,
            dialogue_density=fingerprint.dialogue_density,
            rhetoric_frequency=fingerprint.rhetoric_frequency,
        )

        perturbed.sentence_length_dist = [
            max(0.0, d + random.gauss(0, self.perturbation_rate * d * 0.1))
            for d in fingerprint.sentence_length_dist
        ]
        total = sum(perturbed.sentence_length_dist) or 1
        perturbed.sentence_length_dist = [d / total for d in perturbed.sentence_length_dist]

        perturbed.emotion_tone = [
            max(0.0, e + random.gauss(0, self.perturbation_rate * 0.05))
            for e in fingerprint.emotion_tone
        ]
        total_e = sum(perturbed.emotion_tone) or 1
        perturbed.emotion_tone = [e / total_e for e in perturbed.emotion_tone]

        perturbed.rhythm_pattern = [
            max(0.1, r + random.gauss(0, self.perturbation_rate * 0.1))
            for r in (fingerprint.rhythm_pattern or [1.0])
        ]

        self.last_fingerprint = perturbed
        return perturbed
