import random
import re
import logging
from typing import List, Dict, Tuple
from dataclasses import dataclass
from core.llm_router import call_llm, TaskType
from core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class AIPattern:
    id: str
    name: str
    pattern: str
    description: str
    severity: float


AI_PATTERNS = [
    # === 精准的高置信度AI模式（基于blader/humanizer 25模式 + 幻城AITasteDetector）===
    # 以下模式在真实网文中极少出现，一旦出现就是明显的AI痕迹

    # 1-5: 经典AI套路套话（高权重）
    AIPattern("p1", "三选一排比", r"[，,](?:不是|没有|无需)[^，。]{2,10}，也不是[^，。]{2,10}，更不是[^，。]{2,10}", "AI三段式否定排比", 0.9),
    AIPattern("p2", "不仅更是套路", r"不仅[^，。]{2,15}，更是[^，。]{2,15}", "不仅...更是...AI公式", 0.8),
    AIPattern("p3", "不再也不再套路", r"不再[^，。]{2,15}，也不再[^，。]{2,15}", "不再...也不再...AI公式", 0.8),
    AIPattern("p4", "双重否定填充", r"不可否认|毋庸置疑|毫无疑问", "AI论证语气词", 0.9),
    AIPattern("p5", "值得注意的是", r"值得注意的是|需要指出的是|显而易见|众所周知", "AI填充式引导语", 0.9),

    # 6-10: 生硬比喻和象征（高权重）
    AIPattern("p6", "命运的齿轮", r"命运的齿轮|时光的洪流|岁月的长河|历史车轮", "AI陈词滥调式比喻", 1.0),
    AIPattern("p7", "一首诗/歌表达", r"正如[^，。]{2,15}所说|用一首[诗词歌]来形容|可谓", "AI引用式填充", 0.8),
    AIPattern("p8", "通过的方式", r"通过[^，。]{2,20}的方式", "AI方法描述句式", 0.8),
    AIPattern("p9", "基于的基础", r"基于[^，。]{2,20}的基础", "AI论证句式", 0.8),
    AIPattern("p10", "Em dash连用", r"—{3,}", "AI连续破折号", 0.7),

    # 11-15: 机械表达（中等权重）
    AIPattern("p11", "不禁了起来", r"不禁[^，。]{2,10}了起来", "不禁...了起来套路", 0.8),
    AIPattern("p12", "一股涌上心头", r"一股[^，。]{2,15}涌上心头", "一股...涌上心头套路", 0.9),
    AIPattern("p13", "眼中闪过一丝", r"眼中闪过一丝[^，。]{1,10}", "眼中闪过一丝...套路", 0.8),
    AIPattern("p14", "浑身一震/瞳孔骤缩", r"浑身一震|瞳孔骤缩|倒吸一口凉气", "AI剧烈反应三部曲", 0.8),
    AIPattern("p15", "嘴角微微上扬", r"嘴角微微上扬", "AI笑容描写套路", 0.7),

    # 16-20: 总结性表达（中等权重）
    AIPattern("p16", "这一刻终于明白", r"这一刻[，,]?[^。]{5,30}终于[明白懂得知道]", "AI人生感悟式结尾", 0.9),
    AIPattern("p17", "突如其来的感悟", r"醍醐灌顶|恍然大悟|若有所思", "AI机械式领悟", 0.7),
    AIPattern("p18", "说不出难以言喻", r"说不出[^，。]{2,10}|难以言喻的[^，。]{2,10}", "AI模糊感受描写", 0.7),
    AIPattern("p19", "不由自主地", r"不由自主地|情不自禁地|下意识地", "AI机械副词", 0.7),
    AIPattern("p20", "迈着坚定的步伐", r"迈着坚定的步伐|头也不回地|义无反顾地", "AI决心描写套路", 0.8),

    # 21-24: 管腔官话（低权重，但能叠加）
    AIPattern("p21", "作为的证明/体现", r"作为[^，。]{2,15}的(?:证明|体现|象征)", "AI官腔表达", 0.6),
    AIPattern("p22", "标志着", r"标志着|彰显了|凸显了", "AI叙述视角词", 0.5),
    AIPattern("p23", "致力于/聚焦于", r"致力于|聚焦于|着眼于", "AI动词", 0.5),
    AIPattern("p24", "必不可少/至关重要", r"必不可少|至关重要|不可或缺|息息相关", "AI形容词", 0.5),
]


