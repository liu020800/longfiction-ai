#!/usr/bin/env python3
"""P0 修复：回填已生成小说的脏词标题。

对 project_state.json 中所有标题是脏词（如"主角离开""主动升级"等策划阶段标签）
或与最近 5 章重复的章节，调用 LLM 一次性批量生成新的有意义标题。
不重写正文内容。

Usage:
    python3 scripts/rehash_titles.py <session_id> [--dry-run]

Example:
    python3 scripts/rehash_titles.py f8e1ca1d
    python3 scripts/rehash_titles.py f8e1ca1d --dry-run
"""
import asyncio
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.llm_router import call_llm, TaskType
from agents.planner_agent import PlannerAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("rehash_titles")

DIRTY_TITLE_PATTERNS = PlannerAgent.DIRTY_TITLE_PATTERNS

REHASH_BATCH_PROMPT = """你是一个网文编辑，专精章节命名。请为以下章节重新生成有意义的中文标题。

要求：
1. 标题必须具体反映本章核心事件/转折/新角色（2-5字）
2. 禁止使用抽象阶段词（禁止：主角、中段、长期、战后、终局、一层、敌方、从失败、燃点、反制、败局、远行、重构、深入、新生、余波、裂痕、主动、最终、阶段、真相、情况、问题、局面、目标、压力、选择、代价、牺牲、反转、节点）
3. 标题必须与最近章节标题不重复
4. 只输出新标题本身（每行一个），不要序号不要标点不要引号不要解释

最近章节标题：{recent_titles}

待重命名章节：
{items}

请按顺序输出 {count} 行新标题（每行一个）："""


def is_dirty_title(title: str) -> bool:
    if not title:
        return True
    if len(title) <= 2:
        return True
    for pat in DIRTY_TITLE_PATTERNS:
        if pat in title:
            return True
    return False


def get_chapter_repr(ch: dict, idx: int, total: int) -> str:
    """从已生成章节中提取用于生成标题的上下文（首段 + intent）"""
    title = ch.get("title", "")
    content = ch.get("content", "")
    first_para = content[:200].replace('\n', ' ').strip() if content else ""
    intent = ch.get("intent", {})
    must_advance = intent.get("must_advance", "") if isinstance(intent, dict) else ""
    if must_advance:
        must_advance = must_advance[:80]
    return f"第{idx+1}章（{idx+1}/{total}）\n当前脏标题：{title}\n开头：{first_para[:120]}\n写作意图：{must_advance}"


async def rehash_titles_batch(session_id: str, dry_run: bool = False) -> dict:
    """读取项目状态，重命名脏词标题，保存。"""
    base_dir = Path("data/sessions") / session_id
    state_path = base_dir / "project_state.json"
    if not state_path.exists():
        logger.error(f"project_state.json not found for session {session_id}")
        return {"changed": 0, "error": "not found"}

    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    chapters = state.get("generated_chapters", [])
    if not chapters:
        logger.error(f"No generated_chapters in {state_path}")
        return {"changed": 0, "error": "no chapters"}

    # 找出所有需要重命名的章节
    to_rehash = []
    for i, ch in enumerate(chapters):
        title = ch.get("title", "")
        if is_dirty_title(title):
            to_rehash.append(i)

    logger.info(f"Found {len(to_rehash)} chapters with dirty titles out of {len(chapters)}")

    if not to_rehash:
        return {"changed": 0, "total": len(chapters)}

    if dry_run:
        logger.info("DRY RUN - not making changes")
        for i in to_rehash[:10]:
            logger.info(f"  Chapter {i+1}: '{chapters[i].get('title', '')}'")
        return {"changed": 0, "total": len(chapters), "would_change": len(to_rehash)}

    # 按批调用 LLM（每批最多 10 章，节省 token）
    BATCH_SIZE = 10
    title_overrides: dict[int, str] = {}

    for batch_start in range(0, len(to_rehash), BATCH_SIZE):
        batch_indices = to_rehash[batch_start:batch_start + BATCH_SIZE]
        recent = [chapters[i].get("title", "") for i in range(max(0, batch_indices[0]-5), batch_indices[0])]
        recent_titles = "、".join(recent) if recent else "无"

        items = []
        for idx in batch_indices:
            items.append(get_chapter_repr(chapters[idx], idx, len(chapters)))

        prompt = REHASH_BATCH_PROMPT.format(
            recent_titles=recent_titles,
            items="\n\n".join(items),
            count=len(batch_indices),
        )

        try:
            result = await call_llm(TaskType.PLAN, prompt, system="你是网文编辑，专精章节命名。", temperature=0.6)
            lines = [l.strip() for l in result.split('\n') if l.strip()]
            # 解析每行
            for k, idx in enumerate(batch_indices):
                if k < len(lines):
                    new_title = lines[k].strip().rstrip("。，！？：、""''")
                    # 移除可能的序号前缀
                    new_title = new_title.lstrip("0123456789.、章第 ")
                    if new_title and not is_dirty_title(new_title) and 2 <= len(new_title) <= 8:
                        title_overrides[idx] = new_title
                        logger.info(f"  Ch {idx+1}: '{chapters[idx].get('title', '')}' -> '{new_title}'")
                    else:
                        logger.warning(f"  Ch {idx+1}: LLM returned dirty title '{lines[k]}', skipping")
        except Exception as e:
            logger.warning(f"Batch rehash failed for chapters {batch_indices[0]+1}-{batch_indices[-1]+1}: {e}")

    if not title_overrides:
        return {"changed": 0, "total": len(chapters)}

    # 应用标题变更
    for idx, new_title in title_overrides.items():
        old = chapters[idx].get("title", "")
        chapters[idx]["title"] = new_title
        logger.info(f"Updated ch {idx+1}: '{old}' -> '{new_title}'")

    # 同步更新 structured_memory.json 中的 chapter_summaries
    mem_path = base_dir / "structured_memory.json"
    if mem_path.exists():
        with open(mem_path, "r", encoding="utf-8") as f:
            mem = json.load(f)
        summaries = mem.get("chapter_summaries", [])
        for idx, new_title in title_overrides.items():
            # chapter_summaries 是按 chapter_index 排序的数组
            for cs in summaries:
                ci = cs.get("chapter")
                if ci is not None and int(ci) == idx:
                    cs["title"] = new_title
                    break
        with open(mem_path, "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
        logger.info(f"Updated {mem_path}")

    # 保存 project_state.json
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {state_path}")

    return {"changed": len(title_overrides), "total": len(chapters)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Rehash dirty chapter titles in a project")
    parser.add_argument("session_id", help="Session ID (e.g. f8e1ca1d)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without modifying files")
    args = parser.parse_args()

    result = asyncio.run(rehash_titles_batch(args.session_id, dry_run=args.dry_run))
    logger.info(f"Result: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
