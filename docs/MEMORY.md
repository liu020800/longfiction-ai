# 记忆系统

本文档介绍 LongFiction-AI 的三层记忆架构与 RAG 检索系统。

## 🧠 概述

长篇网文（100+ 章、200万+ 字）的创作面临的最大挑战是**长程上下文管理**。单次 LLM 调用的上下文窗口有限（通常 8K-128K tokens），但整个故事可能长达数十万 tokens。

LongFiction-AI 采用**三层记忆架构**解决这个问题：

```
┌─────────────────────────────────────────┐
│       短期记忆（Short-Term）            │
│   最近 3 章的完整内容                   │
│   用途: 章节间连续性                    │
│   实现: Python deque                    │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│       长期记忆（Long-Term / FAISS）     │
│   所有已定稿章节的摘要向量               │
│   用途: 语义检索相关内容                │
│   实现: FAISS 向量索引                  │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│       结构化记忆（Structured）          │
│   角色/世界观/时间线/伏笔/剧情弧         │
│   用途: 精确查询和持久化                │
│   实现: JSON 文件                       │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│       分层摘要（Hierarchical Summary）   │
│   每 10 章压缩为一个 Arc 摘要            │
│   用途: 跨章节长程依赖                  │
│   实现: 内存 + 数据库                    │
└─────────────────────────────────────────┘
```

## 💾 短期记忆（ShortTermMemory）

**位置**：`memory/short_term.py`

**数据结构**：
```python
class ShortTermMemory:
    chapters: deque  # 最近 N 章 [(title, content, summary), ...]
    scene_context: str  # 当前场景上下文
```

**默认大小**：3 章

**配置**：
```python
# core/config.py
MEMORY_SHORT_TERM_SIZE = 3
```

**用途**：
- 章节间连续性保证
- 续写时的直接参考
- 改写时的风格对齐

**使用示例**：
```python
memory.add_chapter(title, content, summary)
recent = memory.get_context_for_writer()  # 获取最近 3 章上下文
```

## 🔍 长期记忆（LongTermMemory）

**位置**：`memory/long_term.py`

**实现**：FAISS 向量索引

**数据结构**：
```python
class LongTermMemory:
    index: faiss.Index  # 向量索引
    texts: list[str]    # 原始文本
    metas: list[dict]   # 元数据
```

**嵌入模型**：默认 `text-embedding-3-small`

**写入流程**：
```
1. 章节定稿后
2. 生成摘要的 embedding
3. 写入 FAISS 索引
4. 同时保存原始文本和元数据
```

**检索流程**：
```
1. 用户查询 → embedding
2. FAISS 搜索 top-k
3. 返回相关历史片段
```

**配置**：
```python
# core/config.py
READBACK_MAX_CHARS = 8000       # 最大回读字符数
READBACK_RAG_TOP_K = 10          # 检索 top k
READBACK_RECENT_WINDOW = 5       # 近期窗口
READBACK_COMPRESSED_WINDOW = 30  # 压缩回读窗口
```

## 📋 结构化记忆（StructuredMemory）

**位置**：`memory/structured.py`

**存储**：JSON 文件

**结构**：
```json
{
  "characters": {
    "林远": {
      "goal": "成为最强武者",
      "personality": ["坚韧", "内敛"],
      "status": {
        "power_level": "筑基中期",
        "location": "青云宗"
      },
      "memory": ["拜入青云宗", "习得青云剑法"]
    }
  },
  "world": {
    "cultivation_system": "修炼分九境...",
    "factions": [...],
    "locations": [...]
  },
  "timeline": [
    {
      "chapter": 1,
      "event": "林远拜入青云宗",
      "type": "plot"
    }
  ],
  "chapter_summaries": {
    "1": "林远出身平凡，意外觉醒...",
    "2": "..."
  },
  "plot_arcs": [
    {
      "arc_type": "main",
      "description": "主角成长线",
      "progress": 0.15
    }
  ]
}
```

**用途**：
- 角色状态精确查询
- 事件时间线追踪
- 伏笔状态管理
- 跨章节依赖

