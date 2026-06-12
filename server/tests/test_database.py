import sqlite3
import tempfile
import unittest
from pathlib import Path

from file_butler_server.core.database import SCHEMA_VERSION, connect_database, initialize_database


class DatabaseInitializationTest(unittest.TestCase):
    def test_initialize_database_creates_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "file_butler.db"

            created_path = initialize_database(database_path)

            self.assertEqual(created_path, database_path)
            self.assertTrue(database_path.exists())

            with connect_database(database_path) as connection:
                table_names = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
                    )
                }
                user_version = connection.execute("PRAGMA user_version").fetchone()[0]

            self.assertEqual(user_version, SCHEMA_VERSION)
            self.assertTrue(
                {
                    "users",
                    "files",
                    "file_extractions",
                    "organization_suggestions",
                    "suggestion_actions",
                    "knowledge_chunks",
                    "qa_messages",
                    "qa_citations",
                    "processing_jobs",
                    "reminders",
                    "audit_logs",
                    "schema_comments",
                    "file_search",
                }.issubset(table_names)
            )

    def test_initialize_database_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "file_butler.db"

            initialize_database(database_path)
            initialize_database(database_path)

            with connect_database(database_path) as connection:
                table_count = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE name = 'files'"
                ).fetchone()[0]

            self.assertEqual(table_count, 1)

    def test_connection_enforces_foreign_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "file_butler.db"
            initialize_database(database_path)

            with connect_database(database_path) as connection:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        """
                        INSERT INTO files (
                          id,
                          user_id,
                          original_path,
                          current_path,
                          display_name
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            "file-1",
                            "missing-user",
                            "/tmp/a.pdf",
                            "/tmp/a.pdf",
                            "a.pdf",
                        ),
                    )

    def test_file_search_fts5_table_is_queryable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "file_butler.db"
            initialize_database(database_path)

            with connect_database(database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO file_search (
                      file_id,
                      display_name,
                      summary,
                      plain_text,
                      tags,
                      folder_path
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "file-1",
                        "2025-09-01_房屋租赁合同_张三_李四.pdf",
                        "房屋租赁合同，租期一年。",
                        "月租 5800 元，到期日为 2026-09-30。",
                        "租房 合同 家庭",
                        "家庭 / 房屋租赁",
                    ),
                )

                rows = connection.execute(
                    """
                    SELECT file_id
                    FROM file_search
                    WHERE file_search MATCH ?
                    """,
                    ("房屋租赁",),
                ).fetchall()

            self.assertEqual([row["file_id"] for row in rows], ["file-1"])

    def test_initialize_database_syncs_schema_comments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "file_butler.db"
            initialize_database(database_path)

            with connect_database(database_path) as connection:
                table_comment = connection.execute(
                    """
                    SELECT comment
                    FROM schema_comments
                    WHERE object_type = 'table'
                      AND table_name = 'files'
                      AND column_name = ''
                    """
                ).fetchone()[0]
                column_comment = connection.execute(
                    """
                    SELECT comment
                    FROM schema_comments
                    WHERE object_type = 'column'
                      AND table_name = 'files'
                      AND column_name = 'current_path'
                    """
                ).fetchone()[0]

            self.assertEqual(table_comment, "文件主表，保存文件当前状态、路径和元数据。")
            self.assertEqual(column_comment, "当前真实文件路径。")


if __name__ == "__main__":
    unittest.main()
