#!/usr/bin/env python3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.database import SessionLocal
from models.db_models import Chapter


def main() -> int:
    project_id = sys.argv[1] if len(sys.argv) > 1 else ""
    if not project_id:
        print("Usage: python3 scripts/check_chapter_plan_diversity.py <project_id>")
        return 2

    with SessionLocal() as db:
        chapters = db.query(Chapter).filter(Chapter.project_id == project_id).order_by(Chapter.chapter_index).all()

    if not chapters:
        print(f"No chapters found for project {project_id}")
        return 1

    goals = Counter((chapter.goal or "").strip() for chapter in chapters)
    conflicts = Counter((chapter.conflict or "").strip() for chapter in chapters)
    repeated_goals = [(text, count) for text, count in goals.items() if text and count >= 3]
    repeated_conflicts = [(text, count) for text, count in conflicts.items() if text and count >= 3]

    unique_goal_ratio = len(goals) / len(chapters)
    unique_conflict_ratio = len(conflicts) / len(chapters)
    print(f"chapters={len(chapters)} unique_goals={len(goals)} ({unique_goal_ratio:.2%}) unique_conflicts={len(conflicts)} ({unique_conflict_ratio:.2%})")

    if repeated_goals:
        print("Repeated goals:")
        for text, count in sorted(repeated_goals, key=lambda item: item[1], reverse=True)[:8]:
            print(f"- {count}x {text[:140]}")
    if repeated_conflicts:
        print("Repeated conflicts:")
        for text, count in sorted(repeated_conflicts, key=lambda item: item[1], reverse=True)[:8]:
            print(f"- {count}x {text[:140]}")

    if unique_goal_ratio < 0.75 or unique_conflict_ratio < 0.55 or repeated_goals:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
