from memory.short_term import ShortTermMemory
from memory.long_term import LongTermMemory
from memory.structured import StructuredMemory
from memory.working_memory import WorkingMemory, SceneContext
from memory.consolidation import MemoryConsolidation
from memory.relationship_graph import RelationshipGraph
from core.models import CharacterSheet, WorldSetting
from core.config import settings
import os
import re
import logging

logger = logging.getLogger(__name__)


class MemorySystem:
    def __init__(self, session_id: str = None, bm25_searcher=None, reranker=None):
        self.session_id = session_id
        self.short_term = ShortTermMemory()
        self.working_memory = WorkingMemory()
        if session_id:
            base_dir = os.path.join("data", "sessions", session_id)
            self.long_term = LongTermMemory(index_path=os.path.join(base_dir, "faiss_index"))
            self.structured = StructuredMemory(path=os.path.join(base_dir, "structured_memory.json"))
            self.relationship_graph = RelationshipGraph(path=os.path.join(base_dir, "relationship_graph.json"))
        else:
            self.long_term = LongTermMemory()
            self.structured = StructuredMemory()
            self.relationship_graph = RelationshipGraph()

        self.consolidation = MemoryConsolidation(
            working_memory=self.working_memory,
            short_term=self.short_term,
            long_term=self.long_term,
            structured=self.structured,
        )

        from rag.rag_engine import RAGEngine
        self.rag = RAGEngine(self.long_term, bm25_searcher=bm25_searcher, reranker=reranker)
        self.consolidation.embed_fn = self.rag.get_embedding

    def add_chapter_to_memory(self, title: str, content: str, summary: str, embedding=None):
        self.short_term.add_chapter(title, content, summary)
        if embedding is not None:
            self.long_term.add(
                text=f"{title}\n{summary}",
                embedding=embedding,
                meta={"type": "chapter", "title": title}
            )

    def update_character(self, char: CharacterSheet):
        self.structured.update_character(char)

    def get_character(self, name: str):
        return self.structured.get_character(name)

    def update_world(self, world: WorldSetting):
        self.structured.update_world(world)

    def add_timeline_event(self, event: dict):
        self.structured.add_timeline_event(event)

    def add_chapter_summary(self, chapter_idx: int, title: str, summary: str):
        self.structured.add_chapter_summary(chapter_idx, title, summary)

    def update_working_memory(self, scene: SceneContext):
        self.working_memory.update_on_scene_switch(scene)

    def retrieve_context(self, query: str = "", query_embedding=None, top_k: int = 5, max_chars: int = 6000) -> str:
        parts = []
        recent = self.short_term.get_context_for_writer()
        if recent:
            parts.append(recent)
        wm_text = self.working_memory.get_context_text()
        if wm_text:
            parts.append("## 工作记忆\n" + wm_text)
        characters = self.structured.get_character_profiles_text()
        if characters:
            parts.append("## 人物状态\n" + characters)
        rel_text = self.relationship_graph.get_context_text()
        if rel_text:
            parts.append("## 角色关系\n" + rel_text)
        world = self.structured.get_world_text()
        if world and self.structured.world.cultivation_system:
            parts.append("## 世界观\n" + world)
        if query_embedding is not None:
            results = self.long_term.search(query_embedding, top_k)
            if results:
                related = "\n".join([f"- {r.get('text', '')}" for r in results])
                parts.append("## 相关记忆\n" + related)
        full_context = "\n\n".join(parts)
        # 限制上下文总长度，避免超出 LLM context window
        if max_chars and len(full_context) > max_chars:
            # 保留前面的部分（更重要），截断后面
            full_context = full_context[:max_chars] + "\n...(上下文已截断)"
        return full_context

    async def consolidate_chapter(self, chapter_content: str, chapter_title: str, chapter_idx: int, context: dict = None):
        summary = await self.consolidation.consolidate(chapter_content, chapter_title, chapter_idx, context)

        # P2 程序级修复：自动注册新角色（之前是孤立代码，定义但从不调用）
        # best-effort：失败不影响主流程
        try:
            await self.auto_register_characters(chapter_content, chapter_idx)
        except Exception as e:
            logger.warning(f"auto_register_characters failed for chapter {chapter_idx}: {e}")

        return summary

    # P1 修复：自动注册新角色
    # 常见 2-3 字人名误识别白名单（这些不是人名）
    _CHARACTER_FALSE_POSITIVES = {
        # 人称/指示代词
        "他", "她", "它", "你", "我", "我们", "他们", "她们", "它们", "自己",
        "这", "那", "这个", "那个", "这里", "那里", "这些", "那些", "此", "其",
        "什么", "怎么", "为什么", "哪里", "哪个", "谁", "哪些", "啥",
        # 时间/状态副词
        "现在", "刚才", "后来", "最后", "然后", "接着", "以前", "之后", "已经",
        "可能", "应该", "可以", "需要", "必须", "一定", "或许", "似乎", "仿佛",
        # 否定/转折
        "不是", "可是", "但是", "因为", "所以", "如果", "虽然", "不过", "只是",
        "一直", "一下", "一些", "一样", "一切", "一种", "一旦", "一边", "一面",
        # 地点/方位（与"的"搭配时常见）
        "楼上", "楼下", "门口", "床上", "桌上", "墙上", "地上", "空中", "海里",
        "车里", "窗外", "门后", "路上", "水里", "空中", "门外", "车内", "墙上",
        "脸上", "手上", "脚下", "身前", "身后", "头里", "怀里", "腿边",
        "房间", "走廊", "楼梯", "大厅", "屋子", "房子", "仓库", "机舱",
        "方向", "周围", "四周", "远处", "近处", "眼前", "面前", "眼前",
        "向腰间", "向林逸", "向苏玫", "向仓库", "向墙边", "向铁轨",
        "朝着", "向内", "向外",
        # 颜色/材质
        "白色", "黑色", "红色", "蓝色", "绿色", "黄色", "灰色", "紫色", "棕色",
        "金色", "银色", "粉色", "橙色", "深蓝", "浅灰", "暗红", "深灰",
        "金属", "木质", "塑料", "玻璃", "石材", "皮质", "纸质", "棉质",
        "金属味", "金属箱", "金属质", "金属片", "金属环", "金属板", "金属盖",
        "金属屑", "金属框", "金属管", "金属门", "金属杆", "金属面",
        "白大褂", "白瓷上", "黄铜色", "深蓝色", "浅灰色", "暗红色",
        # 人体部位/感官
        "心里", "脑子", "眼中", "眼前", "面前", "耳边", "心里", "脑海",
        "头发", "眉毛", "眼睛", "鼻子", "嘴巴", "耳朵", "手臂", "腿脚",
        "指尖", "手掌", "手心", "拳头", "膝盖",
        # 身体/心理描述
        "老人", "女人", "男人", "孩子", "大家", "某人", "他们俩", "自己",
        # 数字/数量
        "一半", "一半", "两三", "几个", "一段", "一会儿", "一阵", "一下",
        "段数据", "段代码", "段弧线", "段绳子", "段管道", "段走廊",
        "张地图", "张标签", "张纸条", "张纸", "张桌子", "张椅子",
        "条通道", "条管道", "条走廊", "条线索",
        "块屏幕", "块金属", "块石头", "块碎片",
        "把武器", "把刀", "把枪", "把钥匙",
        "份报告", "份文件", "份资料",
        # 方向
        "向上", "向下", "向左", "向右", "向前", "向后", "向北", "向南",
        # 模糊形容词
        "周围", "整体", "局部", "表面", "内部", "外部", "里外", "上下",
        # 通用名词（与"的"搭配的常见组合）
        "毛发", "金属", "塑料", "陶瓷", "石材", "木材", "布料", "纱线",
        "石膏", "玻璃", "石子", "金属", "金属板", "金属片", "金属环",
        # 描述性短语
        "一丝", "一道", "一片", "一阵", "一团", "一条", "一只", "一辆",
        "冰冷的", "温暖的", "沉重的", "锋利的", "坚硬的", "柔软的",
        "灰色的", "黑色的", "白色的", "红色的",
        # 时间/事件
        "一会儿", "一瞬间", "那一刻", "此时", "此刻", "当下",
        "第一天", "第二天", "第三天", "最后一天",
        "上午", "下午", "晚上", "凌晨", "中午", "傍晚",
        # 状态/心理
        "疲惫", "紧张", "焦虑", "愤怒", "悲伤", "恐惧", "兴奋", "平静",
        "沉默", "安静", "喧闹", "混乱", "危险", "安全", "稳定",
        # 抽象名词
        "信息", "数据", "消息", "信号", "证据", "线索", "答案", "结果",
        "任务", "目标", "计划", "方案", "策略", "方法", "步骤",
        "原因", "目的", "理由", "动机", "意义", "价值",
        # 章节相关
        "本章", "本章中", "本章内", "本章末", "本章开", "本章里",
        "一幕", "场景", "故事", "情节", "剧情", "冲突",
    }

    def extract_candidate_character_names(self, text: str, known_names: set[str]) -> set[str]:
        """从正文中提取可能是新角色的 2-3 字中文名字

        策略（修复误报问题）：
        1. 模式 1 (X说/道/走/看) 是最可靠的人名信号 — 必须命中 1+ 次
        2. 模式 2 (X的Y) 加严：要求"的"后面跟有意义内容（不是色味质方位等），
           且名字内部不含"的了着过在是和与或但而"
        3. 模式 3 (X是Y) 加严：要求"是"后面跟名词
        4. 模式 4 (穿着X的Z) 也较可靠
        5. 交叉验证：候选名需满足以下任一条件：
           - 模式 1 命中（最可靠）
           - 模式 4 命中
           - 模式 3 命中 1+ 次
           - 模式 2 命中 2+ 次（多次确认）
           - 模式 2 + 模式 3 组合命中
        6. 排除 known_names 和常见误识别词
        """
        if not text:
            return set()

        pattern1_hits: set[str] = set()
        pattern1_count: dict[str, int] = {}
        pattern2_hits: set[str] = set()
        pattern2_count: dict[str, int] = {}
        pattern3_hits: set[str] = set()
        pattern3_count: dict[str, int] = {}
        pattern4_hits: set[str] = set()

        # 模式 1: 名字 + 说话/动作动词（最可靠）
        # 要求：名字内部不含停用词
        for m in re.finditer(r'(?:^|[\s，。！？：；、])[""「]?([一-鿿]{2,3})[""」]?(?:说|道|问|答|喊|叫|笑|想|走|看|点头|摇头|站|坐|推|抓|握|转|冲|跑|跳|进|出)', text):
            name = m.group(1)
            if self._is_valid_candidate_name(name, known_names):
                pattern1_hits.add(name)
                pattern1_count[name] = pattern1_count.get(name, 0) + 1

        # 模式 2: 名字 + 的 + 身份/物品（"林远的刀"）
        # 修复：要求"的"前是名字（不是"的着过"），且"的"后跟非色/味/质/感/方位/虚词的内容
        # 修复：要求名字内部不含停用词字符
        pattern2_re = re.compile(
            r'(?<![的着过在是和与或但而也不])([一-鿿]{2,3})的(?![色味质感边间里上下中内外等的和与是为，。！？\s])'
        )
        for m in pattern2_re.finditer(text):
            name = m.group(1)
            if self._is_valid_candidate_name(name, known_names):
                pattern2_hits.add(name)
                pattern2_count[name] = pattern2_count.get(name, 0) + 1

        # 模式 3: 名字 + 是/为 + 身份 ("陈浩是永恒之门的技术员")
        # 修复：要求"是"前不是"是"，且后不是色味质
        pattern3_re = re.compile(
            r'(?<![是为])([一-鿿]{2,3})(?:是|为)(?![色味质])'
        )
        for m in pattern3_re.finditer(text):
            name = m.group(1)
            if self._is_valid_candidate_name(name, known_names):
                pattern3_hits.add(name)
                pattern3_count[name] = pattern3_count.get(name, 0) + 1

        # 模式 4: 穿着/戴着/拿着 + 描述 + 的 + 名字 ("穿着灰色工装的男人")
        # 这个模式本身较可靠，不用额外加固
        for m in re.finditer(r'(?:穿着|戴着|拿着|拎着|抱着|抬着|扛着)(?:[^，。！？\n]{1,10}?)的([一-鿿]{2,3})', text):
            name = m.group(1)
            if self._is_valid_candidate_name(name, known_names):
                pattern4_hits.add(name)

        # 交叉验证：候选名需满足以下任一条件（修复：收紧阈值，要求更强证据）
        # 同时对 3 字窗口做"核心名提取"，把 "林逸以" "丁磊知" 还原成 "林逸" "丁磊"
        final_candidates = set()
        for name in pattern1_hits | pattern2_hits | pattern3_hits | pattern4_hits:
            # 先做核心名提取（3 字窗口可能包含真名+附加字）
            core_name = self._extract_core_name(name)
            if not core_name:
                continue
            # 再做交叉验证（更严格的阈值）
            if core_name in pattern1_hits:
                # 模式 1 命中（最可靠的人名信号）
                final_candidates.add(core_name)
            elif core_name in pattern4_hits and pattern3_count.get(core_name, 0) >= 1:
                # 模式 4（穿着X的Z）+ 模式 3 双重确认
                final_candidates.add(core_name)
            elif pattern2_count.get(core_name, 0) >= 3:
                # 模式 2 多次确认（≥3 次）
                final_candidates.add(core_name)
            elif core_name in pattern2_hits and core_name in pattern3_hits:
                # 模式 2 + 模式 3 组合
                final_candidates.add(core_name)

        return final_candidates

    def _extract_core_name(self, name: str) -> str | None:
        """从候选名（2-3 字）中提取核心人名

        中文 2-3 字窗口经常包含真名 + 附加字，例如：
          "丁磊知" (丁磊 + 知道 → 核心 = 丁磊)
          "林逸以" (林逸 + 以 → 核心 = 林逸)
          "苏玫掏" (苏玫 + 掏 → 核心 = 苏玫)

        算法：取名字的最长前缀，要求：
        1. 长度 ≥ 2
        2. 不包含停用词字符
        3. 以常用姓氏开头
        """
        if not name or len(name) < 2:
            return None
        # 从最长前缀开始试
        for length in range(len(name), 1, -1):
            prefix = name[:length]
            if not self._looks_like_name(prefix):
                continue
            if any(c in self._NAME_STOP_CHARS for c in prefix):
                continue
            return prefix
        return None

    def _is_valid_candidate_name(self, name: str, known_names: set[str]) -> bool:
        """验证候选名是否可能是真角色（用于 extract_candidate_character_names 的 4 个模式）

        检验项目：
        1. 名字非空
        2. 不在已知角色集合中
        3. 不在常见误识别白名单中
        4. 满足"看起来像人名"（常用姓氏开头）
        5. 名字内部不含停用词字符 — 涵盖虚词/介词/常见动词/疑问代词/方位词等，
           这能过滤 "丁磊知" "林逸以" "苏玫掏" "陈浩没" 这种 3 字窗口
           （真实人名极少包含这些字符）
        6. 如果是 3 字候选且前 2 字是已知角色名，判定为冗余捕获 — 这能过滤
           "林逸以" "林晓知"（包含已注册角色名的扩展）
        """
        if not name or name in known_names or name in self._CHARACTER_FALSE_POSITIVES:
            return False
        if not self._looks_like_name(name):
            return False
        # 名字内部不应含停用词字符（更全面的列表）
        if any(c in self._NAME_STOP_CHARS for c in name):
            return False
        # 3 字候选如果以 2 字已知角色名开头，是冗余捕获（应被前面的 stop_chars 拦截，
        # 但兜底再检查一次以防漏网）
        if len(name) == 3 and name[:2] in known_names:
            return False
        return True

    # 名字内部不应包含的字符（虚词、常见动词、疑问词、方位词等）
    # 真实人名极少包含这些字符；用于过滤 "X的Y" "X是Z" 等模式中的误切分窗口
    _NAME_STOP_CHARS = (
        "的了着过在是和与或但而也不就要会能"
        # 副词/介词
        "以只被给没走看听说来去做回想起点点抬抽掏摸钻踏吐领拿收放装抱拉推拍敲捏"
        "让把从向对根据因为所以如果虽然不过只是然而因此"
        # 疑问代词
        "哪里什么怎么为什么哪个哪些谁"
        # 人称代词
        "你您我他她它咱们大家自己"
        # 时间/状态
        "已已经曾经正在将快要刚刚突然忽然"
        # 方位（注意"周"是姓氏，不能放入停用词！）
        "上下中里外前后旁边"
        # 数词
        "一二三四五六七八九十百千万几半多"
        # 常见动词（误切分常见源：X + 动词）
        "认知怀疑特工图才片完整手绘折叠记录瞳孔色光"
        # 常见名词/形容词
        "东南西北男女老少"
        # 颜色
        "白红蓝绿黄灰紫棕金银铜铁"
    )

    @staticmethod
    def _looks_like_name(s: str) -> bool:
        """启发式：2-3 字的中文词是否像人名"""
        if len(s) < 2 or len(s) > 3:
            return False
        # 不含停用词
        stopwords = {"这个", "那个", "什么", "怎么", "没有", "可能", "已经", "可以", "应该", "需要", "现在", "刚才", "后来", "最后", "然后", "可是", "可是", "但是", "因为", "所以", "如果", "虽然", "不过", "只是", "一直", "一些", "一样", "一切", "一种", "这个"}
        if s in stopwords:
            return False
        # 至少要有一个常用姓氏
        common_surnames = {"林", "张", "王", "李", "刘", "陈", "杨", "黄", "赵", "周", "吴", "徐", "孙", "马", "朱", "胡", "郭", "何", "高", "罗", "郑", "梁", "谢", "宋", "唐", "许", "韩", "冯", "邓", "曹", "彭", "曾", "萧", "田", "董", "袁", "潘", "蔡", "蒋", "余", "杜", "叶", "程", "苏", "魏", "吕", "丁", "任", "沈", "姚", "卢", "姜", "崔", "钟", "谭", "陆", "汪", "范", "金", "石", "廖", "贾", "夏", "韦", "付", "方", "白", "邹", "孟", "熊", "秦", "邱", "江", "尹", "薛", "闫", "段", "雷", "侯", "龙", "史", "陶", "黎", "贺", "顾", "毛", "郝", "龚", "邵", "万", "钱", "严", "覃", "武", "戴", "莫", "孔", "向", "汤"}
        return s[0] in common_surnames

    async def auto_register_characters(self, chapter_text: str, chapter_idx: int, llm_call=None) -> int:
        """P1 修复：从章节正文中检测并自动注册新角色

        Args:
            chapter_text: 章节正文
            chapter_idx: 章节序号
            llm_call: 可选的 LLM 调用函数，用于确认候选名字是否为真角色

        Returns: 新注册的角色数量
        """
        if not chapter_text:
            return 0

        known = set(self.structured.characters.keys())
        candidates = self.extract_candidate_character_names(chapter_text, known)
        if not candidates:
            return 0

        # 可选：用 LLM 确认每个候选名字是否真的是角色，并提取身份
        if llm_call:
            try:
                prompt = f"""从以下章节正文中识别新出现的角色，输出 JSON 数组。
要求：
1. 只输出在"候选"列表里、且确实是新角色（不是泛指代词、不是人名外号、不是误解）的项
2. 每个角色用 30 字以内总结其身份/目的/关系
3. 排除功能/职务称谓（陈浩-2、苏玫-3 等带数字后缀的不是新角色）

候选名字：{', '.join(sorted(candidates))}

章节正文（节选）：
{chapter_text[:3000]}

输出格式（JSON 数组，每个元素 {{"name": "...", "role": "...", "backstory": "..."}}）："""
                result = await llm_call(prompt=prompt, system="你是文学编辑，专精角色识别。", temperature=0.3, json_mode=True)
                if isinstance(result, dict) and "characters" in result:
                    candidates_to_register = result["characters"]
                elif isinstance(result, list):
                    candidates_to_register = result
                else:
                    candidates_to_register = [{"name": c, "role": "未知", "backstory": ""} for c in candidates]
            except Exception as e:
                logger.warning(f"LLM character verification failed: {e}")
                candidates_to_register = [{"name": c, "role": "未知", "backstory": ""} for c in candidates]
        else:
            candidates_to_register = [{"name": c, "role": "未知", "backstory": ""} for c in candidates]

        registered = 0
        for c in candidates_to_register:
            if not isinstance(c, dict):
                continue
            name = c.get("name", "").strip()
            if not name or name in self.structured.characters:
                continue
            if not self._looks_like_name(name):
                continue
            try:
                sheet = CharacterSheet(
                    name=name,
                    goal=c.get("backstory", "") or c.get("role", ""),
                    personality=[],
                    relationships=[],
                    status={"first_appearance": chapter_idx, "auto_registered": True},
                    memory=[],
                    appearance="",
                    abilities=[],
                    voice={},
                )
                self.structured.update_character(sheet)
                registered += 1
                logger.info(f"Auto-registered character '{name}' in chapter {chapter_idx}: {c.get('role', '')}")
            except Exception as e:
                logger.warning(f"Failed to register character '{name}': {e}")
        return registered

    def sync_relationships_from_characters(self, chapter: int = 0):
        self.relationship_graph.sync_from_characters(self.structured.characters, chapter)

    def add_scene_context(self, context: str):
        self.short_term.add_scene_context(context)

    def clear_scene_context(self):
        self.short_term.clear_scene_context()

    def clear_chapter_memory(self):
        self.short_term.clear_chapters()
        self.short_term.clear_scene_context()

    def clear_story_state(self):
        self.clear_chapter_memory()
        self.structured.clear_story_state()
        self.relationship_graph.clear()
