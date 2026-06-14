"""Suggestion page queries and decisions."""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
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
        if decision == "approve":
            return _approve_and_execute(connection, suggestion_id, user_id)

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

        if decision == "reject":
            connection.execute(
                """
                UPDATE suggestion_actions
                SET status = 'rejected',
                    user_decision_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE suggestion_id = ?
                """,
                (suggestion_id,),
            )

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
        ORDER BY
          CASE organization_suggestions.status
            WHEN 'pending' THEN 0
            WHEN 'needs_input' THEN 1
            WHEN 'completed' THEN 2
            WHEN 'approved' THEN 3
            WHEN 'rejected' THEN 4
            ELSE 5
          END,
          organization_suggestions.created_at DESC,
          organization_suggestions.id ASC
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
        "rawStatus": row["status"],
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
        SELECT summary, plain_text, structured_fields_json
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


def _approve_and_execute(
    connection: sqlite3.Connection,
    suggestion_id: str,
    user_id: str,
) -> dict[str, str]:
    row = connection.execute(
        """
        SELECT
          files.*,
          organization_suggestions.status AS suggestion_status
        FROM organization_suggestions
        JOIN files ON files.id = organization_suggestions.file_id
        WHERE organization_suggestions.id = ?
          AND files.user_id = ?
        """,
        (suggestion_id, user_id),
    ).fetchone()
    if row is None:
        raise LookupError("没有找到属于当前用户的整理建议。")

    if row["suggestion_status"] == "approved":
        return {"id": suggestion_id, "status": "approved"}
    if row["suggestion_status"] == "rejected":
        raise ValueError("已拒绝的建议不能直接确认。")

    action_payloads = _read_action_payloads(connection, suggestion_id)
    folder_path = action_payloads.get("folder") or "未分类"
    new_file_name = _safe_file_name(action_payloads.get("newFileName") or row["display_name"])
    tags = [str(tag) for tag in action_payloads.get("tags", []) if str(tag).strip()]
    root = _read_writable_storage_root(connection, user_id)

    if root is not None:
        folder_id = _ensure_folder(connection, user_id, folder_path)
        target_path = _build_target_path(Path(root["root_path"]), folder_path, new_file_name)
        source_path = Path(row["current_path"])
        before_state = {
            "path": row["current_path"],
            "displayName": row["display_name"],
            "folderId": row["folder_id"],
            "storageRootId": row["storage_root_id"],
        }

        if source_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path = _dedupe_path(target_path)
            shutil.move(str(source_path), str(target_path))
            current_path = str(target_path)
        else:
            current_path = row["current_path"]

        _record_file_version(connection, row)
        connection.execute(
            """
            UPDATE files
            SET storage_root_id = ?,
                folder_id = ?,
                current_path = ?,
                display_name = ?,
                status = 'organized',
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (root["id"], folder_id, current_path, new_file_name, row["id"]),
        )
        _record_action_executions(connection, suggestion_id, before_state, {"path": current_path})
    else:
        connection.execute(
            """
            UPDATE files
            SET display_name = ?,
                status = 'organized',
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (new_file_name, row["id"]),
        )

    _apply_tags(connection, user_id, row["id"], tags)
    _refresh_file_search(connection, row["id"], folder_path, new_file_name, tags)
    connection.execute(
        """
        UPDATE suggestion_actions
        SET status = 'executed',
            user_decision_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE suggestion_id = ?
        """,
        (suggestion_id,),
    )
    connection.execute(
        """
        UPDATE organization_suggestions
        SET status = 'approved',
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (suggestion_id,),
    )
    connection.execute(
        """
        INSERT INTO audit_logs (id, user_id, entity_type, entity_id, event_type, payload_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            f"audit-{uuid.uuid4()}",
            user_id,
            "file",
            row["id"],
            "file_organized",
            json.dumps(
                {
                    "timeLabel": "刚刚",
                    "title": "已整理文件",
                    "description": f"{new_file_name} 移动到 {folder_path}",
                },
                ensure_ascii=False,
            ),
        ),
    )

    return {"id": suggestion_id, "status": "approved"}


