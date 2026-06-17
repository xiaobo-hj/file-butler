"""SQLite database bootstrap for the local File Butler server."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from file_butler_server.core.current_user import CURRENT_USER_ID


SCHEMA_VERSION = 4
DEFAULT_DATA_DIR = Path.home() / ".file-butler"
DEFAULT_DATABASE_NAME = "file_butler.db"
DEFAULT_STORAGE_ROOT_NAME = "我的文件整理目录"


DROP_UNUSED_TABLES_SQL = """
PRAGMA foreign_keys = OFF;

DROP TABLE IF EXISTS qa_citations;
DROP TABLE IF EXISTS qa_messages;
DROP TABLE IF EXISTS qa_sessions;
DROP TABLE IF EXISTS processing_jobs;
DROP TABLE IF EXISTS reminders;
DROP TABLE IF EXISTS action_executions;
DROP TABLE IF EXISTS file_versions;
DROP TABLE IF EXISTS knowledge_chunks;
DROP TABLE IF EXISTS schema_comments;
DROP TABLE IF EXISTS file_search;

PRAGMA foreign_keys = ON;
"""


SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS storage_roots (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  root_path TEXT NOT NULL,
  display_name TEXT NOT NULL,
  access_mode TEXT NOT NULL DEFAULT 'read_write',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (user_id, root_path)
);

CREATE TABLE IF NOT EXISTS folders (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  parent_id TEXT REFERENCES folders(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (user_id, path)
);

CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  storage_root_id TEXT REFERENCES storage_roots(id) ON DELETE SET NULL,
  folder_id TEXT REFERENCES folders(id) ON DELETE SET NULL,
  original_path TEXT NOT NULL,
  current_path TEXT NOT NULL,
  display_name TEXT NOT NULL,
  mime_type TEXT,
  size_bytes INTEGER NOT NULL DEFAULT 0,
  checksum_sha256 TEXT,
  status TEXT NOT NULL DEFAULT 'selected',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (user_id, current_path)
);

CREATE TABLE IF NOT EXISTS file_extractions (
  id TEXT PRIMARY KEY,
  file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  extractor TEXT NOT NULL,
  summary TEXT,
  plain_text TEXT,
  structured_fields_json TEXT NOT NULL DEFAULT '{}',
  confidence REAL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS tags (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  color TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS file_tags (
  file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  PRIMARY KEY (file_id, tag_id)
);

CREATE TABLE IF NOT EXISTS organization_suggestions (
  id TEXT PRIMARY KEY,
  file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  reason TEXT NOT NULL,
  confidence REAL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_by TEXT NOT NULL DEFAULT 'agent',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS suggestion_actions (
  id TEXT PRIMARY KEY,
  suggestion_id TEXT NOT NULL REFERENCES organization_suggestions(id) ON DELETE CASCADE,
  action_type TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending',
  user_decision_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id TEXT PRIMARY KEY,
  user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_storage_roots_user_id ON storage_roots(user_id);
CREATE INDEX IF NOT EXISTS idx_folders_user_path ON folders(user_id, path);
CREATE INDEX IF NOT EXISTS idx_files_user_status ON files(user_id, status);
CREATE INDEX IF NOT EXISTS idx_files_user_current_path ON files(user_id, current_path);
CREATE INDEX IF NOT EXISTS idx_files_checksum ON files(checksum_sha256);
CREATE INDEX IF NOT EXISTS idx_file_extractions_file_id ON file_extractions(file_id);
CREATE INDEX IF NOT EXISTS idx_tags_user_name ON tags(user_id, name);
CREATE INDEX IF NOT EXISTS idx_suggestions_file_status
  ON organization_suggestions(file_id, status);
CREATE INDEX IF NOT EXISTS idx_suggestion_actions_status
  ON suggestion_actions(suggestion_id, status);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id);

PRAGMA user_version = 4;
"""


class FileButlerConnection(sqlite3.Connection):
    """SQLite connection that closes when used as a context manager."""

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()
        return False


def default_database_path() -> Path:
    """Return the default local database path for a user deployment."""

    return default_data_dir() / DEFAULT_DATABASE_NAME


def connect_database(database_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with File Butler's required connection settings."""

    path = Path(database_path) if database_path is not None else default_database_path()
    connection = sqlite3.connect(path, factory=FileButlerConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path: str | Path | None = None) -> Path:
    """Create or update the local SQLite database."""

    path = Path(database_path) if database_path is not None else default_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with connect_database(path) as connection:
        connection.executescript(DROP_UNUSED_TABLES_SQL)
        connection.executescript(SCHEMA_SQL)
        if database_path is None:
            _ensure_single_user_defaults(connection)

    return path


def _ensure_single_user_defaults(connection: sqlite3.Connection) -> None:
    storage_root = default_storage_root_path()
    storage_root.mkdir(parents=True, exist_ok=True)
    connection.execute(
        """
        INSERT OR IGNORE INTO users (id, display_name)
        VALUES (?, ?)
        """,
        (CURRENT_USER_ID, "本机用户"),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO storage_roots (id, user_id, root_path, display_name)
        VALUES (?, ?, ?, ?)
        """,
        ("root-default", CURRENT_USER_ID, str(storage_root), DEFAULT_STORAGE_ROOT_NAME),
    )


def default_data_dir() -> Path:
    return Path(os.environ.get("FILE_BUTLER_DATA_DIR", DEFAULT_DATA_DIR)).expanduser()


def default_analysis_dir() -> Path:
    return default_data_dir() / "analysis"


def default_upload_dir() -> Path:
    return default_analysis_dir()


def default_storage_root_path() -> Path:
    return Path(os.environ.get("FILE_BUTLER_STORAGE_ROOT", default_data_dir() / "storage")).expanduser()
