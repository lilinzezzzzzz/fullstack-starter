import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from uuid import uuid4

import pytest
import tomli_w

from app.config import PROJECT_ROOT


def arguments(target: Path, name: str, port: str) -> list[str]:
    return ["--name", name, "--target-dir", str(target), "--port", port]


def run_creator(script: Path, cwd: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(script), *arguments], cwd=cwd, capture_output=True, text=True, timeout=30
    )


def exported_settings(project: Path) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "export-settings"],
        cwd=project / "backend",
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return json.loads(result.stdout)


def test_create_project_is_clean_independent_and_keeps_locked_dependencies(tmp_path: Path) -> None:
    target = tmp_path / "directory with spaces 中文" / "my application"
    protected = (
        ".gitignore",
        "configs/app.toml",
        "backend/pyproject.toml",
        "backend/uv.lock",
        "frontend/package.json",
        "frontend/pnpm-lock.yaml",
    )
    before = {name: (PROJECT_ROOT / name).read_bytes() for name in protected}
    result = run_creator(
        PROJECT_ROOT / "scripts/create-project.sh",
        tmp_path,
        [*arguments(target, "ledger-app", "18123"), "--vite-port", "5182"],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    settings = exported_settings(target)
    assert settings["application"]["title"] == "ledger-app"
    assert settings["server"]["port"] == 18123
    assert settings["vite"]["port"] == 5182
    assert settings["vite"]["proxy_target"] == "http://127.0.0.1:18123"
    assert "http://127.0.0.1:5182" in settings["allowed_origins"]
    assert "http://localhost:18123" in settings["allowed_origins"]
    assert Path(settings["data_dir"]) == target.resolve() / "data"
    assert Path(settings["service"]["pid_file"]) == target.resolve() / "ledger-app.pid"
    assert Path(settings["logging"]["directory"]) == target.resolve() / "logs"
    for relative in (
        "data",
        "logs",
        ".git",
        "fullstack-starter.pid.lock",
        "backend/.venv",
        "frontend/node_modules",
        "frontend/.pnpm-store",
        "frontend/dist",
    ):
        assert not (target / relative).exists(), relative
    assert (target / "backend/migrations/versions/0001_baseline.py").is_file()
    assert (target / "scripts/create_project.py").is_file()
    assert (target / "backend/tools/__init__.py").is_file()
    assert (target / "backend/tools/service_control.py").is_file()
    assert not (target / "backend/app/scaffold.py").exists()
    assert not (target / "backend/app/service.py").exists()
    assert (target / "frontend/src/types/api.generated.d.ts").is_file()
    assert (target / ".gitignore").is_file()
    assert "Every application setting is required" in (target / "configs/app.toml").read_text()
    assert (
        json.loads((target / "frontend/package.json").read_text())["name"] == "ledger-app-frontend"
    )
    original_lock = tomllib.loads(before["backend/uv.lock"].decode())
    generated_lock = tomllib.loads((target / "backend/uv.lock").read_text())
    original_packages = {
        package["name"]: package
        for package in original_lock["package"]
        if package["source"] != {"virtual": "."}
    }
    generated_packages = {
        package["name"]: package
        for package in generated_lock["package"]
        if package["source"] != {"virtual": "."}
    }
    assert generated_packages == original_packages
    assert (target / "frontend/pnpm-lock.yaml").read_bytes() == before["frontend/pnpm-lock.yaml"]
    assert (target / "README.md").read_text().startswith("# ledger-app\n")
    assert "http://127.0.0.1:18123/" in (target / "README.md").read_text()
    assert "不代表新项目 ledger-app 已完成验证" in (target / "docs/history.md").read_text()
    assert all((PROJECT_ROOT / name).read_bytes() == data for name, data in before.items())


@pytest.mark.parametrize(
    "options",
    [
        ["--name", "Bad_Name"],
        ["--name", "../escape"],
        ["--port", "0"],
        ["--port", "65536"],
        ["--port", "not-a-number"],
        ["--vite-port", "18123"],
    ],
)
def test_invalid_project_arguments_do_not_create_a_target(
    tmp_path: Path, options: list[str]
) -> None:
    target = tmp_path / "must-not-exist"
    result = run_creator(
        PROJECT_ROOT / "scripts/create-project.sh",
        tmp_path,
        [*arguments(target, "sample-app", "18123"), *options],
    )
    assert result.returncode != 0
    assert not target.exists()


def test_relative_target_is_resolved_from_callers_working_directory(tmp_path: Path) -> None:
    result = run_creator(
        PROJECT_ROOT / "scripts/create-project.sh",
        tmp_path,
        arguments(Path("nested/new-project"), "relative-app", "18123"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    target = tmp_path / "nested/new-project"
    assert (target / "configs/app.toml").is_file()
    assert exported_settings(target)["application"]["title"] == "relative-app"


@pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
def test_existing_targets_are_never_overwritten(tmp_path: Path, kind: str) -> None:
    target = tmp_path / "existing"
    marker = tmp_path / "marker"
    marker.write_text("keep")
    if kind == "directory":
        target.mkdir()
        (target / "content").write_text("keep")
    elif kind == "file":
        target.write_text("keep")
    else:
        target.symlink_to(marker)
    result = run_creator(
        PROJECT_ROOT / "scripts/create-project.sh",
        tmp_path,
        arguments(target, "sample-app", "18123"),
    )
    assert result.returncode == 1
    assert "already exists" in result.stderr
    assert marker.read_text() == "keep"
    if kind == "directory":
        assert list(target.iterdir()) == [target / "content"]
        assert (target / "content").read_text() == "keep"
    else:
        assert target.read_text() == "keep"


def test_target_inside_scaffold_is_rejected(tmp_path: Path) -> None:
    target = PROJECT_ROOT / f"rejected-creator-{uuid4().hex}"
    result = run_creator(
        PROJECT_ROOT / "scripts/create-project.sh",
        tmp_path,
        arguments(target, "sample-app", "18123"),
    )
    assert result.returncode == 1
    assert "outside the scaffold" in result.stderr
    assert not target.exists()


def test_failed_copy_removes_only_its_new_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "bin"
    binary.mkdir()
    rsync = binary / "rsync"
    rsync.write_text("#!/bin/sh\nexit 12\n")
    rsync.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary) + os.pathsep + os.environ["PATH"])
    marker = tmp_path / "keep"
    marker.write_text("keep")
    target = tmp_path / "failed-copy"
    result = run_creator(
        PROJECT_ROOT / "scripts/create-project.sh",
        tmp_path,
        arguments(target, "sample-app", "18123"),
    )
    assert result.returncode == 1
    assert not target.exists()
    assert marker.read_text() == "keep"


def test_reusing_generated_project_excludes_custom_paths_and_rebases_absolute_paths(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    result = run_creator(
        PROJECT_ROOT / "scripts/create-project.sh",
        tmp_path,
        arguments(first, "first-app", "18123"),
    )
    assert result.returncode == 0, result.stderr
    with (first / "configs/app.toml").open("rb") as handle:
        config = tomllib.load(handle)
    with (PROJECT_ROOT / "configs/app.toml").open("rb") as handle:
        source = tomllib.load(handle)
    assert config["vite"]["port"] == source["vite"]["port"]
    for field, directory in (
        ("data_dir", "custom/storage"),
        ("backup_directory", "custom/snapshots"),
        ("frontend_dir", "custom/output"),
    ):
        config[field] = str(first / directory)
        (first / directory).mkdir(parents=True)
        (first / directory / "private").write_text("must not copy")
    config["frontend_clean_output"] = False
    config["logging"]["directory"] = str(first / "custom/logs")
    (first / "custom/logs").mkdir()
    (first / "custom/logs/private").write_text("must not copy")
    config["service"]["pid_file"] = str(first / "custom/service.custom")
    (first / "custom/service.custom").write_text("12345")
    (first / "custom/service.custom.lock").touch()
    (first / "configs/app.toml").write_text(tomli_w.dumps(config))
    second = tmp_path / "second"
    port = config["vite"]["port"]
    result = run_creator(
        first / "scripts/create-project.sh",
        tmp_path,
        [*arguments(second, "second-app", str(port)), "--vite-port", str(port + 1)],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    settings = exported_settings(second)
    assert Path(settings["data_dir"]) == second.resolve() / "custom/storage"
    assert Path(settings["service"]["pid_file"]) == second.resolve() / "custom/second-app.pid"
    assert not list(second.rglob("private"))
    assert not (second / "custom/service.custom").exists()
    assert not (second / "custom/service.custom.lock").exists()
    assert f"http://127.0.0.1:{port}/" in (second / "README.md").read_text()
    subprocess.run(["git", "init", "--quiet"], cwd=second, check=True, capture_output=True)
    ignored = subprocess.run(
        [
            "git",
            "check-ignore",
            "--no-index",
            "custom/storage/app.sqlite3",
            "custom/snapshots/backup.sqlite3",
            "custom/output/index.html",
            "custom/logs/app.log",
            "custom/second-app.pid",
            "custom/second-app.pid.lock",
        ],
        cwd=second,
        check=True,
        capture_output=True,
        text=True,
    )
    assert len(ignored.stdout.splitlines()) == 6


def test_external_runtime_path_is_rejected_without_touching_its_data(tmp_path: Path) -> None:
    template = tmp_path / "template"
    result = run_creator(
        PROJECT_ROOT / "scripts/create-project.sh",
        tmp_path,
        arguments(template, "template-app", "18123"),
    )
    assert result.returncode == 0, result.stderr
    outside = tmp_path / "external-data"
    outside.mkdir()
    marker = outside / "keep"
    marker.write_text("keep")
    path = template / "configs/app.toml"
    config = tomllib.loads(path.read_text())
    config["data_dir"] = str(outside)
    path.write_text(tomli_w.dumps(config))
    target = tmp_path / "rejected"
    result = run_creator(
        template / "scripts/create-project.sh",
        tmp_path,
        arguments(target, "sample-app", "18124"),
    )
    assert result.returncode == 1
    assert "data_dir must be inside" in result.stderr
    assert not target.exists()
    assert marker.read_text() == "keep"
