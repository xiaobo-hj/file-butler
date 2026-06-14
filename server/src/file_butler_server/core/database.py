"""SQLite database bootstrap for the local File Butler server."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from file_butler_server.core.current_user import CURRENT_USER_ID


SCHEMA_VERSION = 2
DEFAULT_DATA_DIR = Path.home() / ".file-butler"
DEFAULT_DATABASE_NAME = "file_butler.db"
DEFAULT_STORAGE_ROOT_NAME = "FileButler 归档区"


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
  status TEXT NOT NULL DEFAULT 'uploaded',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (user_id, current_path)
);

CREATE TABLE IF NOT EXISTS file_versions (
  id TEXT PRIMARY KEY,
  file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  path_at_version TEXT NOT NULL,
  checksum_sha256 TEXT,
  size_bytes INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (file_id, version_number)
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

CREATE TABLE IF NOT EXISTS action_executions (
  id TEXT PRIMARY KEY,
  action_id TEXT NOT NULL REFERENCES suggestion_actions(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  before_state_json TEXT NOT NULL DEFAULT '{}',
  after_state_json TEXT NOT NULL DEFAULT '{}',
  error_message TEXT,
  executed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id TEXT PRIMARY KEY,
  file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  extraction_id TEXT REFERENCES file_extractions(id) ON DELETE SET NULL,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  source_locator_json TEXT NOT NULL DEFAULT '{}',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (file_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS qa_sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS qa_messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES qa_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS qa_citations (
  id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL REFERENCES qa_messages(id) ON DELETE CASCADE,
  file_id TEXT REFERENCES files(id) ON DELETE SET NULL,
  chunk_id TEXT REFERENCES knowledge_chunks(id) ON DELETE SET NULL,
  cited_field TEXT,
  quote TEXT,
  confidence REAL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS processing_jobs (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  file_id TEXT REFERENCES files(id) ON DELETE CASCADE,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  error_message TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  file_id TEXT REFERENCES files(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  due_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
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

CREATE TABLE IF NOT EXISTS schema_comments (
  object_type TEXT NOT NULL CHECK (object_type IN ('table', 'column')),
  table_name TEXT NOT NULL,
  column_name TEXT NOT NULL DEFAULT '',
  comment TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  PRIMARY KEY (object_type, table_name, column_name)
);

CREATE VIRTUAL TABLE IF NOT EXISTS file_search USING fts5(
  file_id UNINDEXED,
  display_name,
  summary,
  plain_text,
  tags,
  folder_path,
  tokenize = 'trigram'
);

CREATE INDEX IF NOT EXISTS idx_storage_roots_user_id ON storage_roots(user_id);
CREATE INDEX IF NOT EXISTS idx_folders_user_path ON folders(user_id, path);
CREATE INDEX IF NOT EXISTS idx_files_user_status ON files(user_id, status);
CREATE INDEX IF NOT EXISTS idx_files_user_current_path ON files(user_id, current_path);
CREATE INDEX IF NOT EXISTS idx_files_checksum ON files(checksum_sha256);
CREATE INDEX IF NOT EXISTS idx_file_versions_file_id ON file_versions(file_id);
CREATE INDEX IF NOT EXISTS idx_file_extractions_file_id ON file_extractions(file_id);
CREATE INDEX IF NOT EXISTS idx_tags_user_name ON tags(user_id, name);
CREATE INDEX IF NOT EXISTS idx_suggestions_file_status
  ON organization_suggestions(file_id, status);
CREATE INDEX IF NOT EXISTS idx_suggestion_actions_status
  ON suggestion_actions(suggestion_id, status);
CREATE INDEX IF NOT EXISTS idx_action_executions_action_id ON action_executions(action_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_file_id ON knowledge_chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_qa_sessions_user_id ON qa_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_qa_messages_session_id ON qa_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_qa_citations_message_id ON qa_citations(message_id);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_status ON processing_jobs(status, job_type);
CREATE INDEX IF NOT EXISTS idx_reminders_user_due_at ON reminders(user_id, due_at, status);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id);

PRAGMA user_version = 2;
"""


