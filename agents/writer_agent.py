import logging
import re
from core.llm_router import call_llm, TaskType
from core.models import SceneOutline
from core.config import settings
from core.word_counter import count_chinese_words, compute_deviation, _rule_based_trim

logger = logging.getLogger(__name__)

WRITER_SYSTEM = """你是一个资深网文作者，深谙长篇网文的写作技法。

## AI痕迹禁令（只禁真正有AI感的表达）

以下是典型的AI生成痕迹，正文中必须避免：

### 情绪套话（用具体动作替代）
× 心中涌起、心中升起、心头涌上、心潮澎湃
× 一股暖流涌上心头、一股寒意涌上心头
× 瞳孔骤缩、倒吸一口凉气、浑身一震
× 一种说不出的感觉、一股莫名的

### 空洞形容（用细节替代）
× 美丽的、壮观的、惊人的、震撼的、绝美的
× 不可思议的、难以置信的、无与伦比的
× 令人叹为观止的、令人窒息的

### AI常用句式
× 值得注意的是、显而易见、众所周知、不可否认
× 人生感悟、深刻领悟、恍然大悟、醍醐灌顶
× 此时此刻、在那一刻、这一瞬间

### 重复机械动作（同一章内禁超2次）
× 点了点头、摇了摇头、叹了口气、皱了皱眉

### 格式禁令
× 正文中严禁出现"第X章"等章节编号
× 禁止括号注释人物（如"他（李明）"）

### 替换示例
❌ "突然，他感受到了前所未有的恐惧"
✅ "他的手不受控制地抖了一下，杯子里的水洒出来几滴。"

❌ "他心中涌起一股暖流"
✅ "他鼻子一酸，别过头去。"

## 核心写作原则

### 1. 段落构造
每段必须包含至少两项以下元素：动作、对话、环境反应、情绪递进。严禁连续三段以上纯叙事。

### 2. 对话规则
- 对话必须带有说话人的微动作或神态标识，不要只有"某某说："
- 对话内容要有潜台词（言外之意），不要直白交代信息
- 人物间对话要有张力——即使闲聊也要带出性格冲突或信息差

### 3. 叙事节奏
- 开篇直入场景，不要在段落开头做背景交代
- 每300-500字安排一个微冲突或转折（认知变化、局势反转、新信息揭露）
- 长短句交替使用：连续3个短句后必须有一个长句缓冲，反之亦然
- 场景结尾必须有悬念钩子或情绪收束，不能自然淡出

### 4. 人物呈现
- 用动作和细节展示性格（例如：紧张时攥拳、焦虑时踱步），不做心理分析式描述
- 每个出场角色都要有当下目的，不写无动机的闲聊
- 角色情绪变化必须有前置触发事件，不能凭空转变

### 5. 场景完整性
每个场景必须包括：入场锚点（即时情境）→ 冲突推进（至少一个转折）→ 
情绪落点（角色状态变化或悬念）→ 离场钩子（自然连接到下一场景）。

### 6. 语言风格
- 使用中文网文自然语感，注入口语化表达但不失流畅
- 适度使用短段落制造节奏感（2-4句过渡段）
- 比喻优先使用网文常见意象（刀、火、冰、影等）
- 拒绝书面语、学术式表达
- 用具体细节代替形容词（不要说"他很伤心"，写"他手指微微颤抖"）
- 用动作代替心理描写（不要说"他心中涌起"，写具体动作）

### 7. 信息密度控制（极其重要）
- 每章只聚焦一个核心事件/冲突，不要同时展开多条主线
- 角色的前世/未来信息每章最多透露1-2条关键点，其余留给后续章节
- 不要一次性把角色的完整命运履历全写出来，只露冰山一角
- 新设定（能力、规则、系统）通过具体事件验证，不要用内心旁白硬讲规则体系
- 如果一个信息点读者不需要在本章知道，就不要写

### 8. 主角行动力要求
- 主角在每章必须做出至少一个具体决定或行动（不能只是观察、回忆、震惊）
- 确认性场景（确认日期、确认身份、确认环境）全章只写一次，写完就推进
- 主角的内心独白不能超过连续3段，必须转入行动或对话
- 每章结尾主角必须有一个明确的下一步计划或行动方向

### 9. 反重复铁律
- 同一个事实（日期、环境特征、角色状态）全章只确认一次
- 禁止用不同措辞反复描写同一个动作（看手、看日期、看天花板）
- 如果某段描写与前文表达的是同一个信息，必须删除
- 环境描写不要反复出现相同元素（裂纹、床架、空调等一次到位）

### 10. 高频AI短语禁令（严格限制出现次数）
以下短语在全书中出现次数严重超标，必须严格控制：
- "——不是X，是Y"结构：每章最多1次
- "，像是"：每章最多1次
- "指节发白"：全书最多3次
- "瞳孔微缩/骤缩"：全书最多5次
- "手心出汗/冒汗"：每卷最多3次
- "指尖"：每章最多1次
- "金属质感/金属味"：每章最多1次
- "接入器发烫/变红"：每卷最多5次
- "还有X分钟/秒"倒计时：每章最多1次
- "屏幕黑了/亮了"：每章最多1次
- "表情很干净"：全书最多2次
- "心中涌起/升起"：禁用
- "一股暖流/寒意"：禁用
- "倒吸一口凉气"：禁用
- "浑身一震"：禁用
替换方案：用具体的、独特的感官细节替代这些套话。每个场景的紧张感应该通过不同的方式表达。

### 10b. 词汇多样性（通用原则）
- 同一个词（尤其是道具名、地名、动作词）在同一章内出现不应超过3-5次
- 如果某个物件在前几章已经被高频使用，本章应寻找替代表达或减少提及
- 具体物件（武器、工具、场景标志物）只在关键叙事节点出现，不要作为填充词
- 如果上下文中标注了「已过度重复的词」，必须严格避免再次高频使用那些词

### 11. 章节长度变化
- 不要每章都写成相同的字数
- 关键情感场景、高潮章节可以写到1.5-2倍正常长度
- 过渡章节可以短一些（0.7-0.8倍正常长度）
- 章节长度应随情节需要自然变化，而非机械统一

### 12. 场景多样性
- 连续3章不能使用相同类型的场景（如连续地下通道）
- 每5章至少包含1个地面场景、1个室内场景、1个对话驱动场景
- 场景转换应有叙事意义，不能只是为了"换个地方"
- 禁止"进入→发现线索→被追→逃脱→重复"的机械循环

### 13. 角色一致性
- 已出场的角色不能被遗忘，每个角色必须有完整的弧线
- 如果一个角色在某章被提及（如"女儿苏栀"），后续章节必须有回应
- 角色的动机必须贯穿全书，不能因为情节需要而被忽略
- 配角需要独立的动机和恐惧，不能只是"有用的道具"

### 14. 伏笔回收
- 每埋设一个伏笔，必须在后续章节中回收
- 短期伏笔（1-3章内回收）：小悬念、小秘密
- 中期伏笔（4-8章内回收）：人物关系、事件真相
- 长期伏笔（9-20章内回收）：世界观核心谜团
- 伏笔回收率必须达到70%以上

### 15. 情感深度
- 关键情感场景（见到亲人、失去同伴、重大决定）需要专门的叙事空间
- 不能用"他感到悲伤"一笔带过，要通过具体动作、感官细节、内心独白展现
- 悲伤：不只是"眼眶发红"，可以写"他盯着某个物件看了很久，手指无意识地摩挲着边缘"
- 恐惧：不只是"心跳加速"，可以写"他的视线不受控制地往出口方向飘，脚跟已经转向"
- 喜悦：不只是"嘴角上扬"，可以写"他小跑起来，连自己都没意识到"

### 16. 对话质量
- 禁止"讲课式对话"——一个角色用大段话解释技术原理
- 对话应该在分歧、冲突、试探中展开，信息在交锋中传递
- 每个角色的说话方式要有区分（用词习惯、句子长短、是否直接）
- 对话中要有潜台词——角色说的和想的不一样
"""

