"""Local desktop file picker integration."""

from __future__ import annotations

import subprocess
from sys import platform


def select_local_file_paths() -> list[str]:
    """Open the operating system file picker and return selected local paths."""

    if platform != "darwin":
        raise RuntimeError("当前只支持 macOS 本机文件选择器。")

    script = "\n".join(
        [
            'set promptText to "选择要分析的文件"',
            "set pickedFiles to choose file with prompt promptText "
            "with multiple selections allowed",
            "set outputPaths to {}",
            "repeat with pickedFile in pickedFiles",
            "  set end of outputPaths to POSIX path of pickedFile",
            "end repeat",
            "set AppleScript's text item delimiters to linefeed",
            "return outputPaths as text",
        ]
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode == 0:
        return [line for line in result.stdout.splitlines() if line.strip()]

    if "(-128)" in result.stderr:
        return []

    message = result.stderr.strip() or "打开本机文件选择器失败。"
    raise RuntimeError(message)
