"""Development entrypoint for the File Butler backend package."""

from __future__ import annotations

import os

import uvicorn

from file_butler_server.core.database import initialize_database


def main() -> None:
    database_path = initialize_database()
    print(f"File Butler database is ready: {database_path}")
    uvicorn.run(
        "file_butler_server.api.app:app",
        host=os.environ.get("SERVER_HOST", "127.0.0.1"),
        port=int(os.environ.get("SERVER_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
