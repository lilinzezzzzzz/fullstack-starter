import argparse
import asyncio
import json
from pathlib import Path

import aiosqlite
from alembic.util import CommandError
from sqlalchemy.exc import SQLAlchemyError

from app.config import CONFIG_FILE, load_settings
from app.maintenance.backup import new_database_backup
from migrations.development import new_database_migrations
from migrations.operations import upgrade_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Local scaffold maintenance")
    # 固定的引导文件路径，不提供应用参数默认值。
    parser.add_argument("--config", type=Path, default=CONFIG_FILE)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("export-openapi", help="Write OpenAPI JSON without starting services")
    commands.add_parser("db-backup", help="Create and verify a SQLite snapshot")
    commands.add_parser("db-upgrade", help="Explicitly upgrade the database selected by the file")
    revision = commands.add_parser("db-revision", help="Generate a candidate using a temporary DB")
    revision.add_argument("-m", "--message", required=True, help="Describe the migration")
    revision.add_argument(
        "--empty",
        action="store_true",
        help="Create a manual migration without schema autogeneration",
    )
    commands.add_parser("db-check", help="Replay migrations and compare models in a temporary DB")
    commands.add_parser("export-settings", help="Export validated settings for local build tools")
    args = parser.parse_args()
    try:
        settings = load_settings(args.config)
        if args.command == "export-settings":
            print(json.dumps(settings.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
        elif args.command == "export-openapi":
            from app.main import create_app

            application = create_app(settings)
            try:
                print(
                    json.dumps(application.openapi(), ensure_ascii=False, indent=2, sort_keys=True)
                )
            finally:
                application.state.tracer_provider.shutdown()
        elif args.command == "db-upgrade":
            upgrade_database(settings)
            print(f"Database schema is current: {settings.database_path}")
        elif args.command == "db-revision":
            migration = new_database_migrations(settings).create_revision(
                args.message,
                empty=args.empty,
            )
            if migration is None:
                print(
                    "No schema changes detected; no revision created. Use --empty for manual work."
                )
            else:
                print(f"Candidate migration: {migration}. Review and test it before db-upgrade.")
        elif args.command == "db-check":
            new_database_migrations(settings).check()
            print("Migration check passed: base -> head and model comparison (temporary database).")
        else:
            backup = new_database_backup(settings)
            print(asyncio.run(backup.create_snapshot()))
    except (
        OSError,
        RuntimeError,
        ValueError,
        aiosqlite.Error,
        CommandError,
        SQLAlchemyError,
    ) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
