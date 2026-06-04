import logging
from .enhancement_config import EnhancementConfig

logger = logging.getLogger(__name__)

class PromptEnhancer:
    def __init__(self, config: EnhancementConfig):
        self.config = config

    def build_enhanced_system_prompt(self) -> str:
        parts = []
        parts.append(self.build_core_principles())
        parts.append("\n" + self.build_ai_cliche_ban())
        parts.append("\n【写作技巧库】\n")
        parts.append("=== 十种强力开头技巧 ===")
        for t in self.get_opening_techniques():
            parts.append(f"• {t['name']}：{t['desc']}")
        parts.append("\n=== 五种中文文学技法 ===")
        for t in self.get_literary_techniques():
            parts.append(f"• {t['name']}：{t['desc']}")
        parts.append("\n=== 六种内容扩充技巧 ===")
        for t in self.get_expansion_techniques():
            parts.append(f"• {t['name']}：{t['desc']}")
        parts.append("\n=== 展示而非讲述对照表 ===")
        for p in self.get_show_dont_tell_table():
            parts.append(f"• 讲述「{p['tell']}」→ 展示「{p['show']}」")
        parts.append("\n=== 四种打破预期技术 ===")
        for t in self.get_expectation_breakers():
            parts.append(f"• {t['name']}：{t['desc']}")
        return "\n".join(parts)

    def get_opening_techniques(self) -> list[dict]:
        return [
            {"name": "行动中开场", "desc": "角色正在执行动作，直接拉入场景"},
            {"name": "反常情境", "desc": "违反常理的情况引发好奇"},
            {"name": "震撼对话", "desc": "一句令人震惊的对话开场"},
            {"name": "倒计时开场", "desc": "时间紧迫感推动叙事"},
            {"name": "回忆切入", "desc": "从角色关键记忆切入"},
            {"name": "物件特写", "desc": "聚焦关键物件展开叙事"},
            {"name": "环境渲染", "desc": "用环境氛围暗示即将发生的事件"},
            {"name": "悬念预置", "desc": "先抛出结果再回溯过程"},
            {"name": "内心独白", "desc": "角色内心活动揭示冲突"},
            {"name": "对比反衬", "desc": "用强烈对比场景制造冲击"},
        ]

    def get_literary_techniques(self) -> list[dict]:
        return [
            {"name": "白描", "desc": "不加修饰的直接描写，寥寥数笔勾勒画面"},
            {"name": "留白", "desc": "有意省略，让读者自行补完，信任读者"},
            {"name": "意象营造", "desc": "反复出现某个意象，承载情感和主题"},
            {"name": "草蛇灰线", "desc": "伏笔暗线，前文不经意处埋下，后文呼应"},
            {"name": "蒙太奇剪辑", "desc": "场景快速切换，通过并置产生新含义"},
        ]

    def get_expansion_techniques(self) -> list[dict]:
        return [
            {"name": "场景肌理充实", "desc": "感官层+空间层+情绪层三维充实"},
            {"name": "子弹时间", "desc": "关键时刻放慢，1秒展开为一整段"},
            {"name": "内心世界展开", "desc": "思维链展开+感官触发记忆+内心对话"},
            {"name": "对话层次丰富", "desc": "动作表情中断+潜台词层+话题绕弯"},
            {"name": "次要情节穿插", "desc": "配角片段+暗线推进+伏笔埋设"},
            {"name": "感官维度叠加", "desc": "五感选择与场景情绪匹配"},
        ]

    def get_show_dont_tell_table(self) -> list[dict]:
        return [
            {"tell": "他很愤怒", "show": "他的太阳穴突突跳着，牙齿咬得腮帮子鼓起一道棱"},
            {"tell": "她很悲伤", "show": "她把脸埋进掌心，肩膀一抽一抽的，半天没抬头"},
            {"tell": "他感到害怕", "show": "他的喉结上下滚了一下，脚跟已经在往后挪"},
            {"tell": "她很高兴", "show": "她小跑着迎上去，鞋跟在地面敲出轻快的节奏"},
            {"tell": "他很累", "show": "他把自己摔进椅子里，连抬手关灯的力气都没有"},
            {"tell": "他很惊讶", "show": "他手里的烟掉在地上，火头烫了手指才反应过来"},
            {"tell": "她很紧张", "show": "她把手机翻来覆去地按亮又按灭，屏幕映得脸忽明忽暗"},
            {"tell": "他很自信", "show": "他单手插兜走到台前，扫了一圈，没急着开口"},
            {"tell": "她很犹豫", "show": "她的手指在桌沿上来回摩挲，嘴张了两次又合上"},
            {"tell": "他很失望", "show": "他盯着屏幕上的结果看了很久，然后慢慢把手机扣在桌上"},
        ]

    def get_expectation_breakers(self) -> list[dict]:
        return [
            {"name": "预期反转", "desc": "读者以为是A，实际是B，但逻辑自洽"},
            {"name": "信息差利用", "desc": "读者知道但角色不知道（或反之），制造戏剧反讽"},
            {"name": "复杂动机", "desc": "表面行为背后有多重动机，非单纯善恶"},
            {"name": "节外生枝", "desc": "正当读者以为主线推进时，突然引入意外变量"},
        ]

    def build_ai_cliche_ban(self) -> str:
        bans = [
            ("程度副词类", [
                ("突然", "用具体动作或感官变化替代，如'他猛地一震'"),
                ("竟然", "用角色反应或旁证替代，如'这不可能——'"),
                ("居然", "用意外细节描写替代"),
                ("忽然", "用场景变化直接呈现"),
                ("蓦然", "用角色动作引出"),
            ]),
            ("情绪套话类", [
                ("心中涌起", "用具体身体反应替代，如'胸口一热'"),
                ("内心深处", "用行为表现替代内心独白"),
                ("不由自主", "用无意识动作直接描写"),
                ("情不自禁", "用失控细节描写"),
            ]),
            ("比喻套话类", [
                ("宛如", "用独特比喻或直接描写替代"),
                ("犹如", "用创新意象替代"),
                ("仿佛", "限制使用频率，每段不超过1次"),
                ("就像...一样", "用通感或陌生化比喻替代"),
            ]),
            ("空洞形容词", [
                ("美丽", "用具体视觉细节替代，如'鬓角别着一朵白兰'"),
                ("壮观", "用规模数据或视角变化替代"),
                ("神秘", "用未解细节暗示替代"),
                ("强大", "用具体能力展示替代"),
            ]),
            ("AI常用句式", [
                ("命运的齿轮开始转动", "用具体事件推动替代"),
                ("不仅...更是...", "用递进动作或细节替代"),
                ("与此同时", "用场景切换直接呈现"),
                ("值得注意的是", "删除，直接呈现值得注意的内容"),
            ]),
            ("总结性表达", [
                ("一切尽在不言中", "用沉默或动作暗示替代"),
                ("总而言之", "删除总结句"),
                ("至此", "用下一个小动作过渡"),
            ]),
            ("机械动作描写", [
                ("他点了点头", "用更具体的头部动作或表情替代"),
                ("她摇了摇头", "用动作+态度替代"),
                ("他叹了口气", "用叹气的具体方式描写替代"),
            ]),
        ]
        lines = ["【AI套话禁令】以下表达禁止或限制使用："]
        for category, items in bans:
            lines.append(f"\n=== {category} ===")
            for forbidden, replacement in items:
                lines.append(f"× 禁用「{forbidden}」→ {replacement}")
        return "\n".join(lines)

    def build_core_principles(self) -> str:
        principles = [
            ("段落构造", [
                "每段3-8句，长短交替制造节奏",
                "段落首句设置预期，末句微转或留白",
                "描写段与对话段交替，避免连续3段纯叙事",
            ]),
            ("对话规则", [
                "对话占比不低于15%，不超过40%",
                "每句对话附带动作/表情/环境中的至少一项",
                "避免连续3句以上纯对话无动作",
                "潜台词层：角色说的和想的不完全一致",
            ]),
            ("叙事节奏", [
                "紧张-舒缓交替，高潮段后必有缓冲",
                "关键时刻用子弹时间放慢，过渡段落简洁带过",
                "每3-5章设置1个悬念钩子",
            ]),
            ("人物呈现", [
                "展示而非讲述：用行为、对话、选择展示性格",
                "避免直接描述角色性格标签",
                "角色面临选择时展示内心冲突",
            ]),
            ("场景完整性", [
                "每个场景包含：人物+动作+环境+情绪四要素",
                "场景转换用空间/时间/人物视角切换",
                "关键场景至少包含2个感官维度",
            ]),
            ("语言风格", [
                "句式多样化：避免连续3句相同结构",
                "修辞节制：比喻每段不超过2个",
                "用动词驱动叙事，减少形容词堆砌",
                "口语化对话，书面化叙事，保持区分",
            ]),
        ]
        lines = ["【核心写作原则】"]
        for i, (name, rules) in enumerate(principles, 1):
            lines.append(f"\n{i}. {name}")
            for rule in rules:
                lines.append(f"   • {rule}")
        return "\n".join(lines)
