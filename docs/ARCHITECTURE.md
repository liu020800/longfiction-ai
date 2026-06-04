# 架构设计

本文档详细介绍 LongFiction-AI 的系统架构、设计理念和核心组件。

## 🎯 设计目标

1. **模块化**：每个组件职责单一，易于替换和升级
2. **可扩展**：支持新增 Agent、记忆层、模型路由
3. **可观测**：完整的日志和调用追踪
4. **可配置**：通过环境变量和配置文件调整行为
5. **生产级**：错误处理、超时控制、资源管理

## 🏛️ 五层架构

### 1. 用户交互层（Presentation Layer）

**位置**：`web/`

**职责**：
- 提供 SPA 用户界面
- 与后端 API 通信
- 渲染项目和章节数据
- 用户输入处理

**关键模块**：
- `app-init.js` - 应用初始化、事件绑定
- `workspace.js` - 创作工作台核心
- `api-client.js` - API 调用封装
- `auth.js` - 认证管理
- `dashboard.js` - 仪表盘
- `settings.js` - 设置面板

**路由**：
- `#dashboard` - 仪表盘
- `#workspace` - 创作工作台
- `#settings` - 账户设置
- `#admin` - 管理后台（仅管理员）

### 2. API 层（API Layer）

**位置**：`api/main.py`

**技术**：FastAPI

**职责**：
- HTTP 请求处理
- 参数验证（Pydantic）
- 用户认证（JWT）
- 调用核心流水线
- 任务状态管理

**端点组织**（共 50+）：
- 项目管理：`/api/project/*`
- 章节操作：`/api/chapter/*`
- 数据库操作：`/api/db/*`
- 用户认证：`/api/auth/*`
- 导出：`/api/export/*`
- 工具：`/api/ai-detect`, `/api/llm-config`, `/api/styles`

### 3. 核心流水线层（Pipeline Layer）

**位置**：`main_pipeline.py`

**核心类**：`MainPipeline`

**职责**：
- 项目状态管理
- 章节生成编排
- 记忆系统协调
- 一致性控制
- 增强系统调用

**关键方法**：
```python
class MainPipeline:
    def __init__(session_id): ...
    def init_project(outline, genre, style): ...
    def generate_chapter(chapter_index): ...
    def revise_chapter(chapter_index, guidance): ...
    def continue_chapter(chapter_index): ...
    def finalize_chapter(chapter_index): ...
    def export_project(format): ...
    def save_to_database(): ...
    def load_from_database(): ...
```

### 4. 智能体协作层（Agent Layer）

**位置**：`agents/`

**8 个核心 Agent**：

| Agent | 职责 | 输入 | 输出 |
|-------|------|------|------|
| `PlannerAgent` | 章节规划、场景拆分 | 大纲/章节规划 | 详细计划/场景列表 |
| `WriterAgent` | 章节/场景写作 | 场景信息 | 正文文本 |
| `StyleRewriter` | AI 痕迹去除 | 文本 | 润色文本 |
| `CharacterEngine` | 角色创建/更新 | 章节规划 | 角色 JSON |
| `CharacterStateMachine` | 角色状态管理 | 状态变更 | 状态转移日志 |
| `WorldBuilder` | 世界观构建 | 大纲 | 世界观 JSON |
| `ConsistencyChecker` | 一致性检查 | 章节 + 上下文 | 一致性报告 |
| `CriticAgent` | 质量评估/反馈 | 章节文本 | 摘要/反馈 |

**14 个增强模块**（`agents/enhancement/`）：

1. `EnhancementOrchestrator` - 编排器
2. `AntiResolutionBrake` - 防止过早结局
3. `EventMatrix` - 事件分类与冷却
4. `SuspenseArcManager` - 悬念弧管理
5. `RhythmPlanner` - 节奏规划
6. `QualityScorer` - 9 维度质量评分
7. `PromptEnhancer` - 写作技巧库注入
8. `StructureEnforcer` - 章节结构验证
9. `ReadbackManager` - 上下文回读
10. `OutlineAdjuster` - 大纲动态调整
11. `ProgressManager` - 锚点进度追踪
12. `EntryModeManager` - 叙事入口约束
13. `InfoGapManager` - 信息差管理
14. `EnhancementConfig` - 增强配置

### 5. 基础设施层（Infrastructure Layer）

#### 5.1 模型路由（`core/llm_router.py`）

**职责**：
- 统一 LLM 调用接口
- 模型角色路由
- JSON 模式处理
- 推理 artifacts 清理
- 超时控制

**核心函数**：
```python
async def call_llm(
    task_type: TaskType,    # plan/write/rewrite/check/world/character/plot
    prompt: str,
    system: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    json_mode: bool = False,
) -> str
```

**模型角色映射**：
```python
MODEL_ROUTE = {
    TaskType.PLAN: settings.LLM_PLANNER_MODEL,
    TaskType.WRITE: settings.LLM_WRITER_MODEL,
    TaskType.REWRITE: settings.LLM_STYLE_MODEL,
    TaskType.CHECK: settings.LLM_CHECK_MODEL,
    TaskType.WORLD: settings.LLM_PLANNER_MODEL,
    TaskType.CHARACTER: settings.LLM_PLANNER_MODEL,
    TaskType.PLOT: settings.LLM_PLANNER_MODEL,
}
```

#### 5.2 记忆系统（`memory/`）

**三层架构**：

