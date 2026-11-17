import argparse
import asyncio
import json
from pathlib import Path

import aiosqlite
from alembic.util import CommandError
from sqlalchemy.exc import SQLAlchemyError

from app import config
from app.maintenance.backup import DatabaseBackup
from migrations.development import DatabaseMigrations
from migrations.operations import upgrade_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Local scaffold maintenance")
    # 固定的引导文件路径，不提供应用参数默认值。
    parser.add_argument("--config", type=Path, default=config.CONFIG_FILE)
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
    commands.add_parser("export-service-settings", help="Export validated settings for service.sh")
    args = parser.parse_args()
    try:
        settings = config.load_settings(args.config)
        config.bind_settings(settings)
        if args.command == "export-settings":
            print(json.dumps(settings.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
        elif args.command == "export-service-settings":
            print(
                json.dumps(
                    {
                        "config": str(settings.source_file),
                        "log": str(settings.logging.directory / settings.logging.filename),
                        "startup_timeout": settings.service.startup_timeout_seconds,
                        "stop_timeout": settings.service.stop_timeout_seconds,
                    },
                    ensure_ascii=False,
                )
            )
        elif args.command == "export-openapi":
            from app.application import create_app

            application = create_app()
            print(json.dumps(application.openapi(), ensure_ascii=False, indent=2, sort_keys=True))
        elif args.command == "db-upgrade":
            upgrade_database()
            print(f"Database schema is current: {settings.database_path}")
        elif args.command == "db-revision":
            migration = DatabaseMigrations().create_revision(
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
            DatabaseMigrations().check()
            print("Migration check passed: base -> head and model comparison (temporary database).")
        else:
            print(asyncio.run(DatabaseBackup().create_snapshot()))
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
