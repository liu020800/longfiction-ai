"""测试数据库迁移脚本。"""
import pytest
import sqlite3
import tempfile
import os
from pathlib import Path
import sys

# 把项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.migrate_db import run_migrations, verify_schema, get_existing_columns


class TestMigrations:
    def test_no_database(self, tmp_path, monkeypatch):
        """当数据库不存在时，不应崩溃。"""
        monkeypatch.chdir(tmp_path)
        report = run_migrations()
        assert report["status"] == "skipped"

    def test_add_missing_column(self, tmp_path, monkeypatch):
        """测试添加缺失的列。"""
        monkeypatch.chdir(tmp_path)
        # 创建数据库
        db_path = tmp_path / "data" / "novel.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE foreshadowing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                description TEXT NOT NULL,
                planted_chapter INTEGER NOT NULL,
                status TEXT DEFAULT 'active'
            )
        """)
        conn.commit()
        conn.close()
        # 修复默认 db_path
        import scripts.migrate_db as m
        monkeypatch.setattr(m, "get_db_path", lambda: db_path)
        report = run_migrations()
        assert report["status"] in ("ok", "partial")
        # close_by_chapter 应该被添加
        conn = sqlite3.connect(str(db_path))
        cols = get_existing_columns(conn, "foreshadowing")
        conn.close()
        assert "close_by_chapter" in cols
        assert "resolved_description" in cols

    def test_already_has_column(self, tmp_path, monkeypatch):
        """测试列已存在时不重复添加。"""
        monkeypatch.chdir(tmp_path)
        db_path = tmp_path / "data" / "novel.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE foreshadowing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                description TEXT NOT NULL,
                close_by_chapter INTEGER,
                resolved_description TEXT DEFAULT ''
            )
        """)
        conn.commit()
        conn.close()
        import scripts.migrate_db as m
        monkeypatch.setattr(m, "get_db_path", lambda: db_path)
        report = run_migrations()
        # 不应该有 add_column 操作
        add_actions = [mig for mig in report.get("migrations", []) if mig.get("action") == "add_column"]
        assert len(add_actions) == 0


class TestVerifySchema:
    def test_no_database(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = verify_schema()
        assert result["status"] == "no_database"

    def test_with_database(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        db_path = tmp_path / "data" / "novel.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE projects (id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()
        import scripts.migrate_db as m
        monkeypatch.setattr(m, "get_db_path", lambda: db_path)
        result = verify_schema()
        assert "projects" in result["tables"]
        # 大多数期望表应该 missing
        assert "characters" in result["missing"]
