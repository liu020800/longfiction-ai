import logging
from .models import StructureCheckResult
from .enhancement_config import EnhancementConfig
from core.word_counter import count_chinese_words

logger = logging.getLogger(__name__)

HOOK_KEYWORDS = ["悬念", "冲突", "反常", "震惊", "意外", "危机", "谜团", "威胁", "紧迫", "异常"]
ENDING_HOOK_KEYWORDS = ["然而", "但是", "不过", "突然", "就在这时", "谁知", "不料", "竟然", "此刻", "危险"]
# 开头动作模式：用正则检测行动/对话开场（比关键词更可靠）
OPENING_ACTION_PATTERNS = [
    r'^[""「]',  # 对话开场
    r'^[一-鿿]{2,6}(?:跑|冲|推|踢|砸|抓|拔|握|转|站|坐|跳|喊|叫|骂)',  # 动作开场
    r'(?:门|窗|枪|刀|剑|手|脚)(?:被|猛|突|一)',  # 物件动作
    r'(?:爆炸|枪声|尖叫|警报|轰鸣)',  # 突发事件
]
# 结尾悬念模式：检测未完成的叙事（比转折词更可靠）
ENDING_SUSPENSE_PATTERNS = [
    r'[。！？]\s*$',  # 正常结尾（不算悬念）
    r'[一-鿿]{2,8}(?:还没有|并未|仍未|尚未)',  # 未完成
    r'(?:不知道|不确定|不明白|看不清|听不见)',  # 悬而未决
    r'(?:下一页|下一步|接下来|明天|之后)',  # 指向未来
]

class StructureEnforcer:
    def __init__(self, config: EnhancementConfig):
        self.config = config
    
    def get_structure_instruction(self, target_words: int) -> str:
        hook_words = int(target_words * self.config.STRUCTURE_HOOK_RATIO)
        dev_words = int(target_words * self.config.STRUCTURE_DEV_RATIO)
        climax_words = int(target_words * self.config.STRUCTURE_CLIMAX_RATIO)
        tail_words = int(target_words * self.config.STRUCTURE_TAIL_RATIO)
        return (
            f"\n【章节结构要求】目标{target_words}字\n"
            f"1. 开头钩子({hook_words}字左右)：必须用行动/冲突/悬念开场，禁止天气描写/日常流程/回顾上章\n"
            f"2. 发展推进({dev_words}字左右)：推进主线+至少2个张力波峰，30%以上对话\n"
            f"3. 高潮时刻({climax_words}字左右)：本章核心冲突爆发或转折\n"
            f"4. 结尾钩子({tail_words}字左右)：设置悬念或预告，让读者想翻下一页\n"
        )
    
    def check_structure(self, chapter_text: str, target_words: int) -> StructureCheckResult:
        import re as _re
        issues = []
        total = count_chinese_words(chapter_text)
        if total < target_words * 0.7:
            issues.append(f"字数不足: {total}字 < 目标{target_words}字的70%")

        # 开头检查：关键词 OR 动作模式 OR 对话开场
        hook_end = max(200, int(total * self.config.STRUCTURE_HOOK_RATIO))
        opening = chapter_text[:hook_end]
        has_opening_hook = (
            any(kw in opening for kw in HOOK_KEYWORDS)
            or any(_re.search(p, opening) for p in OPENING_ACTION_PATTERNS)
        )
        if not has_opening_hook:
            issues.append("开头缺少钩子元素(悬念/冲突/反常/动作/对话)")

        # 结尾检查：转折词 OR 悬念模式
        tail_start = int(total * (1 - self.config.STRUCTURE_TAIL_RATIO))
        ending = chapter_text[tail_start:]
        has_ending_hook = (
            any(kw in ending for kw in ENDING_HOOK_KEYWORDS)
            or any(_re.search(p, ending) for p in ENDING_SUSPENSE_PATTERNS)
        )
        if not has_ending_hook:
            issues.append("结尾缺少悬念钩子")

        # 高潮检查：扩展关键词列表
        climax_start = int(total * (1 - self.config.STRUCTURE_CLIMAX_RATIO - self.config.STRUCTURE_TAIL_RATIO))
        climax_end = tail_start
        climax = chapter_text[climax_start:climax_end]
        climax_keywords = ["冲突", "战斗", "对峙", "爆发", "转折", "击败", "揭露",
                          "选择", "牺牲", "决定", "真相", "秘密", "发现", "失去"]
        has_climax_conflict = any(kw in climax for kw in climax_keywords)
        if not has_climax_conflict:
            issues.append("高潮段落缺少冲突/转折")

        return StructureCheckResult(
            compliant=len(issues) == 0,
            issues=issues,
            hook_present_opening=has_opening_hook,
            hook_present_ending=has_ending_hook,
        )
    
    def get_state(self) -> dict:
        return {}
    
    def restore_state(self, state: dict):
        pass
