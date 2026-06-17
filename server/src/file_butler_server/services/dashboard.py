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
    "approved": "已确认",
    "rejected": "已拒绝",
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
            "knowledgePrompt": _read_file_prompt(connection, user_id),
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
    analyzed_files = connection.execute(
        """
        SELECT COUNT(*)
        FROM files
        WHERE user_id = ?
          AND status IN ('suggested', 'organized', 'indexed')
        """,
        (user_id,),
    ).fetchone()[0]
    folder_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM folders
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()[0]

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
            "key": "analyzed_files",
            "label": "已分析文件",
            "value": str(analyzed_files),
            "trend": "已生成建议或已整理",
            "tone": "success",
        },
        {
            "key": "folder_count",
            "label": "整理目录",
            "value": str(folder_count),
            "trend": "自动分类目录",
            "tone": "success",
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


def _read_file_prompt(connection: sqlite3.Connection, user_id: str) -> dict[str, str]:
    organized_files = connection.execute(
        """
        SELECT COUNT(*)
        FROM files
        WHERE files.user_id = ?
          AND files.status IN ('organized', 'indexed')
        """,
        (user_id,),
    ).fetchone()[0]

    if organized_files:
        return {
            "title": "文件库可以开始浏览",
            "description": "已整理的文件会集中出现在文件库里。",
            "actionLabel": "去文件库",
            "targetPage": "library",
        }

    return {
        "title": "还没有整理文件",
        "description": "分析并确认文件后，FileButler 会移动到你的整理目录。",
        "actionLabel": "分析文件",
        "targetPage": "upload",
    }


def _format_confidence(confidence: float | None) -> str:
    if confidence is None:
        return "-"
    return f"{round(confidence * 100)}%"
