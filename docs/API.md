# API 文档

完整的 REST API 参考。所有端点都以 `/api` 为前缀，认证通过 `Authorization: Bearer <token>` 头。

## 🔐 认证

### 登录

```http
POST /api/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "admin123456"
}
```

**响应**：
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "admin",
    "role": "admin"
  }
}
```

### 注册

```http
POST /api/auth/register
Content-Type: application/json

{
  "username": "newuser",
  "password": "password123",
  "email": "user@example.com"
}
```

### 当前用户

```http
GET /api/auth/me
Authorization: Bearer <token>
```

## 📚 项目管理

### 初始化项目

```http
POST /api/init
Authorization: Bearer <token>
Content-Type: application/json

{
  "outline": "一个普通少年在都市中觉醒神秘系统...",
  "genre": "urban_fantasy",
  "style": "web_novel",
  "target_chapters": 100,
  "words_per_chapter": 2000
}
```

**响应**：
```json
{
  "task_id": "abc123",
  "status": "running",
  "result": {}
}
```

### 项目列表

```http
GET /api/projects
Authorization: Bearer <token>
```

### 项目详情

```http
GET /api/project/{project_id}
Authorization: Bearer <token>
```

### 保存并确认设定

```http
POST /api/project
Authorization: Bearer <token>
Content-Type: application/json

{
  "project_id": "abc123",
  "approved": true
}
```

### 重新生成设定

```http
POST /api/project/regenerate/world
POST /api/project/regenerate/characters
POST /api/project/regenerate/chapters
Authorization: Bearer <token>
Content-Type: application/json

{
  "project_id": "abc123"
}
```

## 📖 章节操作

### 生成章节

```http
POST /api/chapter
Authorization: Bearer <token>
Content-Type: application/json

{
  "task_id": "abc123",
  "chapter_index": 0,
  "multi_version": false,
  "guidance": "本章重点表现主角的内心挣扎",
  "auto_finalize": false
}
```

**响应**：
```json
{
  "task_id": "abc123",
  "chapter_index": 0,
  "content": "...",
  "word_count": 2150,
  "consistency_score": 0.92,
  "quality_scores": {
    "coherence": 8.5,
    "creativity": 7.0,
    "readability": 9.0
  }
}
```

### 重新生成章节

```http
POST /api/chapter/regenerate
Authorization: Bearer <token>
Content-Type: application/json

{
  "task_id": "abc123",
  "chapter_index": 0,
  "guidance": ""
}
```

### 续写章节

```http
POST /api/chapter/continue
Authorization: Bearer <token>
Content-Type: application/json

{
  "task_id": "abc123",
  "chapter_index": 0,
  "guidance": "续写 800 字，引入新角色",
  "target_words": 800
}
```

### 改写章节

```http
POST /api/chapter/revise
Authorization: Bearer <token>
Content-Type: application/json

{
  "task_id": "abc123",
  "chapter_index": 0,
  "guidance": "增加环境描写，减少对话"
}
```

### 片段改写

```http
POST /api/chapter/revise-fragment
Authorization: Bearer <token>
Content-Type: application/json

{
  "task_id": "abc123",
  "chapter_index": 0,
  "fragment": "原文片段...",
  "instruction": "改写这段对话"
}
```

### 定稿章节

```http
POST /api/chapter/finalize
Authorization: Bearer <token>
Content-Type: application/json

{
  "task_id": "abc123",
  "chapter_index": 0
}
```

### 取消定稿

```http
POST /api/chapter/unfinalize
Authorization: Bearer <token>
Content-Type: application/json

{
  "task_id": "abc123",
  "chapter_index": 0
}
```

### 获取章节内容

```http
GET /api/chapter/{task_id}/{chapter_index}
Authorization: Bearer <token>
```

### 批量生成

```http
POST /api/batch-generate
Authorization: Bearer <token>
Content-Type: application/json

{
  "task_id": "abc123",
  "start_chapter": 0,
  "end_chapter": 4,
  "auto_finalize": false
}
```

## 🔄 版本管理

### 版本历史

```http
GET /api/db/chapter/{chapter_id}/versions
Authorization: Bearer <token>
```

### 版本内容

```http
GET /api/db/chapter/{chapter_id}/content/{version}
Authorization: Bearer <token>
```

### 切换版本

```http
POST /api/db/chapter/select-version
Authorization: Bearer <token>
Content-Type: application/json

{
  "chapter_id": 1,
  "version": 2
}
```

### 版本对比

```http
POST /api/db/chapter/compare
Authorization: Bearer <token>
Content-Type: application/json

{
  "chapter_id": 1,
  "version_a": 1,
  "version_b": 2
}
```

## 🔍 一致性控制

### 时间线

```http
GET /api/db/project/{project_id}/timeline
Authorization: Bearer <token>
```

### 伏笔面板

```http
GET /api/db/foreshadow/{project_id}
Authorization: Bearer <token>
```

### 埋设伏笔

```http
POST /api/db/foreshadow/plant
Authorization: Bearer <token>
Content-Type: application/json

{
  "project_id": "abc123",
  "description": "一把神秘的钥匙",
  "foreshadow_type": "item",
  "planted_chapter": 1,
  "close_by_chapter": 50,
  "trigger_keywords": ["钥匙", "古代"]
}
```

### 回收伏笔

```http
POST /api/db/foreshadow/resolve
Authorization: Bearer <token>
Content-Type: application/json

{
  "foreshadow_id": 1,
  "resolved_chapter": 50,
  "resolved_description": "主角用钥匙打开了..."
}
```

## 📤 导出

### ZIP 项目包

```http
GET /api/export/{project_id}
Authorization: Bearer <token>
```

### TXT 导出

```http
GET /api/export/{project_id}/txt
GET /api/export/{project_id}/txt?finalized_only=true
Authorization: Bearer <token>
```

### EPUB 导出

```http
GET /api/export/{project_id}/epub
GET /api/export/{project_id}/epub?finalized_only=true
Authorization: Bearer <token>
```

## 🤖 工具

### AI 痕迹检测

```http
POST /api/ai-detect
Authorization: Bearer <token>
Content-Type: application/json

{
  "content": "要检测的文本..."
}
```

**响应**：
```json
{
  "ai_score": 0.72,
  "matched_patterns": [
    {"pattern": "三选一排比", "matches": 3},
    {"pattern": "心中涌起", "matches": 1}
  ],
  "suggestions": ["使用更具体的动作描写"]
}
```

### 对话分析

```http
POST /api/dialogue-analyze
Authorization: Bearer <token>
Content-Type: application/json

{
  "content": "对话文本..."
}
```

### 风格库

```http
GET /api/styles
Authorization: Bearer <token>
```

### LLM 配置

```http
GET /api/llm-config
PUT /api/llm-config
Authorization: Bearer <token>
```

## 🏥 健康检查

```http
GET /api/health
```

**响应**：
```json
{
  "status": "ok",
  "version": "1.0.0",
  "llm_configured": true
}
```

## 📊 错误码

| 状态码 | 含义 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |
| 503 | LLM 服务不可用 |

**错误响应格式**：
```json
{
  "detail": "错误描述"
}
```

## 🔧 交互式 API 文档

启动服务后访问：
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
