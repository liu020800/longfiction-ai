"""数据库迁移脚本。

自动检测并修复数据库 schema 差异。
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def get_db_path() -> Path:
    """获取数据库路径。"""
    return Path("data/novel.db")


def get_existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """获取表的所有列名。"""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def get_existing_tables(conn: sqlite3.Connection) -> set[str]:
    """获取所有表名。"""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    return {row[0] for row in cursor.fetchall()}


def run_migrations() -> dict:
    """运行所有迁移。

    Returns:
        迁移报告
    """
    db_path = get_db_path()
    if not db_path.exists():
        return {"status": "skipped", "reason": "database does not exist"}

    report = {
        "status": "ok",
        "migrations": [],
        "errors": [],
    }

    conn = sqlite3.connect(str(db_path))
    try:
        existing_tables = get_existing_tables(conn)
        logger.info(f"Existing tables: {existing_tables}")

        # === foreshadowing 表迁移 ===
        if "foreshadowing" in existing_tables:
            existing_cols = get_existing_columns(conn, "foreshadowing")
            logger.info(f"foreshadowing columns: {existing_cols}")

            if "close_by_chapter" not in existing_cols:
                try:
                    conn.execute(
                        "ALTER TABLE foreshadowing ADD COLUMN close_by_chapter INTEGER"
                    )
                    conn.commit()
                    report["migrations"].append({
                        "table": "foreshadowing",
                        "action": "add_column",
                        "column": "close_by_chapter",
                    })
                    logger.info("Added close_by_chapter column to foreshadowing")
                except Exception as e:
                    report["errors"].append(f"foreshadowing: {e}")
                    logger.error(f"Migration failed: {e}")

            if "resolved_description" not in existing_cols:
                try:
                    conn.execute(
                        "ALTER TABLE foreshadowing ADD COLUMN resolved_description TEXT DEFAULT ''"
                    )
                    conn.commit()
                    report["migrations"].append({
                        "table": "foreshadowing",
                        "action": "add_column",
                        "column": "resolved_description",
                    })
                    logger.info("Added resolved_description column to foreshadowing")
                except Exception as e:
                    report["errors"].append(f"foreshadowing: {e}")

        # === chapters 表迁移 ===
        if "chapters" in existing_tables:
            existing_cols = get_existing_columns(conn, "chapters")
            if "guidance" not in existing_cols:
                try:
                    conn.execute("ALTER TABLE chapters ADD COLUMN guidance TEXT DEFAULT ''")
                    conn.commit()
                    report["migrations"].append({
                        "table": "chapters",
                        "action": "add_column",
                        "column": "guidance",
                    })
                except Exception as e:
                    report["errors"].append(f"chapters: {e}")

        # === characters 表迁移 ===
        if "characters" in existing_tables:
            existing_cols = get_existing_columns(conn, "characters")
            for col, defn in [
                ("voice", "JSON DEFAULT '{}'"),
                ("memory", "JSON DEFAULT '[]'"),
            ]:
                if col not in existing_cols:
                    try:
                        conn.execute(f"ALTER TABLE characters ADD COLUMN {col} {defn}")
                        conn.commit()
                        report["migrations"].append({
                            "table": "characters",
                            "action": "add_column",
                            "column": col,
                        })
                    except Exception as e:
                        report["errors"].append(f"characters.{col}: {e}")

    finally:
        conn.close()

    if report["errors"]:
        report["status"] = "partial"
    return report


def verify_schema() -> dict:
    """验证当前数据库 schema。"""
    db_path = get_db_path()
    if not db_path.exists():
        return {"status": "no_database"}

    result = {"tables": {}, "missing": []}
    conn = sqlite3.connect(str(db_path))
    try:
        tables = get_existing_tables(conn)
        # 期望的表
        expected_tables = {
            "projects", "characters", "world_settings", "chapters",
            "scenes", "chapter_versions", "timeline_events",
            "plot_arcs", "foreshadowing", "users",
        }
        for t in expected_tables:
            if t in tables:
                cols = get_existing_columns(conn, t)
                result["tables"][t] = sorted(cols)
            else:
                result["missing"].append(t)
    finally:
        conn.close()
    return result


if __name__ == "__main__":
    import json
    report = run_migrations()
    print(json.dumps(report, indent=2, ensure_ascii=False))