## 📚 分层摘要（HierarchicalSummary）

**位置**：`memory/hierarchical_summary.py`

**核心思想**：将长篇小说按章节分组，每组生成一个 Arc 摘要。

**参数**：
```python
chapters_per_arc = 10    # 每 10 章一个 Arc
recent_chapters = 5      # 保留最近 5 章完整内容
```

**结构**：
```
Arc 1 (Ch 1-10):  摘要 + 关键事件
Arc 2 (Ch 11-20): 摘要 + 关键事件
...
Recent: Ch 96-100 完整内容
```

**生成时机**：
- 章节定稿后
- Arc 完成后自动压缩

**使用场景**：
- 生成第 50 章时，自动检索 Arc 1-5 摘要 + Recent 完整内容
- 避免单次注入过多 token

## 🔄 RAG 检索（RAGEngine）

**位置**：`rag/rag_engine.py`

**职责**：在生成新章节时检索相关内容

**检索流程**：
```python
def retrieve(query, top_k=5):
    # 1. 短期记忆
    recent = short_term.get_recent()
    
    # 2. 长期记忆 RAG
    query_embedding = embed(query)
    related = faiss.search(query_embedding, top_k)
    
    # 3. 结构化记忆
    characters = structured.get_active_characters()
    world = structured.get_world()
    timeline = structured.get_recent_events()
    foreshadowing = structured.get_active_foreshadowing()
    
    # 4. 组装上下文
    context = combine(recent, related, characters, world, timeline, foreshadowing)
    
    return context
```

**上下文组装顺序**（优先级从高到低）：
1. 本章创作指导（guidance）
2. 短期记忆（最近 3 章）
3. 角色当前状态
4. 未回收伏笔
5. 最近时间线事件
6. 长期记忆 RAG 结果
7. 角色关系图谱
8. 世界观核心规则

## 📊 记忆注入策略

每次新章节生成时，记忆系统自动注入：

| 信息类型 | 来源 | 字符限制 |
|----------|------|----------|
| 本章创作指导 | 用户输入 | 无 |
| 最近 N 章摘要 | 短期记忆 | 2000 |
| 当前角色状态 | 结构化记忆 | 1000 |
| 未回收伏笔 | 结构化记忆 | 1500 |
| 相关历史片段 | FAISS 检索 top-5 | 2000 |
| 时间线 | 结构化记忆 | 1000 |
| 世界观 | 结构化记忆 | 500 |

**总字符限制**：约 8000 字符（可通过 `READBACK_MAX_CHARS` 配置）

## 🔧 性能优化

### 1. 摘要压缩

定期将老章节压缩为摘要：

```python
# 每 20 章触发一次压缩
if chapter_index % 20 == 0:
    hierarchical_summary.compress(recent_chapters)
```

### 2. 向量索引优化

- FAISS-CPU 已足够大多数场景
- 大规模（>100K 章节）可升级到 FAISS-GPU 或 Milvus
- 嵌入模型选择影响精度

### 3. 缓存层

未来计划：
- LLM 响应缓存（基于 prompt hash）
- Embedding 缓存

## 🐛 已知问题

1. **FAISS 索引丢失**：进程崩溃后需重建
   - 缓解：定期持久化 `faiss_index` 到 `data/sessions/`
2. **嵌入成本**：每次写入都需要调用 embedding API
   - 缓解：批量嵌入
3. **摘要质量依赖 LLM**：摘要质量影响检索精度

## 🔮 未来增强

- [ ] RAG 2.0（混合检索 + 重排序）
- [ ] 多向量索引（不同 embedding 维度）
- [ ] 跨项目记忆共享
- [ ] 用户私有记忆库

## 📚 相关代码

- `memory/memory_system.py` - 统一入口
- `memory/short_term.py` - 短期
- `memory/long_term.py` - 长期
- `memory/structured.py` - 结构化
- `memory/hierarchical_summary.py` - 分层摘要
- `rag/rag_engine.py` - 检索引擎
- `agents/enhancement/readback_manager.py` - 上下文回读管理
