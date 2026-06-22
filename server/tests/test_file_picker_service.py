import subprocess
import unittest
from unittest.mock import patch

from file_butler_server.services.file_picker import select_local_file_paths


class FilePickerServiceTest(unittest.TestCase):
    def test_select_local_file_paths_returns_selected_paths(self):
        result = subprocess.CompletedProcess(
            args=["osascript"],
            returncode=0,
            stdout="/Users/xiaobo/a.pdf\n/Users/xiaobo/b.txt\n",
            stderr="",
        )

        with (
            patch("file_butler_server.services.file_picker.platform", "darwin"),
            patch("subprocess.run", return_value=result),
        ):
            paths = select_local_file_paths()

        self.assertEqual(paths, ["/Users/xiaobo/a.pdf", "/Users/xiaobo/b.txt"])

    def test_select_local_file_paths_returns_empty_list_when_user_cancels(self):
        result = subprocess.CompletedProcess(
            args=["osascript"],
            returncode=1,
            stdout="",
            stderr="execution error: User canceled. (-128)",
        )

        with (
            patch("file_butler_server.services.file_picker.platform", "darwin"),
            patch("subprocess.run", return_value=result),
        ):
            paths = select_local_file_paths()

        self.assertEqual(paths, [])

    def test_select_local_file_paths_rejects_unsupported_platforms(self):
        with patch("file_butler_server.services.file_picker.platform", "linux"):
            with self.assertRaisesRegex(RuntimeError, "macOS"):
                select_local_file_paths()


if __name__ == "__main__":
    unittest.main()
