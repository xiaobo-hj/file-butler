"""File analysis page queries and registration."""

from __future__ import annotations

import binascii
import hashlib
import json
import mimetypes
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from file_butler_server.core.current_user import CURRENT_USER_ID
from file_butler_server.core.database import connect_database, default_analysis_dir
from file_butler_server.services.agent import OrganizationPlan, build_organization_plan


STATUS_LABELS = {
    "uploaded": "已选择",
    "selected": "已选择",
    "analyzing": "解析中",
    "suggested": "已生成建议",
    "approved": "已确认",
    "organized": "已整理",
    "indexed": "已索引",
    "error": "失败",
}

STATUS_PROGRESS = {
    "uploaded": 18,
    "selected": 18,
    "analyzing": 62,
    "suggested": 100,
    "approved": 100,
    "organized": 100,
    "indexed": 100,
    "error": 100,
}


def get_analysis_page(
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
        "queue": [_format_analysis_row(row) for row in rows],
        "hint": "提示：选择文件后只生成建议，确认前不会放进你的整理目录。",
    }


def get_upload_page(
    database_path: str | Path | None = None,
    user_id: str = CURRENT_USER_ID,
) -> dict[str, Any]:
    return get_analysis_page(database_path, user_id)


def register_analysis_metadata(
    *,
    file_name: str,
    size_bytes: int,
    mime_type: str | None,
    database_path: str | Path | None = None,
    user_id: str = CURRENT_USER_ID,
) -> dict[str, Any]:
    file_id = f"file-{uuid.uuid4()}"
    pending_path = f"待分析区/{file_name}"

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
                    pending_path,
                    pending_path,
                    file_name,
                    mime_type,
                    max(size_bytes, 0),
                    "selected",
                ),
            )
    except sqlite3.IntegrityError as error:
        raise ValueError("当前用户不存在，或文件路径已存在。") from error

    return {
        "id": file_id,
        "fileName": file_name,
        "sizeLabel": _format_size(size_bytes),
        "progress": STATUS_PROGRESS["selected"],
        "status": STATUS_LABELS["selected"],
        "tone": "default",
    }


def register_upload_metadata(
    *,
    file_name: str,
    size_bytes: int,
    mime_type: str | None,
    database_path: str | Path | None = None,
    user_id: str = CURRENT_USER_ID,
) -> dict[str, Any]:
    return register_analysis_metadata(
        file_name=file_name,
        size_bytes=size_bytes,
        mime_type=mime_type,
        database_path=database_path,
        user_id=user_id,
    )


def analyze_selected_file(
    *,
    file_name: str,
    content_base64: str,
    mime_type: str | None,
    database_path: str | Path | None = None,
    user_id: str = CURRENT_USER_ID,
) -> dict[str, Any]:
    file_id = f"file-{uuid.uuid4()}"
    safe_name = _safe_file_name(file_name)
    content = _decode_base64(content_base64)
    checksum = hashlib.sha256(content).hexdigest()
    source_path = _write_analysis_source(file_id, safe_name, content, database_path)
    text_preview = _extract_text_preview(content, mime_type, safe_name)
    plan = build_organization_plan(
        file_name=safe_name,
        mime_type=mime_type,
        text_preview=text_preview,
    )

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
                  checksum_sha256,
                  status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    user_id,
                    str(source_path),
                    str(source_path),
                    safe_name,
                    mime_type,
                    len(content),
                    checksum,
                    "suggested",
                ),
            )
            _persist_agent_outputs(connection, file_id, user_id, plan, text_preview)
    except sqlite3.IntegrityError as error:
        raise ValueError("当前用户不存在，或文件路径已存在。") from error

    return {
        "id": file_id,
        "fileName": safe_name,
        "sizeLabel": _format_size(len(content)),
        "progress": STATUS_PROGRESS["suggested"],
        "status": STATUS_LABELS["suggested"],
        "tone": "success",
        "suggestion": {
            "folder": plan.folder_path,
            "newFileName": plan.new_file_name,
            "confidence": _format_confidence(plan.confidence),
        },
    }


def _format_upload_row(row: sqlite3.Row) -> dict[str, Any]:
    return _format_analysis_row(row)


def upload_and_analyze_file(
    *,
    file_name: str,
    content_base64: str,
    mime_type: str | None,
    database_path: str | Path | None = None,
    user_id: str = CURRENT_USER_ID,
) -> dict[str, Any]:
    return analyze_selected_file(
        file_name=file_name,
        content_base64=content_base64,
        mime_type=mime_type,
        database_path=database_path,
        user_id=user_id,
    )