SCENE_DRAFT_PROMPT = """直接写一段完整的小说场景正文。不要先列大纲，直接输出正文。

章节契约：
{chapter_contract}
场景：{scene_desc}
出场人物：{characters}
地点：{location}
氛围：{mood}
人物状态：{char_status}
上下文：{context}
场景张力：{tension_label}
感官重点：{sensory_focus}

要求：
- 直接输出小说正文，不要任何说明和前言，不要列事件点。
- 严格控制在{target_words}字左右，至少{min_words}字，理想范围 {min_words}-{max_words} 字。
- 不要输出章节标题，不要写"第X章"。
- 场景开头第一句直接进入情境，不能做背景交代。
- 场景中间必须有一次冲突或转折（意见分歧、意外信息、局势反转）。
- 场景结尾必须留钩子（悬念、情绪余韵、或明示下一动作方向）。
- 必须有对话推动，不能全是叙事描写。
- 每个出场人物都应有其当下的动机和行为。
- 至少写出一种非视觉感官细节，优先服从"感官重点"。
- 同一场景里不同角色说话要有区分，不要所有人都一个语气。
- 用动作和细节心理代替"他感到/他觉得/他意识到"。
- 本场景只聚焦一个核心事件，不要在一个场景里堆叠多个重大信息。
- 主角必须有具体行动，不能只做旁观者、回忆者或震惊者。
- 同一个事实（日期/身份/环境）只确认一次，确认完立即推进剧情。"""

CHAPTER_DRAFT_PROMPT = """直接写出一整章完整的小说正文。不要先列大纲，直接输出正文。

【最高优先级：章节契约（本章必须严格围绕以下内容展开）】
{chapter_contract}

场景结构指引（仅供参考节奏，不要分段标注场景编号）：
{scene_guide}

出场人物：{characters}
人物状态：{char_status}
背景参考（仅供参考，不要主动在正文中引入背景参考中的信息，除非章节契约明确要求）：
{context}

跨章衔接信息：
{previous_ending}

衔接要求：
- 如果有「上一章结尾原文」，本章开头必须与其无缝衔接，像同一篇文章的自然延续。
- 如果有「上章结尾钩子」，本章前1/3必须回应该钩子。
- 保持角色情绪和位置的连续性，不要凭空切换场景。

要求：
- 直接输出小说正文，不要任何说明和前言。
- 严格控制在{target_words}字左右，至少{min_words}字，理想范围 {min_words}-{max_words} 字。
- 不要输出章节标题，不要写"第X章"。
- 本章正文必须围绕章节契约中的「章节目标」和「章节冲突」展开，不得偏离。
- 这是一整章连续叙事，所有场景之间必须有自然过渡，禁止出现拼接感。
- 章节开头第一句必须与上一章结尾自然衔接（如果有跨章衔接信息的话）。
- 如果没有跨章衔接信息，开篇直接进入情境，不做背景交代。
- 整章必须有完整的叙事弧：入局→冲突升级→转折→情绪落点→离场钩子。
- 全章围绕一个核心事件推进，场景转换用叙事过渡而非硬切。
- 必须有对话推动情节，不能全是叙事描写。
- 每个出场人物都要有其当下的动机和行为。
- 主角必须有具体行动和决定，不能只做旁观者、回忆者或震惊者。
- 同一个事实（日期/身份/环境）只确认一次，确认完立即推进剧情。
- 场景转换处用1-2句过渡句衔接，不要硬切到新场景。
- 结尾必须留钩子（悬念、情绪余韵、或明示下一行动方向）。
- 不要在正文中引入章节契约未提及的重大新设定、新年代或新历史事件。
- 章节长度应随情节需要变化：高潮章节可以写长（1.5倍），过渡章节可以写短（0.7倍）。
- 如果本章包含伏笔回收，必须明确写出回收过程，不能暗示或省略。
- 如果有已出场但近期未出现的角色，本章应适当提及或出场。
- 禁止使用"进入地下→发现线索→被追→逃脱"的机械循环模式。
- 每个场景必须有独立的叙事目的，不能只是"换个地方继续同样的事"。
- 结尾钩子不要用"接入器发烫"或"屏幕闪烁"这类已被过度使用的手段。"""

SCENE_CONTINUATION_PROMPT = """继续写本章的下一个场景。必须与前文紧密衔接，像是同一篇文章的自然延续。

章节契约：
{chapter_contract}
当前场景：{scene_desc}
出场人物：{characters}
地点：{location}
氛围：{mood}
场景张力：{tension_label}
感官重点：{sensory_focus}

本章前文（你已经写好的部分，必须从这里自然续写）：
...{previous_text}

要求：
- 直接输出本场景正文，不要任何说明。
- 严格控制在{target_words}字左右。
- 开头第一句必须与前文最后一段自然衔接，禁止重新开场。
- 禁止重复前文已经写过的内容（对话、描写、事件）。
- 保持人物状态与前文一致（情绪、位置、正在做的事）。
- 场景结尾如果不是全章最后一个场景，要为下一场景留自然过渡口。"""

