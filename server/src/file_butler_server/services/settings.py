"""User settings for the local File Butler server."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from file_butler_server.core.current_user import CURRENT_USER_ID
from file_butler_server.core.database import (
    DEFAULT_STORAGE_ROOT_NAME,
    connect_database,
    default_storage_root_path,
)


def get_storage_root_setting(
    database_path: str | Path | None = None,
    user_id: str = CURRENT_USER_ID,
) -> dict[str, Any]:
    with connect_database(database_path) as connection:
        row = _read_storage_root(connection, user_id)
        if row is None:
            root_path = default_storage_root_path()
            root_path.mkdir(parents=True, exist_ok=True)
            root_id = _ensure_storage_root(connection, user_id, root_path)
            row = _read_storage_root(connection, user_id, root_id)

    return _format_storage_root(row)


def update_storage_root_setting(
    *,
    root_path: str,
    database_path: str | Path | None = None,
    user_id: str = CURRENT_USER_ID,
) -> dict[str, Any]:
    path = Path(root_path).expanduser()
    if not str(path).strip():
        raise ValueError("整理目录不能为空。")
    path.mkdir(parents=True, exist_ok=True)

    with connect_database(database_path) as connection:
        root_id = _ensure_storage_root(connection, user_id, path)
        connection.execute(
            """
            UPDATE storage_roots
            SET root_path = ?,
                display_name = ?,
                access_mode = 'read_write',
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
              AND user_id = ?
            """,
            (str(path), DEFAULT_STORAGE_ROOT_NAME, root_id, user_id),
        )
        row = _read_storage_root(connection, user_id, root_id)

    return _format_storage_root(row)


def _read_storage_root(
    connection: sqlite3.Connection,
    user_id: str,
    root_id: str | None = None,
) -> sqlite3.Row | None:
    if root_id is not None:
        return connection.execute(
            """
            SELECT id, root_path, display_name, access_mode
            FROM storage_roots
            WHERE id = ?
              AND user_id = ?
            """,
            (root_id, user_id),
        ).fetchone()

    return connection.execute(
        """
        SELECT id, root_path, display_name, access_mode
        FROM storage_roots
        WHERE user_id = ?
          AND access_mode = 'read_write'
        ORDER BY created_at ASC, id ASC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()


def _ensure_storage_root(
    connection: sqlite3.Connection,
    user_id: str,
    root_path: Path,
) -> str:
    existing = _read_storage_root(connection, user_id)
    if existing is not None:
        return existing["id"]

    root_id = "root-default"
    connection.execute(
        """
        INSERT INTO storage_roots (id, user_id, root_path, display_name)
        VALUES (?, ?, ?, ?)
        """,
        (root_id, user_id, str(root_path), DEFAULT_STORAGE_ROOT_NAME),
    )
    return root_id


def _format_storage_root(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {
            "id": "",
            "rootPath": "",
            "displayName": DEFAULT_STORAGE_ROOT_NAME,
            "accessMode": "read_write",
        }

    return {
        "id": row["id"],
        "rootPath": row["root_path"],
        "displayName": row["display_name"],
        "accessMode": row["access_mode"],
    }