```
┌─────────────────────────────────────────┐
│          Short-Term Memory              │
│   deque: 最近 3 章完整内容               │
│   用途: 章节间上下文传递                 │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│          Long-Term Memory (FAISS)       │
│   向量索引: 章节摘要 + 元数据            │
│   用途: 语义检索历史相关内容             │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│       Structured Memory (JSON)          │
│   角色/世界观/时间线/伏笔/章节摘要        │
│   用途: 精确查询和持久化                │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│       Hierarchical Summary              │
│   每 10 章压缩为一个 Arc 摘要           │
│   用途: 跨章节长程依赖                  │
└─────────────────────────────────────────┘
```

#### 5.3 数据持久化（`models/db_models.py`）

**13 张表**：

| 表名 | 用途 |
|------|------|
| `projects` | 项目主表 |
| `characters` | 角色 |
| `world_settings` | 世界观 |
| `chapters` | 章节 |
| `scenes` | 场景 |
| `chapter_versions` | 章节版本 |
| `timeline_events` | 时间线事件 |
| `plot_arcs` | 剧情弧 |
| `foreshadowing` | 伏笔 |
| `users` | 用户 |
| `user_projects` | 用户-项目关联 |
| `recharge_records` | 充值记录 |
| `consumption_records` | 消费记录 |

**关系图**：
```
users ─┬─ user_projects ─→ projects
       ├─ recharge_records
       └─ consumption_records
                                          │
projects ─┬─ characters                   │
          ├─ world_settings               │
          ├─ chapters ─┬─ scenes         │
          │             ├─ chapter_versions
          │             └─ (in-memory)
          ├─ timeline_events              │
          ├─ plot_arcs                    │
          └─ foreshadowing                │
                                          │
```

## 🔄 核心流程

### 项目初始化流程

```python
def init_project(outline, genre, style):
    # 1. 生成世界观
    world = world_builder.build(outline, genre)
    
    # 2. 生成角色
    characters = character_engine.create(outline, world)
    
    # 3. 生成章节规划
    plan = planner_agent.plan_chapters(outline, world, characters)
    
    # 4. 保存到内存
    self.world = world
    self.characters = characters
    self.volume = plan
    
    # 5. 持久化到数据库
    self.ensure_project_in_database()
```

### 章节生成流程

```python
async def generate_chapter(chapter_index, guidance=""):
    # 1. 加载上下文
    context = memory.retrieve_context()
    
    # 2. 章节规划（场景拆分）
    scenes = planner_agent.split_scenes(chapter_plan, characters)
    
    # 3. 逐场景写作 + 字数控制
    scene_texts = []
    for scene in scenes:
        draft = writer_agent.draft_scene(scene, context, guidance)
        draft = word_controller.adjust(draft, target_words)
        scene_texts.append(draft)
    
    # 4. 合并为完整章节
    chapter_content = "\n\n".join(scene_texts)
    
    # 5. 一致性检查
    consistency = consistency_checker.check(chapter_content, context)
    if not consistency.is_consistent:
        chapter_content = fix_issues(chapter_content, consistency.issues)
    
    # 6. 风格润色
    chapter_content = style_rewriter.rewrite(chapter_content)
    
    # 7. 增强处理
    enhanced = enhancement.post_generation(chapter_content, chapter_index)
    
    # 8. 质量评分
    quality = await enhancement.post_critic(chapter_content)
    
    # 9. 保存版本
    self.save_chapter_version(chapter_index, chapter_content, quality)
    
    return chapter_content
```

### 定稿流程

```python
def finalize_chapter(chapter_index):
    chapter = self.get_chapter(chapter_index)
    
    # 1. 更新短期记忆
    memory.add_chapter_to_memory(chapter.title, chapter.content, chapter.summary)
    
    # 2. 写入时间线
    self.add_timeline_events(chapter)
    
    # 3. 记录/回收伏笔
    self.update_foreshadowing(chapter)
    
    # 4. 更新角色状态
    self.update_character_states(chapter)
    
    # 5. 更新 FAISS 索引
    self.rag.add_chapter(chapter)
    
    # 6. 标记定稿
    chapter.finalized = True
    self.save()
```

## 🛡️ 一致性保证机制

### 写入时检查

- **JSON 格式校验**：所有 LLM 返回的 JSON 都要通过 schema 验证
- **字数控制**：扩写/修剪循环，最大 4 次尝试
- **一致性 Gate**：生成前检查人物状态、世界观冲突

### 读取时检查

- **Pydantic 验证**：所有 API 参数
- **关系完整性**：外键约束
- **状态转换验证**：角色状态机

## 📊 性能与扩展

### 性能瓶颈

1. **LLM 调用延迟**：单次调用 5-30 秒
2. **FAISS 检索**：百万级向量毫秒级
3. **数据库写入**：SQLite 串行写

### 扩展点

1. **多模型路由**：可针对不同任务使用不同模型
2. **记忆后端**：FAISS → Milvus / Pinecone
3. **数据库**：SQLite → PostgreSQL
4. **缓存层**：Redis 缓存 LLM 响应
5. **任务队列**：Celery 处理长任务

## 🔒 安全设计

1. **认证**：JWT + bcrypt
2. **授权**：基于角色（user/admin）
3. **输入验证**：Pydantic
4. **CORS**：可配置
5. **密钥管理**：环境变量 + .env.example
6. **SQL 注入**：SQLAlchemy ORM
7. **XSS**：前端转义

## 📈 监控与日志

- **请求日志**：中间件记录所有 HTTP 请求
- **LLM 调用日志**：耗时、模型、token 数
- **错误日志**：完整堆栈跟踪
- **API 文档**：FastAPI 自动生成 `/docs`
