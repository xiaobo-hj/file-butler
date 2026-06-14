import tempfile
import unittest
from pathlib import Path

from file_butler_server.core.database import connect_database, initialize_database
from file_butler_server.services.library import get_library_page


class LibraryServiceTest(unittest.TestCase):
    def test_library_page_returns_empty_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "file_butler.db"
            initialize_database(database_path)

            library = get_library_page(database_path)

        self.assertEqual(library["summary"]["totalFiles"], "0")
        self.assertEqual(library["summary"]["organizedFiles"], "0")
        self.assertEqual(library["files"], [])
        self.assertEqual(library["filters"]["folders"], [])

    def test_library_page_reads_files_tags_and_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "file_butler.db"
            initialize_database(database_path)
            self._insert_library_rows(database_path)

            library = get_library_page(database_path)

        self.assertEqual(library["summary"]["totalFiles"], "2")
        self.assertEqual(library["summary"]["organizedFiles"], "2")
        self.assertEqual(library["summary"]["indexedFiles"], "1")
        self.assertEqual(library["summary"]["folders"], "1")
        self.assertEqual(library["files"][0]["fileName"], "合同.pdf")
        self.assertEqual(library["files"][0]["folder"], "家庭 / 合同")
        self.assertEqual(library["files"][0]["tags"], ["合同", "家庭"])
        self.assertEqual(library["files"][0]["summary"], "房屋租赁合同。")
        self.assertEqual(library["filters"]["statuses"][0]["value"], "indexed")

    def _insert_library_rows(self, database_path: Path) -> None:
        with connect_database(database_path) as connection:
            connection.execute("INSERT INTO users (id, display_name) VALUES (?, ?)", ("1", "用户"))
            connection.execute(
                """
                INSERT INTO storage_roots (id, user_id, root_path, display_name)
                VALUES (?, ?, ?, ?)
                """,
                ("root-1", "1", "/tmp/files", "测试归档区"),
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
                  mime_type,
                  size_bytes,
                  status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        "application/pdf",
                        2048,
                        "indexed",
                    ),
                    (
                        "file-2",
                        "1",
                        "root-1",
                        None,
                        "/tmp/发票.txt",
                        "/tmp/files/发票.txt",
                        "发票.txt",
                        "text/plain",
                        1024,
                        "organized",
                    ),
                ],
            )
            connection.execute(
                """
                INSERT INTO file_extractions (id, file_id, extractor, summary)
                VALUES (?, ?, ?, ?)
                """,
                ("extraction-1", "file-1", "test", "房屋租赁合同。"),
            )
            connection.executemany(
                """
                INSERT INTO tags (id, user_id, name)
                VALUES (?, ?, ?)
                """,
                [
                    ("tag-1", "1", "合同"),
                    ("tag-2", "1", "家庭"),
                ],
            )
            connection.executemany(
                """
                INSERT INTO file_tags (file_id, tag_id)
                VALUES (?, ?)
                """,
                [
                    ("file-1", "tag-1"),
                    ("file-1", "tag-2"),
                ],
            )


if __name__ == "__main__":
    unittest.main()
