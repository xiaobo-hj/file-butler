import json
import tempfile
import unittest
from pathlib import Path

from file_butler_server.core.database import connect_database, initialize_database
from file_butler_server.services.dashboard import get_overview_dashboard


class DashboardServiceTest(unittest.TestCase):
    def test_overview_dashboard_returns_empty_database_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "file_butler.db"
            initialize_database(database_path)

            dashboard = get_overview_dashboard(database_path)

        self.assertEqual(dashboard["metrics"][0]["value"], "0")
        self.assertEqual(dashboard["metrics"][1]["value"], "0")
        self.assertEqual(dashboard["metrics"][2]["value"], "0")
        self.assertEqual(dashboard["metrics"][3]["value"], "0%")
        self.assertEqual(dashboard["suggestions"], [])
        self.assertEqual(dashboard["activities"], [])
        self.assertEqual(dashboard["knowledgePrompt"]["actionLabel"], "上传文件")

    def test_overview_dashboard_reads_from_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "file_butler.db"
            initialize_database(database_path)
            self._insert_dashboard_rows(database_path)

            dashboard = get_overview_dashboard(database_path)

        self.assertEqual(dashboard["metrics"][0]["value"], "2")
        self.assertEqual(dashboard["metrics"][1]["value"], "1")
        self.assertEqual(dashboard["metrics"][2]["value"], "1")
        self.assertEqual(dashboard["metrics"][3]["value"], "50%")
        self.assertEqual(dashboard["suggestions"][0]["fileName"], "合同.pdf")
        self.assertEqual(dashboard["activities"][0]["title"], "已归档")
        self.assertEqual(dashboard["knowledgePrompt"]["actionLabel"], "去问答")

    def _insert_dashboard_rows(self, database_path: Path) -> None:
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
                ("root-1", "1", "/tmp/files", "测试目录"),
            )
            connection.execute(
                """
                INSERT INTO folders (id, user_id, parent_id, name, path)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("folder-1", "1", None, "合同", "家庭 / 合同"),
            )
            connection.executemany(
                """
                INSERT INTO files (
                  id,
                  user_id,
                  storage_root_id,
                  folder_id,
                  original_path,
                  current_path,
                  display_name,
                  status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "file-1",
                        "1",
                        "root-1",
                        "folder-1",
                        "/tmp/合同.pdf",
                        "/tmp/files/合同.pdf",
                        "合同.pdf",
                        "indexed",
                    ),
                    (
                        "file-2",
                        "1",
                        "root-1",
                        "folder-1",
                        "/tmp/发票.pdf",
                        "/tmp/files/发票.pdf",
                        "发票.pdf",
                        "organized",
                    ),
                ],
            )
            connection.execute(
                """
                INSERT INTO organization_suggestions (
                  id,
                  file_id,
                  reason,
                  confidence,
                  status
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                ("suggestion-1", "file-1", "建议整理", 0.9, "pending"),
            )
            connection.execute(
                """
                INSERT INTO knowledge_chunks (id, file_id, chunk_index, content)
                VALUES (?, ?, ?, ?)
                """,
                ("chunk-1", "file-1", 0, "合同内容"),
            )
            connection.execute(
                """
                INSERT INTO reminders (id, user_id, file_id, title, due_at, status)
                VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '+10 days'), ?)
                """,
                ("reminder-1", "1", "file-1", "合同到期", "active"),
            )
            connection.execute(
                """
                INSERT INTO audit_logs (
                  id,
                  user_id,
                  entity_type,
                  entity_id,
                  event_type,
                  payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "audit-1",
                    "1",
                    "file",
                    "file-1",
                    "file_archived",
                    json.dumps(
                        {
                            "timeLabel": "今天 10:35",
                            "title": "已归档",
                            "description": "合同移动到 家庭 / 合同",
                        },
                        ensure_ascii=False,
                    ),
                ),
            )


if __name__ == "__main__":
    unittest.main()
