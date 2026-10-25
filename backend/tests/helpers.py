import tomllib
from pathlib import Path

import tomli_w

from app.config import CONFIG_FILE, Settings, load_settings


def read_config(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def save_config(path: Path, data: dict) -> None:
    path.write_text(tomli_w.dumps(data), encoding="utf-8")


def write_config(directory: Path, **overrides: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    data = read_config(CONFIG_FILE)
    data.update(
        data_dir=str(directory / "data"),
        frontend_dir=str(directory / "dist"),
        serve_frontend=False,
        frontend_clean_output=False,
        backup_directory=str(directory / "backups"),
        sqlite_timeout_seconds=0.05,
    )
    data["logging"]["directory"] = str(directory / "logs")
    data["service"]["pid_file"] = str(directory / "service.pid")
    data.update(overrides)
    path = directory / "settings.toml"
    save_config(path, data)
    return path


def settings_for(directory: Path, **overrides: object) -> Settings:
    return load_settings(write_config(directory, **overrides))
