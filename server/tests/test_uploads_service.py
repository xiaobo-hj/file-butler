import base64
import tempfile
import unittest
from pathlib import Path

from file_butler_server.core.database import connect_database, initialize_database
from file_butler_server.services.suggestions import decide_suggestion
from file_butler_server.services.uploads import analyze_file_path
from file_butler_server.services.uploads import get_analysis_page, register_analysis_metadata
from file_butler_server.services.uploads import upload_and_analyze_file


class UploadsServiceTest(unittest.TestCase):
    def test_register_analysis_metadata_uses_current_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "file_butler.db"
            initialize_database(database_path)
            with connect_database(database_path) as connection:
                connection.execute("INSERT INTO users (id, display_name) VALUES (?, ?)", ("1", "用户"))

            item = register_analysis_metadata(
                file_name="合同.pdf",
                size_bytes=2048,
                mime_type="application/pdf",
                database_path=database_path,
            )
            page = get_analysis_page(database_path)

        self.assertEqual(item["fileName"], "合同.pdf")
        self.assertEqual(page["queue"][0]["fileName"], "合同.pdf")
        self.assertEqual(page["queue"][0]["status"], "已选择")

    def test_upload_and_approve_moves_file_into_storage_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            database_path = temp_path / "file_butler.db"
            storage_root = temp_path / "storage"
            initialize_database(database_path)
            with connect_database(database_path) as connection:
                connection.execute("INSERT INTO users (id, display_name) VALUES (?, ?)", ("1", "用户"))
                connection.execute(
                    """
                    INSERT INTO storage_roots (id, user_id, root_path, display_name)
                    VALUES (?, ?, ?, ?)
                    """,
                    ("root-1", "1", str(storage_root), "测试归档区"),
                )

            upload = upload_and_analyze_file(
                file_name="租赁合同.txt",
                content_base64=base64.b64encode("这是一份房屋租赁合同。".encode()).decode(),
                mime_type="text/plain",
                database_path=database_path,
            )

            with connect_database(database_path) as connection:
                suggestion_id = connection.execute(
                    "SELECT id FROM organization_suggestions WHERE file_id = ?",
                    (upload["id"],),
                ).fetchone()[0]

            decide_suggestion(suggestion_id, "approve", database_path)

            with connect_database(database_path) as connection:
                row = connection.execute(
                    """
                    SELECT files.current_path, files.status, folders.path AS folder_path
                    FROM files
                    LEFT JOIN folders ON folders.id = files.folder_id
                    WHERE files.id = ?
                    """,
                    (upload["id"],),
                ).fetchone()
                tag_names = [
                    tag["name"]
                    for tag in connection.execute(
                        """
                        SELECT tags.name
                        FROM file_tags
                        JOIN tags ON tags.id = file_tags.tag_id
                        WHERE file_tags.file_id = ?
                        ORDER BY tags.name
                        """,
                        (upload["id"],),
                    ).fetchall()
                ]

            second_result = decide_suggestion(suggestion_id, "approve", database_path)

            with connect_database(database_path) as connection:
                row_after_second_approve = connection.execute(
                    "SELECT current_path, status FROM files WHERE id = ?",
                    (upload["id"],),
                ).fetchone()

            file_exists = Path(row["current_path"]).exists()

            self.assertEqual(row["status"], "organized")
            self.assertEqual(row["folder_path"], "家庭 / 合同")
            self.assertTrue(file_exists)
            self.assertIn("合同", tag_names)
            self.assertEqual(second_result["status"], "approved")
            self.assertEqual(row_after_second_approve["status"], "organized")
            self.assertEqual(row_after_second_approve["current_path"], row["current_path"])

    def test_analyze_file_path_and_approve_moves_original_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            database_path = temp_path / "file_butler.db"
            storage_root = temp_path / "storage"
            source_file = temp_path / "待整理合同.txt"
            source_file.write_text("这是一份房屋租赁合同。", encoding="utf-8")
            initialize_database(database_path)
            with connect_database(database_path) as connection:
                connection.execute("INSERT INTO users (id, display_name) VALUES (?, ?)", ("1", "用户"))
                connection.execute(
                    """
                    INSERT INTO storage_roots (id, user_id, root_path, display_name)
                    VALUES (?, ?, ?, ?)
                    """,
                    ("root-1", "1", str(storage_root), "测试整理目录"),
                )

            analysis = analyze_file_path(
                source_path=source_file,
                database_path=database_path,
            )

            with connect_database(database_path) as connection:
                suggestion_id = connection.execute(
                    "SELECT id FROM organization_suggestions WHERE file_id = ?",
                    (analysis["id"],),
                ).fetchone()[0]

            decide_suggestion(suggestion_id, "approve", database_path)

            with connect_database(database_path) as connection:
                current_path = connection.execute(
                    "SELECT current_path FROM files WHERE id = ?",
                    (analysis["id"],),
                ).fetchone()[0]

            self.assertFalse(source_file.exists())
            self.assertTrue(Path(current_path).exists())
            self.assertTrue(str(current_path).startswith(str(storage_root)))


if __name__ == "__main__":
    unittest.main()
