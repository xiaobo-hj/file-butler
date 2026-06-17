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
            self.assertEqual(
                {
                    "audit_logs",
                    "file_extractions",
                    "file_tags",
                    "files",
                    "folders",
                    "organization_suggestions",
                    "sqlite_sequence",
                    "storage_roots",
                    "suggestion_actions",
                    "tags",
                    "users",
                }
                & table_names,
                {
                    "audit_logs",
                    "file_extractions",
                    "file_tags",
                    "files",
                    "folders",
                    "organization_suggestions",
                    "storage_roots",
                    "suggestion_actions",
                    "tags",
                    "users",
                },
            )
            self.assertFalse(
                {
                    "action_executions",
                    "file_search",
                    "file_versions",
                    "knowledge_chunks",
                    "processing_jobs",
                    "qa_citations",
                    "qa_messages",
                    "qa_sessions",
                    "reminders",
                    "schema_comments",
                }
                & table_names
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

    def test_initialize_database_drops_unused_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "file_butler.db"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute("CREATE TABLE reminders (id TEXT PRIMARY KEY)")
                connection.execute("CREATE TABLE schema_comments (id TEXT PRIMARY KEY)")
                connection.execute(
                    "CREATE VIRTUAL TABLE file_search USING fts5(file_id, display_name)"
                )
                connection.commit()
            finally:
                connection.close()

            initialize_database(database_path)

            with connect_database(database_path) as connection:
                rows = connection.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type IN ('table', 'virtual table')
                    """
                ).fetchall()

            table_names = {row["name"] for row in rows}
            self.assertFalse({"reminders", "schema_comments", "file_search"} & table_names)


if __name__ == "__main__":
    unittest.main()
