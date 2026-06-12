"""Development entrypoint for the File Butler backend package."""

from __future__ import annotations

from file_butler_server.core.database import initialize_database


def main() -> None:
    database_path = initialize_database()
    print(f"File Butler database is ready: {database_path}")


if __name__ == "__main__":
    main()
