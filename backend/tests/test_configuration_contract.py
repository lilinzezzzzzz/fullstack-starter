import asyncio
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from textwrap import dedent

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app import config as app_config
from app.application import create_app
from app.config import PROJECT_ROOT, ApplicationSettings, load_settings
from app.infra.database import create_database_engine
from app.utils.path_safety import validate_runtime_paths
from migrations.operations import upgrade_database
from tests.helpers import read_config, save_config, write_config


def test_binding_preserves_proxy_and_can_restore_unloaded_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = load_settings(write_config(tmp_path / "first"))
    second = load_settings(write_config(tmp_path / "second"))
    proxy = app_config.settings
    previous = app_config.bind_settings(first)
    assert previous is None
    assert app_config.get_settings() is first
    assert app_config.settings is proxy
    assert app_config.bind_settings(second) is first
    assert proxy.database_path == second.database_path
    assert app_config.get_settings() is second
    with pytest.raises(TypeError, match="real Settings"):
        app_config.bind_settings(proxy)
    assert app_config.get_settings() is second
    assert app_config.bind_settings(previous) is second
    assert app_config.settings is proxy

    def forbidden_load(path: str | Path) -> app_config.Settings:
        raise AssertionError("configuration reload probe")

    monkeypatch.setattr(app_config, "load_settings", forbidden_load)
    assert repr(proxy) == "<_LazyProxy>"
    with pytest.raises(AssertionError, match="configuration reload"):
        app_config.get_settings()


def test_failed_binding_input_never_discards_current_real_settings(tmp_path: Path) -> None:
    configuration = load_settings(write_config(tmp_path))
    app_config.bind_settings(configuration)
    with pytest.raises(TypeError, match="real Settings"):
        app_config.bind_settings({"data_dir": "not validated"})
    assert app_config.get_settings() is configuration


