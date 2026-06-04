#!/usr/bin/env python3
"""P0 修复：补写已生成小说的最后一章。

对 project_state.json 中的最后一章，如果：
- 字数 < 目标字数 × 0.9
- 或内容过短（< 1000字）
- 或末句未以正常标点结尾

调用 LLM 续写补全，更新 content 字段和 word_count。

Usage:
    python3 scripts/extend_last_chapter.py <session_id> [--dry-run] [--target-ratio 0.95]

Example:
    python3 scripts/extend_last_chapter.py f8e1ca1d
"""
import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.llm_router import call_llm, TaskType
from core.word_counter import count_chinese_words

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("extend_last_chapter")

_SENTENCE_ENDERS = set("。！？…）」』】")
_MID_SENTENCE_CHARS = set("，、；：的了着过在是和与或但而就也都不还又才刚")


def looks_truncated(text: str) -> bool:
    if not text:
        return True
    stripped = text.rstrip()
    if not stripped:
        return True
    last = stripped[-1]
    if last in _SENTENCE_ENDERS:
        return False
    if last in _MID_SENTENCE_CHARS:
        return True
    if '一' <= last <= '鿿':
        return True
    return False


EXTEND_PROMPT = """你是资深网文作者。请续写以下章节的剩余内容，让本章完整自然收束。

【要求】
1. 续写内容必须与前文连贯，保持人物性格、语气、节奏
2. 本章是全书的最后一章，必须有：
   - 明确的角色抉择（主角做出不可逆选择）
   - 主题落点（回应全书核心问题）
   - 情感收束（情感线在最后一刻有落点）
3. 续写约 {target_words} 字
4. 禁止使用元说明、禁止引用指令、禁止提示词泄漏
5. 末段必须以"。"或"！"或"？"结尾，给读者完整感

【上一章的标题和目标】
{title}
{goal}

【上一章的意图】
{intent}

【已有正文（最后 1500 字）】
{content_tail}

【请续写】
"""


async def extend_last_chapter(session_id: str, dry_run: bool = False, target_ratio: float = 0.95) -> dict:
    base_dir = Path("data/sessions") / session_id
    state_path = base_dir / "project_state.json"
    if not state_path.exists():
        logger.error(f"project_state.json not found for session {session_id}")
        return {"extended": False, "error": "not found"}

    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    chapters = state.get("generated_chapters", [])
    if not chapters:
        return {"extended": False, "error": "no chapters"}

    last_ch = chapters[-1]
    last_idx = len(chapters) - 1
    target_chapters = state.get("target_chapters") or len(chapters)
    target_words = state.get("words_per_chapter") or 2000

    # 末章特别要求：target × 1.2
    if last_idx == target_chapters - 1:
        target_words = int(target_words * 1.2)
    else:
        # 中间章节但被识别为"末章"（章节数不够）
        target_words = int(target_words * 1.0)

    current_wc = count_chinese_words(last_ch.get("content", ""))
    target_wc = int(target_words * target_ratio)

    needs_extension = current_wc < target_wc or looks_truncated(last_ch.get("content", ""))
    if not needs_extension:
        logger.info(f"Last chapter already meets requirements ({current_wc} words, target {target_wc})")
        return {"extended": False, "current_wc": current_wc, "target_wc": target_wc}

    needed_words = max(200, target_wc - current_wc)
    logger.info(f"Last chapter needs extension: {current_wc} -> ~{target_wc} words (need +{needed_words})")

    if dry_run:
        logger.info("DRY RUN - not making changes")
        return {"extended": False, "current_wc": current_wc, "target_wc": target_wc, "would_extend": needed_words}

    content = last_ch.get("content", "")
    title = last_ch.get("title", "")
    intent = last_ch.get("intent", {})
    if not isinstance(intent, dict):
        intent = {}
    goal = intent.get("must_advance", "")
    if not goal:
        goal = "完成全书高潮与角色抉择"

    prompt = EXTEND_PROMPT.format(
        title=title,
        goal=goal,
        intent=str(intent)[:300],
        content_tail=content[-1500:],
        target_words=needed_words,
    )

    try:
        continuation = await call_llm(
            TaskType.WRITE,
            prompt,
            system="你是一个资深网文作者，擅长收束高潮章节。",
            temperature=0.7,
            max_tokens=int(needed_words * 3.5 + 200),
        )
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return {"extended": False, "error": str(e)}

    if not continuation or count_chinese_words(continuation) < 50:
        logger.error("LLM returned empty/short continuation")
        return {"extended": False, "error": "empty continuation"}

    # 提取 continuation 中从第一个中文字符开始的内容
    cont = continuation.strip()
    first_cjk = None
    for i, ch in enumerate(cont):
        if '一' <= ch <= '鿿':
            first_cjk = i
            break
    if first_cjk is not None and first_cjk > 0:
        cont = cont[first_cjk:]

    # Strip any leaked instructions
    cont = _strip_leaked_instructions(cont)

    # 拼接
    new_content = content.rstrip() + "\n" + cont
    new_wc = count_chinese_words(new_content)
    logger.info(f"After extension: {new_wc} words (was {current_wc}, added {new_wc-current_wc})")

    # 更新 last_ch
    last_ch["content"] = new_content
    last_ch["word_count"] = new_wc

    # 保存
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {state_path}")

    # 同步更新 structured_memory.json 中的 chapter_summaries[-1]
    mem_path = base_dir / "structured_memory.json"
    if mem_path.exists():
        with open(mem_path, "r", encoding="utf-8") as f:
            mem = json.load(f)
        summaries = mem.get("chapter_summaries", [])
        if summaries:
            # 取最后一章 summary
            last_summary = summaries[-1]
            if isinstance(last_summary, dict):
                last_summary["summary"] = new_content[:500] + "..."  # 更新摘要
                last_summary["observations"]["state_summary"] = new_content[:1500] + "..."
        with open(mem_path, "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
        logger.info(f"Updated {mem_path}")

    return {"extended": True, "old_wc": current_wc, "new_wc": new_wc, "target_wc": target_wc}


def _strip_leaked_instructions(text: str) -> str:
    """简单剥离泄漏的指令式行"""
    patterns = [
        r'出场人物[：:].*',
        r'推动冲突变化.*',
        r'本章落点.*',
        r'场景\d+[（(]约\d+字[）)].*',
    ]
    for p in patterns:
        text = re.sub(p, '', text)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="Extend the last chapter of a project")
    parser.add_argument("session_id", help="Session ID")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--target-ratio", type=float, default=0.95, help="Target word count as ratio of intended (default 0.95)")
    args = parser.parse_args()

    result = asyncio.run(extend_last_chapter(args.session_id, dry_run=args.dry_run, target_ratio=args.target_ratio))
    logger.info(f"Result: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
