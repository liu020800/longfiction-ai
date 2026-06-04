<div align="center">

# LongFiction-AI

**多智能体驱动的长篇网文自动创作系统**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688.svg)](https://fastapi.tiangolo.com)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

[功能特性](#-功能特性) • [快速开始](#-快速开始) • [架构](#-架构) • [文档](#-文档) • [路线图](#-路线图) • [贡献](#-贡献)

</div>

---

## 📖 项目简介

**LongFiction-AI** 是一个面向长篇网络小说创作的多智能体 AI 写作系统。它通过 8 个专业化 Agent 协作，结合三层记忆架构、AI 痕迹去除、风格控制等技术，实现长篇小说的自动化创作与一致性管理。

### 核心问题

长篇网文创作（100+ 章、200万+ 字）面临的核心挑战：
- **角色一致性**：数百个角色、复杂的势力关系，AI 容易 OOC（Out of Character）
- **伏笔管理**：大量伏笔需要埋设、追踪、回收
- **风格统一**：长篇作品的文风需要保持一致
- **AI 痕迹**：模型生成的文本有明显 AI 感，需要深度润色
- **上下文管理**：单章 2000-3000 字，但需参考前文数百章的内容

### 解决方案

| 挑战 | 解决方案 |
|------|----------|
| 角色一致性 | `CharacterStateMachine` + 角色状态机 + OOC 检测 |
| 伏笔管理 | `ForeshadowingService` + 自动埋设/回收 |
| 风格统一 | `StyleLearner` + 风格向量索引 + 风格迁移 |
| AI 痕迹 | 24 个正则模式 + LLM 语义重写 + 5 种策略库 |
| 上下文管理 | 三层记忆（短期/长期/结构化）+ FAISS 向量检索 + RAG 2.0 |

---

## ✨ 功能特性

### 🎯 项目层
- ✅ 创建小说项目，支持 6 种体裁模板（都市玄幻、玄幻、仙侠、科幻、言情、人类困境）
- ✅ AI 自动扩展世界观、角色表、章节规划
- ✅ 项目列表与恢复（SQLite/PostgreSQL 持久化）
- ✅ 一键导出（ZIP / TXT / EPUB）

### 📚 设定层
- ✅ 世界观编辑与 AI 重新生成
- ✅ 角色编辑与 AI 重新生成（含人物状态机）
- ✅ 章节规划编辑与 AI 重新生成
- ✅ 设定确认流程（保存后才可生成章节）

### 📖 章节层
- ✅ 单章生成（自动场景拆分 → 逐场景写作 → 字数控制 → 一致性检查 → 润色）
- ✅ 单章重新生成
- ✅ 章节续写
- ✅ 整章改写
- ✅ 局部片段改写
- ✅ 本章创作指导（guidance）

### 🔄 版本层
- ✅ 完整版本历史
- ✅ 查看任意版本内容
- ✅ 切换版本为当前
- ✅ 双版本差异对比

### ✍️ 定稿层
- ✅ 章节定稿 / 取消定稿
- ✅ 定稿后自动更新记忆系统
- ✅ 定稿后写回正式时间线
- ✅ 定稿后记录伏笔

### 🔍 一致性控制层
- ✅ 最近定稿章节摘要注入后续写作
- ✅ 正式时间线注入后续写作
- ✅ 未回收伏笔注入后续写作
- ✅ 角色状态机注入后续写作
- ✅ 自动伏笔回收（关键词启发式）
- ✅ 故事控制信息前移到章节规划阶段

### 🤖 AI 智能体（8 个）
- `PlannerAgent` - 章节规划、场景拆分
- `WriterAgent` - 场景/章节写作、扩写、改写、续写
- `StyleRewriter` - AI 痕迹检测与重写
- `CharacterEngine` - 角色创建/更新/OOC 检测
- `CharacterStateMachine` - 角色状态转移（战力、关系）
- `WorldBuilder` - 世界观构建
- `ConsistencyChecker` - 一致性检查（LLM + 规则）
- `CriticAgent` - 章节摘要/读者反馈/版本选择

### 🛡️ 增强子系统（14 个模块）
- `EnhancementOrchestrator` - 增强编排器
- `AntiResolutionBrake` - 防止过早结局
- `EventMatrix` - 事件分类与冷却
- `SuspenseArcManager` - 悬念弧管理
- `RhythmPlanner` - 节奏规划
- `QualityScorer` - 9 维度质量评分
- `PromptEnhancer` - 写作技巧库注入
- `StructureEnforcer` - 章节结构验证（钩子/发展/高潮/收束）
- `ReadbackManager` - 上下文回读
- `OutlineAdjuster` - 大纲动态调整
- `ProgressManager` - 锚点进度追踪
- `EntryModeManager` - 叙事入口约束
- `InfoGapManager` - 信息差管理
- `EnhancementConfig` - 增强配置

### 💾 记忆系统（三层）
- **短期记忆**：最近 N 章的 deque 缓存
- **长期记忆**：FAISS 向量索引 + 关键词倒排
- **结构化记忆**：JSON 持久化的角色/世界观/时间线
- **分层摘要**：每 10 章一个 Arc 摘要，跨章节上下文压缩

### 🌐 前端工作台
- 仪表盘 - 项目概览、统计、搜索
- 创作工作台 - 项目参数、世界观/角色/章节编辑器、目录、章节查看、版本、时间线、伏笔、增强面板、批量生成
- 账户设置 - 用户资料、LLM 配置
- 管理后台 - 用户管理、充值（管理员可见）

---

## 🚀 快速开始

### 环境要求

- **Python**：3.10 或更高版本
- **操作系统**：Windows / macOS / Linux
- **内存**：建议 8GB+（FAISS 向量检索需要）
- **磁盘**：建议 10GB+ 可用空间

### 1. 克隆仓库

```bash
git clone https://github.com/liu020800/longfiction-ai.git
cd longfiction-ai
```

### 2. 安装依赖

```bash
# 推荐使用虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/macOS
# 或 venv\Scripts\activate  # Windows

pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
# 复制示例配置文件
cp .env.example .env

# 编辑 .env 文件，填入你的 API Key
# 任何 OpenAI 兼容的 API 都可使用：
#   - OpenAI:     https://api.openai.com/v1
#   - DeepSeek:   https://api.deepseek.com/v1
#   - Qwen:       https://dashscope.aliyuncs.com/compatible-mode/v1
#   - 本地 LLM:   http://localhost:1234/v1
```

### 4. 启动服务

```bash
python main.py
```

服务将在 `http://localhost:8000` 启动。

### 5. 访问工作台

打开浏览器访问 `http://localhost:8000`

**默认管理员账号**（首次启动自动创建）：
- 用户名：`admin`
- 密码：`admin123456`（请在 `.env` 中修改 `ADMIN_PASSWORD`）

### Docker 部署

```bash
docker-compose up -d
```

详见 [DEPLOYMENT.md](docs/DEPLOYMENT.md)

---

## 🏗️ 架构

### 五层架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      用户交互层（Web SPA）                       │
│  Dashboard | Workspace | Settings | Admin                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│               API 层（FastAPI REST Endpoints）                   │
│  2072 行核心 API  | 50+ REST 端点                                │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│              核心流水线层（MainPipeline）                        │
│  项目初始化 | 章节生成 | 一致性检查 | 风格重写 | 导出            │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                智能体协作层（8 Agents）                          │
│  Planner | Writer | Style | Character | World | Check | ...     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│         基础设施层（记忆/RAG/数据库/模型路由）                    │
│  Memory | RAG | SQLite/PG | LiteLLM | FAISS | Logging           │
└─────────────────────────────────────────────────────────────────┘
```

### 核心数据流

```
用户输入大纲
    ↓
MainPipeline.init_project()
    ↓
WorldBuilder → CharacterEngine → PlannerAgent
    ↓
用户确认设定（approved = true）
    ↓
MainPipeline.generate_chapter() (循环)
    ↓
PlannerAgent.scene_split() → 场景拆分
    ↓
WriterAgent.scene_draft() → 逐场景写作
    ↓
字数控制循环 (expand/trim) ← WordCounter
    ↓
ConsistencyChecker → 一致性检查
    ↓
StyleRewriter → AI 痕迹重写
    ↓
EnhancementOrchestrator → 14 个增强模块
    ↓
QualityScorer → 9 维度评分
    ↓
保存版本 (Database)
    ↓
用户定稿 (finalize)
    ↓
更新记忆 (Short/Long/Structured)
写入时间线 (TimelineEvent)
记录/回收伏笔 (Foreshadowing)
更新角色状态 (CharacterStateMachine)
    ↓
继续下一章
```

---

## 🧰 技术栈

| 类别 | 技术 |
|------|------|
| **后端框架** | FastAPI 0.110 + Uvicorn 0.27 |
| **数据验证** | Pydantic 2.6 + pydantic-settings |
| **数据库** | SQLite 3（默认）/ PostgreSQL 15+（生产） |
| **ORM** | SQLAlchemy 2.0 + Alembic 1.13 |
| **AI 调用** | LiteLLM 1.17（OpenAI 兼容协议） |
| **向量检索** | FAISS-CPU 1.7 |
| **认证** | JWT (python-jose) + bcrypt (passlib) |
| **前端** | 原生 HTML + CSS + JavaScript（无构建步骤） |
| **HTTP 客户端** | httpx 0.27 |
| **依赖管理** | pip + requirements.txt |

---

## 📁 项目结构

```
longfiction-ai/
├── main.py                          # 入口
├── main_pipeline.py                 # 核心流水线（MainPipeline 类）
├── requirements.txt
├── .env.example
├── README.md
├── LICENSE
│
├── api/                             # FastAPI 应用
│   └── main.py                      # 所有 REST 端点
│
├── agents/                          # 8 个核心 Agent
│   ├── planner_agent.py
│   ├── writer_agent.py
│   ├── style_rewriter.py
│   ├── character_engine.py
│   ├── character_state_machine.py
│   ├── world_builder.py
│   ├── consistency_checker.py
│   ├── critic_agent.py
│   └── enhancement/                 # 14 个增强模块
│
├── core/                            # 核心基础设施
│   ├── config.py                    # Pydantic Settings
│   ├── database.py                  # SQLAlchemy
│   ├── models.py                    # Pydantic 数据模型
│   ├── llm_router.py                # LiteLLM 路由
│   ├── auth.py                      # JWT 认证
│   ├── word_counter.py              # 字数统计
│   ├── logging_util.py
│   └── email_service.py
│
├── memory/                          # 三层记忆系统
│   ├── memory_system.py
│   ├── short_term.py
│   ├── long_term.py                 # FAISS
│   ├── structured.py                # JSON
│   └── hierarchical_summary.py
│
├── rag/                             # RAG 检索增强
│   └── rag_engine.py
│
├── models/                          # 数据库 ORM
│   ├── db_models.py
│   ├── db_service.py
│   └── user_service.py
│
├── web/                             # 前端 SPA
│   ├── index.html
│   ├── components/
│   ├── modules/
│   └── styles/
│
├── configs/                         # 配置与模板
│   ├── default.json
│   └── templates.json
│
├── docs/                            # 项目文档
│   ├── ARCHITECTURE.md
│   ├── DEPLOYMENT.md
│   ├── API.md
│   ├── AGENTS.md
│   ├── MEMORY.md
│   └── UPGRADE_PLAN.md
│
└── .github/                         # GitHub 配置
    ├── workflows/                   # CI/CD
    ├── ISSUE_TEMPLATE/
    └── PULL_REQUEST_TEMPLATE.md
```

---

## 📡 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 主工作台 |
| GET | `/api/health` | 服务健康检查 |
| POST | `/api/init` | 初始化项目 |
| GET/POST | `/api/project/*` | 项目 CRUD |
| POST | `/api/project/regenerate/{world,characters,chapters}` | 重新生成设定 |
| GET | `/api/catalog/{id}` | 章节目录 |
| POST | `/api/chapter` | 生成章节 |
| POST | `/api/chapter/regenerate` | 重新生成章节 |
| POST | `/api/chapter/continue` | 续写章节 |
| POST | `/api/chapter/revise` | 改写章节 |
| POST | `/api/chapter/revise-fragment` | 片段改写 |
| POST | `/api/chapter/finalize` | 定稿章节 |
| POST | `/api/chapter/unfinalize` | 取消定稿 |
| GET | `/api/chapter/{id}/{index}` | 获取章节内容 |
| POST | `/api/batch-generate` | 批量生成 |
| GET/POST | `/api/db/*` | 数据库操作（版本、对比、时间线、伏笔） |
| GET | `/api/export/{id}` | 导出（ZIP/TXT/EPUB） |
| POST | `/api/auth/login` | 登录 |
| POST | `/api/auth/register` | 注册 |
| GET/PUT | `/api/auth/me` | 用户资料 |
| POST | `/api/ai-detect` | AI 痕迹检测 |
| GET/PUT | `/api/llm-config` | LLM 配置 |

完整 API 文档：[docs/API.md](docs/API.md)

---

## 🧠 多智能体协作

### Agent 角色分工

| Agent | 输入 | 输出 | 模型 |
|-------|------|------|------|
| **PlannerAgent** | 大纲/章节规划 | 章节计划/场景拆分 | `LLM_PLANNER_MODEL` |
| **WriterAgent** | 场景信息 | 章节正文 | `LLM_WRITER_MODEL` |
| **StyleRewriter** | 文本 | 润色后文本 | `LLM_STYLE_MODEL` |
| **CharacterEngine** | 章节规划 | 角色表 | `LLM_PLANNER_MODEL` |
| **WorldBuilder** | 大纲 | 世界观 | `LLM_PLANNER_MODEL` |
| **ConsistencyChecker** | 章节文本 + 上下文 | 一致性报告 | `LLM_CHECK_MODEL` |
| **CriticAgent** | 章节文本 | 摘要/反馈 | `LLM_PLANNER_MODEL` |
| **PlotEngine** | 章节信息 | 节奏控制 | `LLM_PLANNER_MODEL` |

### 典型写作流程

```
1. 用户提供大纲
2. WorldBuilder 生成完整世界观（JSON）
3. CharacterEngine 从世界观提取主要角色（JSON）
4. PlannerAgent 将大纲拆分为 12 章的详细规划（JSON）
5. 用户在前端确认/编辑设定
6. 用户点击"生成第 1 章"
7. PlannerAgent 将本章拆分为 2-4 个场景
8. WriterAgent 逐场景生成正文（控制字数）
9. 字数控制循环：扩写/修剪
10. ConsistencyChecker 检查角色/世界观/逻辑一致性
11. StyleRewriter 去除 AI 痕迹
12. EnhancementOrchestrator 14 个增强模块
13. QualityScorer 9 维度评分
14. 保存为版本 v1
15. 用户可定稿 → 触发记忆系统更新
16. 继续下一章（注入上一章摘要/时间线/伏笔）
```

---

## 💾 记忆系统

### 三层记忆架构

| 层级 | 存储 | 用途 | 容量 |
|------|------|------|------|
| 短期记忆 | deque（内存） | 最近 3 章完整内容 | 3 章 |
| 长期记忆 | FAISS 向量索引 | 语义检索历史章节 | 无限 |
| 结构化记忆 | JSON 文件 | 角色/世界观/时间线/伏笔 | 无限 |
| 分层摘要 | 内存 + 定期持久化 | 每 10 章压缩为一个 Arc 摘要 | 10 章/Arc |

### 记忆注入策略

每次新章节生成时，自动注入：
1. **前章摘要**（短期记忆）
2. **相关历史片段**（长期记忆 RAG 检索 top-5）
3. **当前角色状态**（结构化记忆）
4. **正式时间线**（结构化记忆）
5. **未回收伏笔**（结构化记忆）

---

## ⚙️ 配置说明

### LLM 模型选择

支持任何 OpenAI 兼容 API：

| 提供商 | API Base | 推荐模型 |
|--------|----------|----------|
| OpenAI | `https://api.openai.com/v1` | gpt-4o-mini, gpt-4o |
| DeepSeek | `https://api.deepseek.com/v1` | deepseek-chat |
| Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | qwen-plus, qwen-max |
| Claude | (via proxy) | claude-3-5-sonnet |
| Gemini | (via proxy) | gemini-pro |
| 本地 | `http://localhost:1234/v1` | qwen, llama |

详见 [docs/MODELS.md](docs/MODELS.md)

### 关键参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `CHAPTER_MIN_WORDS` | 2000 | 每章最小字数（中文） |
| `SCENE_TARGET_WORDS` | 800 | 每场景目标字数 |
| `MULTI_VERSION_COUNT` | 1 | 每章生成版本数（1=单版本） |
| `LLM_TIMEOUT_SECONDS` | 90 | LLM 调用超时 |
| `FAST_TEST_MODE` | false | 快速测试模式（跳过增强层） |

---

## 🛠️ 开发指南

### 本地开发

```bash
# 克隆仓库
git clone https://github.com/liu020800/longfiction-ai.git
cd longfiction-ai

# 创建虚拟环境
python -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
pip install pytest black flake8 mypy

# 启动开发服务器
python main.py
```

### 启用 CI/CD

CI/CD workflow 文件位于 `docs/workflows-reference/`（不是 `.github/workflows/`，
因为推送到 `.github/workflows/` 需要 GitHub PAT 的 `workflow` 权限）。

要启用：

```bash
# 方式 1：复制到标准位置（需要 workflow 权限的 PAT）
cp docs/workflows-reference/*.yml .github/workflows/
git add .github/workflows/
git commit -m "ci: enable GitHub Actions"
git push

# 方式 2：通过 GitHub Web UI 上传
# 在 GitHub 仓库页面 → Actions → set up a workflow yourself
# 复制 docs/workflows-reference/ 中的内容

# 方式 3：直接使用 GitHub CLI（需要 gh auth login 并有 workflow 权限）
gh workflow enable ci.yml
```

包含的 workflow：

- `ci.yml` - 基础 CI 检查
- `tests.yml` - pytest 测试运行
- `lint.yml` - black/flake8/mypy/isort 代码质量
- `docker.yml` - Docker 镜像构建
- `docs.yml` - GitHub Pages 文档部署
- `codeql.yml` - 安全分析

### 代码规范

- **格式化**：`black .`
- **Linting**：`flake8 .`
- **类型检查**：`mypy .`
- **测试**：`pytest tests/`

---

## 📚 文档

- [架构设计](docs/ARCHITECTURE.md) - 详细架构说明
- [部署指南](docs/DEPLOYMENT.md) - 生产环境部署
- [API 文档](docs/API.md) - 完整 API 参考
- [Agent 系统](docs/AGENTS.md) - 多智能体协作
- [记忆系统](docs/MEMORY.md) - 三层记忆架构
- [升级方案](docs/UPGRADE_PLAN.md) - 未来路线图
- [贡献指南](CONTRIBUTING.md) - 如何贡献
- [更新日志](CHANGELOG.md) - 版本历史

---

## 🗺️ 路线图

### v1.1（计划中）
- [ ] 流式输出支持（SSE）
- [ ] LLM 调用重试机制
- [ ] 数据库迁移工具完善
- [ ] 前端撤销/重做

### v1.2
- [ ] 风格学习与迁移
- [ ] 多模型路由
- [ ] RAG 2.0 混合检索

### v2.0
- [ ] 强化学习反馈
- [ ] 个性化写作风格
- [ ] 协作编辑（WebSocket）

详见 [docs/UPGRADE_PLAN.md](docs/UPGRADE_PLAN.md)

---

## 🤝 贡献

我们欢迎所有形式的贡献！请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 了解如何参与。

### 贡献者

- [@liu020800](https://github.com/liu020800) - 项目创建者

---

## 📄 许可证

本项目采用 [MIT 许可证](LICENSE)。

---

## 🙏 致谢

- [LiteLLM](https://github.com/BerriAI/litellm) - 统一的 LLM 调用层
- [FAISS](https://github.com/facebookresearch/faiss) - 向量相似度搜索
- [FastAPI](https://github.com/tiangolo/fastapi) - 现代化的 Python Web 框架
- [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) - Python ORM

---

## ⚠️ 安全提示

- **请勿将 `.env` 文件提交到版本控制**
- **请使用强管理员密码**（修改 `ADMIN_PASSWORD`）
- **生产环境请使用 HTTPS**
- **定期轮换 API Key**

---

## 📮 联系方式

- **Issues**: [GitHub Issues](https://github.com/liu020800/longfiction-ai/issues)
- **Discussions**: [GitHub Discussions](https://github.com/liu020800/longfiction-ai/discussions)

---

<div align="center">

**如果这个项目对你有帮助，请给一个 ⭐ Star！**

Made with ❤️ by [@liu020800](https://github.com/liu020800)

</div>
