# Agent 系统

本文档介绍 LongFiction-AI 的多智能体协作系统。

## 🤖 概述

LongFiction-AI 使用 8 个专业化的 Agent 协作完成长篇小说的创作。每个 Agent 负责特定任务，通过 `MainPipeline` 编排调用。

## 🎭 Agent 详细说明

### 1. PlannerAgent（规划师）

**职责**：
- 将用户大纲拆分为 12 章详细规划
- 将单章规划拆分为多个场景

**输入**：
- 大纲文本
- 已有世界观
- 已有角色
- 目标章节数

**输出**：
- `VolumeOutline` JSON 结构
- `SceneOutline` 列表

**提示词关键点**：
- 章节目标（goal）
- 章节冲突（conflict）
- 场景分解
- 角色出场

**调用示例**：
```python
from agents.planner_agent import PlannerAgent

planner = PlannerAgent()
chapter_plans = await planner.plan_chapters(
    outline=outline,
    world=world,
    characters=characters,
    target_chapters=12
)
```

### 2. WriterAgent（写手）

**职责**：
- 场景初稿生成
- 章节扩写/修剪
- 章节续写
- 整章/片段改写

**核心提示词** `WRITER_SYSTEM`：
- 禁止使用的 AI 套话（程度副词、情绪套话、比喻套话等）
- 段落构造原则
- 对话规则
- 叙事节奏
- 人物呈现
- 场景完整性

**场景写作流程**：
```
1. 接收场景信息（描述/角色/地点/氛围）
2. 注入上下文（前章摘要、角色状态、相关历史）
3. 生成场景初稿
4. 字数控制（扩写/修剪循环）
5. 质量检查（完整性、节奏、对话比例）
6. 输出场景文本
```

**关键方法**：
```python
async def draft_scene(scene, context, guidance) -> str
async def expand(text, target_words) -> str
async def polish(text) -> str
async def continue_chapter(content, target_words) -> str
async def revise_chapter(content, guidance) -> str
async def revise_fragment(content, fragment, instruction) -> str
async def trim(text, target_words) -> str
```

### 3. StyleRewriter（风格润色师）

**职责**：
- 检测 AI 生成痕迹
- 深度润色以去除 AI 感

**24 个 AI 模式正则**（`AI_PATTERNS`）：
- 高置信度模式：
  - 三选一排比（"要么...要么...要么..."）
  - 命运的齿轮
  - 一股涌上心头
  - 心中涌起
  - 眼中闪过一丝
  - 难以言喻
  - 瞳孔骤缩
  - 倒吸一口凉气
  - 义无反顾
  - 由此可知
  - ...
- 中等置信度模式：...
- 低置信度模式：...

**风格库**（`STYLE_LIBRARY`）：
- `web_novel` - 网文风格
- `dark` - 暗黑风格
- `humor` - 幽默风格
- `serious` - 严肃文学

**重写策略**：
```
1. 检测 AI 模式（正则 + LLM 语义）
2. 标记问题段落
3. 针对性重写（保留核心叙事）
4. 风格一致性检查
5. 输出润色文本
```

### 4. CharacterEngine（角色工程师）

**职责**：
- 从大纲生成角色表
- 更新角色状态
- OOC（Out of Character）检测

**角色数据结构**：
```python
class CharacterSheet:
    name: str
    goal: str                 # 角色目标
    personality: list[str]    # 性格特征
    relationships: list[dict] # 关系网络
    status: dict              # 当前状态
    memory: list[str]         # 记忆
    appearance: str           # 外貌
    abilities: list[str]      # 能力
    voice: dict               # 语言风格
```

**OOC 检测**：
- 对比角色性格与言行
- 检查目标/动机一致性
- 标记可疑行为

### 5. CharacterStateMachine（角色状态机）

**职责**：
- 跟踪角色状态转移
- 战力等级管理
- 关系变化追踪

**状态类型**：
- 战力等级
- 健康状态
- 情绪状态
- 当前位置
- 关系亲密度

**状态转移规则**：
- 等级提升需要相应事件
- 关系变化需要触发条件
- 状态冲突检测

### 6. WorldBuilder（世界构建师）

**职责**：
- 从大纲生成完整世界观
- 扩展设定规则

**世界观结构**：
```python
class WorldSetting:
    cultivation_system: str    # 修炼体系
    factions: list[dict]        # 势力
    rules: list[str]            # 规则
    history: list[str]          # 历史
    locations: list[dict]       # 地点
```

### 7. ConsistencyChecker（一致性检查员）

**职责**：
- LLM 一致性检查
- 规则一致性检查
- 自动修复

**检查维度**：
1. **角色一致性**：言行符合已建立性格
2. **世界观一致性**：不违反已定义规则
3. **时间线一致性**：事件顺序合理
4. **逻辑一致性**：因果关系正确
5. **伏笔一致性**：已埋设伏笔得到回收

**输出**：
```python
class ConsistencyReport:
    is_consistent: bool
    issues: list[str]
    ooc_characters: list[str]
    world_conflicts: list[str]
    logic_errors: list[str]
    score: float  # 0.0 - 1.0
```

