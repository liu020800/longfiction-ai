from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import os
from core.config import settings
from models.db_models import Base

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'novel.db')}")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=False,
)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
    _run_schema_migrations()


def _run_schema_migrations():
    def _get_columns(table_name: str) -> set[str]:
        try:
            return {column["name"] for column in inspect(engine).get_columns(table_name)}
        except Exception:
            return set()

    inspector = inspect(engine)
    try:
        columns = {column["name"] for column in inspector.get_columns("projects")}
    except Exception:
        return
    foreshadow_cols = _get_columns("foreshadowing")
    character_cols = _get_columns("characters")
    migration_sql = []
    if "title" not in columns:
        migration_sql.append("ALTER TABLE projects ADD COLUMN title VARCHAR(256) DEFAULT ''")
    if "foreshadow_type" not in foreshadow_cols:
        migration_sql.append("ALTER TABLE foreshadowing ADD COLUMN foreshadow_type VARCHAR(32) DEFAULT 'clue'")
    if "trigger_keywords" not in foreshadow_cols:
        migration_sql.append("ALTER TABLE foreshadowing ADD COLUMN trigger_keywords JSON")
    if "payoff_condition" not in foreshadow_cols:
        migration_sql.append("ALTER TABLE foreshadowing ADD COLUMN payoff_condition TEXT DEFAULT ''")
    if "source_excerpt" not in foreshadow_cols:
        migration_sql.append("ALTER TABLE foreshadowing ADD COLUMN source_excerpt TEXT DEFAULT ''")
    if "close_by_chapter" not in foreshadow_cols:
        migration_sql.append("ALTER TABLE foreshadowing ADD COLUMN close_by_chapter INTEGER")
    if "voice" not in character_cols:
        migration_sql.append("ALTER TABLE characters ADD COLUMN voice JSON")
    if migration_sql:
        with engine.begin() as conn:
            for sql in migration_sql:
                try:
                    conn.execute(text(sql))
                except Exception as e:
                    message = str(e).lower()
                    if "duplicate column" not in message and "already exists" not in message:
                        raise


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Session:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
