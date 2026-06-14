"""Library page queries for organized files."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from file_butler_server.core.current_user import CURRENT_USER_ID
from file_butler_server.core.database import connect_database
from file_butler_server.services.uploads import STATUS_LABELS


def get_library_page(
    database_path: str | Path | None = None,
    user_id: str = CURRENT_USER_ID,
) -> dict[str, Any]:
    with connect_database(database_path) as connection:
        rows = _read_file_rows(connection, user_id)

    files = [_format_file_row(row) for row in rows]
    folders = sorted({file["folder"] for file in files if file["folder"] != "未分类"})
    statuses = _format_status_filters(files)

    return {
        "summary": _build_summary(files),
        "files": files,
        "filters": {
            "folders": folders,
            "statuses": statuses,
        },
    }


def _read_file_rows(connection: sqlite3.Connection, user_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT
          files.id,
          files.display_name,
          files.current_path,
          files.mime_type,
          files.size_bytes,
          files.status,
          files.updated_at,
          folders.path AS folder_path,
          storage_roots.display_name AS storage_root_name,
          storage_roots.root_path AS storage_root_path,
          (
            SELECT file_extractions.summary
            FROM file_extractions
            WHERE file_extractions.file_id = files.id
            ORDER BY file_extractions.created_at DESC, file_extractions.id ASC
            LIMIT 1
          ) AS summary,
          GROUP_CONCAT(tags.name) AS tag_names
        FROM files
        LEFT JOIN folders ON folders.id = files.folder_id
        LEFT JOIN storage_roots ON storage_roots.id = files.storage_root_id
        LEFT JOIN file_tags ON file_tags.file_id = files.id
        LEFT JOIN tags ON tags.id = file_tags.tag_id
        WHERE files.user_id = ?
        GROUP BY files.id
        ORDER BY files.updated_at DESC, files.created_at DESC, files.id ASC
        """,
        (user_id,),
    ).fetchall()


def _format_file_row(row: sqlite3.Row) -> dict[str, Any]:
    status = row["status"]
    return {
        "id": row["id"],
        "fileName": row["display_name"],
        "folder": row["folder_path"] or "未分类",
        "currentPath": row["current_path"],
        "mimeType": row["mime_type"] or "未知",
        "sizeBytes": row["size_bytes"] or 0,
        "sizeLabel": _format_size(row["size_bytes"]),
        "status": STATUS_LABELS.get(status, status),
        "rawStatus": status,
        "updatedAt": row["updated_at"],
        "storageRoot": row["storage_root_name"] or "临时上传区",
        "storageRootPath": row["storage_root_path"] or "",
        "summary": row["summary"] or "",
        "tags": _split_tags(row["tag_names"]),
        "fileType": _file_type(row["mime_type"], row["display_name"]),
    }


def _build_summary(files: list[dict[str, Any]]) -> dict[str, str]:
    organized_count = sum(1 for file in files if file["rawStatus"] in {"organized", "indexed"})
    indexed_count = sum(1 for file in files if file["rawStatus"] == "indexed")
    folders_count = len({file["folder"] for file in files if file["folder"] != "未分类"})
    total_size = sum(file["sizeBytes"] for file in files)
    return {
        "totalFiles": str(len(files)),
        "organizedFiles": str(organized_count),
        "indexedFiles": str(indexed_count),
        "folders": str(folders_count),
        "totalSize": _format_size(total_size),
    }


def _format_status_filters(files: list[dict[str, Any]]) -> list[dict[str, str]]:
    values = sorted({file["rawStatus"] for file in files})
    return [{"value": value, "label": STATUS_LABELS.get(value, value)} for value in values]


def _split_tags(value: str | None) -> list[str]:
    if not value:
        return []
    return sorted({tag for tag in value.split(",") if tag})


def _file_type(mime_type: str | None, file_name: str) -> str:
    if mime_type == "application/pdf" or file_name.lower().endswith(".pdf"):
        return "PDF"
    if mime_type and "/" in mime_type:
        return mime_type.split("/", maxsplit=1)[-1].upper()
    suffix = Path(file_name).suffix.lstrip(".")
    return suffix.upper() if suffix else "FILE"


def _format_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return "0 KB"
    if size_bytes < 1024 * 1024:
        return f"{round(size_bytes / 1024)} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"
