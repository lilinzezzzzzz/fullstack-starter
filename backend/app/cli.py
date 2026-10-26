import argparse
import asyncio
import json
from pathlib import Path

import aiosqlite

from app.config import CONFIG_FILE, load_settings
from app.database import upgrade_database
from app.maintenance.backup import new_database_backup


def main() -> None:
    parser = argparse.ArgumentParser(description="Local scaffold maintenance")
    # A fixed bootstrap file locator; it supplies no application parameter defaults.
    parser.add_argument("--config", type=Path, default=CONFIG_FILE)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("export-openapi", help="Write OpenAPI JSON without starting services")
    commands.add_parser("db-backup", help="Create and verify a SQLite snapshot")
    commands.add_parser("db-upgrade", help="Explicitly upgrade the database selected by the file")
    commands.add_parser("export-settings", help="Export validated settings for local build tools")
    args = parser.parse_args()
    try:
        settings = load_settings(args.config)
        if args.command == "export-settings":
            print(json.dumps(settings.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
        elif args.command == "export-openapi":
            from app.main import create_app

            application = create_app(settings)
            print(json.dumps(application.openapi(), ensure_ascii=False, indent=2, sort_keys=True))
        elif args.command == "db-upgrade":
            upgrade_database(settings)
            print(f"Database schema is current: {settings.database_path}")
        else:
            backup = new_database_backup(settings)
            print(asyncio.run(backup.create_snapshot()))
    except (OSError, RuntimeError, ValueError, aiosqlite.Error) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