STYLE_LIBRARY = {
    "web_novel": {
        "name": "爽文网文",
        "features": {
            "dialogue_density": 0.3,
            "short_sentence_ratio": 0.5,
            "conflict_per_1000": 1,
            "emotion_words": ["爽", "快", "强", "狠", "绝"],
            "avoid_patterns": ["过度解释", "心理描写过多"],
        }
    },
    "dark": {
        "name": "暗黑流",
        "features": {
            "dialogue_density": 0.25,
            "short_sentence_ratio": 0.4,
            "conflict_per_1000": 0.8,
            "emotion_words": ["冷", "暗", "狠", "绝", "杀"],
            "avoid_patterns": ["情感直述", "程度副词滥用"],
        }
    },
    "humor": {
        "name": "轻松搞笑",
        "features": {
            "dialogue_density": 0.4,
            "short_sentence_ratio": 0.6,
            "conflict_per_1000": 0.5,
            "emotion_words": ["笑", "乐", "逗", "趣", "搞"],
            "avoid_patterns": ["严肃语气", "沉重描写"],
        }
    },
    "serious": {
        "name": "严肃正剧",
        "features": {
            "dialogue_density": 0.2,
            "short_sentence_ratio": 0.3,
            "conflict_per_1000": 0.6,
            "emotion_words": ["深", "重", "沉", "凝", "肃"],
            "avoid_patterns": ["轻浮语气", "玩笑对白"],
        }
    },
}