def _read_writable_storage_root(connection: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT id, root_path
        FROM storage_roots
        WHERE user_id = ?
          AND access_mode = 'read_write'
        ORDER BY created_at ASC, id ASC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()


def _ensure_folder(connection: sqlite3.Connection, user_id: str, folder_path: str) -> str:
    existing = connection.execute(
        """
        SELECT id
        FROM folders
        WHERE user_id = ?
          AND path = ?
        """,
        (user_id, folder_path),
    ).fetchone()
    if existing is not None:
        return existing["id"]

    folder_id = f"folder-{uuid.uuid4()}"
    name = folder_path.split(" / ")[-1] if folder_path else "未分类"
    connection.execute(
        """
        INSERT INTO folders (id, user_id, parent_id, name, path)
        VALUES (?, ?, ?, ?, ?)
        """,
        (folder_id, user_id, None, name, folder_path),
    )
    return folder_id


def _build_target_path(root_path: Path, folder_path: str, file_name: str) -> Path:
    target = root_path
    for part in folder_path.split(" / "):
        safe_part = _safe_path_part(part)
        if safe_part:
            target = target / safe_part
    return target / _safe_file_name(file_name)


def _dedupe_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError("目标目录里同名文件过多，无法生成安全文件名。")


def _record_file_version(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    connection.execute(
        """
        INSERT INTO file_versions (
          id,
          file_id,
          version_number,
          path_at_version,
          checksum_sha256,
          size_bytes
        )
        VALUES (
          ?,
          ?,
          COALESCE((SELECT MAX(version_number) FROM file_versions WHERE file_id = ?), 0) + 1,
          ?,
          ?,
          ?
        )
        """,
        (
            f"version-{uuid.uuid4()}",
            row["id"],
            row["id"],
            row["current_path"],
            row["checksum_sha256"],
            row["size_bytes"],
        ),
    )


def _record_action_executions(
    connection: sqlite3.Connection,
    suggestion_id: str,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
) -> None:
    action_rows = connection.execute(
        """
        SELECT id
        FROM suggestion_actions
        WHERE suggestion_id = ?
        """,
        (suggestion_id,),
    ).fetchall()
    connection.executemany(
        """
        INSERT INTO action_executions (
          id,
          action_id,
          status,
          before_state_json,
          after_state_json
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                f"execution-{uuid.uuid4()}",
                action["id"],
                "success",
                json.dumps(before_state, ensure_ascii=False),
                json.dumps(after_state, ensure_ascii=False),
            )
            for action in action_rows
        ],
    )


def _apply_tags(
    connection: sqlite3.Connection,
    user_id: str,
    file_id: str,
    tags: list[str],
) -> None:
    for tag in tags:
        tag_name = tag.strip()
        if not tag_name:
            continue
        existing = connection.execute(
            """
            SELECT id
            FROM tags
            WHERE user_id = ?
              AND name = ?
            """,
            (user_id, tag_name),
        ).fetchone()
        tag_id = existing["id"] if existing else f"tag-{uuid.uuid4()}"
        if existing is None:
            connection.execute(
                """
                INSERT INTO tags (id, user_id, name)
                VALUES (?, ?, ?)
                """,
                (tag_id, user_id, tag_name),
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO file_tags (file_id, tag_id)
            VALUES (?, ?)
            """,
            (file_id, tag_id),
        )


def _refresh_file_search(
    connection: sqlite3.Connection,
    file_id: str,
    folder_path: str,
    file_name: str,
    tags: list[str],
) -> None:
    extraction = _read_latest_extraction(connection, file_id)
    connection.execute("DELETE FROM file_search WHERE file_id = ?", (file_id,))
    connection.execute(
        """
        INSERT INTO file_search (file_id, display_name, summary, plain_text, tags, folder_path)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            file_name,
            extraction["summary"] if extraction else "",
            extraction["plain_text"] if extraction else "",
            " ".join(tags),
            folder_path,
        ),
    )


def _safe_file_name(file_name: str) -> str:
    cleaned = Path(file_name.replace("\\", "/")).name.strip()
    return cleaned or "文件"


def _safe_path_part(part: str) -> str:
    return part.replace("/", " ").replace("\\", " ").replace(":", " ").strip()
