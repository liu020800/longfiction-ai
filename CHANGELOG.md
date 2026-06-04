# 更新日志

所有项目的显著变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
并且本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/) 规范。

## [未发布] - Unreleased

### 计划中
- 流式输出支持（SSE）
- LLM 调用重试机制
- 数据库迁移工具完善
- 风格学习与迁移
- 多模型路由

## [1.0.0] - 2026-06-04

### ✨ 新增
- **核心架构**：8 个专业化 Agent 协作系统
  - PlannerAgent - 章节规划、场景拆分
  - WriterAgent - 场景/章节写作、扩写、改写、续写
  - StyleRewriter - AI 痕迹检测与重写
  - CharacterEngine - 角色创建/更新/OOC 检测
  - CharacterStateMachine - 角色状态转移
  - WorldBuilder - 世界观构建
  - ConsistencyChecker - 一致性检查
  - CriticAgent - 章节摘要/读者反馈/版本选择
- **增强子系统**：14 个增强模块
  - EnhancementOrchestrator, AntiResolutionBrake, EventMatrix
  - SuspenseArcManager, RhythmPlanner, QualityScorer
  - PromptEnhancer, StructureEnforcer, ReadbackManager
  - OutlineAdjuster, ProgressManager, EntryModeManager
  - InfoGapManager, EnhancementConfig
- **三层记忆系统**：
  - 短期记忆（deque 缓存最近 3 章）
  - 长期记忆（FAISS 向量索引）
  - 结构化记忆（JSON 持久化）
  - 分层摘要（每 10 章一个 Arc）
- **REST API**：50+ 端点
  - 项目管理：CRUD、初始化、重新生成
  - 章节操作：生成、重生成、续写、改写、片段改写
  - 版本管理：历史、对比、切换
  - 定稿：定稿、取消定稿
  - 一致性：时间线、伏笔、AI 痕迹检测
  - 导出：ZIP、TXT、EPUB
  - 用户系统：注册、登录、认证
- **前端 SPA**（原生 HTML/CSS/JS）
  - 仪表盘、项目工作台、设置、管理后台
  - 暗色/亮色主题
  - 响应式布局
- **配置管理**：
  - Pydantic Settings
  - .env 环境变量
  - 体裁模板（6 种）
- **数据库**：
  - SQLite（默认）
  - PostgreSQL（可选）
  - SQLAlchemy 2.0 ORM
  - Alembic 迁移
- **AI 模型集成**：
  - LiteLLM 统一调用层
  - 5 种角色模型：default/planner/writer/style/check
  - 支持任何 OpenAI 兼容 API
- **安全特性**：
  - JWT 认证
  - bcrypt 密码哈希
  - 角色权限控制

### 🐛 已知问题
- 数据库 schema 迁移偶发失败，需要手动执行 `ALTER TABLE`
- LLM JSON 解析容错能力有限
- 长文本生成时偶发超时（90 秒）
- 字数控制精度待提升

### 📝 文档
- README.md
- LICENSE (MIT)
- CONTRIBUTING.md
- 本 CHANGELOG

---

## 版本说明

- **主版本号**：不兼容的 API 修改
- **次版本号**：向下兼容的功能性新增
- **修订号**：向下兼容的问题修正

[未发布]: https://github.com/liu020800/longfiction-ai/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/liu020800/longfiction-ai/releases/tag/v1.0.0
