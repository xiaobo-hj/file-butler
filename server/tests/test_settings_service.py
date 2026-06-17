import tempfile
import unittest
from pathlib import Path

from file_butler_server.core.database import connect_database, initialize_database
from file_butler_server.services.settings import (
    get_storage_root_setting,
    update_storage_root_setting,
)


class SettingsServiceTest(unittest.TestCase):
    def test_update_storage_root_setting_uses_single_user_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            database_path = temp_path / "file_butler.db"
            root_path = temp_path / "my-files"
            initialize_database(database_path)
            with connect_database(database_path) as connection:
                connection.execute("INSERT INTO users (id, display_name) VALUES (?, ?)", ("1", "用户"))

            updated = update_storage_root_setting(
                root_path=str(root_path),
                database_path=database_path,
            )
            current = get_storage_root_setting(database_path)

            self.assertTrue(root_path.exists())
            self.assertEqual(updated["rootPath"], str(root_path))
            self.assertEqual(current["rootPath"], str(root_path))


if __name__ == "__main__":
    unittest.main()