class AIPatternDetector:
    def __init__(self):
        self.patterns = AI_PATTERNS
    
    def detect(self, text: str) -> List[Dict]:
        results = []
        for pattern in self.patterns:
            matches = list(re.finditer(pattern.pattern, text, re.MULTILINE))
            if matches:
                results.append({
                    "id": pattern.id,
                    "name": pattern.name,
                    "count": len(matches),
                    "severity": pattern.severity,
                    "description": pattern.description,
                    "examples": [m.group()[:50] for m in matches[:3]]
                })
        return sorted(results, key=lambda x: x["severity"] * x["count"], reverse=True)
    
    def get_score(
        self,
        text: str,
        chapter_title: str = "",
        recent_texts: List[str] | None = None,
        recent_titles: List[str] | None = None,
        is_final: bool = False,
    ) -> float:
        results = self.detect(text)
        score = 0.95 if not results else 1.0
        # 每类模式：高权重(>0.7)每次匹配-0.15，中权重(0.5-0.7)每次-0.08，低权重(<0.5)每次-0.05
        # 总惩罚上限0.85，确保分数不会到0.00
        total_penalty = 0.0
        for r in results:
            if r["severity"] >= 0.8:
                total_penalty += min(r["count"], 3) * 0.15
            elif r["severity"] >= 0.6:
                total_penalty += min(r["count"], 3) * 0.08
            else:
                total_penalty += min(r["count"], 3) * 0.05
        structure_penalty = self._structure_penalty(
            text,
            chapter_title=chapter_title,
            recent_texts=recent_texts,
            recent_titles=recent_titles,
            is_final=is_final,
        )
        return max(0.15, score - min(total_penalty + structure_penalty, 0.85))
    
    def get_report(
        self,
        text: str,
        chapter_title: str = "",
        recent_texts: List[str] | None = None,
        recent_titles: List[str] | None = None,
        is_final: bool = False,
    ) -> Dict:
        results = self.detect(text)
        score = self.get_score(
            text,
            chapter_title=chapter_title,
            recent_texts=recent_texts,
            recent_titles=recent_titles,
            is_final=is_final,
        )
        structure_flags = self._structure_flags(
            text,
            chapter_title=chapter_title,
            recent_texts=recent_texts,
            recent_titles=recent_titles,
            is_final=is_final,
        )
        return {
            "ai_score": score,
            "is_ai_like": score < 0.7,
            "patterns_found": len(results),
            "details": results[:10],
            "structure_flags": structure_flags,
            "suggestions": self._generate_suggestions(results, structure_flags)
        }
    
    def detect_text(self, text: str) -> str:
        """检测文本并返回格式化报告（用于前端展示）"""
        results = self.detect(text)
        if not results:
            return "✅ 未检测到明显AI痕迹（24项检查全部通过）"
        lines = [f"📊 AI痕迹评分: {self.get_score(text):.2f} (越低越像AI)"]
        for r in results[:8]:
            lines.append(f"  ❌ {r['name']} x{r['count']}: {r['description']}")
        if len(results) > 8:
            lines.append(f"  ...及{len(results)-8}项其他模式")
        return "\n".join(lines)
    
    def highlight_text(self, text: str) -> Dict:
        """返回带标记位置的检测结果，用于前端内联高亮"""
        results = self.detect(text)
        score = self.get_score(text)
        positions = []
        for r in results:
            for m in re.finditer(r["pattern"], text, re.MULTILINE if "^{" not in r["pattern"] else 0):
                severity_class = "high" if r["severity"] >= 0.8 else ("mid" if r["severity"] >= 0.6 else "low")
                positions.append({
                    "start": m.start(),
                    "end": m.end(),
                    "severity": r["severity"],
                    "severity_class": severity_class,
                    "pattern_name": r["name"],
                    "matched_text": m.group()[:60],
                })
        positions.sort(key=lambda p: p["start"])
        return {
            "ai_score": score,
            "patterns_found": len(results),
            "positions": positions,
            "details": results[:10],
        }
    
    def _normalize_opening(self, text: str, limit: int = 60) -> str:
        compact = re.sub(r"\s+", "", text or "")
        compact = re.sub(r"[，。！？；：“”‘’、,.!?;:\"'()（）【】\\-—]", "", compact)
        return compact[:limit]

    def _resolution_density(self, text: str) -> int:
        markers = ["真相", "承认", "交代", "证实", "解释", "归档", "结案", "结束", "收束", "回答", "代价", "归宿", "公开"]
        return sum(text.count(marker) for marker in markers)

    def _structure_flags(
        self,
        text: str,
        chapter_title: str = "",
        recent_texts: List[str] | None = None,
        recent_titles: List[str] | None = None,
        is_final: bool = False,
    ) -> List[str]:
        flags = []
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if len(paragraphs) >= 4:
            openings = [re.sub(r"\s+", "", p[:20]) for p in paragraphs[:8]]
            if len(openings) != len(set(openings)):
                flags.append("段落开头重复，像模板拼接")
        if text.count("承接前序线索") >= 2:
            flags.append("正文混入规划语言")
        if "下一部或番外的可能性" in text or "下一轮，你来选" in text:
            flags.append("终章仍在新增强钩子，缺少收束")
        if text.count("温静宜") > 25 and text.count("陆彦舟") > 25 and text.count("苏漾") > 25 and text.count("真相") < 2:
            flags.append("人物互动高频重复，但核心问题推进不足")
        repeated_title = False
        normalized_title = re.sub(r"\s+", "", chapter_title or "")
        if normalized_title and recent_titles:
            repeated_title = normalized_title in {re.sub(r"\s+", "", title or "") for title in recent_titles}
            if repeated_title:
                flags.append("相邻章节标题重复，像批量套模板")
        current_opening = self._normalize_opening(text)
        if current_opening and recent_texts:
            overlap_count = 0
            for prev in recent_texts[-3:]:
                prev_opening = self._normalize_opening(prev)
                if not prev_opening:
                    continue
                shared = sum(1 for ch in current_opening[:20] if ch in prev_opening[:24])
                if current_opening[:14] == prev_opening[:14] or shared >= 12:
                    overlap_count += 1
            if overlap_count >= 1:
                flags.append("章节开场动作/感官模板与前文高度重复")
        terminal_lines = [line.strip() for line in text.splitlines() if line.strip()]
        terminal_text = " ".join(terminal_lines[-4:]) if terminal_lines else text[-120:]
        if any(marker in terminal_text for marker in ["下一次", "下一轮", "新的谜团", "新的开始", "更大的真相", "真正的故事才刚开始"]):
            flags.append("章节结尾在重开新主钩子，像续写预告")
        if is_final:
            if self._resolution_density(text) < 3:
                flags.append("终章回收密度过低，像没真正结尾")
            if any(marker in terminal_text for marker in ["疑问", "还没有结束", "只是开始", "下一部", "番外", "更深的秘密"]):
                flags.append("终章结尾仍在开新坑")
        return flags

    def _structure_penalty(
        self,
        text: str,
        chapter_title: str = "",
        recent_texts: List[str] | None = None,
        recent_titles: List[str] | None = None,
        is_final: bool = False,
    ) -> float:
        penalty = 0.0
        for flag in self._structure_flags(
            text,
            chapter_title=chapter_title,
            recent_texts=recent_texts,
            recent_titles=recent_titles,
            is_final=is_final,
        ):
            if "终章" in flag:
                penalty += 0.20
            elif "规划语言" in flag:
                penalty += 0.18
            elif "标题重复" in flag or "开场动作" in flag:
                penalty += 0.15
            else:
                penalty += 0.10
        return penalty

    def _generate_suggestions(self, results: List[Dict], structure_flags: List[str] | None = None) -> List[str]:
        suggestions = []
        for r in results[:5]:
            if r["severity"] > 0.6:
                suggestions.append(f"建议修改「{r['name']}」: {r['description']}")
        for flag in structure_flags or []:
            suggestions.append(f"结构问题：{flag}")
        return suggestions