### 8. CriticAgent（评论家）

**职责**：
- 章节摘要
- 模拟读者反馈
- 多版本选择

**摘要策略**：
- 关键事件提取
- 人物状态更新
- 伏笔状态变化

**读者反馈模拟**：
- 情感反应
- 注意力曲线
- 满意度评估

## 🎼 增强子系统（14 模块）

### 1. EnhancementOrchestrator
**职责**：编排其他 13 个增强模块，按需调用。

### 2. AntiResolutionBrake
**职责**：防止故事过早进入结局状态，确保长篇节奏。

### 3. EventMatrix
**职责**：
- 事件分类（冲突/解决/揭示/转折等）
- 事件冷却（避免重复）
- 配额管理（A/B/C 类事件限制）

### 4. SuspenseArcManager
**职责**：
- 悬念弧生命周期管理
- 埋设→发酵→回收
- 跨章节悬念追踪

### 5. RhythmPlanner
**职责**：
- 情绪曲线规划
- 密度交替（高/低密度事件）
- 节奏偏差检测

### 6. QualityScorer
**职责**：9 维度质量评分
- coherence（连贯性）
- creativity（创意性）
- readability（可读性）
- emotional（情感）
- logic（逻辑）
- flow（流畅度）
- depth（深度）
- originality（原创性）
- engagement（参与度）

### 7. PromptEnhancer
**职责**：注入写作技巧库
- 10 种开头技巧
- 5 种文学技巧
- 6 种扩写技巧
- "show don't tell" 对照表
- 4 种打破期待的方式

### 8. StructureEnforcer
**职责**：验证章节结构
- 钩子（20%）
- 发展（55%）
- 高潮（17%）
- 收束（8%）

### 9. ReadbackManager
**职责**：智能上下文回读
- 短期记忆（最近章节）
- 长期记忆（FAISS 检索）
- 结构化记忆（角色/事件）
- 压缩回读（远程历史）

### 10. OutlineAdjuster
**职责**：根据实际进展动态调整大纲
- 评分监测
- 连续低分检测
- 大纲修正建议

### 11. ProgressManager
**职责**：锚点进度追踪
- 关键事件锚点
- 完成度评估
- 偏移检测

### 12. EntryModeManager
**职责**：叙事入口约束
- 限制章节开头的常见 AI 模式
- 强制直接进入场景

### 13. InfoGapManager
**职责**：读者/角色信息差管理
- 跟踪读者已知信息
- 跟踪角色已知信息
- 信息揭露节奏

### 14. EnhancementConfig
**职责**：增强子系统配置
- 阈值参数
- 启用/禁用模块
- 调优参数

## 🔄 Agent 协作流程

### 章节生成完整流程

```python
# 1. 加载上下文
context = readback_manager.get_context(chapter_index)

# 2. 场景拆分
scenes = planner.split_scenes(chapter_plan, context)

# 3. 生成前增强
pre_instructions = enhancement.pre_generation(
    chapter_index=chapter_index,
    target_words=2000,
    pacing_label="normal"
)

# 4. 逐场景写作
scene_texts = []
for scene in scenes:
    # 写作
    draft = writer.draft_scene(scene, context, pre_instructions)
    # 字数控制
    draft = word_controller.adjust(draft, target=800)
    scene_texts.append(draft)

# 5. 合并章节
chapter = "\n\n".join(scene_texts)

# 6. 一致性检查
consistency = consistency_checker.check(chapter, context)
if not consistency.is_consistent:
    chapter = consistency_checker.auto_fix(chapter, consistency.issues)

# 7. 风格润色
chapter = style_rewriter.rewrite(chapter)

# 8. 增强后处理
post_result = enhancement.post_generation(chapter, chapter_index)

# 9. 质量评分
quality = await enhancement.post_critic(chapter)

# 10. 保存
save_version(chapter, quality)
```

## 🎛️ Agent 配置

每个 Agent 通过以下参数配置：

| 参数 | 作用 |
|------|------|
| `LLM_PLANNER_MODEL` | 规划任务使用的模型 |
| `LLM_WRITER_MODEL` | 写作任务使用的模型 |
| `LLM_STYLE_MODEL` | 风格润色模型 |
| `LLM_CHECK_MODEL` | 检查任务模型 |
| `LLM_TIMEOUT_SECONDS` | 单次调用超时 |
| `LLM_USE_RESPONSE_FORMAT` | 是否请求 JSON 模式 |
| `FAST_TEST_MODE` | 跳过增强层 |
| `SKIP_DEEP_DEAI` | 跳过深度去 AI 痕迹 |
| `SKIP_QUALITY_SCORE` | 跳过质量评分 |

## 📊 性能考虑

- **顺序 vs 并行**：当前为顺序调用，未来可并行独立任务
- **缓存**：未实现 LLM 响应缓存（计划中）
- **Token 控制**：通过 `max_tokens` 参数控制
- **超时控制**：所有调用都有超时保护

## 🔮 未来扩展

- [ ] 引入更多专业 Agent（情节节奏、对话写作）
- [ ] Agent 间通信总线
- [ ] Agent 效果自动评估
- [ ] 用户自定义 Agent
