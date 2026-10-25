"""Create independent projects behind scripts/create-project.sh using the standard library."""

import argparse
import copy
import json
import os
import re
import shlex
import shutil
import subprocess
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def update_toml(text: str, changes: dict[tuple[str, ...], object]) -> str:
    """Edit known settings without reformatting comments or unrelated TOML values."""
    expected = copy.deepcopy(tomllib.loads(text))
    for path, value in changes.items():
        section = expected
        for part in path[:-1]:
            section = section[part]
        if path[-1] not in section:
            raise ValueError(f"Missing TOML field: {'.'.join(path)}")
        section[path[-1]] = value

    lines = text.splitlines(keepends=True)
    result = []
    section = ()
    remaining = set(changes)
    index = 0
    while index < len(lines):
        line = lines[index]
        header = re.fullmatch(r"\s*\[([\w.-]+)\]\s*(?:#.*)?\n?", line)
        if header:
            section = tuple(header[1].split("."))
        assignment = re.match(r"\s*([\w-]+)\s*=\s*(.*)", line)
        path = (*section, assignment[1]) if assignment else None
        if path in remaining:
            expression = assignment[2] + "\n"
            while True:
                try:
                    tomllib.loads("value = " + expression)
                    break
                except tomllib.TOMLDecodeError:
                    index += 1
                    if index == len(lines):
                        raise ValueError(f"Unterminated TOML field: {'.'.join(path)}") from None
                    expression += lines[index]
            encoded = json.dumps(changes[path], ensure_ascii=False, allow_nan=False)
            result.append(f"{path[-1]} = {encoded}\n")
            remaining.remove(path)
        else:
            result.append(line)
        index += 1
    updated = "".join(result)
    if remaining or tomllib.loads(updated) != expected:
        raise ValueError("Unsupported TOML layout; no generated configuration was accepted.")
    return updated


def rename_lock_project(path: Path, old_name: str, new_name: str) -> None:
    """Rename only the virtual root record; retain all dependency versions and hashes."""
    text = path.read_text(encoding="utf-8")
    expected = copy.deepcopy(tomllib.loads(text))
    matches = [
        package
        for package in expected["package"]
        if package["name"] == old_name and package["source"] == {"virtual": "."}
    ]
    if len(matches) != 1:
        raise ValueError("Expected exactly one virtual local project in backend/uv.lock.")
    if new_name != old_name and any(package["name"] == new_name for package in expected["package"]):
        raise ValueError("Project name conflicts with a locked dependency.")
    matches[0]["name"] = new_name
    blocks = re.split(r"(?=^\[\[package\]\]\s*$)", text, flags=re.MULTILINE)
    for index, block in enumerate(blocks[1:], start=1):
        package = tomllib.loads(block)["package"][0]
        if package["name"] == old_name and package["source"] == {"virtual": "."}:
            blocks[index], count = re.subn(
                r"^name\s*=.*$",
                f"name = {json.dumps(new_name)}",
                block,
                count=1,
                flags=re.MULTILINE,
            )
            if count != 1:
                raise ValueError("Could not locate local project name in backend/uv.lock.")
    updated = "".join(blocks)
    if tomllib.loads(updated) != expected:
        raise ValueError("Refusing an unexpected dependency lockfile change.")
    path.write_text(updated, encoding="utf-8")


def relative_runtime_path(value: str, field: str) -> Path:
    path = (PROJECT_ROOT / value).resolve()
    if path == PROJECT_ROOT or not path.is_relative_to(PROJECT_ROOT):
        raise ValueError(f"{field} must be inside the scaffold before creating a project: {path}")
    return path.relative_to(PROJECT_ROOT)


def with_port(url: str, port: int) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username:
        raise ValueError(f"Expected a local HTTP URL in configuration: {url}")
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return parts._replace(netloc=f"{host}:{port}").geturl()