class DialogueAnalyzer:
    def analyze(self, text: str) -> Dict:
        dialogue_pattern = r'[「」""]'
        dialogues = re.findall(dialogue_pattern, text)
        dialogue_count = len(dialogues) // 2
        
        total_chars = len(text)
        dialogue_ratio = (dialogue_count * 20) / total_chars if total_chars > 0 else 0
        
        paragraphs = text.split('\n\n')
        para_without_dialogue = sum(1 for p in paragraphs if not re.search(dialogue_pattern, p))
        
        return {
            "dialogue_count": dialogue_count,
            "dialogue_ratio": round(dialogue_ratio, 3),
            "total_paragraphs": len(paragraphs),
            "para_without_dialogue": para_without_dialogue,
            "dialogue_density": round(dialogue_count / max(len(paragraphs), 1), 2)
        }
    
    def adjust_density(self, text: str, target_density: float = 0.3) -> Tuple[str, Dict]:
        current = self.analyze(text)
        current_density = current["dialogue_density"]
        
        if current_density >= target_density:
            return text, current
        
        return text, current

INNER_MONOLOGUES = [
    "不行，不能就这样算了。",
    "这一步，必须走对。",
    "果然如此……",
    "来不及多想了。",
    "看来，只能赌一把了。",
    "该来的，终究还是来了。",
    "这感觉……不对劲。",
    "算了，先走一步看一步吧。",
]

CASUAL_PHRASES = [
    "嗯，",
    "——",
    "……",
    "说实话，",
    "怎么说呢，",
    "倒也",
    "偏偏",
]

