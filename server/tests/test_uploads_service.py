import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from file_butler_server.core.database import connect_database, initialize_database
from file_butler_server.services.agent import OrganizationPlan
from file_butler_server.services.suggestions import decide_suggestion
from file_butler_server.services.suggestions import get_suggestions_page
from file_butler_server.services.uploads import analyze_selected_file
from file_butler_server.services.uploads import analyze_file_path
from file_butler_server.services.uploads import get_analysis_page, register_analysis_metadata


class UploadsServiceTest(unittest.TestCase):
    def test_register_analysis_metadata_uses_current_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "file_butler.db"
            initialize_database(database_path)
            with connect_database(database_path) as connection:
                connection.execute(
                    "INSERT INTO users (id, display_name) VALUES (?, ?)",
                    ("1", "用户"),
                )

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

    def test_analyze_path_and_approve_moves_source_file_into_storage_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            database_path = temp_path / "file_butler.db"
            storage_root = temp_path / "storage"
            source_file = temp_path / "租赁合同.txt"
            source_file.write_text("这是一份房屋租赁合同。", encoding="utf-8")
            initialize_database(database_path)
            with connect_database(database_path) as connection:
                connection.execute(
                    "INSERT INTO users (id, display_name) VALUES (?, ?)",
                    ("1", "用户"),
                )
                connection.execute(
                    """
                    INSERT INTO storage_roots (id, user_id, root_path, display_name)
                    VALUES (?, ?, ?, ?)
                    """,
                    ("root-1", "1", str(storage_root), "测试归档区"),
                )

            with patch(
                "file_butler_server.services.uploads.build_organization_plan",
                return_value=OrganizationPlan(
                    summary="租赁合同",
                    folder_path="家庭 / 合同",
                    new_file_name="合同_租赁合同.txt",
                    tags=["合同", "待确认"],
                    key_info={"文件类型": "text/plain"},
                    reason="模型判断属于合同文件",
                    confidence=0.91,
                    extractor="test",
                ),
            ):
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
                row = connection.execute(
                    """
                    SELECT files.current_path, files.status, folders.path AS folder_path
                    FROM files
                    LEFT JOIN folders ON folders.id = files.folder_id
                    WHERE files.id = ?
                    """,
                    (analysis["id"],),
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
                        (analysis["id"],),
                    ).fetchall()
                ]

            second_result = decide_suggestion(suggestion_id, "approve", database_path)

            with connect_database(database_path) as connection:
                row_after_second_approve = connection.execute(
                    "SELECT current_path, status FROM files WHERE id = ?",
                    (analysis["id"],),
                ).fetchone()

            file_exists = Path(row["current_path"]).exists()

            self.assertEqual(row["status"], "organized")
            self.assertEqual(row["folder_path"], "家庭 / 合同")
            self.assertTrue(file_exists)
            self.assertIn("合同", tag_names)
            self.assertEqual(second_result["status"], "approved")
            self.assertEqual(row_after_second_approve["status"], "organized")
            self.assertEqual(row_after_second_approve["current_path"], row["current_path"])

    def test_content_upload_is_rejected_instead_of_copied(self):
        with self.assertRaisesRegex(ValueError, "不再复制上传文件"):
            analyze_selected_file(
                file_name="合同.txt",
                content_base64="5ZCI5ZCM",
                mime_type="text/plain",
            )

    def test_rejected_file_path_can_be_analyzed_again_with_new_suggestion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            database_path = temp_path / "file_butler.db"
            source_file = temp_path / "待整理合同.txt"
            source_file.write_text("这是一份合同。", encoding="utf-8")
            initialize_database(database_path)
            with connect_database(database_path) as connection:
                connection.execute(
                    "INSERT INTO users (id, display_name) VALUES (?, ?)",
                    ("1", "用户"),
                )

            with patch(
                "file_butler_server.services.uploads.build_organization_plan",
                return_value=OrganizationPlan(
                    summary="合同",
                    folder_path="家庭 / 合同",
                    new_file_name="合同_待整理合同.txt",
                    tags=["合同"],
                    key_info={},
                    reason="模型判断属于合同",
                    confidence=0.88,
                    extractor="test",
                ),
            ):
                first_analysis = analyze_file_path(
                    source_path=source_file,
                    database_path=database_path,
                )
                with connect_database(database_path) as connection:
                    first_suggestion_id = connection.execute(
                        "SELECT id FROM organization_suggestions WHERE file_id = ?",
                        (first_analysis["id"],),
                    ).fetchone()[0]

                decide_suggestion(first_suggestion_id, "reject", database_path)
                second_analysis = analyze_file_path(
                    source_path=source_file,
                    database_path=database_path,
                )

            with connect_database(database_path) as connection:
                file_count = connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]
                suggestion_statuses = [
                    row["status"]
                    for row in connection.execute(
                        """
                        SELECT status
                        FROM organization_suggestions
                        WHERE file_id = ?
                        ORDER BY created_at DESC, id ASC
                        """,
                        (first_analysis["id"],),
                    ).fetchall()
                ]
            suggestions_page = get_suggestions_page(database_path)

        self.assertEqual(second_analysis["id"], first_analysis["id"])
        self.assertEqual(file_count, 1)
        self.assertEqual(sorted(suggestion_statuses), ["pending", "rejected"])
        self.assertEqual(len(suggestions_page["suggestions"]), 2)
        self.assertEqual(
            sorted(item["rawStatus"] for item in suggestions_page["suggestions"]),
            ["pending", "rejected"],
        )

    def test_file_path_with_pending_suggestion_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            database_path = temp_path / "file_butler.db"
            source_file = temp_path / "待整理合同.txt"
            source_file.write_text("这是一份合同。", encoding="utf-8")
            initialize_database(database_path)
            with connect_database(database_path) as connection:
                connection.execute(
                    "INSERT INTO users (id, display_name) VALUES (?, ?)",
                    ("1", "用户"),
                )

            with patch(
                "file_butler_server.services.uploads.build_organization_plan",
                return_value=OrganizationPlan(
                    summary="合同",
                    folder_path="家庭 / 合同",
                    new_file_name="合同_待整理合同.txt",
                    tags=["合同"],
                    key_info={},
                    reason="模型判断属于合同",
                    confidence=0.88,
                    extractor="test",
                ),
            ):
                analyze_file_path(source_path=source_file, database_path=database_path)
                with self.assertRaisesRegex(ValueError, "已有待确认建议"):
                    analyze_file_path(source_path=source_file, database_path=database_path)

    def test_analyze_file_path_passes_existing_library_context_to_agent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            database_path = temp_path / "file_butler.db"
            source_file = temp_path / "新合同.txt"
            source_file.write_text("新的合同文件", encoding="utf-8")
            initialize_database(database_path)
            with connect_database(database_path) as connection:
                connection.execute(
                    "INSERT INTO users (id, display_name) VALUES (?, ?)",
                    ("1", "用户"),
                )
                connection.execute(
                    """
                    INSERT INTO folders (id, user_id, parent_id, name, path)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    ("folder-1", "1", None, "合同", "家庭 / 合同"),
                )
                connection.execute(
                    """
                    INSERT INTO files (
                      id,
                      user_id,
                      folder_id,
                      original_path,
                      current_path,
                      display_name,
                      mime_type,
                      size_bytes,
                      status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "file-existing",
                        "1",
                        "folder-1",
                        "/tmp/旧合同.txt",
                        "/tmp/旧合同.txt",
                        "旧合同.txt",
                        "text/plain",
                        32,
                        "organized",
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO file_extractions (id, file_id, extractor, summary)
                    VALUES (?, ?, ?, ?)
                    """,
                    ("extraction-1", "file-existing", "test", "一份已经归档的租赁合同"),
                )

            captured_context = {}

            def fake_build_plan(**kwargs):
                captured_context.update(kwargs["library_context"])
                return OrganizationPlan(
                    summary="新合同",
                    folder_path="家庭 / 合同",
                    new_file_name="新合同.txt",
                    tags=["合同"],
                    key_info={},
                    reason="参考现有合同目录",
                    confidence=0.9,
                    extractor="test",
                )

            with patch(
                "file_butler_server.services.uploads.build_organization_plan",
                fake_build_plan,
            ):
                analyze_file_path(source_path=source_file, database_path=database_path)

        self.assertEqual(captured_context["folders"], ["家庭 / 合同"])
        self.assertEqual(captured_context["files"][0]["fileName"], "旧合同.txt")
        self.assertEqual(captured_context["files"][0]["folderPath"], "家庭 / 合同")
        self.assertEqual(
            captured_context["files"][0]["summary"],
            "一份已经归档的租赁合同",
        )

    def test_analyze_file_path_and_approve_moves_original_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            database_path = temp_path / "file_butler.db"
            storage_root = temp_path / "storage"
            source_file = temp_path / "待整理合同.txt"
            source_file.write_text("这是一份房屋租赁合同。", encoding="utf-8")
            initialize_database(database_path)
            with connect_database(database_path) as connection:
                connection.execute(
                    "INSERT INTO users (id, display_name) VALUES (?, ?)",
                    ("1", "用户"),
                )
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