def copy_source(target: Path, excluded: list[Path]) -> None:
    if shutil.which("rsync") is None:
        raise ValueError("rsync is required to create a project.")
    command = [
        "rsync",
        "-a",
        "--exclude=.git",
        "--exclude=.env*",
        "--exclude=.secrets*",
        f"--exclude-from={PROJECT_ROOT / '.gitignore'}",
    ]
    for path in excluded:
        pattern = re.sub(r"([\\*?\[\]])", r"\\\1", path.as_posix())
        command.append(f"--exclude=/{pattern}")
    subprocess.run([*command, f"{PROJECT_ROOT}/", f"{target}/"], check=True)
    for path in target.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(target):
            raise ValueError(f"Copied symlink points outside the new project: {path}")


def ignore_runtime_paths(target: Path, directories: list[Path], pid: Path) -> None:
    paths = [(path, "/") for path in directories]
    paths.extend(((pid, ""), (pid.with_suffix(pid.suffix + ".lock"), "")))
    patterns = []
    for path, suffix in paths:
        if "\n" in str(path) or "\r" in str(path):
            raise ValueError("Runtime paths cannot contain line breaks.")
        escaped = re.sub(r"([\\*?\[\]])", r"\\\1", path.as_posix())
        patterns.append(f"/{escaped}{suffix}")
    ignore = target / ".gitignore"
    text = ignore.read_text(encoding="utf-8")
    additions = [pattern for pattern in patterns if pattern not in text.splitlines()]
    if additions:
        ignore.write_text(
            text.rstrip()
            + "\n\n# Configured runtime paths for this project.\n"
            + "\n".join(additions)
            + "\n",
            encoding="utf-8",
        )


def update_documents(target: Path, name: str, settings: dict, vite_port: int, port: int) -> None:
    old_title = settings["application"]["title"]
    ports = {settings["server"]["port"]: port, settings["vite"]["port"]: vite_port}
    pattern = r"(?<!\d)(?:" + "|".join(map(str, ports)) + r")(?!\d)"
    for relative in ("README.md", "AGENTS.md", "docs/design.md", "docs/configuration.md"):
        path = target / relative
        text = path.read_text(encoding="utf-8")
        if relative == "README.md" and "## 基于脚手架创建新项目\n" in text:
            start = text.index("## 基于脚手架创建新项目\n")
            end = text.index("## 配置文件\n", start)
            text = text[:start] + text[end:]
        text = text.replace(str(PROJECT_ROOT), str(target)).replace(old_title, name)
        text = re.sub(pattern, lambda match: str(ports[int(match[0])]), text)
        path.write_text(text, encoding="utf-8")
    history = target / "docs/history.md"
    text = history.read_text(encoding="utf-8")
    history.write_text(
        f"> 继承自 {old_title} 的验证记录；不代表新项目 {name} 已完成验证。\n\n" + text,
        encoding="utf-8",
    )