REWRITE_SYSTEM = """你是一个保守的文本润色专家，专攻去除AI生成痕迹。
只做最小幅度的修改来消除明显的AI痕迹：

AI高频套话（必须转换）：
1. 三选一排比"不是...也不是...更不是..." → 简化为直接陈述
2. "不仅...更是...""不再...也不再..." → 拆成自然短句
3. "值得注意的是/显而易见/不可否认/毋庸置疑" → 删除
4. "通过...的方式/基于...的基础" → 简化为"用/靠/凭"
5. "命运的齿轮/时光的洪流" → 删除或用具体描写替代
6. "一股...涌上心头/眼中闪过一丝..." → 改为动作描写
7. "浑身一震/瞳孔骤缩/倒吸一口凉气" → 改为具体反应
8. "这一刻...终于明白/醍醐灌顶/恍然大悟" → 去掉总结句式
9. "不由自主地/情不自禁地/下意识地" → 简化或删除
10. "标志着/彰显了/致力于"等官腔 → 改为口语化表达

重点：不要重写没有问题的句子。保留原文的语气、风格和节奏。不要添加原文没有的内容。"""

REWRITE_PROMPT = """请对以下文本做最小幅度润色，只修改有明显AI痕迹的部分：

{text}

检查以下AI痕迹并修正（其他保持不动）：
1. 三选一排比"不是A也不是B更不是C" → 拆成自然句
2. "不仅...更是...""不再...也不再..." → 改为自然连接
3. "值得注意的是/显而易见/不可否认" → 删除
4. "通过...的方式/基于...的基础" → 简化为"用/靠"
5. "一股...涌上心头/眼中闪过一丝..." → 改为动作
6. "浑身一震/瞳孔骤缩" → 改为具体描写
7. "这一刻...终于明白" → 去掉总结性表达
8. "不由自主地/情不自禁地" → 简化
9. "标志着/彰显了/致力于" → 口语化
10. "命运的齿轮/时光的洪流" → 用具体叙事替代

禁止：
- 不要增加原文没有的内容
- 不要改动对话内容
- 不要重写没有问题的段落
- 不要改变段落顺序
- 不要插入心理描写或内心独白

直接输出修改后的文本，不要任何说明。"""


