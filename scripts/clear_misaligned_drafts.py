#!/usr/bin/env python3
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.database import SessionLocal
from models.db_models import Chapter, ChapterVersion


HEADING_RE = re.compile(r"^\s*(#{1,6}\s*)?(第[0-9一二三四五六七八九十百千]+章|章节\s*[0-9]+|Chapter\s+\d+)([：:\s].*)?$", re.I)


def first_non_empty_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def is_misaligned(chapter: Chapter, latest: ChapterVersion) -> bool:
    first = first_non_empty_line(latest.content)
    if HEADING_RE.match(first):
        return True
    keyword_text = f"{chapter.title} {chapter.goal} {chapter.conflict}"
    anchors = [w for w in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}", keyword_text)[:12] if w]
    hits = sum(1 for word in anchors if word in latest.content)
    return bool(anchors and hits == 0)


def main() -> int:
    project_id = sys.argv[1] if len(sys.argv) > 1 else ""
    include_finalized = "--include-finalized" in sys.argv
    if not project_id:
        print("Usage: python3 scripts/clear_misaligned_drafts.py <project_id> [--include-finalized]")
        return 2

    cleared = []
    skipped_finalized = []
    with SessionLocal() as db:
        chapters = db.query(Chapter).filter(Chapter.project_id == project_id).order_by(Chapter.chapter_index).all()
        for chapter in chapters:
            latest = db.query(ChapterVersion).filter(ChapterVersion.chapter_id == chapter.id).order_by(ChapterVersion.version.desc()).first()
            if not latest or not is_misaligned(chapter, latest):
                continue
            if chapter.status == "finalized" and not include_finalized:
                skipped_finalized.append(chapter.chapter_index + 1)
                continue
            db.query(ChapterVersion).filter(ChapterVersion.chapter_id == chapter.id).delete(synchronize_session=False)
            chapter.current_version = 0
            chapter.status = "draft"
            cleared.append(chapter.chapter_index + 1)
        db.commit()

    print(f"cleared={cleared}")
    if skipped_finalized:
        print(f"skipped_finalized={skipped_finalized}")
    if cleared:
        state_path = Path("data") / "sessions" / project_id / "project_state.json"
        if state_path.exists():
            import json

            data = json.loads(state_path.read_text(encoding="utf-8"))
            cleared_indices = {idx - 1 for idx in cleared}
            data["generated_chapters"] = [
                chapter for chapter in data.get("generated_chapters", [])
                if int(chapter.get("chapter_index", -1)) not in cleared_indices
            ]
            pending = data.get("pending_chapter_updates", {})
            data["pending_chapter_updates"] = {
                key: value for key, value in pending.items()
                if int(key) not in cleared_indices
            }
            data["finalized_chapters"] = [
                idx for idx in data.get("finalized_chapters", [])
                if int(idx) not in cleared_indices
            ]
            state_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"state_cleaned={state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
