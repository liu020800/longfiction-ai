"""句式多样化器。

通过打散句式结构、引入变化模式，让文本读起来更自然。
"""
from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# 句式变换规则：模式 -> 替换函数
TRANSFORMATIONS = {
    # 主-谓-宾 顺序调整
    "subject_verb_object": [
        # 简单主谓 -> 倒装
        (r"^(.{2,8})([，。])", lambda m: f"{m.group(2)}{m.group(1)}" if random.random() < 0.2 else m.group(0)),
    ],
    # 主动 -> 被动
    "active_to_passive": [
        # "他开了门" -> "门被他打开"
        (r"(\w{1,3})([打开关闭杀死抓住])(了|着)?(\w{1,3})",
         lambda m: f"{m.group(4)}{m.group(3) or ''}{m.group(2)}于{m.group(1)}"
         if random.random() < 0.3 else m.group(0)),
    ],
}


# 句首多样化模板
SENTENCE_OPENERS = [
    "{subject}",  # 直接主语
    "当{condition}时，{subject}",  # 时间状语前置
    "在{location}，{subject}",  # 地点状语前置
    "{subject}，{verb}",  # 主语停顿
    "——{dialogue}",  # 破折号引语
    "「{dialogue}」",  # 日式引号
    "原来，{subject}",  # 揭示
    "却见{subject}",  # 视角转换
    "只见{subject}",  # 视觉化
    "恰在此时，{subject}",  # 时间标志
    "{subject}却",  # 转折
    "{subject}仍",  # 持续
    "{subject}已",  # 完成
    "就在{subject}",  # 紧迫感
]


@dataclass
class DiversifyResult:
    """多样化结果。"""
    original: str
    diversified: str
    sentences_before: int
    sentences_after: int
    avg_length_before: float
    avg_length_after: float
    transformations_applied: list[str]


class SentenceDiversifier:
    """句式多样化器。"""

    def __init__(
        self,
        target_avg_length: float = 30.0,
        min_length: int = 5,
        max_length: int = 100,
        apply_probability: float = 0.5,
    ):
        self.target_avg_length = target_avg_length
        self.min_length = min_length
        self.max_length = max_length
        self.apply_probability = apply_probability

    def diversify(self, text: str) -> DiversifyResult:
        """对文本进行句式多样化。"""
        if not text:
            return DiversifyResult(
                original="", diversified="",
                sentences_before=0, sentences_after=0,
                avg_length_before=0, avg_length_after=0,
                transformations_applied=[],
            )

        original = text
        transformations = []

        # 1. 句子拆分：过长的句子拆开
        sentences = self._split_sentences(text)
        original_count = len(sentences)
        original_lens = [len(s) for s in sentences]
        original_avg = sum(original_lens) / max(original_count, 1)

        new_sentences = []
        for sent in sentences:
            if len(sent) > self.max_length and random.random() < self.apply_probability:
                split = self._split_long_sentence(sent)
                new_sentences.extend(split)
                transformations.append("split_long")
            else:
                new_sentences.append(sent)

        # 2. 短句合并：过短的句子合并
        merged = self._merge_short_sentences(new_sentences)
        if len(merged) != len(new_sentences):
            transformations.append("merge_short")

        # 3. 句式变化：替换部分句首
        if random.random() < self.apply_probability:
            merged = self._vary_openers(merged)
            transformations.append("vary_openers")

        # 4. 长短句交替
        if random.random() < self.apply_probability:
            merged = self._alternate_lengths(merged)
            transformations.append("alternate_lengths")

        diversified = "".join(merged)
        new_lens = [len(s) for s in merged]
        new_avg = sum(new_lens) / max(len(merged), 1)

        return DiversifyResult(
            original=original,
            diversified=diversified,
            sentences_before=original_count,
            sentences_after=len(merged),
            avg_length_before=original_avg,
            avg_length_after=new_avg,
            transformations_applied=transformations,
        )

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """切分句子（保留标点）。"""
        # 在 。！？ 之后切分
        result = []
        buffer = ""
        for ch in text:
            buffer += ch
            if ch in "。！？!?\n":
                if buffer.strip():
                    result.append(buffer)
                buffer = ""
        if buffer.strip():
            result.append(buffer)
        return result

    @staticmethod
    def _split_long_sentence(sent: str) -> list[str]:
        """拆分过长句子。"""
        # 寻找合适的切分点（，；）
        for sep in ["，", "；", "、", "："]:
            if sep in sent:
                idx = sent.find(sep)
                if idx > 5:
                    first = sent[: idx + 1]
                    second = sent[idx + 1 :]
                    # 第二个部分如果是完整的子句，加句号
                    if not second.endswith(("。", "！", "？", "，", "；")):
                        second = second + "。"
                    return [first, second]
        # 找不到合适切分点，随机切
        mid = len(sent) // 2
        return [sent[:mid] + "，", sent[mid:]]

    @staticmethod
    def _merge_short_sentences(sentences: list[str]) -> list[str]:
        """合并过短的连续句子。"""
        if len(sentences) < 2:
            return sentences
        result = []
        i = 0
        while i < len(sentences):
            current = sentences[i]
            # 如果当前句子很短（< 10 字），尝试与下一句合并
            if (
                len(current.strip()) < 10
                and i + 1 < len(sentences)
                and len(sentences[i + 1].strip()) < 30
                and random.random() < 0.4
            ):
                # 用逗号连接
                merged = current.rstrip("。！？!?\n").rstrip() + "，" + sentences[i + 1].lstrip()
                result.append(merged)
                i += 2
            else:
                result.append(current)
                i += 1
        return result

    @staticmethod
    def _vary_openers(sentences: list[str]) -> list[str]:
        """变化句首。"""
        result = []
        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 8:
                result.append(sent)
                continue
            # 5% 概率变化句首
            if random.random() < 0.05:
                # 在句首加 "——"
                if not sent.startswith("——") and not sent.startswith("「"):
                    sent = "——" + sent
            result.append(sent)
        return result

    @staticmethod
    def _alternate_lengths(sentences: list[str]) -> list[str]:
        """长短句交替重排。

        不改变语义，但打散连续长句或连续短句。
        """
        if len(sentences) < 4:
            return sentences
        # 计算每句长度
        lens = [len(s) for s in sentences]
        avg = sum(lens) / len(lens)
        # 简单策略：如果连续 3 句都长或都短，打乱顺序
        result = list(sentences)
        for i in range(len(result) - 3):
            if all(l > avg * 1.3 for l in lens[i : i + 3]):
                # 三句都长，交换中间两句
                result[i + 1], result[i + 2] = result[i + 2], result[i + 1]
            elif all(l < avg * 0.7 for l in lens[i : i + 3]):
                # 三句都短，合并前两句
                first = result[i].rstrip("。！？!?\n")
                second = result[i + 1].rstrip("。！？!?\n")
                if len(first + "，" + second) < 80:
                    result[i] = first + "，" + second + "。"
                    result.pop(i + 1)
                    lens = [len(s) for s in result]
        return result


# 全局实例
_default_diversifier = SentenceDiversifier()


def diversify_text(text: str) -> str:
    """便捷函数：使用默认配置多样化文本。"""
    return _default_diversifier.diversify(text).diversified
