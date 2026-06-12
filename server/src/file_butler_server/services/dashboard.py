"""Dashboard queries for the File Butler overview page."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from file_butler_server.core.current_user import CURRENT_USER_ID
from file_butler_server.core.database import connect_database


SUGGESTION_STATUS_LABELS = {
    "pending": "待确认",
    "completed": "解析完成",
    "needs_input": "待补充",
}


def get_overview_dashboard(
    database_path: str | Path | None = None,
    user_id: str = CURRENT_USER_ID,
) -> dict[str, Any]:
    """Read the overview dashboard data from SQLite."""

    with connect_database(database_path) as connection:
        return {
            "metrics": _read_metrics(connection, user_id),
            "suggestions": _read_suggestions(connection, user_id),
            "activities": _read_activities(connection, user_id),
            "knowledgePrompt": _read_knowledge_prompt(connection, user_id),
        }


def _read_metrics(connection: sqlite3.Connection, user_id: str) -> list[dict[str, str]]:
    organized_files = connection.execute(
        """
        SELECT COUNT(*)
        FROM files
        WHERE user_id = ?
          AND status IN ('organized', 'indexed')
        """,
        (user_id,),
    ).fetchone()[0]
    recently_created = connection.execute(
        """
        SELECT COUNT(*)
        FROM files
        WHERE user_id = ?
          AND status IN ('organized', 'indexed')
          AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-7 days')
        """,
        (user_id,),
    ).fetchone()[0]
    pending_suggestions = connection.execute(
        """
        SELECT COUNT(*)
        FROM organization_suggestions
        JOIN files ON files.id = organization_suggestions.file_id
        WHERE files.user_id = ?
          AND organization_suggestions.status IN ('pending', 'completed', 'needs_input')
        """,
        (user_id,),
    ).fetchone()[0]
    expiring_items = connection.execute(
        """
        SELECT COUNT(*)
        FROM reminders
        WHERE user_id = ?
          AND status = 'active'
          AND due_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '+30 days')
        """,
        (user_id,),
    ).fetchone()[0]
    indexed_files = connection.execute(
        """
        SELECT COUNT(DISTINCT file_id)
        FROM knowledge_chunks
        JOIN files ON files.id = knowledge_chunks.file_id
        WHERE files.user_id = ?
        """,
        (user_id,),
    ).fetchone()[0]
    index_health = round((indexed_files / organized_files) * 100) if organized_files else 0

    return [
        {
            "key": "organized_files",
            "label": "已整理文件",
            "value": str(organized_files),
            "trend": f"较上周 +{recently_created}",
            "tone": "success",
        },
        {
            "key": "pending_suggestions",
            "label": "待确认建议",
            "value": str(pending_suggestions),
            "trend": "等待用户确认",
            "tone": "success",
        },
        {
            "key": "expiring_items",
            "label": "即将到期事项",
            "value": str(expiring_items),
            "trend": "30 天内",
            "tone": "success",
        },
        {
            "key": "index_health",
            "label": "知识库索引完成度",
            "value": f"{index_health}%",
            "trend": "索引健康" if index_health >= 80 else "需要补充索引",
            "tone": "success" if index_health >= 80 else "warning",
        },
    ]


def _read_suggestions(connection: sqlite3.Connection, user_id: str) -> list[dict[str, str]]:
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
        LIMIT 3
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
        }
        for row in rows
    ]


def _read_activities(connection: sqlite3.Connection, user_id: str) -> list[dict[str, str]]:
    rows = connection.execute(
        """
        SELECT id, payload_json
        FROM audit_logs
        WHERE user_id = ?
        ORDER BY created_at DESC, id ASC
        LIMIT 3
        """,
        (user_id,),
    ).fetchall()

    activities = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        activities.append(
            {
                "id": row["id"],
                "time": payload.get("timeLabel", ""),
                "title": payload.get("title", row["id"]),
                "description": payload.get("description", ""),
            }
        )
    return activities


def _read_knowledge_prompt(connection: sqlite3.Connection, user_id: str) -> dict[str, str]:
    indexed_files = connection.execute(
        """
        SELECT COUNT(DISTINCT knowledge_chunks.file_id)
        FROM knowledge_chunks
        JOIN files ON files.id = knowledge_chunks.file_id
        WHERE files.user_id = ?
        """,
        (user_id,),
    ).fetchone()[0]

    if indexed_files:
        return {
            "title": "知识库可以开始回答问题",
            "description": "试试询问：“我有哪些合同快到期？”",
            "actionLabel": "去问答",
        }

    return {
        "title": "知识库等待索引",
        "description": "上传并确认文件后，FileButler 会建立可问答的资料库。",
        "actionLabel": "上传文件",
    }


def _format_confidence(confidence: float | None) -> str:
    if confidence is None:
        return "-"
    return f"{round(confidence * 100)}%"