SCHEMA_COMMENTS = (
    ("table", "users", "", "用户表。本地版可先只有一个用户，后续支持多用户。"),
    ("column", "users", "id", "用户 ID。"),
    ("column", "users", "display_name", "用户展示名。"),
    ("column", "users", "created_at", "创建时间，UTC ISO 字符串。"),
    ("column", "users", "updated_at", "更新时间，UTC ISO 字符串。"),
    ("table", "storage_roots", "", "用户授权给 FileButler 管理或扫描的文件根目录。"),
    ("column", "storage_roots", "id", "文件根目录 ID。"),
    ("column", "storage_roots", "user_id", "所属用户 ID。"),
    ("column", "storage_roots", "root_path", "本机文件系统根路径。"),
    ("column", "storage_roots", "display_name", "根目录展示名。"),
    ("column", "storage_roots", "access_mode", "访问模式，例如 read_write。"),
    ("column", "storage_roots", "created_at", "创建时间，UTC ISO 字符串。"),
    ("column", "storage_roots", "updated_at", "更新时间，UTC ISO 字符串。"),
    ("table", "folders", "", "FileButler 的逻辑分类目录，不一定等同真实文件夹。"),
    ("column", "folders", "id", "逻辑目录 ID。"),
    ("column", "folders", "user_id", "所属用户 ID。"),
    ("column", "folders", "parent_id", "父目录 ID，用于目录树。"),
    ("column", "folders", "name", "当前目录名。"),
    ("column", "folders", "path", "完整逻辑目录路径，例如 家庭 / 房屋租赁。"),
    ("column", "folders", "created_at", "创建时间，UTC ISO 字符串。"),
    ("column", "folders", "updated_at", "更新时间，UTC ISO 字符串。"),
    ("table", "files", "", "文件主表，保存文件当前状态、路径和元数据。"),
    ("column", "files", "id", "文件 ID。"),
    ("column", "files", "user_id", "所属用户 ID。"),
    ("column", "files", "storage_root_id", "所属文件根目录 ID。"),
    ("column", "files", "folder_id", "所属逻辑目录 ID。"),
    ("column", "files", "original_path", "首次导入或扫描到的原始路径。"),
    ("column", "files", "current_path", "当前真实文件路径。"),
    ("column", "files", "display_name", "当前文件名。"),
    ("column", "files", "mime_type", "文件 MIME 类型。"),
    ("column", "files", "size_bytes", "文件大小，单位字节。"),
    ("column", "files", "checksum_sha256", "文件 SHA-256，用于去重和版本判断。"),
    ("column", "files", "status", "文件状态，例如 uploaded、organized、indexed、error。"),
    ("column", "files", "created_at", "创建时间，UTC ISO 字符串。"),
    ("column", "files", "updated_at", "更新时间，UTC ISO 字符串。"),
    ("table", "file_versions", "", "文件版本表，记录文件路径、大小、hash 的历史版本。"),
    ("column", "file_versions", "id", "文件版本 ID。"),
    ("column", "file_versions", "file_id", "所属文件 ID。"),
    ("column", "file_versions", "version_number", "文件版本号。"),
    ("column", "file_versions", "path_at_version", "该版本对应的文件路径。"),
    ("column", "file_versions", "checksum_sha256", "该版本文件 SHA-256。"),
    ("column", "file_versions", "size_bytes", "该版本文件大小，单位字节。"),
    ("column", "file_versions", "created_at", "版本创建时间，UTC ISO 字符串。"),
    ("table", "file_extractions", "", "文件解析结果表，保存摘要、正文和结构化字段。"),
    ("column", "file_extractions", "id", "解析结果 ID。"),
    ("column", "file_extractions", "file_id", "所属文件 ID。"),
    ("column", "file_extractions", "extractor", "解析器名称，例如 pdf_parser、ocr、llm。"),
    ("column", "file_extractions", "summary", "文件摘要。"),
    ("column", "file_extractions", "plain_text", "从文件中提取的可检索正文。"),
    ("column", "file_extractions", "structured_fields_json", "结构化字段 JSON。"),
    ("column", "file_extractions", "confidence", "解析置信度，0 到 1。"),
    ("column", "file_extractions", "created_at", "解析时间，UTC ISO 字符串。"),
    ("table", "tags", "", "标签字典表。"),
    ("column", "tags", "id", "标签 ID。"),
    ("column", "tags", "user_id", "所属用户 ID。"),
    ("column", "tags", "name", "标签名。"),
    ("column", "tags", "color", "标签颜色。"),
    ("column", "tags", "created_at", "创建时间，UTC ISO 字符串。"),
    ("table", "file_tags", "", "文件和标签的多对多关系表。"),
    ("column", "file_tags", "file_id", "文件 ID。"),
    ("column", "file_tags", "tag_id", "标签 ID。"),
    ("column", "file_tags", "created_at", "打标签时间，UTC ISO 字符串。"),
    ("table", "organization_suggestions", "", "Agent 生成的整理建议表，用户确认前不直接改文件。"),
    ("column", "organization_suggestions", "id", "整理建议 ID。"),
    ("column", "organization_suggestions", "file_id", "建议关联的文件 ID。"),
    ("column", "organization_suggestions", "reason", "Agent 给出建议的原因。"),
    ("column", "organization_suggestions", "confidence", "建议置信度，0 到 1。"),
    ("column", "organization_suggestions", "status", "建议状态，例如 pending、approved、rejected、completed。"),
    ("column", "organization_suggestions", "created_by", "建议创建者，默认 agent。"),
    ("column", "organization_suggestions", "created_at", "创建时间，UTC ISO 字符串。"),
    ("column", "organization_suggestions", "updated_at", "更新时间，UTC ISO 字符串。"),
    ("table", "suggestion_actions", "", "整理建议拆分出的具体动作，例如移动、重命名、打标签。"),
    ("column", "suggestion_actions", "id", "建议动作 ID。"),
    ("column", "suggestion_actions", "suggestion_id", "所属整理建议 ID。"),
    ("column", "suggestion_actions", "action_type", "动作类型，例如 move、rename、tag、index、add_reminder。"),
    ("column", "suggestion_actions", "payload_json", "动作参数 JSON。"),
    ("column", "suggestion_actions", "status", "动作状态，例如 pending、approved、rejected、executed、failed。"),
    ("column", "suggestion_actions", "user_decision_at", "用户确认或拒绝时间。"),
    ("column", "suggestion_actions", "created_at", "创建时间，UTC ISO 字符串。"),
    ("column", "suggestion_actions", "updated_at", "更新时间，UTC ISO 字符串。"),
    ("table", "action_executions", "", "用户确认后实际执行文件操作的记录表。"),
    ("column", "action_executions", "id", "执行记录 ID。"),
    ("column", "action_executions", "action_id", "对应的建议动作 ID。"),
    ("column", "action_executions", "status", "执行状态，例如 success、failed。"),
    ("column", "action_executions", "before_state_json", "执行前状态 JSON，用于回溯。"),
    ("column", "action_executions", "after_state_json", "执行后状态 JSON，用于回溯。"),
    ("column", "action_executions", "error_message", "执行失败原因。"),
    ("column", "action_executions", "executed_at", "执行时间，UTC ISO 字符串。"),
    ("table", "knowledge_chunks", "", "知识库切片表，用于全文检索、语义检索和问答引用。"),
    ("column", "knowledge_chunks", "id", "知识切片 ID。"),
    ("column", "knowledge_chunks", "file_id", "来源文件 ID。"),
    ("column", "knowledge_chunks", "extraction_id", "来源解析结果 ID。"),
    ("column", "knowledge_chunks", "chunk_index", "文件内切片序号。"),
    ("column", "knowledge_chunks", "content", "切片正文。"),
    ("column", "knowledge_chunks", "source_locator_json", "来源定位 JSON，例如页码、时间戳、字段路径。"),
    ("column", "knowledge_chunks", "metadata_json", "检索过滤元数据 JSON。"),
    ("column", "knowledge_chunks", "created_at", "创建时间，UTC ISO 字符串。"),
    ("table", "qa_sessions", "", "知识库问答会话表。"),
    ("column", "qa_sessions", "id", "问答会话 ID。"),
    ("column", "qa_sessions", "user_id", "所属用户 ID。"),
    ("column", "qa_sessions", "title", "会话标题。"),
    ("column", "qa_sessions", "created_at", "创建时间，UTC ISO 字符串。"),
    ("column", "qa_sessions", "updated_at", "更新时间，UTC ISO 字符串。"),
    ("table", "qa_messages", "", "知识库问答消息表。"),
    ("column", "qa_messages", "id", "消息 ID。"),
    ("column", "qa_messages", "session_id", "所属问答会话 ID。"),
    ("column", "qa_messages", "role", "消息角色，例如 user、assistant、system。"),
    ("column", "qa_messages", "content", "消息内容。"),
    ("column", "qa_messages", "created_at", "创建时间，UTC ISO 字符串。"),
    ("table", "qa_citations", "", "问答回答的引用来源表。"),
    ("column", "qa_citations", "id", "引用 ID。"),
    ("column", "qa_citations", "message_id", "引用所属回答消息 ID。"),
    ("column", "qa_citations", "file_id", "引用来源文件 ID。"),
    ("column", "qa_citations", "chunk_id", "引用来源知识切片 ID。"),
    ("column", "qa_citations", "cited_field", "引用的结构化字段名。"),
    ("column", "qa_citations", "quote", "引用片段。"),
    ("column", "qa_citations", "confidence", "引用可信度，0 到 1。"),
    ("column", "qa_citations", "created_at", "创建时间，UTC ISO 字符串。"),
    ("table", "processing_jobs", "", "后台处理任务表，例如上传、解析、索引。"),
    ("column", "processing_jobs", "id", "任务 ID。"),
    ("column", "processing_jobs", "user_id", "所属用户 ID。"),
    ("column", "processing_jobs", "file_id", "关联文件 ID。"),
    ("column", "processing_jobs", "job_type", "任务类型，例如 upload、parse、index。"),
    ("column", "processing_jobs", "status", "任务状态，例如 queued、running、succeeded、failed。"),
    ("column", "processing_jobs", "error_message", "失败原因。"),
    ("column", "processing_jobs", "created_at", "创建时间，UTC ISO 字符串。"),
    ("column", "processing_jobs", "started_at", "开始时间，UTC ISO 字符串。"),
    ("column", "processing_jobs", "finished_at", "结束时间，UTC ISO 字符串。"),
    ("table", "reminders", "", "提醒表，例如合同到期、报销截止、续租确认。"),
    ("column", "reminders", "id", "提醒 ID。"),
    ("column", "reminders", "user_id", "所属用户 ID。"),
    ("column", "reminders", "file_id", "关联文件 ID。"),
    ("column", "reminders", "title", "提醒标题。"),
    ("column", "reminders", "due_at", "到期时间，UTC ISO 字符串。"),
    ("column", "reminders", "status", "提醒状态，例如 active、done、canceled。"),
    ("column", "reminders", "created_at", "创建时间，UTC ISO 字符串。"),
    ("column", "reminders", "updated_at", "更新时间，UTC ISO 字符串。"),
    ("table", "audit_logs", "", "审计日志表，记录关键实体变更和文件操作历史。"),
    ("column", "audit_logs", "id", "审计日志 ID。"),
    ("column", "audit_logs", "user_id", "操作用户 ID。"),
    ("column", "audit_logs", "entity_type", "实体类型，例如 file、tag、knowledge。"),
    ("column", "audit_logs", "entity_id", "关联实体 ID。"),
    ("column", "audit_logs", "event_type", "事件类型，例如 file_archived、tags_added、file_indexed。"),
    ("column", "audit_logs", "payload_json", "事件载荷 JSON，用于展示和追溯。"),
    ("column", "audit_logs", "created_at", "创建时间，UTC ISO 字符串。"),
    ("table", "file_search", "", "SQLite FTS5 全文搜索虚拟表，用于文件名、摘要、正文、标签和目录路径搜索。"),
    ("column", "file_search", "file_id", "对应文件 ID，不参与全文索引。"),
    ("column", "file_search", "display_name", "文件名全文索引内容。"),
    ("column", "file_search", "summary", "摘要全文索引内容。"),
    ("column", "file_search", "plain_text", "正文全文索引内容。"),
    ("column", "file_search", "tags", "标签全文索引内容。"),
    ("column", "file_search", "folder_path", "目录路径全文索引内容。"),
    ("table", "schema_comments", "", "数据库表和字段注释元数据。"),
    ("column", "schema_comments", "object_type", "注释对象类型：table 或 column。"),
    ("column", "schema_comments", "table_name", "被注释的表名。"),
    ("column", "schema_comments", "column_name", "被注释的字段名；表注释固定为空字符串。"),
    ("column", "schema_comments", "comment", "注释内容。"),
    ("column", "schema_comments", "updated_at", "注释同步时间，UTC ISO 字符串。"),
)


def default_database_path() -> Path:
    """Return the default local database path for a user deployment."""

    return default_data_dir() / DEFAULT_DATABASE_NAME


def connect_database(database_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with File Butler's required connection settings."""

    path = Path(database_path) if database_path is not None else default_database_path()
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path: str | Path | None = None) -> Path:
    """Create the local SQLite database and schema if they do not already exist."""

    path = Path(database_path) if database_path is not None else default_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with connect_database(path) as connection:
        connection.executescript(SCHEMA_SQL)
        _sync_schema_comments(connection)
        if database_path is None:
            _ensure_single_user_defaults(connection)

    return path


def _sync_schema_comments(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM schema_comments")
    connection.executemany(
        """
        INSERT INTO schema_comments (object_type, table_name, column_name, comment)
        VALUES (?, ?, ?, ?)
        """,
        SCHEMA_COMMENTS,
    )


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


def default_upload_dir() -> Path:
    return default_data_dir() / "uploads"


def default_storage_root_path() -> Path:
    return Path(os.environ.get("FILE_BUTLER_STORAGE_ROOT", default_data_dir() / "storage")).expanduser()