class StyleRewriter:
    def insert_inner_monologue(self, text: str, rate: float = None) -> str:
        rate = rate or settings.STYLE_PERTURBATION_RATE
        sentences = re.split(r'([。！？])', text)
        result = []
        i = 0
        while i < len(sentences):
            result.append(sentences[i])
            if i + 1 < len(sentences) and sentences[i + 1] in '。！？':
                result.append(sentences[i + 1])
                if random.random() < rate and len(sentences[i]) > 5:
                    monologue = random.choice(INNER_MONOLOGUES)
                    result.append(f"\n{monologue}\n")
                i += 2
            else:
                i += 1
        return "".join(result)

    def insert_casual_phrases(self, text: str, rate: float = 0.1) -> str:
        result = text
        commas = list(re.finditer(r'，', result))
        for m in reversed(commas):
            if random.random() < rate:
                phrase = random.choice(CASUAL_PHRASES)
                pos = m.start() + 1
                result = result[:pos] + phrase + result[pos:]
        return result

    def vary_sentence_length(self, text: str) -> str:
        sentences = re.split(r'([。！？])', text)
        result = []
        for i, s in enumerate(sentences):
            if len(s) > 50 and random.random() < 0.3:
                mid = len(s) // 2
                for pos in range(mid, len(s)):
                    if s[pos] == '，':
                        result.append(s[:pos] + '。\n')
                        result.append(s[pos + 1:])
                        break
                else:
                    result.append(s)
            else:
                result.append(s)
        return "".join(result)

    def reduce_repetitive_patterns(self, text: str) -> str:
        result = text
        patterns = [r'他(.{1,4})了', r'她(.{1,4})了']
        for pattern in patterns:
            count = len(re.findall(pattern, result))
            if count > 3:
                matches = list(re.finditer(pattern, result))
                offset = 0
                for m in matches[1::2]:
                    start = m.start() + offset
                    end = m.end() + offset
                    replacement = f"{m.group(0)[:-1]}，"
                    result = result[:start] + replacement + result[end:]
                    offset += len(replacement) - (end - start)
        return result

    def humanize_rule_replacement(self, text: str) -> str:
        result = text

        replacements = [
            (r'然而，', lambda m: random.choice(['不过', '但', '只是'])),
            (r'因此，', lambda m: random.choice(['所以', '于是', '这么一来'])),
            (r'此外，', lambda m: random.choice(['另外', '还有', '再说'])),
            (r'与此同时，', lambda m: random.choice(['同一时间', '这会儿', '这边'])),
            (r'毫无疑问，', lambda m: ''),
            (r'值得注意的是，', lambda m: ''),
            (r'需要指出的是，', lambda m: ''),
            (r'众所周知，', lambda m: ''),
            (r'显而易见，', lambda m: ''),
            (r'事实上，', lambda m: ''),
            (r'总而言之，', lambda m: random.choice(['总之', '说白了'])),
            (r'综上所述，', lambda m: '说白了'),
            (r'换言之，', lambda m: random.choice(['也就是说', '换个说法'])),
            (r'在一定程度上', lambda m: random.choice(['多少', '有些'])),
            (r'另一方面', lambda m: random.choice(['反过来说', '换个角度'])),
            (r'令人印象深刻的是', lambda m: random.choice(['让人惊叹', '叫人难忘'])),
            (r'不可或缺', lambda m: random.choice(['少不了', '离不了'])),
            (r'至关重要', lambda m: random.choice(['要紧', '关键'])),
            (r'息息相关', lambda m: random.choice(['连着', '绑在一起'])),
            (r'层出不穷', lambda m: random.choice(['一个接一个', '没完没了'])),
            (r'作为[^，。]{2,10}的证明', lambda m: ''),
            (r'作为[^，。]{2,10}的体现', lambda m: ''),
            (r'标志着', lambda m: random.choice(['意味着', '说明'])),
            (r'见证了', lambda m: random.choice(['经历了', '看到了'])),
            (r'凸显了', lambda m: random.choice(['显出了', '透出了'])),
            (r'彰显了', lambda m: random.choice(['透出了', '显出了'])),
            (r'致力于', lambda m: random.choice(['一直在做', '专心于'])),
            (r'充满了活力', lambda m: '热闹'),
            (r'充满活力的', lambda m: '热闹的'),
            (r'令人叹为观止', lambda m: random.choice(['让人惊叹', '真叫人叫绝'])),
            (r'不断演变的格局', lambda m: '变局'),
            (r'深刻的', lambda m: random.choice(['深的', '透彻的'])),
            (r'持久的', lambda m: random.choice(['长久的', '持续的'])),
            (r'增强其', lambda m: '增强'),
            (r'深入探讨', lambda m: random.choice(['细说', '深聊'])),
            (r'为了实现这一目标', lambda m: '为此'),
            (r'在这个时间点', lambda m: '现在'),
            (r'值得注意的是数据显示', lambda m: '数据显示'),
            (r'可以潜在地', lambda m: '可能'),
            (r'希望这对您有帮助', lambda m: ''),
            (r'希望这对你有帮助', lambda m: ''),
            (r'坐落在[^，。]{2,20}中心', lambda m: random.choice(['在', '地处'])),
            (r'拥有丰富的', lambda m: random.choice(['有不少', '有着丰富的'])),
            (r'不仅仅[^。？]{2,30}而是', lambda m: random.choice(['不是', '与其说'])),
        ]

        for pattern, repl_fn in replacements:
            result = re.sub(pattern, repl_fn, result)

        return result

    def humanize_reduce_fillers(self, text: str) -> str:
        result = text
        filler_patterns = [
            (r'其实', 2),
            (r'确实', 2),
            (r'的确', 2),
            (r'实际上', 2),
            (r'本身', 2),
            (r'真的', 3),
        ]
        for pattern, threshold in filler_patterns:
            count = len(re.findall(pattern, result))
            if count > threshold:
                matches = list(re.finditer(pattern, result))
                remove_indices = set()
                for i, m in enumerate(matches):
                    if i > 0 and (i + 1) % 2 == 0:
                        remove_indices.add(i)
                for i in sorted(remove_indices, reverse=True):
                    m = matches[i]
                    result = result[:m.start()] + result[m.end():]
        return result

    def humanize_show_dont_tell(self, text: str) -> str:
        result = text
        show_replacements = [
            (r'他感到愤怒', '他攥紧了拳头，牙关咬得咯咯作响'),
            (r'她感到愤怒', '她攥紧了拳头，牙关咬得咯咯作响'),
            (r'他感到悲伤', '他的眼眶不由得一红'),
            (r'她感到悲伤', '她的眼眶不由得一红'),
            (r'他感到害怕', '他后背一阵发凉'),
            (r'她感到害怕', '她后背一阵发凉'),
            (r'他感到惊讶', '他瞳孔猛地一缩'),
            (r'她感到惊讶', '她瞳孔猛地一缩'),
            (r'他感到高兴', '他嘴角不由得翘了起来'),
            (r'她感到高兴', '她嘴角不由得翘了起来'),
            (r'他觉得很累', '他像是被抽干了力气'),
            (r'她觉得很累', '她像是被抽干了力气'),
        ]
        for pattern, replacement in show_replacements:
            result = re.sub(pattern, replacement, result)
        return result

    def humanize_break_long_sentences(self, text: str) -> str:
        result = text
        sentences = re.split(r'([。！？])', result)
        new_sentences = []
        for s in sentences:
            if len(s) > 80:
                comma_positions = [m.start() for m in re.finditer(r'[，,；；]', s)]
                if comma_positions:
                    mid = len(s) // 2
                    best = min(comma_positions, key=lambda x: abs(x - mid))
                    new_sentences.append(s[:best + 1] + '\n')
                    new_sentences.append(s[best + 1:])
                else:
                    new_sentences.append(s)
            else:
                new_sentences.append(s)
        return "".join(new_sentences)

    def humanize_add_micro_actions(self, text: str, rate: float = 0.15) -> str:
        micro_actions = [
            "他舔了舔干裂的嘴唇。",
            "她下意识攥紧了衣角。",
            "他深吸一口气。",
            "她皱了皱眉。",
            "他目光微沉。",
            "她偏了偏头。",
            "他指尖微微收紧。",
            "她不自觉屏住了呼吸。",
        ]
        sentences = re.split(r'([。！？])', text)
        result = []
        i = 0
        while i < len(sentences):
            result.append(sentences[i])
            if i + 1 < len(sentences) and sentences[i + 1] in '。！？':
                result.append(sentences[i + 1])
                if random.random() < rate and len(sentences[i]) > 10:
                    action = random.choice(micro_actions)
                    result.append(f"\n{action}\n")
                i += 2
            else:
                i += 1
        return "".join(result)

    def rule_based_rewrite(self, text: str) -> str:
        text = self.humanize_rule_replacement(text)
        text = self.humanize_reduce_fillers(text)
        text = self.humanize_show_dont_tell(text)
        text = self.humanize_break_long_sentences(text)
        return text

    async def llm_rewrite(self, text: str) -> str:
        prompt = REWRITE_PROMPT.format(text=text)
        rewritten = await call_llm(TaskType.REWRITE, prompt, system=REWRITE_SYSTEM, temperature=0.3, max_tokens=len(text) * 2)
        return rewritten

    async def rewrite(self, text: str, use_llm: bool = True) -> str:
        text = self.rule_based_rewrite(text)
        if use_llm and len(text) > 200:
            text = await self.llm_rewrite(text)
        return text

    async def remove_ai_traces(self, content: str) -> str:
        content = self.vary_sentence_length(content)
        content = self.humanize_rule_replacement(content)
        content = self.insert_inner_monologue(content)
        content = self.humanize_break_long_sentences(content)
        content = self.humanize_reduce_fillers(content)
        content = self.humanize_add_micro_actions(content)
        return content

    def detect_5_strategies(self, text: str) -> list[dict]:
        results = []
        pattern_results = self.detect(text)
        if pattern_results:
            results.append({
                "strategy": "regex_pattern",
                "name": "正则模式匹配",
                "findings": pattern_results,
                "total": len(pattern_results),
            })

        sentences = _split_sentences(text)
        if len(sentences) >= 3:
            consecutive_same = 0
            max_consecutive = 0
            for i in range(1, len(sentences)):
                if self._same_structure(sentences[i], sentences[i-1]):
                    consecutive_same += 1
                    max_consecutive = max(max_consecutive, consecutive_same + 1)
                else:
                    consecutive_same = 0
            if max_consecutive >= 3:
                results.append({
                    "strategy": "sentence_diversity",
                    "name": "句式多样性分析",
                    "findings": [f"连续{max_consecutive}句相同句式结构"],
                    "total": 1,
                })

        cliche_patterns = [
            (r'不仅[^，。]{2,15}，更是', "套话排比"),
            (r'不由自主地|情不自禁地', "机械副词"),
            (r'宛如[^，。]{2,15}一般', "空洞比喻"),
        ]
        expression_findings = []
        for pattern, name in cliche_patterns:
            matches = re.findall(pattern, text)
            if matches:
                expression_findings.append(f"{name}: {len(matches)}处")
        if expression_findings:
            results.append({
                "strategy": "expression_humanization",
                "name": "表达方式人性化检测",
                "findings": expression_findings,
                "total": len(expression_findings),
            })

        rhetoric_types = {"比喻": 0, "排比": 0, "设问": 0, "反问": 0}
        rhetoric_types["比喻"] = len(re.findall(r'像|如|似|仿佛', text))
        rhetoric_types["排比"] = len(re.findall(r'也[^。]{2,15}，也[^。]{2,15}，也', text))
        rhetoric_types["设问"] = len(re.findall(r'[吗呢吧？].{0,5}[？?]', text))
        overused = {k: v for k, v in rhetoric_types.items() if v > 5}
        if overused:
            results.append({
                "strategy": "rhetoric_pattern",
                "name": "修辞模式检测",
                "findings": [f"{k}过度使用({v}次)" for k, v in overused.items()],
                "total": len(overused),
            })

        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        summary_findings = []
        for para in paragraphs[-3:]:
            if any(kw in para for kw in ["总而言之", "至此", "一切尽在不言中", "终于明白"]):
                summary_findings.append(f"段落含总结性表达")
        if summary_findings:
            results.append({
                "strategy": "summary_expression",
                "name": "总结性表达检测",
                "findings": summary_findings,
                "total": len(summary_findings),
            })

        return results

    def _same_structure(self, s1: str, s2: str) -> bool:
        def structure_key(s):
            has_subj = bool(re.search(r'[他她它我你]', s[:5]))
            has_dlg = any(q in s for q in ['\u201c', '\u201d', '"'])
            length_bin = len(s) // 20
            return (has_subj, has_dlg, length_bin)
        return structure_key(s1) == structure_key(s2)

    def compute_residual_score(self, text: str) -> dict:
        all_findings = self.detect_5_strategies(text)
        total_findings = sum(r.get("total", 0) for r in all_findings)
        sentences = _split_sentences(text)
        total_segments = max(1, len(sentences))
        residual_score = total_findings / total_segments

        return {
            "residual_score": round(residual_score, 3),
            "total_findings": total_findings,
            "total_segments": total_segments,
            "strategies": all_findings,
            "is_acceptable": residual_score < 0.1,
        }


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？；\n]", text)
    return [s.strip() for s in parts if len(s.strip()) > 5]
