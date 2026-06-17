import json
import tempfile
import unittest
from pathlib import Path

from file_butler_server.core.database import connect_database, initialize_database
from file_butler_server.services.suggestions import decide_suggestion, get_suggestions_page


class SuggestionsServiceTest(unittest.TestCase):
    def test_suggestions_page_reads_detail_for_current_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "file_butler.db"
            initialize_database(database_path)
            self._insert_suggestion_rows(database_path)

            page = get_suggestions_page(database_path)

        self.assertEqual(page["summary"]["pendingCount"], 1)
        self.assertEqual(page["suggestions"][0]["fileName"], "合同.pdf")
        self.assertEqual(page["selectedSuggestion"]["suggestedFileName"], "2026_合同.pdf")
        self.assertEqual(page["selectedSuggestion"]["tags"], ["合同", "家庭"])
        self.assertEqual(page["selectedSuggestion"]["keyInfo"][0]["label"], "甲方")

    def test_decide_suggestion_updates_current_user_suggestion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            database_path = temp_path / "file_butler.db"
            initialize_database(database_path)
            source_file = temp_path / "合同.pdf"
            source_file.write_text("合同内容", encoding="utf-8")
            self._insert_suggestion_rows(database_path, source_path=source_file)

            result = decide_suggestion("suggestion-1", "approve", database_path)

            with connect_database(database_path) as connection:
                status = connection.execute(
                    "SELECT status FROM organization_suggestions WHERE id = ?",
                    ("suggestion-1",),
                ).fetchone()[0]

        self.assertEqual(result["status"], "approved")
        self.assertEqual(status, "approved")

    def _insert_suggestion_rows(self, database_path: Path, source_path: Path | None = None) -> None:
        source = source_path or Path("/tmp/合同.pdf")
        with connect_database(database_path) as connection:
            connection.execute("INSERT INTO users (id, display_name) VALUES (?, ?)", ("1", "用户"))
            connection.execute(
                """
                INSERT INTO storage_roots (id, user_id, root_path, display_name)
                VALUES (?, ?, ?, ?)
                """,
                ("root-1", "1", str(database_path.parent / "storage"), "测试整理目录"),
            )
            connection.execute(
                "INSERT INTO folders (id, user_id, parent_id, name, path) VALUES (?, ?, ?, ?, ?)",
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
                    "file-1",
                    "1",
                    "folder-1",
                    str(source),
                    str(source),
                    "合同.pdf",
                    "application/pdf",
                    2048,
                    "suggested",
                ),
            )
            connection.execute(
                """
                INSERT INTO organization_suggestions (id, file_id, reason, confidence, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("suggestion-1", "file-1", "符合合同特征", 0.91, "pending"),
            )
            connection.execute(
                """
                INSERT INTO suggestion_actions (id, suggestion_id, action_type, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "action-0",
                    "suggestion-1",
                    "set_folder",
                    json.dumps({"folderPath": "家庭 / 合同"}, ensure_ascii=False),
                ),
            )
            connection.execute(
                """
                INSERT INTO suggestion_actions (id, suggestion_id, action_type, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "action-1",
                    "suggestion-1",
                    "rename",
                    json.dumps({"newFileName": "2026_合同.pdf"}, ensure_ascii=False),
                ),
            )
            connection.execute(
                """
                INSERT INTO suggestion_actions (id, suggestion_id, action_type, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "action-2",
                    "suggestion-1",
                    "tag",
                    json.dumps({"tags": ["合同", "家庭"]}, ensure_ascii=False),
                ),
            )
            connection.execute(
                """
                INSERT INTO file_extractions (
                  id,
                  file_id,
                  extractor,
                  summary,
                  structured_fields_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "extraction-1",
                    "file-1",
                    "test",
                    "这是一份合同。",
                    json.dumps({"甲方": "张三"}, ensure_ascii=False),
                ),
            )


if __name__ == "__main__":
    unittest.main()
