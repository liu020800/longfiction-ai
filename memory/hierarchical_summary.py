"""
分层摘要管理器 - 解决长篇小说上下文断裂问题

核心思想：
- 将小说按卷划分（默认10章一卷）
- 每卷生成一个摘要（约500字）
- 保留最近N章的完整内容
- 生成章节时组合所有卷摘要 + 最近章节内容 + 前一章尾巴

参考：幻城科技 ai-novel-generator HierarchicalSummaryManager
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class HierarchicalSummaryManager:
    """管理小说的分层摘要系统

    解决问题：当小说超过N章时，早期章节被完全丢弃，导致伏笔遗忘、角色设定丢失

    方案：
    - 第1-10章 → 第一卷摘要（500字）
    - 第11-20章 → 第二卷摘要（500字）
    - ...
    - 最新5章 → 完整内容
    - 前一章结尾 → 800字原文
    """

    def __init__(
        self,
        project_id: str,
        chapters_per_arc: int = 10,
        recent_chapters: int = 5,
        cache_dir: Optional[Path] = None
    ):
        self.project_id = project_id
        self.chapters_per_arc = chapters_per_arc
        self.recent_chapters = recent_chapters
        self.cache_dir = cache_dir or Path("cache/coherence")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 卷摘要存储 {arc_id: {summary, main_events, character_changes, foreshadowing}}
        self.arc_summaries: Dict[int, Dict] = {}

        self._load_summaries()

    def _normalize_foreshadowing_items(self, items: Optional[List[Any]]) -> List[dict]:
        normalized: List[dict] = []
        for item in items or []:
            if isinstance(item, str):
                cleaned = item.strip()
                if cleaned:
                    normalized.append({"description": cleaned})
                continue
            if isinstance(item, dict):
                description = str(item.get("description", "") or "").strip()
                if not description:
                    continue
                payload = dict(item)
                payload["description"] = description
                normalized.append(payload)
        return normalized

    def _foreshadowing_texts(self, items: Optional[List[Any]]) -> List[str]:
        texts: List[str] = []
        for item in self._normalize_foreshadowing_items(items):
            description = item.get("description", "")
            if description:
                texts.append(description)
        return texts

    def _get_summary_file(self) -> Path:
        return self.cache_dir / f"{self.project_id}_arc_summaries.json"

    def _load_summaries(self) -> None:
        summary_file = self._get_summary_file()
        if not summary_file.exists():
            return
        with open(summary_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for arc_key, arc_data in data.items():
            if arc_key.startswith("arc_"):
                arc_id = int(arc_key.replace("arc_", ""))
                if isinstance(arc_data, dict):
                    arc_data["foreshadowing"] = self._normalize_foreshadowing_items(arc_data.get("foreshadowing"))
                self.arc_summaries[arc_id] = arc_data
        logger.info(f"已加载 {len(self.arc_summaries)} 个卷摘要")

    def _save_summaries(self) -> None:
        summary_file = self._get_summary_file()
        data = {}
        for arc_id, arc_data in self.arc_summaries.items():
            data[f"arc_{arc_id}"] = arc_data
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_arc_id(self, chapter_num: int) -> int:
        return (chapter_num - 1) // self.chapters_per_arc + 1

    def get_context_for_chapter(
        self,
        chapter_num: int,
        all_chapters: List[Dict],
        prev_chapter_tail_chars: int = 800
    ) -> str:
        """获取生成指定章节所需的上下文"""
        if not all_chapters:
            return "【这是第一章，直接开始创作】"

        context_parts = []
        current_arc = self.get_arc_id(chapter_num)

        # 1. 所有前卷摘要
        if current_arc > 1:
            context_parts.append("【前文总览】")
            for arc_id in range(1, current_arc):
                arc_data = self.arc_summaries.get(arc_id)
                if arc_data and arc_data.get("summary"):
                    start = (arc_id - 1) * self.chapters_per_arc + 1
                    end = arc_id * self.chapters_per_arc
                    context_parts.append(f"\n第{start}-{end}章摘要: {arc_data['summary']}")
                    if arc_data.get("main_events"):
                        for event in arc_data["main_events"]:
                            context_parts.append(f"- {event}")
                    if arc_data.get("foreshadowing"):
                        fs_list = self._foreshadowing_texts(arc_data["foreshadowing"])
                        if fs_list:
                            context_parts.append(f"伏笔: {'; '.join(fs_list)}")
            context_parts.append("")

        # 2. 本卷已有章节摘要
        arc_start = current_arc * self.chapters_per_arc - self.chapters_per_arc + 1
        arc_chapters = [
            ch for ch in all_chapters
            if arc_start <= ch.get("chapter_index", 0) + 1 < chapter_num
        ]
        if arc_chapters:
            context_parts.append("【本卷内容】")
            for ch in arc_chapters:
                title = ch.get("title", "")
                summary = ch.get("summary", "")
                idx = ch.get("chapter_index", 0)
                if summary:
                    context_parts.append(f"第{idx+1}章《{title}》: {summary[:200]}")
                elif title:
                    context_parts.append(f"第{idx+1}章《{title}》")
            context_parts.append("")

        # 3. 最近章节：前2章给全文（续写衔接），其余只给摘要（防上下文溢出）
        recent_start = max(0, chapter_num - self.recent_chapters - 1)
        recent_list = [
            ch for ch in all_chapters
            if recent_start <= ch.get("chapter_index", 0) < chapter_num - 1
        ]
        recent_list.sort(key=lambda x: x.get("chapter_index", 0))
        if recent_list:
            full_text_count = 2  # 只对最近2章保留全文，其余用摘要
            context_parts.append(f"【最近{len(recent_list)}章内容】")
            for i, ch in enumerate(recent_list):
                content = ch.get("content", "")
                title = ch.get("title", "")
                idx = ch.get("chapter_index", 0)
                is_recent = (i >= len(recent_list) - full_text_count)
                if is_recent and content and len(content) > 100:
                    # 最近2章：保留全文（截取关键部分，避免过长）
                    if len(content) > 3000:
                        context_parts.append(f"\n第{idx+1}章《{title}》（节选）:")
                        context_parts.append(content[:1500] + "\n...\n" + content[-1200:])
                    else:
                        context_parts.append(f"\n第{idx+1}章《{title}》:")
                        context_parts.append(content)
                elif ch.get("summary"):
                    context_parts.append(f"\n第{idx+1}章《{title}》摘要: {ch['summary'][:300]}")
                elif title:
                    context_parts.append(f"\n第{idx+1}章《{title}》")
            context_parts.append("")

        # 4. 前一章尾部原文 — 已移至 _build_chapter_bridge() 统一管理，此处不再注入
        # 避免与 CHAPTER_DRAFT_PROMPT 的 {previous_ending} 三重重复

        return "\n".join(context_parts)

    def update_arc_summary(
        self,
        arc_id: int,
        summary: str,
        main_events: Optional[List[str]] = None,
        character_changes: Optional[List[str]] = None,
        foreshadowing: Optional[List[Any]] = None
    ) -> None:
        self.arc_summaries[arc_id] = {
            "summary": summary,
            "main_events": main_events or [],
            "character_changes": character_changes or [],
            "foreshadowing": self._normalize_foreshadowing_items(foreshadowing),
        }
        self._save_summaries()
        logger.info(f"已更新第{arc_id}卷摘要")

    def should_generate_arc_summary(self, chapter_num: int) -> bool:
        return chapter_num > 0 and chapter_num % self.chapters_per_arc == 0

    def get_arc_chapters(self, arc_id: int, all_chapters: List[Dict]) -> List[Dict]:
        start = (arc_id - 1) * self.chapters_per_arc + 1
        end = arc_id * self.chapters_per_arc
        return [
            ch for ch in all_chapters
            if start <= ch.get("chapter_index", 0) + 1 <= end
        ]

    def get_summary_stats(self) -> Dict:
        return {
            "total_arcs": len(self.arc_summaries),
            "chapters_per_arc": self.chapters_per_arc,
            "recent_chapters_kept": self.recent_chapters,
            "arc_ids": list(self.arc_summaries.keys())
        }

    def clear_summaries(self) -> None:
        self.arc_summaries = {}
        summary_file = self._get_summary_file()
        if summary_file.exists():
            summary_file.unlink()