def create_project(name: str, target: Path, port: int, vite_port: int | None) -> int:
    settings = read_toml(PROJECT_ROOT / "configs/app.toml")
    if vite_port is None:
        vite_port = settings["vite"]["port"]
    if port == vite_port:
        raise ValueError("Backend and Vite ports must be different.")
    if settings["server"]["port"] == settings["vite"]["port"]:
        raise ValueError("Template backend and Vite ports must be different.")
    if os.path.lexists(target):
        raise ValueError(f"Target already exists; nothing was overwritten: {target}")
    target = target.resolve()
    if target.is_relative_to(PROJECT_ROOT):
        raise ValueError("Target must be outside the scaffold directory.")

    paths = {
        ("data_dir",): relative_runtime_path(settings["data_dir"], "data_dir"),
        ("backup_directory",): relative_runtime_path(
            settings["backup_directory"], "backup_directory"
        ),
        ("frontend_dir",): relative_runtime_path(settings["frontend_dir"], "frontend_dir"),
        ("logging", "directory"): relative_runtime_path(
            settings["logging"]["directory"], "logging.directory"
        ),
        ("service", "pid_file"): relative_runtime_path(
            settings["service"]["pid_file"], "service.pid_file"
        ),
    }
    testing_directory = (PROJECT_ROOT / settings["testing"]["temporary_directory"]).resolve()
    if testing_directory.is_relative_to(PROJECT_ROOT):
        paths[("testing", "temporary_directory")] = relative_runtime_path(
            settings["testing"]["temporary_directory"], "testing.temporary_directory"
        )
    pid = paths[("service", "pid_file")]
    changes = {field: path.as_posix() for field, path in paths.items()}
    changes.update(
        {
            ("application", "title"): name,
            ("server", "port"): port,
            ("service", "pid_file"): (pid.parent / f"{name}.pid").as_posix(),
            ("vite", "port"): vite_port,
            ("vite", "proxy_target"): with_port(settings["vite"]["proxy_target"], port),
        }
    )
    origin_ports = {settings["server"]["port"]: port, settings["vite"]["port"]: vite_port}
    changes[("allowed_origins",)] = [
        with_port(origin, origin_ports[urlsplit(origin).port])
        if urlsplit(origin).port in origin_ports
        else origin
        for origin in settings["allowed_origins"]
    ]
    config = update_toml((PROJECT_ROOT / "configs/app.toml").read_text(encoding="utf-8"), changes)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    try:
        copy_source(target, [*paths.values(), pid.with_suffix(pid.suffix + ".lock")])
        (target / "configs/app.toml").write_text(config, encoding="utf-8")
        ignore_runtime_paths(
            target,
            [path for field, path in paths.items() if field != ("service", "pid_file")],
            Path(changes[("service", "pid_file")]),
        )
        metadata = target / "backend/pyproject.toml"
        old_name = read_toml(metadata)["project"]["name"]
        metadata.write_text(
            update_toml(
                metadata.read_text(encoding="utf-8"),
                {
                    ("project", "name"): f"{name}-backend",
                    ("project", "description"): f"{name}: a local FastAPI and SQLite application",
                },
            ),
            encoding="utf-8",
        )
        rename_lock_project(target / "backend/uv.lock", old_name, f"{name}-backend")
        package_path = target / "frontend/package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package["name"] = f"{name}-frontend"
        package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n")
        update_documents(target, name, settings, vite_port, port)
        subprocess.run(
            ["uv", "lock", "--directory", str(target / "backend"), "--check", "--offline"],
            check=True,
        )
    except BaseException:
        shutil.rmtree(target)
        raise
    return vite_port


def project_name(value: str) -> str:
    if len(value) > 63 or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", value):
        raise argparse.ArgumentTypeError(
            "Use 1-63 lowercase letters, digits or hyphens; start with a letter."
        )
    return value


def port_number(value: str) -> int:
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 65535:
        raise argparse.ArgumentTypeError("Port must be an integer from 1 to 65535.")
    return int(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a clean independent full-stack project")
    parser.add_argument("--name", required=True, type=project_name)
    parser.add_argument(
        "--target-dir", required=True, type=Path, help="Final new project directory"
    )
    parser.add_argument("--port", required=True, type=port_number, help="Backend HTTP port")
    parser.add_argument(
        "--vite-port", type=port_number, help="Otherwise inherit vite.port from configs/app.toml"
    )
    args = parser.parse_args()
    try:
        vite_port = create_project(args.name, args.target_dir, args.port, args.vite_port)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Creation failed: {exc}\n")
    except KeyboardInterrupt:
        parser.exit(130, "Creation interrupted.\n")
    target = args.target_dir.resolve()
    print(f"Created: {target}")
    print(f"Application: {args.name}; backend port: {args.port}; Vite port: {vite_port}")
    print("Next commands:")
    print(f"  cd {shlex.quote(str(target))}")
    print("  uv sync --directory backend --frozen")
    print("  pnpm --dir frontend install --frozen-lockfile")
    print("  pnpm --dir frontend api:types")
    print("  pnpm --dir frontend build")
    print("  uv run --directory backend python -m app.cli db-upgrade")
    print("  sh scripts/service.sh start")


if __name__ == "__main__":
    main()