def analyze_file_path(
    *,
    source_path: str | Path,
    database_path: str | Path | None = None,
    user_id: str = CURRENT_USER_ID,
) -> dict[str, Any]:
    path = Path(source_path).expanduser()
    if not path.exists() or not path.is_file():
        raise ValueError("选择的文件不存在，或不是普通文件。")

    file_id = f"file-{uuid.uuid4()}"
    safe_name = _safe_file_name(path.name)
    content = path.read_bytes()
    checksum = hashlib.sha256(content).hexdigest()
    mime_type = mimetypes.guess_type(safe_name)[0]
    text_preview = _extract_text_preview(content, mime_type, safe_name)
    plan = build_organization_plan(
        file_name=safe_name,
        mime_type=mime_type,
        text_preview=text_preview,
    )

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
                  checksum_sha256,
                  status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    user_id,
                    str(path),
                    str(path),
                    safe_name,
                    mime_type,
                    len(content),
                    checksum,
                    "suggested",
                ),
            )
            _persist_agent_outputs(connection, file_id, user_id, plan, text_preview)
    except sqlite3.IntegrityError as error:
        raise ValueError("当前用户不存在，或文件路径已存在。") from error

    return {
        "id": file_id,
        "fileName": safe_name,
        "sizeLabel": _format_size(len(content)),
        "progress": STATUS_PROGRESS["suggested"],
        "status": STATUS_LABELS["suggested"],
        "tone": "success",
        "suggestion": {
            "folder": plan.folder_path,
            "newFileName": plan.new_file_name,
            "confidence": _format_confidence(plan.confidence),
        },
    }


def _format_analysis_row(row: sqlite3.Row) -> dict[str, Any]:
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
    if status in {"suggested", "approved", "organized", "indexed"}:
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


def _persist_agent_outputs(
    connection: sqlite3.Connection,
    file_id: str,
    user_id: str,
    plan: OrganizationPlan,
    text_preview: str,
) -> None:
    extraction_id = f"extraction-{uuid.uuid4()}"
    suggestion_id = f"suggestion-{uuid.uuid4()}"
    connection.execute(
        """
        INSERT INTO file_extractions (
          id,
          file_id,
          extractor,
          summary,
          plain_text,
          structured_fields_json,
          confidence
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            extraction_id,
            file_id,
            plan.extractor,
            plan.summary,
            text_preview,
            json.dumps(plan.key_info, ensure_ascii=False),
            plan.confidence,
        ),
    )
    connection.execute(
        """
        INSERT INTO organization_suggestions (id, file_id, reason, confidence, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (suggestion_id, file_id, plan.reason, plan.confidence, "pending"),
    )
    actions = [
        ("set_folder", {"folderPath": plan.folder_path}),
        ("rename", {"newFileName": plan.new_file_name}),
        ("tag", {"tags": plan.tags}),
    ]
    connection.executemany(
        """
        INSERT INTO suggestion_actions (id, suggestion_id, action_type, payload_json)
        VALUES (?, ?, ?, ?)
        """,
        [
            (
                f"action-{uuid.uuid4()}",
                suggestion_id,
                action_type,
                json.dumps(payload, ensure_ascii=False),
            )
            for action_type, payload in actions
        ],
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
            file_id,
            "suggestion_created",
            json.dumps(
                {
                    "timeLabel": "刚刚",
                    "title": "已生成整理建议",
                    "description": f"{plan.new_file_name} -> {plan.folder_path}",
                },
                ensure_ascii=False,
            ),
        ),
    )


def _decode_base64(content_base64: str) -> bytes:
    try:
        import base64

        return base64.b64decode(content_base64, validate=True)
    except binascii.Error as error:
        raise ValueError("文件内容不是合法的 base64。") from error


def _write_analysis_source(
    file_id: str,
    file_name: str,
    content: bytes,
    database_path: str | Path | None,
) -> Path:
    analysis_root = Path(database_path).parent / "analysis" if database_path is not None else default_analysis_dir()
    folder = analysis_root / file_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / file_name
    path.write_bytes(content)
    return path


def _extract_text_preview(content: bytes, mime_type: str | None, file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if (mime_type and mime_type.startswith("text/")) or suffix in {".txt", ".md", ".csv", ".json"}:
        return _decode_text(content)[:8000]
    return f"文件名：{file_name}\nMIME 类型：{mime_type or '未知'}\n文件大小：{_format_size(len(content))}"


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def _safe_file_name(file_name: str) -> str:
    cleaned = Path(file_name.replace("\\", "/")).name.strip()
    return cleaned or "upload.bin"


def _format_confidence(confidence: float | None) -> str:
    if confidence is None:
        return "-"
    return f"{round(confidence * 100)}%"
