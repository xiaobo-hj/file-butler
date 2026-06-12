"""Suggestion page queries and decisions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from file_butler_server.core.current_user import CURRENT_USER_ID
from file_butler_server.core.database import connect_database
from file_butler_server.services.dashboard import SUGGESTION_STATUS_LABELS


DECISION_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "later": "pending",
}


def get_suggestions_page(
    database_path: str | Path | None = None,
    user_id: str = CURRENT_USER_ID,
) -> dict[str, Any]:
    with connect_database(database_path) as connection:
        rows = _read_suggestion_rows(connection, user_id)
        selected = _read_suggestion_detail(connection, rows[0]["id"], user_id) if rows else None

    pending_count = sum(1 for row in rows if row["rawStatus"] in {"pending", "needs_input", "completed"})
    return {
        "suggestions": rows,
        "selectedSuggestion": selected,
        "summary": {
            "pendingCount": pending_count,
            "label": f"{pending_count} 条建议待确认",
            "description": "确认后才会执行整理操作",
        },
    }


def decide_suggestion(
    suggestion_id: str,
    decision: str,
    database_path: str | Path | None = None,
    user_id: str = CURRENT_USER_ID,
) -> dict[str, str]:
    if decision not in DECISION_STATUS:
        raise ValueError("未知的建议处理动作。")

    with connect_database(database_path) as connection:
        cursor = connection.execute(
            """
            UPDATE organization_suggestions
            SET status = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
              AND file_id IN (SELECT id FROM files WHERE user_id = ?)
            """,
            (DECISION_STATUS[decision], suggestion_id, user_id),
        )

        if cursor.rowcount == 0:
            raise LookupError("没有找到属于当前用户的整理建议。")

    return {"id": suggestion_id, "status": DECISION_STATUS[decision]}


def _read_suggestion_rows(connection: sqlite3.Connection, user_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
          organization_suggestions.id,
          organization_suggestions.confidence,
          organization_suggestions.status,
          files.display_name AS file_name,
          folders.path AS folder_path
        FROM organization_suggestions
        JOIN files ON files.id = organization_suggestions.file_id
        LEFT JOIN folders ON folders.id = files.folder_id
        WHERE files.user_id = ?
        ORDER BY organization_suggestions.created_at DESC, organization_suggestions.id ASC
        """,
        (user_id,),
    ).fetchall()

    return [
        {
            "id": row["id"],
            "fileName": row["file_name"],
            "folder": row["folder_path"] or "未分类",
            "confidence": _format_confidence(row["confidence"]),
            "status": SUGGESTION_STATUS_LABELS.get(row["status"], row["status"]),
            "rawStatus": row["status"],
        }
        for row in rows
    ]


def _read_suggestion_detail(
    connection: sqlite3.Connection,
    suggestion_id: str,
    user_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT
          organization_suggestions.id,
          organization_suggestions.reason,
          organization_suggestions.confidence,
          organization_suggestions.status,
          files.id AS file_id,
          files.current_path,
          files.display_name,
          files.mime_type,
          files.size_bytes,
          files.created_at,
          folders.path AS folder_path
        FROM organization_suggestions
        JOIN files ON files.id = organization_suggestions.file_id
        LEFT JOIN folders ON folders.id = files.folder_id
        WHERE organization_suggestions.id = ?
          AND files.user_id = ?
        """,
        (suggestion_id, user_id),
    ).fetchone()

    if row is None:
        return None

    actions = _read_action_payloads(connection, suggestion_id)
    extraction = _read_latest_extraction(connection, row["file_id"])
    tags = _read_tags(connection, row["file_id"])
    fields = _parse_json(extraction["structured_fields_json"] if extraction else None)

    return {
        "id": row["id"],
        "fileName": row["display_name"],
        "status": SUGGESTION_STATUS_LABELS.get(row["status"], row["status"]),
        "confidence": _format_confidence(row["confidence"]),
        "currentPath": row["current_path"],
        "suggestedFolder": actions.get("folder") or row["folder_path"] or "未分类",
        "suggestedFileName": actions.get("newFileName") or row["display_name"],
        "fileType": _file_type(row["mime_type"], row["display_name"]),
        "tags": actions.get("tags") or tags,
        "summary": extraction["summary"] if extraction and extraction["summary"] else "",
        "keyInfo": _format_key_info(fields),
        "reason": row["reason"],
        "fileInfo": {
            "originalName": row["display_name"],
            "size": _format_size(row["size_bytes"]),
            "uploadedAt": row["created_at"],
            "type": _file_type(row["mime_type"], row["display_name"]).upper(),
        },
    }


def _read_action_payloads(connection: sqlite3.Connection, suggestion_id: str) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT action_type, payload_json
        FROM suggestion_actions
        WHERE suggestion_id = ?
        """,
        (suggestion_id,),
    ).fetchall()

    result: dict[str, Any] = {}
    for row in rows:
        payload = _parse_json(row["payload_json"])
        if row["action_type"] in {"move", "set_folder"}:
            result["folder"] = payload.get("folderPath") or payload.get("targetPath")
        elif row["action_type"] == "rename":
            result["newFileName"] = payload.get("newFileName")
        elif row["action_type"] == "tag":
            result["tags"] = payload.get("tags", [])
    return result


def _read_latest_extraction(connection: sqlite3.Connection, file_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT summary, structured_fields_json
        FROM file_extractions
        WHERE file_id = ?
        ORDER BY created_at DESC, id ASC
        LIMIT 1
        """,
        (file_id,),
    ).fetchone()


def _read_tags(connection: sqlite3.Connection, file_id: str) -> list[str]:
    rows = connection.execute(
        """
        SELECT tags.name
        FROM file_tags
        JOIN tags ON tags.id = file_tags.tag_id
        WHERE file_tags.file_id = ?
        ORDER BY tags.name ASC
        """,
        (file_id,),
    ).fetchall()
    return [row["name"] for row in rows]


def _format_key_info(fields: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"label": str(key), "value": str(value)}
        for key, value in fields.items()
        if value is not None and str(value) != ""
    ]


def _parse_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _file_type(mime_type: str | None, file_name: str) -> str:
    if mime_type == "application/pdf" or file_name.lower().endswith(".pdf"):
        return "pdf"
    if mime_type and "/" in mime_type:
        return mime_type.split("/", maxsplit=1)[-1]
    return "file"


def _format_confidence(confidence: float | None) -> str:
    if confidence is None:
        return "-"
    return f"{round(confidence * 100)}%"


def _format_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return "0 KB"
    if size_bytes < 1024 * 1024:
        return f"{round(size_bytes / 1024)} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"
