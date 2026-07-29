"""SQLite connection + schema management.

Single source of truth for the artifacts DB path. Anchors to the backend
directory regardless of CWD so the HTTP CRUD router and the LLM's
`create_artifact` tool always hit the same file.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_DEFAULT_DB_DIR = Path.home() / ".disha"
_DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get("DISHA_DB", str(_DEFAULT_DB_DIR / "disha.db")))


def get_connection(workspace: str | None = None) -> sqlite3.Connection:
    if workspace:
        # Resolve to workspace-specific DB path under a hidden folder
        ws_dir = Path(workspace) / ".disha"
        ws_dir.mkdir(parents=True, exist_ok=True)
        db_file = ws_dir / "disha.db"
        conn = sqlite3.connect(str(db_file), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            pass
        
        # Run migrations dynamically on this database
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for version, sql in enumerate(_MIGRATIONS, start=1):
            if version > current:
                try:
                    conn.executescript(sql)
                except sqlite3.OperationalError as e:
                    if "duplicate column name" not in str(e).lower():
                        raise
                conn.execute(f"PRAGMA user_version = {version}")
                conn.commit()
        return conn
    else:
        conn = sqlite3.connect(str(DB_PATH), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            pass
        return conn


# Ordered list of migrations. Index = target user_version. Each migration
# brings the DB from version (i) to version (i+1).
_MIGRATIONS: list[str] = [
    # 0 → 1 : initial schema
    """
    CREATE TABLE IF NOT EXISTS artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        artifact_type TEXT NOT NULL DEFAULT 'note',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # 1 → 2 : typed artifacts
    """
    ALTER TABLE artifacts ADD COLUMN format TEXT NOT NULL DEFAULT 'markdown';
    ALTER TABLE artifacts ADD COLUMN file_path TEXT;
    ALTER TABLE artifacts ADD COLUMN meta TEXT;
    """,
    # 2 → 3 : artifact position / sorting
    """
    ALTER TABLE artifacts ADD COLUMN position INTEGER NOT NULL DEFAULT 0;
    """,
]


def init_db() -> None:
    conn = get_connection()
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for version, sql in enumerate(_MIGRATIONS, start=1):
            if version > current:
                try:
                    conn.executescript(sql)
                except sqlite3.OperationalError as e:
                    if "duplicate column name" not in str(e).lower():
                        raise
                conn.execute(f"PRAGMA user_version = {version}")
                conn.commit()
    finally:
        conn.close()