EXPAND_SYSTEM = """你是一个资深网文作者，擅长扩写场景。
扩写时自然地增加细节、对话、动作和环境描写，保持故事节奏和语气连贯。"""

EXPAND_QUALITY_CONSTRAINTS = """【扩写质量约束——违反任意一条即判不合格】
1. 禁止空洞凑字：每新增100字必须包含至少一个叙事推进元素（新信息、冲突升级、情节转折、人物行动）
2. 禁止重复已有描写：不得重复原文中已出现的环境描写、心理描写或动作描写
3. 禁止添加无关支线：扩写内容必须服务于当前场景的核心冲突，不得引入新角色或新事件线
4. 必须推进叙事：新增内容必须揭示人物新信息、推进情节、加深冲突或埋设伏笔
5. 必须保持人物一致性：人物言行必须符合其已建立的性格和当前动机，不得OOC
6. 禁止无关回溯：不得插入与当前场景无关的回忆、闪回或背景交代
7. 严禁重写开头：正文第一段必须与原文第一段完全一致，不得创建新的开场
8. 严禁改变时间线：原文中出现的日期、时间、星期等事实不得修改或新增矛盾版本
9. 严禁重复觉醒/确认场景：如果原文已有角色确认日期/环境/身份的场景，不得再写一遍类似确认"""

EXPAND_PROMPT = """请扩写以下章节正文，在原有场景骨架中自然地增加细节。

【关键规则：只输出扩写后的完整正文，禁止在正文前后添加任何说明。】

原文（约 {current_words} 字）：
{draft}

扩写要求：
- 目标总字数：约 {target_words} 字（需新增约 {needed_words} 字）
- 在原文段落之间或段落内部自然插入新内容，不要在末尾追加新段落
- 增加对话（特别是带有潜台词的对话）
- 增加环境细节（光、声、温度、气味等感官描写）
- 增加人物微动作（手势、表情、姿态）
- 保持原有情节骨架和时间线不变
- ⚠️ 严禁重写开头、严禁重复已有段落、严禁改变场景发生的日期和时间
- 直接输出扩写后的完整正文（从原文第一段开始，到原文最后一段结束）

{quality_constraints}"""

POLISH_PROMPT = """润色以下文本，使其更流畅、更有网文感：

{text}

要求：
- 修正语病
- 让对话更自然
- 增加节奏感
- 直接输出润色后正文"""

CONTINUE_PROMPT = """基于以下已有章节内容，继续往后写，不要重复前文：

章节标题：{title}
已有正文：
{content}

本次追加方向：{guidance}
上下文：{context}

要求：
- 直接续写小说正文
- 与前文衔接自然
- 承接现有冲突并推进
- 控制在{target_words}字左右
- 不要总结前文，不要解释任务
- 禁止重复前文已有的描写模式（如相同的逃跑路线、相同的紧张描写）
- 本段续写必须推进情节，不能只是延长场景
- 如果前文已接近场景高潮，续写应该完成高潮并过渡到下一节拍
- 结尾必须有明确的情绪落点或悬念钩子，不能自然淡出"""

REVISE_CHAPTER_PROMPT = """请根据用户要求改写以下章节正文：

章节标题：{title}
原正文：
{content}

修改要求：{guidance}

要求：
- 保留章节核心事件
- 按要求调整语气、节奏、冲突或细节
- 直接输出修改后的完整章节正文"""

REVISE_FRAGMENT_PROMPT = """请只改写正文中的指定片段，并保持上下文衔接自然：

章节标题：{title}
原正文：
{content}

需要重点改写的片段：
{fragment}

修改要求：{guidance}

要求：
- 输出修改后的完整章节正文
- 尽量只影响相关片段和必要的上下文衔接
- 不要删除无关剧情"""

TRIM_SYSTEM = """你是一个资深网文编辑，擅长在不损失核心剧情的前提下精简文本。
裁剪原则：
1. 保留所有冲突、转折、悬念钩子和对话核心信息
2. 删除冗余描写、重复情感表达、过长环境描写
3. 保持叙事节奏和语气连贯
4. 直接输出裁剪后的正文"""

TRIM_QUALITY_CONSTRAINTS = """【裁剪质量约束——违反任意一条即判不合格】
1. 保留冲突节点：人物冲突、内心冲突、环境冲突不得删除
2. 保留转折节点：局势反转、信息揭露、立场转变不得删除
3. 保留悬念钩子：未解之谜、即将发生的危机、情绪余韵不得删除
4. 保留关键对话：可精简寒暄，但不得删除传达新信息或改变关系的对话
5. 保留人物动机揭示：揭示人物行动原因的内容不得删除
6. 优先删除顺序：重复描写 → 冗长过渡 → 对话寒暄 → 静态环境描写
7. 禁止删除场景首尾句：每个段落的第一句和最后一句必须保留"""

TRIM_PROMPT = """将以下章节正文裁剪至约{target_words}字，要求：
- 保留所有关键剧情节点（冲突、转折、悬念）
- 保留对话核心内容，可精简对话中的冗余部分
- 删除冗余的描写和心理分析
- 保持段落结构完整
- 直接输出裁剪后正文

原文：
{text}

{quality_constraints}"""