@pytest.mark.parametrize("explicit", [False, True])
def test_settings_proxy_loads_real_settings_once_without_import_side_effects(
    service_project: Path, tmp_path: Path, explicit: bool
) -> None:
    config = (
        write_config(tmp_path / "selected config")
        if explicit
        else service_project / "configs/app.toml"
    )
    environment = {key: value for key, value in os.environ.items() if key != "APP_CONFIG_FILE"}
    if explicit:
        environment["APP_CONFIG_FILE"] = str(config)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            dedent("""\
                import os
                import sys
                from pathlib import Path
                from unittest.mock import Mock
                import app.config as config
                loader = Mock(wraps=config.load_settings)
                config.load_settings = loader
                from app.config import settings
                assert repr(settings) == "<_LazyProxy>"
                loader.assert_not_called()
                loaded = config.get_settings()
                assert type(loaded) is config.Settings
                assert settings.source_file == Path(sys.argv[1])
                assert config.get_settings() is loaded
                loader.assert_called_once()
                os.environ["APP_CONFIG_FILE"] = "/missing-after-first-access.toml"
                from app.config import settings as again
                assert again is settings
                independent = config.load_settings(sys.argv[1])
                assert independent is not loaded
                assert independent.model_dump() == settings.model_dump()
                assert config.settings is settings
                assert config.bind_settings(independent) is loaded
                assert config.settings is settings
                assert config.get_settings() is independent
                assert loader.call_count == 2
                assert not settings.database_path.exists()
                assert not settings.logging.directory.exists()
            """),
            str(config),
        ],
        cwd=service_project / "backend",
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "command", ["export-settings", "export-service-settings", "export-openapi"]
)
def test_explicit_cli_config_does_not_load_default_or_process_settings(
    service_project: Path, tmp_path: Path, command: str
) -> None:
    (service_project / "configs/app.toml").unlink()
    config = write_config(tmp_path / "explicit config", serve_frontend=True)
    result = subprocess.run(
        [sys.executable, "-m", "entrypoints.cli", "--config", str(config), command],
        cwd=service_project / "backend",
        env={**os.environ, "APP_CONFIG_FILE": str(tmp_path / "missing.toml")},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    exported = json.loads(result.stdout)
    if command == "export-service-settings":
        assert exported["config"] == str(config)
    elif command == "export-openapi":
        assert exported["info"]["title"] == read_config(config)["application"]["title"]
    else:
        assert exported == load_settings(config).model_dump(mode="json")
    assert not (config.parent / "data").exists()
    assert not (config.parent / "logs").exists()
    assert not (config.parent / "dist").exists()
    assert not (service_project / ".run").exists()


def test_openapi_cli_uses_selected_file_even_after_shared_settings_were_loaded(
    service_project: Path, tmp_path: Path
) -> None:
    previous = write_config(tmp_path / "previous config")
    selected = write_config(tmp_path / "selected config", serve_frontend=True)
    data = read_config(selected)
    data["application"].update(title="selected-application", version="2.3.4")
    save_config(selected, data)
    (service_project / "configs/app.toml").unlink()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            dedent("""\
                import sys
                from pathlib import Path
                from app import config
                from entrypoints.cli import main
                proxy = config.settings
                previous = config.get_settings()
                assert previous.source_file == Path(sys.argv[1])
                selected = Path(sys.argv[2])
                sys.argv = ["cli", "--config", str(selected), "export-openapi"]
                main()
                assert config.settings is proxy
                assert config.get_settings() is not previous
                assert config.settings.source_file == selected
            """),
            str(previous),
            str(selected),
        ],
        cwd=service_project / "backend",
        env={**os.environ, "APP_CONFIG_FILE": str(previous)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["info"] == {
        "title": "selected-application",
        "version": "2.3.4",
    }
    for directory in (previous.parent, selected.parent):
        assert not (directory / "data").exists()
        assert not (directory / "logs").exists()
        assert not (directory / "dist").exists()


@pytest.mark.parametrize("invalid", ["missing-file", "missing-field"])
def test_settings_export_does_not_fall_back_on_invalid_selected_configuration(
    service_project: Path, tmp_path: Path, invalid: str
) -> None:
    config = write_config(tmp_path / "invalid config")
    if invalid == "missing-file":
        config.unlink()
    else:
        data = read_config(config)
        del data["logging"]["level"]
        save_config(config, data)
    result = subprocess.run(
        [sys.executable, "-c", "from app.config import settings; settings.logging"],
        cwd=service_project / "backend",
        env={**os.environ, "APP_CONFIG_FILE": str(config)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert ("FileNotFoundError" if invalid == "missing-file" else "logging.level") in result.stderr
    assert not (config.parent / "logs").exists()


@pytest.mark.parametrize(
    "command",
    [
        "export-settings",
        "export-service-settings",
        "db-upgrade",
        "db-backup",
        "db-check",
        "db-revision",
    ],
)
def test_all_cli_commands_bind_selected_file_before_execution(
    service_project: Path, tmp_path: Path, command: str
) -> None:
    previous = write_config(tmp_path / "previous")
    selected = write_config(tmp_path / "selected")
    values = read_config(selected)
    values["testing"]["temporary_directory"] = str(selected.parent / "scratch")
    save_config(selected, values)
    (service_project / "configs/app.toml").unlink()
    environment = {**os.environ, "APP_CONFIG_FILE": str(previous)}
    if command == "db-backup":
        prepared = subprocess.run(
            [sys.executable, "-m", "entrypoints.cli", "--config", str(selected), "db-upgrade"],
            cwd=service_project / "backend",
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            dedent("""\
                import sys
                from pathlib import Path
                from app import config
                from entrypoints.cli import main
                proxy = config.settings
                previous = config.get_settings()
                assert previous.source_file == Path(sys.argv[1])
                selected = Path(sys.argv[2])
                operation = sys.argv[3]
                sys.argv = ["cli", "--config", str(selected), operation]
                if operation == "db-revision":
                    sys.argv += ["--empty", "-m", "selected configuration probe"]
                main()
                assert config.settings is proxy
                assert config.get_settings() is not previous
                assert config.settings.source_file == selected
            """),
            str(previous),
            str(selected),
            command,
        ],
        cwd=service_project / "backend",
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (previous.parent / "data").exists()
    assert not (previous.parent / "backups").exists()
    assert not (previous.parent / "logs").exists()
    assert not (selected.parent / "logs").exists()
    assert not (selected.parent / "dist").exists()
    if command in {"db-upgrade", "db-backup"}:
        assert (selected.parent / "data/app.sqlite3").is_file()
    else:
        assert not (selected.parent / "data").exists()
    if command in {"db-check", "db-revision"}:
        assert list((selected.parent / "scratch").iterdir()) == []


@pytest.mark.parametrize("command", ["db-upgrade", "db-backup"])
def test_invalid_cli_configuration_never_reuses_cached_database_target(
    service_project: Path, tmp_path: Path, command: str
) -> None:
    previous = write_config(tmp_path / "previous")
    selected = write_config(tmp_path / "invalid")
    values = read_config(selected)
    del values["logging"]["level"]
    save_config(selected, values)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            dedent("""\
                import sys
                from app import config
                from entrypoints.cli import main
                previous = config.get_settings()
                sys.argv = ["cli", "--config", sys.argv[1], sys.argv[2]]
                main()
            """),
            str(selected),
            command,
        ],
        cwd=service_project / "backend",
        env={**os.environ, "APP_CONFIG_FILE": str(previous)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "logging.level" in result.stderr
    assert not (previous.parent / "data").exists()
    assert not (previous.parent / "backups").exists()
    assert not (selected.parent / "data").exists()


def test_documentation_relationship_is_validated_by_its_own_section(tmp_path: Path) -> None:
    data = read_config(write_config(tmp_path))["application"]
    data.update(docs_enabled=True, openapi_enabled=False)
    with pytest.raises(ValidationError, match="requires openapi_enabled=true"):
        ApplicationSettings.model_validate(data)


def configuration_paths(data: dict, prefix: tuple[str, ...] = ()):
    for key, value in data.items():
        path = (*prefix, key)
        yield path
        if isinstance(value, dict):
            yield from configuration_paths(value, path)


def test_every_configuration_field_is_required(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    original = read_config(path)
    for field_path in configuration_paths(original):
        incomplete = deepcopy(original)
        parent = incomplete
        for part in field_path[:-1]:
            parent = parent[part]
        del parent[field_path[-1]]
        save_config(path, incomplete)
        with pytest.raises(ValidationError) as error:
            load_settings(path)
        assert any(item["type"] == "missing" for item in error.value.errors()), field_path


@pytest.mark.parametrize("field", ["database.pool_size", "service.startup_timeout_seconds"])
def test_wrong_types_are_not_coerced_or_defaulted(tmp_path: Path, field: str) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    section, key = field.split(".")
    data[section][key] = "123"
    save_config(path, data)
    with pytest.raises(ValidationError):
        load_settings(path)


def test_legacy_json_is_not_an_implicit_fallback(tmp_path: Path) -> None:
    (tmp_path / "app.json").write_text('{"data_dir": "wrong-directory"}')
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "app.toml")
    with pytest.raises(ValueError, match=".toml"):
        load_settings(tmp_path / "app.json")


def test_non_finite_timeout_is_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    data["service"]["startup_timeout_seconds"] = float("inf")
    save_config(path, data)
    with pytest.raises(ValidationError):
        load_settings(path)


def test_zero_and_false_are_explicit_values_not_missing_values(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    data["database"]["max_overflow"] = 0
    data["testing"]["action_timeout_seconds"] = 0.0
    data["logging"]["request_logging"] = False
    save_config(path, data)
    settings = load_settings(path)
    assert settings.database.max_overflow == 0
    assert settings.testing.action_timeout_seconds == 0
    assert settings.logging.request_logging is False


@pytest.mark.parametrize("section", ["client", "vite"])
def test_old_frontend_sections_are_rejected(tmp_path: Path, section: str) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    data[section] = {}
    save_config(path, data)
    with pytest.raises(ValidationError) as error:
        load_settings(path)
    assert any(
        item["loc"] == (section,) and item["type"] == "extra_forbidden"
        for item in error.value.errors()
    )


@pytest.mark.parametrize(
    ("docs_enabled", "redoc_enabled", "openapi_enabled"),
    [
        (True, True, True),
        (True, False, True),
        (False, True, True),
        (False, False, True),
        (False, False, False),
    ],
)
def test_documentation_and_metadata_are_driven_by_file(
    tmp_path: Path,
    docs_enabled: bool,
    redoc_enabled: bool,
    openapi_enabled: bool,
) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    data["application"].update(
        title="configured-project",
        version="2.3.4",
        docs_enabled=docs_enabled,
        redoc_enabled=redoc_enabled,
        openapi_enabled=openapi_enabled,
        docs_path="/reference/swagger",
        redoc_path="/reference/redoc",
        openapi_path="/spec/openapi.json",
    )
    data["serve_frontend"] = True
    frontend = tmp_path / "dist"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html><body>Hello</body></html>")
    save_config(path, data)
    settings = load_settings(path)
    assert settings.application.model_dump() == data["application"]
    app_config.bind_settings(settings)
    upgrade_database()
    app = create_app()
    assert app.openapi()["info"] == {"title": "configured-project", "version": "2.3.4"}
    assert "ClientSettings" not in app.openapi()["components"]["schemas"]
    with TestClient(app, base_url="http://127.0.0.1") as client:
        for url, enabled in (
            (settings.application.docs_path, docs_enabled),
            (settings.application.redoc_path, redoc_enabled),
            (settings.application.openapi_path, openapi_enabled),
        ):
            response = client.get(url, headers={"accept": "text/html"})
            assert response.status_code == (200 if enabled else 404)
            if not enabled:
                assert response.json()["code"] == "NOT_FOUND"
        assert client.get("/", headers={"accept": "text/html"}).status_code == 200
        assert client.get("/api/v1/hello").json() == {"message": "Hello World"}


@pytest.mark.anyio
async def test_journal_and_durability_are_driven_by_file(
    tmp_path: Path,
) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    data["database"].update(journal_mode="DELETE", synchronous="EXTRA")
    save_config(path, data)
    settings = load_settings(path)
    app_config.bind_settings(settings)
    await asyncio.to_thread(upgrade_database)
    engine = create_database_engine()
    try:
        async with engine.connect() as connection:
            assert (await connection.exec_driver_sql("PRAGMA journal_mode")).scalar() == "delete"
            assert (await connection.exec_driver_sql("PRAGMA synchronous")).scalar() == 3
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_pool_limits_are_driven_by_file(
    tmp_path: Path,
) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    data["database"].update(pool_size=2, max_overflow=0, pool_timeout_seconds=0.05)
    save_config(path, data)
    settings = load_settings(path)
    app_config.bind_settings(settings)
    await asyncio.to_thread(upgrade_database)
    engine = create_database_engine()
    try:
        async with engine.connect(), engine.connect():
            with pytest.raises(PoolTimeoutError):
                await engine.connect()
    finally:
        await engine.dispose()


def test_public_output_cannot_contain_private_storage(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    data["frontend_dir"] = data["data_dir"]
    save_config(path, data)
    with pytest.raises(ValidationError, match="private data"):
        load_settings(path)


@pytest.mark.parametrize(
    "destination",
    [
        "backend/app",
        "backend/entrypoints",
        "entrypoints",
        "scripts",
        "docs",
        ".git",
        "frontend/public",
        ".",
        "README.md",
        ".prettierrc.toml",
        ".prettierignore",
    ],
)
def test_public_output_cannot_overlap_source(tmp_path: Path, destination: str) -> None:
    path = write_config(tmp_path, frontend_dir=destination)
    with pytest.raises(ValidationError, match="protected project source"):
        load_settings(path)


@pytest.mark.parametrize(
    "field",
    [
        "data_dir",
        "backup_directory",
        "logging.directory",
        "testing.temporary_directory",
    ],
)
@pytest.mark.parametrize(
    "destination", ["backend/app", "entrypoints", ".prettierrc.toml", ".prettierignore"]
)
def test_runtime_paths_cannot_use_source_directories(
    tmp_path: Path, field: str, destination: str
) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    section, separator, name = field.partition(".")
    if separator:
        data[section][name] = destination
    else:
        data[field] = destination
    save_config(path, data)
    with pytest.raises(ValidationError, match="project source"):
        load_settings(path)


def test_output_alias_cannot_bypass_source_protection(tmp_path: Path) -> None:
    alias = tmp_path / "source-alias"
    alias.symlink_to(PROJECT_ROOT / "frontend/src", target_is_directory=True)
    with pytest.raises(ValidationError, match="protected project source"):
        load_settings(write_config(tmp_path, frontend_dir=str(alias)))


def test_public_output_cannot_be_inside_private_storage(tmp_path: Path) -> None:
    path = write_config(
        tmp_path, data_dir=str(tmp_path / "storage"), frontend_dir=str(tmp_path / "storage/dist")
    )
    with pytest.raises(ValidationError, match="private data"):
        load_settings(path)


def test_clean_output_cannot_follow_symlink_outside_default_tree(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "output-alias"
    alias.symlink_to(outside, target_is_directory=True)
    path = write_config(
        tmp_path,
        frontend_dir=str(alias),
        frontend_clean_output=True,
    )
    with pytest.raises(ValidationError, match="Automatic output cleaning"):
        load_settings(path)


def test_clean_output_rejects_symlinked_default_tree(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "frontend").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "frontend/dist").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="Automatic output cleaning"):
        validate_runtime_paths(
            project,
            frontend_dir=project / "frontend/dist",
            frontend_clean_output=True,
            data_dir=project / "data",
            backup_directory=project / "backups",
            logging_directory=project / "logs",
            temporary_directory=tmp_path / "tmp",
            database_filename="app.sqlite3",
            logging_filename="app.log",
        )


@pytest.mark.parametrize(
    "destination",
    [
        "Backend/app",
        "BACKEND/ENTRYPOINTS",
        "ENTRYPOINTS",
        "SCRIPTS",
        "DOCS",
        ".GIT",
        "LOGS",
        ".DATA",
    ],
)
def test_case_only_source_and_runtime_aliases_are_rejected(
    tmp_path: Path, destination: str
) -> None:
    path = write_config(tmp_path, frontend_dir=destination)
    with pytest.raises(ValidationError, match="protected project source"):
        load_settings(path)


@pytest.mark.parametrize("destination", ["data", ".run", ".venv"])
def test_legacy_and_dependency_directories_cannot_be_public_output(
    tmp_path: Path, destination: str
) -> None:
    path = write_config(tmp_path, frontend_dir=destination)
    with pytest.raises(ValidationError, match="protected project source"):
        load_settings(path)


@pytest.mark.parametrize(
    "field",
    [
        "data_dir",
        "logging.directory",
        "testing.temporary_directory",
    ],
)
def test_case_only_source_aliases_are_rejected_for_runtime_paths(
    tmp_path: Path, field: str
) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    section, separator, name = field.partition(".")
    if separator:
        data[section][name] = "Backend/app"
    else:
        data[field] = "Backend/app"
    save_config(path, data)
    with pytest.raises(ValidationError, match="project source"):
        load_settings(path)


def test_runtime_file_paths_must_not_collide(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    data = read_config(path)
    data["logging"]["directory"] = data["data_dir"]
    data["logging"]["filename"] = data["database_filename"] + ".lock"
    save_config(path, data)
    with pytest.raises(ValidationError, match="same file path"):
        load_settings(path)

    path = write_config(tmp_path / "logging-collision")
    data = read_config(path)
    data["logging"]["directory"] = data["data_dir"]
    data["logging"]["filename"] = data["database_filename"]
    save_config(path, data)
    with pytest.raises(ValidationError, match="same file path"):
        load_settings(path)
