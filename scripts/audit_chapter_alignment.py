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


def main() -> int:
    project_id = sys.argv[1] if len(sys.argv) > 1 else ""
    if not project_id:
        print("Usage: python3 scripts/audit_chapter_alignment.py <project_id>")
        return 2

    bad = []
    with SessionLocal() as db:
        chapters = db.query(Chapter).filter(Chapter.project_id == project_id).order_by(Chapter.chapter_index).all()
        for chapter in chapters:
            versions = db.query(ChapterVersion).filter(ChapterVersion.chapter_id == chapter.id).order_by(ChapterVersion.version).all()
            latest = versions[-1] if versions else None
            if not latest:
                continue
            first = first_non_empty_line(latest.content)
            heading_bad = bool(HEADING_RE.match(first))
            keyword_text = f"{chapter.title} {chapter.goal} {chapter.conflict}"
            anchors = [w for w in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}", keyword_text)[:12] if w]
            hits = sum(1 for word in anchors if word in latest.content)
            if heading_bad or (anchors and hits == 0):
                bad.append((chapter.chapter_index + 1, chapter.title, chapter.status, chapter.current_version, first, hits, len(anchors)))

    if not bad:
        print("No obvious chapter alignment issues found.")
        return 0

    print("Potential alignment issues:")
    for chapter_no, title, status, version, first, hits, total in bad:
        print(f"- 第{chapter_no}章《{title}》 status={status} current_version={version} keyword_hits={hits}/{total} first_line={first[:80]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
