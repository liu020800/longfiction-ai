"""风格控制器。

提取、分析、控制生成文本的风格特征。
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class StyleFeatures:
    """风格特征向量。"""
    # 句子长度统计
    avg_sentence_length: float = 0.0
    sentence_length_std: float = 0.0
    short_sentence_ratio: float = 0.0     # < 20 字的句子占比
    long_sentence_ratio: float = 0.0      # > 60 字的句子占比

    # 词汇丰富度
    type_token_ratio: float = 0.0         # TTR：不同词数 / 总词数
    avg_word_length: float = 0.0

    # 对话密度
    dialogue_ratio: float = 0.0           # 对话字数 / 总字数
    dialogue_sentence_ratio: float = 0.0  # 含对话的句子占比

    # 修辞密度
    metaphor_count: int = 0
    onomatopoeia_count: int = 0           # 拟声词
    parallelism_count: int = 0            # 排比

    # 情感倾向
    positive_words: int = 0
    negative_words: int = 0
    neutral_score: float = 0.5

    # 段落特征
    avg_paragraph_length: float = 0.0
    paragraph_count: int = 0

    # 原始统计
    total_chars: int = 0
    total_sentences: int = 0
    total_words: int = 0

    def to_dict(self) -> dict:
        return {
            "avg_sentence_length": round(self.avg_sentence_length, 2),
            "sentence_length_std": round(self.sentence_length_std, 2),
            "short_sentence_ratio": round(self.short_sentence_ratio, 3),
            "long_sentence_ratio": round(self.long_sentence_ratio, 3),
            "type_token_ratio": round(self.type_token_ratio, 3),
            "avg_word_length": round(self.avg_word_length, 2),
            "dialogue_ratio": round(self.dialogue_ratio, 3),
            "dialogue_sentence_ratio": round(self.dialogue_sentence_ratio, 3),
            "metaphor_count": self.metaphor_count,
            "onomatopoeia_count": self.onomatopoeia_count,
            "parallelism_count": self.parallelism_count,
            "positive_words": self.positive_words,
            "negative_words": self.negative_words,
            "neutral_score": round(self.neutral_score, 3),
            "avg_paragraph_length": round(self.avg_paragraph_length, 2),
            "paragraph_count": self.paragraph_count,
            "total_chars": self.total_chars,
            "total_sentences": self.total_sentences,
            "total_words": self.total_words,
        }


# 中文情感词典（精简版）
POSITIVE_WORDS = set([
    "好", "很好", "优秀", "出色", "精彩", "完美", "强大", "厉害", "高兴", "快乐",
    "开心", "幸福", "满足", "喜欢", "爱", "希望", "成功", "胜利", "突破", "成长",
    "温暖", "温柔", "善良", "友好", "光明", "希望", "微笑", "笑容", "欣喜", "激动",
])
NEGATIVE_WORDS = set([
    "坏", "糟糕", "差", "失败", "痛苦", "悲伤", "难过", "失望", "绝望", "恐惧",
    "害怕", "愤怒", "生气", "厌恶", "讨厌", "黑暗", "死亡", "毁灭", "崩溃", "失败",
    "冷酷", "残忍", "痛苦", "孤单", "寂寞", "凄凉", "悲惨", "凶狠",
])

# 修辞提示词
METAPHOR_MARKERS = ["像", "如", "仿佛", "好似", "犹如", "宛如", "如同", "好比", "似的", "一般"]
ONOMATOPOEIA = ["哗啦", "轰隆", "嗖", "啪", "咔嚓", "嘎吱", "滴答", "叮当", "嘶嘶", "嗡嗡", "咚咚"]


def extract_style_features(text: str) -> StyleFeatures:
    """从文本中提取风格特征。"""
    if not text:
        return StyleFeatures()

    features = StyleFeatures()
    features.total_chars = len(text)

    # 段落
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    features.paragraph_count = len(paragraphs)
    if paragraphs:
        features.avg_paragraph_length = sum(len(p) for p in paragraphs) / len(paragraphs)

    # 句子（按中文标点切分）
    sentences = re.split(r"[。！？!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    features.total_sentences = len(sentences)
    if sentences:
        sent_lens = [len(s) for s in sentences]
        features.avg_sentence_length = sum(sent_lens) / len(sent_lens)
        mean = features.avg_sentence_length
        features.sentence_length_std = (
            (sum((x - mean) ** 2 for x in sent_lens) / len(sent_lens)) ** 0.5
        )
        features.short_sentence_ratio = sum(1 for x in sent_lens if x < 20) / len(sent_lens)
        features.long_sentence_ratio = sum(1 for x in sent_lens if x > 60) / len(sent_lens)

    # 词汇（粗略切分：中文单字 + 英文单词）
    words = re.findall(r"[\u4e00-\u9fff]", text) + re.findall(r"[a-zA-Z]+", text)
    features.total_words = len(words)
    if words:
        unique_words = set(words)
        features.type_token_ratio = len(unique_words) / len(words)
        # 词长（中文单字为 1，英文按字符数）
        word_lens = [len(w) for w in words]
        features.avg_word_length = sum(word_lens) / len(word_lens)

    # 对话（双引号、破折号）
    dialogue_chars = 0
    dialogue_sentences = 0
    for sent in sentences:
        if '"' in sent or '"' in sent or '"' in sent or '——' in sent:
            dialogue_sentences += 1
            # 对话内容长度
            d = re.findall(r'"[^"]*"|"[^"]*"|"[^"]*"', sent)
            dialogue_chars += sum(len(x) for x in d)
    features.dialogue_ratio = dialogue_chars / max(features.total_chars, 1)
    features.dialogue_sentence_ratio = dialogue_sentences / max(features.total_sentences, 1)

    # 修辞
    features.metaphor_count = sum(text.count(m) for m in METAPHOR_MARKERS)
    features.onomatopoeia_count = sum(text.count(o) for o in ONOMATOPOEIA)
    # 排比：连续三句以上结构相似
    features.parallelism_count = 0
    for i in range(len(sentences) - 2):
        s1, s2, s3 = sentences[i], sentences[i + 1], sentences[i + 2]
        if len(s1) > 5 and len(s2) > 5 and len(s3) > 5:
            # 简单启发式：首三字相同
            if s1[:3] == s2[:3] == s3[:3] and s1[:3] not in ["。", "，"]:
                features.parallelism_count += 1

    # 情感
    pos_count = 0
    neg_count = 0
    for word in POSITIVE_WORDS:
        if word in text:
            pos_count += text.count(word)
    for word in NEGATIVE_WORDS:
        if word in text:
            neg_count += text.count(word)
    features.positive_words = pos_count
    features.negative_words = neg_count
    total_sentiment = pos_count + neg_count
    if total_sentiment > 0:
        features.neutral_score = pos_count / total_sentiment
    return features


@dataclass
class StyleProfile:
    """风格画像。"""
    name: str
    features: StyleFeatures
    description: str = ""
    sample_texts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "features": self.features.to_dict(),
            "sample_count": len(self.sample_texts),
        }


# 预定义风格画像
PRESET_STYLES: dict[str, StyleProfile] = {}


def init_preset_styles():
    """初始化预定义风格画像。"""
    global PRESET_STYLES
    PRESET_STYLES = {
        "web_novel": StyleProfile(
            name="web_novel",
            description="网文风格：节奏快、对话多、悬念强",
            features=StyleFeatures(
                avg_sentence_length=25.0,
                short_sentence_ratio=0.4,
                dialogue_ratio=0.25,
                avg_paragraph_length=120.0,
            ),
        ),
        "literary": StyleProfile(
            name="literary",
            description="纯文学风格：长句多、心理描写细腻、修辞丰富",
            features=StyleFeatures(
                avg_sentence_length=45.0,
                long_sentence_ratio=0.4,
                metaphor_count=5,
                avg_paragraph_length=200.0,
                dialogue_ratio=0.1,
            ),
        ),
        "humor": StyleProfile(
            name="humor",
            description="幽默风格：短句、对话多、节奏感强",
            features=StyleFeatures(
                avg_sentence_length=18.0,
                short_sentence_ratio=0.6,
                dialogue_ratio=0.4,
                onomatopoeia_count=3,
            ),
        ),
        "dark": StyleProfile(
            name="dark",
            description="暗黑风格：长句、阴郁词汇多、对话少",
            features=StyleFeatures(
                avg_sentence_length=35.0,
                long_sentence_ratio=0.3,
                dialogue_ratio=0.15,
                negative_words=10,
                metaphor_count=4,
            ),
        ),
        "tense": StyleProfile(
            name="tense",
            description="紧张风格：短句、动作多、节奏紧凑",
            features=StyleFeatures(
                avg_sentence_length=15.0,
                short_sentence_ratio=0.7,
                dialogue_ratio=0.2,
                onomatopoeia_count=2,
            ),
        ),
    }


# 自动初始化
init_preset_styles()


def get_style_profile(name: str) -> Optional[StyleProfile]:
    """获取风格画像。"""
    return PRESET_STYLES.get(name)


def learn_style_from_samples(samples: list[str], name: str = "custom") -> StyleProfile:
    """从样本文本学习风格。"""
    if not samples:
        return get_style_profile("web_novel") or PRESET_STYLES["web_novel"]

    # 提取所有样本的特征
    all_features = [extract_style_features(s) for s in samples if s]

    # 加权平均
    if not all_features:
        return get_style_profile("web_novel") or PRESET_STYLES["web_novel"]

    # 简单平均（后续可改为加权）
    n = len(all_features)
    avg = StyleFeatures()
    for f in all_features:
        avg.avg_sentence_length += f.avg_sentence_length
        avg.sentence_length_std += f.sentence_length_std
        avg.short_sentence_ratio += f.short_sentence_ratio
        avg.long_sentence_ratio += f.long_sentence_ratio
        avg.type_token_ratio += f.type_token_ratio
        avg.avg_word_length += f.avg_word_length
        avg.dialogue_ratio += f.dialogue_ratio
        avg.dialogue_sentence_ratio += f.dialogue_sentence_ratio
        avg.metaphor_count += f.metaphor_count
        avg.onomatopoeia_count += f.onomatopoeia_count
        avg.parallelism_count += f.parallelism_count
        avg.positive_words += f.positive_words
        avg.negative_words += f.negative_words
        avg.neutral_score += f.neutral_score
        avg.avg_paragraph_length += f.avg_paragraph_length
        avg.paragraph_count += f.paragraph_count
        avg.total_chars += f.total_chars
        avg.total_sentences += f.total_sentences
        avg.total_words += f.total_words

    for field_name in avg.__dataclass_fields__:
        setattr(avg, field_name, getattr(avg, field_name) / n)

    return StyleProfile(
        name=name,
        features=avg,
        description=f"From {n} samples",
        sample_texts=samples[:3],  # 保留前 3 个样本
    )


def style_features_to_prompt(profile: StyleProfile) -> str:
    """将风格画像转换为 prompt 描述。"""
    f = profile.features
    return (
        f"## 风格指南：{profile.name}\n"
        f"{profile.description}\n\n"
        f"目标特征：\n"
        f"- 句子长度：平均 {f.avg_sentence_length:.0f} 字\n"
        f"- 短句比例：{f.short_sentence_ratio * 100:.0f}%\n"
        f"- 长句比例：{f.long_sentence_ratio * 100:.0f}%\n"
        f"- 对话比例：{f.dialogue_ratio * 100:.0f}%\n"
        f"- 段落长度：平均 {f.avg_paragraph_length:.0f} 字\n"
    )


def style_distance(a: StyleFeatures, b: StyleFeatures) -> float:
    """计算两个风格特征的距离（欧氏距离，越小越相似）。"""
    keys = [
        "avg_sentence_length", "sentence_length_std",
        "short_sentence_ratio", "long_sentence_ratio",
        "type_token_ratio", "avg_word_length",
        "dialogue_ratio", "metaphor_count", "parallelism_count",
        "neutral_score", "avg_paragraph_length",
    ]
    distance_sq = 0.0
    for k in keys:
        va = getattr(a, k, 0.0)
        vb = getattr(b, k, 0.0)
        # 归一化：除以最大值做缩放
        max_val = max(abs(va), abs(vb), 1.0)
        distance_sq += ((va - vb) / max_val) ** 2
    return distance_sq ** 0.5
