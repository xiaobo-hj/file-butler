"""Upload page queries and metadata registration."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

from file_butler_server.core.current_user import CURRENT_USER_ID
from file_butler_server.core.database import connect_database


STATUS_LABELS = {
    "uploaded": "已上传",
    "analyzing": "解析中",
    "suggested": "已生成建议",
    "organized": "已整理",
    "indexed": "已索引",
    "error": "失败",
}

STATUS_PROGRESS = {
    "uploaded": 18,
    "analyzing": 62,
    "suggested": 100,
    "organized": 100,
    "indexed": 100,
    "error": 100,
}


def get_upload_page(
    database_path: str | Path | None = None,
    user_id: str = CURRENT_USER_ID,
) -> dict[str, Any]:
    with connect_database(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, display_name, size_bytes, status, created_at
            FROM files
            WHERE user_id = ?
            ORDER BY created_at DESC, id ASC
            LIMIT 20
            """,
            (user_id,),
        ).fetchall()

    return {
        "queue": [_format_upload_row(row) for row in rows],
        "hint": "提示：你可以继续上传，FileButler 会把每个文件转成待确认建议。",
    }


def register_upload_metadata(
    *,
    file_name: str,
    size_bytes: int,
    mime_type: str | None,
    database_path: str | Path | None = None,
    user_id: str = CURRENT_USER_ID,
) -> dict[str, Any]:
    file_id = f"file-{uuid.uuid4()}"
    upload_path = f"临时上传区/{file_name}"

    try:
        with connect_database(database_path) as connection:
            connection.execute(
                """
                INSERT INTO files (
                  id,
                  user_id,
                  original_path,
                  current_path,
                  display_name,
                  mime_type,
                  size_bytes,
                  status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    user_id,
                    upload_path,
                    upload_path,
                    file_name,
                    mime_type,
                    max(size_bytes, 0),
                    "uploaded",
                ),
            )
    except sqlite3.IntegrityError as error:
        raise ValueError("当前用户不存在，或文件路径已存在。") from error

    return {
        "id": file_id,
        "fileName": file_name,
        "sizeLabel": _format_size(size_bytes),
        "progress": STATUS_PROGRESS["uploaded"],
        "status": STATUS_LABELS["uploaded"],
        "tone": "default",
    }


def _format_upload_row(row: sqlite3.Row) -> dict[str, Any]:
    status = row["status"]
    return {
        "id": row["id"],
        "fileName": row["display_name"],
        "sizeLabel": _format_size(row["size_bytes"]),
        "progress": STATUS_PROGRESS.get(status, 0),
        "status": STATUS_LABELS.get(status, status),
        "tone": _status_tone(status),
    }


def _status_tone(status: str) -> str:
    if status in {"suggested", "organized", "indexed"}:
        return "success"
    if status == "analyzing":
        return "processing"
    if status == "error":
        return "error"
    return "default"


def _format_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return "0 KB"
    if size_bytes < 1024 * 1024:
        return f"{round(size_bytes / 1024)} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"