class WriterAgent:
    def _looks_like_placeholder(self, text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return True
        markers = ["前段铺垫", "后段推进", "地点：，气氛：。", "地点：", "气氛："]
        if any(marker in raw for marker in markers):
            return True
        compact = raw.replace("\n", "")
        return len(compact) < 120 and ("（前段" in raw or "（后段" in raw)

    def _target_bounds(self, target_words: int, tolerance: float | None = None) -> tuple[int, int]:
        tolerance = settings.WC_TOLERANCE_PCT if tolerance is None else tolerance
        lower = max(50, int(target_words * max(0.5, 1 - tolerance / 100.0)))
        upper = max(lower + 20, int(target_words * (1 + tolerance / 100.0)))
        return lower, upper

    async def generate_scene_draft(self, scene: SceneOutline, char_status: str, context: str, chapter_contract: str = "") -> str:
        min_words, max_words = self._target_bounds(scene.target_words, tolerance=10.0)
        tension = float(getattr(scene, "tension_weight", 1.0) or 1.0)
        if tension >= 1.4:
            tension_label = "高张力场景：冲突、压迫感和转折密度要更强，少铺陈空镜。"
        elif tension >= 1.15:
            tension_label = "中高张力场景：要有明显推进和试探，不要平铺直叙。"
        elif tension <= 0.9:
            tension_label = "过渡场景：允许留白，但必须带出新信息、关系变化或情绪余波。"
        else:
            tension_label = "标准推进场景：保持冲突推进与信息释放平衡。"
        prompt = SCENE_DRAFT_PROMPT.format(
            chapter_contract=chapter_contract or "无",
            scene_desc=scene.description,
            characters=", ".join(scene.characters) if scene.characters else "按章节需要",
            location=scene.location or "按章节需要",
            mood=scene.mood or "按剧情推进",
            char_status=char_status[:2500],
            context=context[:8000],
            tension_label=tension_label,
            sensory_focus=getattr(scene, "sensory_focus", "") or "至少补出一种非视觉感官细节。",
            target_words=scene.target_words,
            min_words=min_words,
            max_words=max_words,
        )
        max_tokens = int(scene.target_words * max(settings.WC_EXPAND_TOKEN_FACTOR, 2.6) + settings.WC_EXPAND_TOKEN_MARGIN)
        draft = await call_llm(TaskType.WRITE, prompt, system=WRITER_SYSTEM, temperature=0.8, max_tokens=max_tokens)
        actual_words = count_chinese_words(draft)
        if actual_words < 100:
            logger.warning(f"Scene draft extremely short ({actual_words} words), retrying with high temperature")
            draft = await call_llm(TaskType.WRITE, prompt, system=WRITER_SYSTEM, temperature=0.95, max_tokens=max_tokens)
            actual_words = count_chinese_words(draft)
        if actual_words < min_words:
            logger.warning(f"Scene draft severely short ({actual_words} vs target {scene.target_words}), retrying generation")
            draft = await call_llm(TaskType.WRITE, prompt, system=WRITER_SYSTEM, temperature=0.75, max_tokens=int(max_tokens * 1.15))
            actual_words = count_chinese_words(draft)
        if self._looks_like_placeholder(draft):
            logger.warning("Scene draft still looks like placeholder, forcing one more regeneration")
            draft = await call_llm(TaskType.WRITE, prompt + "\n\n禁止输出“前段铺垫/后段推进/地点/气氛”这类场景标签，必须直接写成小说正文。", system=WRITER_SYSTEM, temperature=0.85, max_tokens=int(max_tokens * 1.2))
            actual_words = count_chinese_words(draft)
        if actual_words > max_words:
            logger.warning(f"Scene draft too long ({actual_words} vs target {scene.target_words}), trimming at scene level")
            draft = _rule_based_trim(draft, scene.target_words)
        return draft

    async def expand(self, draft: str, target_words: int = 800) -> str:
        current_words = count_chinese_words(draft)
        needed_words = max(80, target_words - current_words)
        prompt = EXPAND_PROMPT.format(
            draft=draft,
            current_words=current_words,
            needed_words=needed_words,
            target_words=target_words,
            quality_constraints=EXPAND_QUALITY_CONSTRAINTS,
        )
        max_tokens = min(int(max(needed_words, target_words * 0.6) * max(settings.WC_EXPAND_TOKEN_FACTOR, 2.4) + settings.WC_EXPAND_TOKEN_MARGIN), 60000)
        expanded = await call_llm(TaskType.WRITE, prompt, system=EXPAND_SYSTEM, temperature=0.7, max_tokens=max_tokens)
        if count_chinese_words(expanded) <= count_chinese_words(draft) + 50:
            logger.warning(f"Expand produced insufficient length, retrying with higher temperature")
            expanded = await call_llm(TaskType.WRITE, prompt, system=EXPAND_SYSTEM, temperature=0.9, max_tokens=int(max_tokens * 1.3))
        # 安全检查：检测扩写结果是否出现了重复开头（多版本拼接的典型特征）
        expanded = self._remove_duplicate_openings(draft, expanded)
        return expanded

    def _remove_duplicate_openings(self, original: str, expanded: str) -> str:
        """检测扩写结果是否包含原文开头的重复版本，如果是则返回原文。"""
        if not original or not expanded:
            return expanded or original
        # 取原文前150字作为开头指纹
        orig_opening = original.strip()[:150]
        # 在扩写结果中查找原文开头出现的位置
        expanded_stripped = expanded.strip()
        if not orig_opening or len(orig_opening) < 30:
            return expanded
        # 如果扩写文本中，原文开头的前50字在后半部分再次出现，说明产生了重复版本
        marker = orig_opening[:50]
        first_pos = expanded_stripped.find(marker)
        if first_pos < 0:
            return expanded
        second_pos = expanded_stripped.find(marker, first_pos + len(marker))
        if second_pos > 0:
            logger.warning(f"Expand produced duplicate opening (marker found at pos {first_pos} and {second_pos}), reverting to original")
            return original
        return expanded

    async def polish(self, text: str, target_words: int = 0) -> str:
        prompt = POLISH_PROMPT.format(text=text)
        # 润色输出长度接近原文；中文 token≈字符数/1.5，预留 20% 余量
        max_tokens = max(int(len(text) / 1.5 * 1.2), 800)
        polished = await call_llm(TaskType.WRITE, prompt, temperature=0.5, max_tokens=max_tokens)
        return polished

    # ─── Truncated ending detection & repair ───

    _SENTENCE_ENDERS = set("。！？…）」』】")
    _MID_SENTENCE_CHARS = set("，、；：的了着过在是和与或但而就也都不还又才刚")

    @staticmethod
    def _is_truncated_ending(text: str) -> bool:
        """Detect if text ends with an incomplete sentence (mid-clause or no punctuation)."""
        if not text:
            return False
        stripped = text.rstrip()
        if not stripped:
            return False
        last_char = stripped[-1]
        if last_char in WriterAgent._SENTENCE_ENDERS:
            return False
        if last_char in WriterAgent._MID_SENTENCE_CHARS:
            return True
        # CJK character without sentence-ending punctuation → likely truncated
        if '一' <= last_char <= '鿿':
            return True
        return False

    def _sanitize_generated_text(self, text: str) -> str:
        """Remove prompt instructions / generation directives that leaked into novel text."""
        if not text:
            return text

        # Pattern: Chinese instruction phrases that appear at the end of chapters
        instruction_patterns = [
            # "出场人物：XXX" style instructions
            r'[。！？]\s*出场人物[：:]\s*[^。！？\n]+[。]?\s*$',
            # "推动冲突变化并完成本章落点" style directives
            r'[。！？]\s*推动冲突变化[^。！？\n]*[。]?\s*$',
            # "人物底牌揭示" / "关键牺牲或反转连锁发生" style scene directives
            r'[。！？]\s*(?:主战场|人物底牌|关键牺牲|反转连锁|把全书张力推到峰值)[^。！？\n]*[。]?\s*$',
            # "XXX在场" style stage directions (short trailing lines)
            r'[。！？]\s*[一-鿿]{1,20}在场[。]\s*$',
            # Generic: instruction-like sentences ending with "。" that contain meta-language
            r'[。！？]\s*(?:本章|本场景|本段)[^。！？\n]*(?:目标|要求|冲突|节拍)[^。！？\n]*[。]?\s*$',
            # "场景X（约Y字）：..." style scene structure leaking
            r'[。！？]\s*场景\d+[（(]约\d+字[）)][：:][^。！？\n]*[。]?\s*$',
            # "推动冲突变化并完成本章落点。，XXX在场。" combined pattern
            r'[。！？]\s*推动冲突变化[^。]*[。]\s*[一-鿿，、]+在场[。]\s*$',
        ]

        cleaned = text
        for pattern in instruction_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.MULTILINE)

        # Strip trailing lines that look like leaked generation instructions
        # 只删除非常短（< 40字）且包含多个指令关键词的行，避免误杀正常叙事
        lines = cleaned.rstrip().split('\n')
        # 高置信度指令关键词组合（需要至少2个同时出现才判定为泄漏）
        high_confidence_keywords = [
            '出场人物', '推动冲突变化', '完成本章落点', '把全书张力',
            '主战场高潮', '人物底牌揭示', '关键牺牲', '反转连锁发生',
            '场景结构指引', '推动冲突变化并完成',
        ]
        while lines:
            last_line = lines[-1].strip()
            if not last_line:
                lines.pop()
                continue
            # 只处理非常短的行（< 40字），长行更可能是正常叙事
            if len(last_line) < 40:
                kw_hits = sum(1 for kw in high_confidence_keywords if kw in last_line)
                if kw_hits >= 1:
                    logger.warning(f"Stripped leaked instruction from chapter end: {last_line[:60]}...")
                    lines.pop()
                    continue
            break

        return '\n'.join(lines).rstrip()

    async def _fix_truncated_ending(self, text: str, target_words: int) -> str:
        """Complete truncated endings by generating a continuation."""
        current_wc = count_chinese_words(text)
        remaining = max(100, min(target_words - current_wc, 400))
        continuation = await self.continue_chapter(
            "", text, "自然收束当前段落，给读者一个完整的感觉", "",
            target_words=remaining,
        )
        if not continuation:
            return text
        # Strip any leading non-content lines from continuation (e.g. model artifacts)
        cont_stripped = continuation.strip()
        # Find first CJK character
        first_cjk = None
        for i, ch in enumerate(cont_stripped):
            if '一' <= ch <= '鿿':
                first_cjk = i
                break
        if first_cjk is not None:
            cont_stripped = cont_stripped[first_cjk:]
        combined = text.rstrip() + "\n" + cont_stripped
        new_wc = count_chinese_words(combined)
        if new_wc <= current_wc + 20:
            logger.warning("Continuation didn't add meaningful content, keeping original")
            return text
        return combined

    async def _ensure_word_count(self, draft: str, target: int) -> str:
        best_text = draft
        best_deviation = compute_deviation(count_chinese_words(draft), target)
        lower, upper = self._target_bounds(target)
        if not settings.ENABLE_GENERATION_RETRY:
            actual = count_chinese_words(draft)
            if actual > upper:
                logger.info(f"Word count high ({actual} > {upper}), using rule-based trim in fast path")
                return _rule_based_trim(draft, target)
            if actual < lower:
                logger.info(f"Word count low ({actual} < {lower}), accepting unified draft in fast path")
            return draft
        for attempt in range(settings.WC_MAX_CORRECTION_ATTEMPTS):
            actual = count_chinese_words(draft)
            deviation = compute_deviation(actual, target)
            if deviation <= settings.WC_TOLERANCE_PCT:
                return draft
            if deviation < best_deviation:
                best_text = draft
                best_deviation = deviation
            try:
                if actual > upper:
                    trimmed = await self.trim(draft, target)
                    new_actual = count_chinese_words(trimmed)
                    if new_actual >= actual:
                        trimmed = _rule_based_trim(draft, target)
                        new_actual = count_chinese_words(trimmed)
                    if new_actual <= upper:
                        draft = trimmed
                        if compute_deviation(new_actual, target) < best_deviation:
                            best_text = draft
                            best_deviation = compute_deviation(new_actual, target)
                        continue
                    logger.warning(f"Trim not converging (attempt {attempt+1}), {new_actual} vs target {target}")
                    return best_text
                if actual >= lower:
                    return best_text
                expanded = await self.expand(draft, target)
                new_actual = count_chinese_words(expanded)
                new_deviation = compute_deviation(new_actual, target)
                if new_actual < actual:
                    logger.warning(f"Expand produced shorter text ({new_actual} < {actual}), reverting")
                    return best_text
                if new_actual > upper:
                    expanded = _rule_based_trim(expanded, target)
                    new_actual = count_chinese_words(expanded)
                    new_deviation = compute_deviation(new_actual, target)
                draft = expanded
                # 振荡检测：如果字数没有改善或方向反转，提前退出
                if new_deviation >= best_deviation and attempt >= 1:
                    logger.warning(f"Word count correction not improving (attempt {attempt+1}), stopping early")
                    return best_text
                best_text = draft
                best_deviation = new_deviation
            except Exception as e:
                logger.warning(f"Expand failed on attempt {attempt+1}: {e}")
                return best_text
        # After correction loop, if still below target, try continuation
        final_wc = count_chinese_words(best_text)
        if final_wc < lower:
            try:
                needed = max(200, target - final_wc)
                continuation = await self.continue_chapter(
                    "", best_text,
                    f"继续推进剧情，再写约{needed}字",
                    "", target_words=needed,
                )
                if continuation and count_chinese_words(continuation) > 50:
                    best_text = best_text.rstrip() + "\n" + continuation.strip()
                    logger.info(f"Continuation added: {count_chinese_words(best_text)} words (was {final_wc})")
            except Exception as cont_e:
                logger.warning(f"Continuation fallback failed: {cont_e}")
        # Repair truncated endings
        if self._is_truncated_ending(best_text):
            try:
                fixed = await self._fix_truncated_ending(best_text, target)
                if count_chinese_words(fixed) > count_chinese_words(best_text):
                    best_text = fixed
            except Exception as fix_e:
                logger.warning(f"Truncated ending fix failed: {fix_e}")
        return best_text

    async def generate_scene(self, scene: SceneOutline, plot_direction: str, char_status: str, context: str, chapter_contract: str = "") -> str:
        fallback_used = False
        try:
            draft = await self.generate_scene_draft(scene, char_status, context, chapter_contract=chapter_contract)
        except Exception as e:
            logger.warning(f"Scene draft LLM call failed, using fallback: {e}")
            chars = "、".join(scene.characters) if scene.characters else ""
            loc = scene.location or ""
            mood = scene.mood or ""
            fallback_parts = [scene.description or ""]
            if loc:
                fallback_parts.append(f"{loc}里")
            if chars:
                fallback_parts.append(f"{chars}面对面站着")
            if mood:
                fallback_parts.append(f"空气里弥漫着{mood}的气息")
            draft = "，".join(p for p in fallback_parts if p) + "。"
            fallback_used = True
        if not fallback_used and self._looks_like_placeholder(draft):
            raise ValueError("scene placeholder detected after draft generation")
        try:
            draft = await self._ensure_word_count(draft, scene.target_words)
        except Exception as e:
            logger.warning(f"Scene word count enforcement failed, using draft: {e}")
        return draft

    async def generate_chapter_unified(
        self, scenes: list[SceneOutline], plot_direction: str,
        char_status: str, context: str, chapter_contract: str = "",
        previous_ending: str = "",
    ) -> str:
        """整章一次性生成：所有场景作为结构指引，LLM输出连续叙事。"""
        total_target = sum(s.target_words for s in scenes)
        min_words, max_words = self._target_bounds(total_target, tolerance=settings.WC_TOLERANCE_PCT)

        # 构建场景指引（不是逐个生成，而是作为写作节奏参考）
        scene_guide_parts = []
        for i, s in enumerate(scenes):
            tension = float(getattr(s, "tension_weight", 1.0) or 1.0)
            guide = f"场景{i+1}（约{s.target_words}字）：{s.description}"
            if s.location:
                guide += f"，地点：{s.location}"
            if s.mood:
                guide += f"，氛围：{s.mood}"
            if tension >= 1.4:
                guide += "【高张力：强冲突】"
            elif tension <= 0.9:
                guide += "【过渡场景：可留白】"
            scene_guide_parts.append(guide)
        scene_guide = "\n".join(scene_guide_parts)

        all_characters = []
        for s in scenes:
            for c in (s.characters or []):
                if c not in all_characters:
                    all_characters.append(c)

        prompt = CHAPTER_DRAFT_PROMPT.format(
            chapter_contract=chapter_contract or "无",
            scene_guide=scene_guide,
            characters=", ".join(all_characters),
            char_status=char_status[:3000],
            context=context[:10000],
            previous_ending=previous_ending[-2500:] if previous_ending else "（本章为第一章或无前章内容）",
            target_words=total_target,
            min_words=min_words,
            max_words=max_words,
        )
        max_tokens = int(total_target * max(settings.WC_EXPAND_TOKEN_FACTOR, 3.5) + settings.WC_EXPAND_TOKEN_MARGIN)
        max_tokens = min(max_tokens, 60000)

        draft = await call_llm(TaskType.WRITE, prompt, system=WRITER_SYSTEM, temperature=0.8, max_tokens=max_tokens)
        actual = count_chinese_words(draft)

        # P0 修复：跨章节重复检测 — 如果新章前 300 字与上一章末 300 字高度相似，追加反重复指引重生成
        if previous_ending and self._is_too_similar(draft, previous_ending, threshold=0.5):
            logger.warning(f"Chapter draft too similar to previous ending (Jaccard>0.5), regenerating with anti-repeat guidance")
            # 找出具体重复片段
            dup = self._find_duplicate_segment(draft, previous_ending)
            if dup:
                # 直接裁掉重复片段并强制以新开场补足
                dup_text = draft[dup[0]:dup[1]]
                logger.info(f"Found duplicate segment of length {dup[1]-dup[0]}: {dup_text[:50]}...")
                # 在原 prompt 末尾追加强约束
                anti_repeat_modifier = "\n\n【强制约束】上一章以 'X...' 结尾，本章绝对不能从相同情境/对话/动作开篇。本章必须从新的视角、时间或地点切入，不能重复上一章任何完整的句子或场景描写。"
                prompt_enhanced = prompt + anti_repeat_modifier
                draft = await call_llm(TaskType.WRITE, prompt_enhanced, system=WRITER_SYSTEM, temperature=0.85, max_tokens=max_tokens)
                actual = count_chinese_words(draft)

        if settings.ENABLE_GENERATION_RETRY and (actual < 100 or self._looks_like_placeholder(draft)):
            logger.warning(f"Unified chapter draft too short/placeholder ({actual} words), retrying")
            draft = await call_llm(TaskType.WRITE, prompt, system=WRITER_SYSTEM, temperature=0.9, max_tokens=int(max_tokens * 1.15))
            actual = count_chinese_words(draft)

        if settings.ENABLE_GENERATION_RETRY and actual < min_words:
            logger.warning(f"Unified draft short ({actual} vs target {total_target}), retrying")
            draft = await call_llm(TaskType.WRITE, prompt, system=WRITER_SYSTEM, temperature=0.75, max_tokens=int(max_tokens * 1.2))
            actual = count_chinese_words(draft)

        if actual > max_words:
            draft = _rule_based_trim(draft, total_target)

        return draft

    async def _generate_scene_with_history(
        self, scene: SceneOutline, char_status: str, context: str,
        chapter_contract: str, previous_text: str,
    ) -> str:
        """生成带前文上下文的场景。"""
        min_words, max_words = self._target_bounds(scene.target_words, tolerance=10.0)
        tension = float(getattr(scene, "tension_weight", 1.0) or 1.0)
        if tension >= 1.4:
            tension_label = "高张力场景"
        elif tension >= 1.15:
            tension_label = "中高张力场景"
        elif tension <= 0.9:
            tension_label = "过渡场景"
        else:
            tension_label = "标准推进场景"

        prompt = SCENE_CONTINUATION_PROMPT.format(
            chapter_contract=chapter_contract or "无",
            scene_desc=scene.description,
            characters=", ".join(scene.characters) if scene.characters else "按章节需要",
            location=scene.location or "按章节需要",
            mood=scene.mood or "按剧情推进",
            tension_label=tension_label,
            sensory_focus=getattr(scene, "sensory_focus", "") or "至少补出一种非视觉感官细节。",
            previous_text=previous_text[-2000:],
            target_words=scene.target_words,
        )
        max_tokens = int(scene.target_words * max(settings.WC_EXPAND_TOKEN_FACTOR, 2.6) + settings.WC_EXPAND_TOKEN_MARGIN)
        draft = await call_llm(TaskType.WRITE, prompt, system=WRITER_SYSTEM, temperature=0.8, max_tokens=max_tokens)
        return draft

    async def generate_chapter_sequential(
        self, scenes: list[SceneOutline], plot_direction: str,
        char_status: str, context: str, chapter_contract: str = "",
        previous_ending: str = "",
    ) -> str:
        """分场景顺序生成，但每个场景携带前文累积上下文。"""
        parts = []
        accumulated_text = previous_ending[-1000:] if previous_ending else ""

        for i, scene in enumerate(scenes):
            try:
                if i == 0 and not accumulated_text:
                    # 第一个场景且无前章内容，用原有方式
                    text = await self.generate_scene_draft(scene, char_status, context, chapter_contract=chapter_contract)
                else:
                    # 后续场景：带前文上下文
                    text = await self._generate_scene_with_history(
                        scene, char_status, context, chapter_contract,
                        accumulated_text[-2000:]
                    )
                text = await self._ensure_word_count(text, scene.target_words)
            except Exception as e:
                logger.warning(f"Sequential scene {i} failed: {e}")
                chars = "、".join(scene.characters) if scene.characters else ""
                loc = scene.location or ""
                fallback_parts = [scene.description or ""]
                if loc:
                    fallback_parts.append(f"场景在{loc}")
                if chars:
                    fallback_parts.append(f"{chars}在场")
                text = "，".join(p for p in fallback_parts if p) + "。"
                # 回退文本不做 placeholder 检测，直接使用
                parts.append(text)
                accumulated_text += "\n\n" + text
                continue

            if self._looks_like_placeholder(text):
                raise ValueError(f"Scene {i} placeholder detected")

            parts.append(text)
            accumulated_text += "\n\n" + text

        return "\n\n".join(parts)

    async def generate_chapter(self, scenes: list[SceneOutline], plot_direction: str, char_status: str, context: str, chapter_contract: str = "", previous_ending: str = "", is_last_chapter: bool = False) -> str:
        total_target = sum(s.target_words for s in scenes)

        # 主路径：整章一次性生成。默认不回退到分场景拼接，避免章节割裂。
        try:
            draft = await self.generate_chapter_unified(
                scenes, plot_direction, char_status, context,
                chapter_contract, previous_ending,
            )
            draft = self._sanitize_generated_text(draft)
            if not self._looks_like_placeholder(draft) and count_chinese_words(draft) >= 100:
                result = await self._ensure_word_count(draft, total_target)
                # P0 修复：截断检测 + 强制续写 + 跨章去重
                result = await self._post_generation_recovery(result, total_target, is_last_chapter, previous_ending)
                return result
            raise ValueError("unified generation produced placeholder or too-short draft")
        except Exception as e:
            detail = str(e) or e.__class__.__name__
            logger.warning(f"Unified generation failed: {e}, falling back to sequential generation")

        # 整章生成失败时回退到分场景顺序生成（容错策略，与重试无关）。
        try:
            result = await self.generate_chapter_sequential(
                scenes, plot_direction, char_status, context,
                chapter_contract, previous_ending,
            )
            result = self._sanitize_generated_text(result)
            # P0 修复：截断检测 + 强制续写 + 跨章去重（也应用于回退路径）
            result = await self._post_generation_recovery(result, total_target, is_last_chapter, previous_ending)
            return result
        except Exception as e:
            raise ValueError(f"章节生成失败：整章生成和显式顺序重试均失败：{e}") from e

    async def _validate_and_fix_title(self, raw_title: str, fallback_outline_title: str) -> str:
        """P2 程序级修复：生成后再次校验标题。

        软修复策略：
        - 若 LLM 返回的标题不含脏词，直接返回
        - 若含脏词，回退到 outline 提供的标题（更安全）
        - 硬拦截由 OutputValidator 在 main_pipeline 层负责

        Args:
            raw_title: 生成后的标题
            fallback_outline_title: 备用标题（来自 chapter_outline.title）

        Returns:
            清洗后的标题
        """
        from agents.planner_agent import PlannerAgent
        try:
            if not PlannerAgent._is_dirty_title(self, raw_title or ""):
                return raw_title
        except Exception as e:
            logger.warning(f"_validate_and_fix_title: dirty check failed: {e}")
            return raw_title
        # 脏词：回退到 outline 标题
        if fallback_outline_title and not PlannerAgent._is_dirty_title(self, fallback_outline_title):
            logger.info(f"Replacing dirty title '{raw_title}' with outline title '{fallback_outline_title}'")
            return fallback_outline_title
        # 兜底：保留原标题，让 OutputValidator 在更上层拦截
        return raw_title

    async def _post_generation_recovery(self, text: str, target_words: int, is_last_chapter: bool = False, previous_ending: str = "") -> str:
        """P0 修复：生成后恢复——处理截断、字数不足、跨章重复三种情况。

        处理流程：
        1. 如果末句未以正常标点结尾，调用续写补全末尾
        2. 如果字数 < 目标字数 70%，强制续写（最多 2 次）
        3. 末章特殊要求：字数 >= 目标的 95%
        4. 跨章重复：去除与上一章重复的开场段
        """
        if not text:
            return text

        # P0 修复：跨章重复 - 直接裁掉前部与上一章重复的片段
        if previous_ending and self._is_too_similar(text, previous_ending, threshold=0.5):
            dup = self._find_duplicate_segment(text, previous_ending)
            if dup and dup[0] < 200:
                # 重复片段在文本前 200 字内，直接裁掉
                logger.warning(f"Trimming {dup[0]}-{dup[1]} chars of duplicate opening")
                # 保留第一段（开场部分），从重复片段之后开始重新构造
                # 找到重复段之后的第一个句号作为新开头
                tail_start = text.find('。', dup[1])
                if tail_start > 0 and tail_start < dup[1] + 100:
                    # 跳到下一段开头
                    next_para = text.find('\n', tail_start)
                    if next_para > 0 and next_para < tail_start + 200:
                        text = text[next_para+1:].lstrip()
                        logger.info(f"After dedup trim: {count_chinese_words(text)} words")

        max_continuations = 2 if is_last_chapter else 1
        for attempt in range(max_continuations):
            current_wc = count_chinese_words(text)
            needs_continuation = False
            reason = ""

            # 截断检测
            if self._is_truncated_ending(text):
                needs_continuation = True
                reason = "truncated_ending"
            # 字数不足检测
            elif current_wc < target_words * 0.7:
                needs_continuation = True
                reason = f"word_count_low({current_wc}/{target_words})"
            # 末章特殊要求
            elif is_last_chapter and current_wc < target_words * 0.95:
                needs_continuation = True
                reason = f"last_chapter_short({current_wc}/{int(target_words*0.95)})"

            if not needs_continuation:
                break

            logger.warning(f"Post-generation recovery triggered: {reason}, attempt {attempt+1}/{max_continuations}")
            try:
                needed = max(200, int(target_words * 0.95 - current_wc)) if is_last_chapter else max(200, target_words - current_wc + 100)
                guidance = (
                    "续写本章剩余内容直到本章自然完整结束。本章是全书的最后一章，必须有明确的角色抉择和主题落点，不能戛然而止。"
                    if is_last_chapter else
                    "续写本章剩余内容直到本章自然结束，保持前文风格与节奏。"
                )
                continuation = await self.continue_chapter(
                    "", text, guidance, "", target_words=needed,
                )
                if not continuation or count_chinese_words(continuation) < 50:
                    logger.warning(f"Recovery continuation too short, stopping recovery")
                    break
                # 提取 continuation 中从第一个中文字符开始的内容
                cont_stripped = continuation.strip()
                first_cjk = None
                for i, ch in enumerate(cont_stripped):
                    if '一' <= ch <= '鿿':
                        first_cjk = i
                        break
                if first_cjk is not None and first_cjk > 0:
                    cont_stripped = cont_stripped[first_cjk:]
                text = text.rstrip() + "\n" + cont_stripped
                # 末尾再 sanitize 一遍
                text = self._sanitize_generated_text(text)
            except Exception as e:
                logger.warning(f"Post-generation recovery attempt {attempt+1} failed: {e}")
                break

        return text

    async def continue_chapter(self, title: str, content: str, guidance: str, context: str, target_words: int = 800) -> str:
        prompt = CONTINUE_PROMPT.format(
            title=title,
            content=content[-3000:],
            guidance=guidance or "延续当前剧情并自然推进",
            context=context[:4000],
            target_words=target_words,
        )
        return await call_llm(TaskType.WRITE, prompt, system=WRITER_SYSTEM, temperature=0.8, max_tokens=int(target_words * settings.WC_EXPAND_TOKEN_FACTOR + settings.WC_EXPAND_TOKEN_MARGIN))

    # P0 修复：跨章节相似度检测（N-gram Jaccard）
    @staticmethod
    def _ngrams(text: str, n: int = 4) -> set[str]:
        if len(text) < n:
            return set()
        return set(text[i:i+n] for i in range(len(text) - n + 1))

    def _is_too_similar(self, new_text: str, prev_text: str, threshold: float = 0.5) -> bool:
        """检测新章前 300 字与上一章最后 300 字是否有 50% 以上字符重叠 (4-gram Jaccard)。"""
        if not new_text or not prev_text:
            return False
        new_head = new_text[:300]
        prev_tail = prev_text[-300:]
        new_ngrams = self._ngrams(new_head, 4)
        prev_ngrams = self._ngrams(prev_tail, 4)
        if not new_ngrams or not prev_ngrams:
            return False
        intersection = len(new_ngrams & prev_ngrams)
        union = len(new_ngrams | prev_ngrams)
        jaccard = intersection / union if union else 0
        return jaccard > threshold

    @staticmethod
    def _find_duplicate_segment(new_text: str, prev_text: str, min_len: int = 30) -> tuple[int, int] | None:
        """在新章前 500 字中找出与上一章最后 500 字重叠的连续片段 (返回 (start, end) 偏移)。

        用于精准定位重复区段以便改写。
        """
        if not new_text or not prev_text:
            return None
        new_head = new_text[:500]
        prev_tail = prev_text[-500:]
        # 从长到短尝试匹配（5-gram 滚降）
        for n in range(min(80, len(prev_tail), len(new_head)), min_len - 1, -1):
            for i in range(len(prev_tail) - n + 1):
                snippet = prev_tail[i:i+n]
                if snippet in new_head:
                    start = new_head.find(snippet)
                    return (start, start + n)
        return None

    async def revise_chapter(self, title: str, content: str, guidance: str) -> str:
        prompt = REVISE_CHAPTER_PROMPT.format(
            title=title,
            content=content[:8000],
            guidance=guidance or "让内容更流畅",
        )
        # 改写需要足够空间输出完整章节；上限 60000 避免超过 LLM 限制
        max_tokens = min(int(len(content) * 2.5 + 400), 60000)
        revised = await call_llm(TaskType.WRITE, prompt, system=WRITER_SYSTEM, temperature=0.7, max_tokens=max_tokens)
        if settings.FAST_TEST_MODE:
            return revised
        try:
            return await self.polish(revised)
        except Exception as e:
            logger.warning(f"Chapter revision polish failed, using revised text: {e}")
            return revised

    async def revise_fragment(self, title: str, content: str, fragment: str, guidance: str) -> str:
        prompt = REVISE_FRAGMENT_PROMPT.format(
            title=title,
            content=content[:10000],
            fragment=fragment[:2000],
            guidance=guidance or "优化这一段内容",
        )
        # 改写需要足够空间输出完整章节；上限 60000 避免超过 LLM 限制
        max_tokens = min(int(len(content) * 2.5 + 400), 60000)
        revised = await call_llm(TaskType.WRITE, prompt, system=WRITER_SYSTEM, temperature=0.7, max_tokens=max_tokens)
        if settings.FAST_TEST_MODE:
            return revised
        try:
            return await self.polish(revised)
        except Exception as e:
            logger.warning(f"Fragment revision polish failed, using revised text: {e}")
            return revised

    async def trim(self, text: str, target_words: int) -> str:
        prompt = TRIM_PROMPT.format(text=text, target_words=target_words, quality_constraints=TRIM_QUALITY_CONSTRAINTS)
        max_tokens = min(int(target_words * settings.WC_EXPAND_TOKEN_FACTOR + settings.WC_EXPAND_TOKEN_MARGIN), 60000)
        try:
            trimmed = await call_llm(TaskType.WRITE, prompt, system=TRIM_SYSTEM, temperature=0.3, max_tokens=max_tokens)
            if count_chinese_words(trimmed) > count_chinese_words(text):
                logger.warning("Trim produced longer text, falling back to rule-based trim")
                return _rule_based_trim(text, target_words)
            return trimmed
        except Exception as e:
            logger.warning(f"LLM trim failed: {e}, falling back to rule-based trim")
            return _rule_based_trim(text, target_words)
