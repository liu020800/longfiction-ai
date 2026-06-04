"""数据库状态检查脚本。"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def check_database():
    """检查数据库状态。"""
    db_path = Path("data/novel.db")
    if not db_path.exists():
        print("ERROR: database not found")
        return

    conn = sqlite3.connect(str(db_path))
    try:
        # 所有表
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        print(f"=== Tables ({len(tables)}) ===")
        for t in tables:
            print(f"  {t}")

        # foreshadowing schema
        if "foreshadowing" in tables:
            print("\n=== foreshadowing schema ===")
            cursor = conn.execute("PRAGMA table_info(foreshadowing)")
            for row in cursor.fetchall():
                cid, name, type_, notnull, default, pk = row
                print(f"  {name} ({type_}){' PRIMARY KEY' if pk else ''}")

        # 数据行数
        print("\n=== Row counts ===")
        for t in tables:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {t}")
            count = cursor.fetchone()[0]
            print(f"  {t}: {count}")

    finally:
        conn.close()


if __name__ == "__main__":
    check_database()
