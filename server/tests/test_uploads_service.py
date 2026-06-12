import tempfile
import unittest
from pathlib import Path

from file_butler_server.core.database import connect_database, initialize_database
from file_butler_server.services.uploads import get_upload_page, register_upload_metadata


class UploadsServiceTest(unittest.TestCase):
    def test_register_upload_metadata_uses_current_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "file_butler.db"
            initialize_database(database_path)
            with connect_database(database_path) as connection:
                connection.execute("INSERT INTO users (id, display_name) VALUES (?, ?)", ("1", "用户"))

            item = register_upload_metadata(
                file_name="合同.pdf",
                size_bytes=2048,
                mime_type="application/pdf",
                database_path=database_path,
            )
            page = get_upload_page(database_path)

        self.assertEqual(item["fileName"], "合同.pdf")
        self.assertEqual(page["queue"][0]["fileName"], "合同.pdf")
        self.assertEqual(page["queue"][0]["status"], "已上传")


if __name__ == "__main__":
    unittest.main()
