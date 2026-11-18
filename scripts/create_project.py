"""使用标准库实现 scripts/create-project.sh 的独立项目创建功能。"""

import argparse
import copy
import importlib.util
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
VITE_CONFIG = Path("frontend/configs/vite.toml")


def load_path_policy():
    # 仅加载基于标准库的共享路径策略；创建项目无需应用依赖。
    spec = importlib.util.spec_from_file_location(
        "scaffold_path_safety", PROJECT_ROOT / "backend/app/utils/path_safety.py"
    )
    if spec is None or spec.loader is None:
        raise ValueError("The scaffold path policy is missing.")
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    return policy


PATH_POLICY = load_path_policy()


def read_service_port() -> int:
    try:
        script = (PROJECT_ROOT / "entrypoints/service.sh").read_text()
    except FileNotFoundError as exc:
        raise ValueError("Template is missing required files: entrypoints/service.sh") from exc
    values = re.findall(
        r"^server_port=([0-9]+)$",
        script,
        re.MULTILINE,
    )
    if len(values) != 1 or not 1 <= int(values[0]) <= 65535:
        raise ValueError("Template server_port must be one integer from 1 to 65535")
    return int(values[0])


def read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def update_toml(text: str, changes: dict[tuple[str, ...], object]) -> str:
    """修改已知配置项，保留注释和无关 TOML 值的原有格式。"""
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
    """仅重命名虚拟根包记录，保留所有依赖的版本和哈希。"""
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
    if PATH_POLICY.paths_equal(path, PROJECT_ROOT) or not PATH_POLICY.path_is_relative_to(
        path, PROJECT_ROOT
    ):
        raise ValueError(f"{field} must be inside the scaffold before creating a project: {path}")
    return path.relative_to(PROJECT_ROOT)


def with_port(url: str, port: int) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username:
        raise ValueError(f"Expected a local HTTP URL in configuration: {url}")
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return parts._replace(netloc=f"{host}:{port}").geturl()


def validate_template_shape(settings: dict) -> None:
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(message)

    def valid_filename(value: object) -> bool:
        return (
            isinstance(value, str)
            and bool(value)
            and value not in {".", ".."}
            and "/" not in value
            and "\\" not in value
        )

    application = settings.get("application")
    require(
        isinstance(application, dict)
        and isinstance(application.get("title"), str)
        and bool(application["title"]),
        "Template application.title must be a non-empty string",
    )
    require(
        isinstance(settings.get("allowed_origins"), list)
        and all(isinstance(origin, str) for origin in settings["allowed_origins"]),
        "Template allowed_origins must be a list of strings",
    )
    for field in (
        "data_dir",
        "backup_directory",
        "frontend_dir",
        "database_filename",
        "serve_frontend",
        "frontend_clean_output",
    ):
        expected = bool if field in {"serve_frontend", "frontend_clean_output"} else str
        require(isinstance(settings.get(field), expected), f"Template {field} has an invalid type")
    require(
        valid_filename(settings.get("database_filename")),
        "Template database_filename must be a filename without directories",
    )
    logging_settings = settings.get("logging")
    require(
        isinstance(logging_settings, dict)
        and isinstance(logging_settings.get("directory"), str)
        and valid_filename(logging_settings.get("filename")),
        "Template logging directory must be a string and log filenames must be filenames",
    )
    testing = settings.get("testing")
    require(
        isinstance(testing, dict) and isinstance(testing.get("temporary_directory"), str),
        "Template testing.temporary_directory must be a string",
    )


def validate_template_paths(settings: dict) -> None:
    PATH_POLICY.validate_runtime_paths(
        PROJECT_ROOT,
        frontend_dir=settings["frontend_dir"],
        frontend_clean_output=settings["frontend_clean_output"],
        data_dir=settings["data_dir"],
        backup_directory=settings["backup_directory"],
        logging_directory=settings["logging"]["directory"],
        temporary_directory=settings["testing"]["temporary_directory"],
        database_filename=settings["database_filename"],
        logging_filename=settings["logging"]["filename"],
    )


ROOT_PROJECT_FILES = (
    "AGENTS.md",
    "README.md",
    ".gitignore",
    ".editorconfig",
    ".node-version",
    ".prettierrc.toml",
    ".prettierignore",
    "configs/app.toml",
    "backend/pyproject.toml",
    "backend/app/application.py",
    "backend/app/telemetry/adapter.py",
    "backend/app/utils/lazy_proxy.py",
    "backend/app/infra/__init__.py",
    "backend/app/infra/database.py",
    "backend/app/infra/errors.py",
    "backend/app/infra/frontend.py",
    "backend/app/infra/logging.py",
    "backend/app/infra/middleware.py",
    "backend/entrypoints/__init__.py",
    "backend/entrypoints/cli.py",
    "backend/entrypoints/api.py",
    "entrypoints/service.sh",
    "backend/uv.lock",
    "backend/alembic.ini",
    "backend/.python-version",
    "frontend/index.html",
    "frontend/package.json",
    "frontend/pnpm-lock.yaml",
    "frontend/vite.config.ts",
    "frontend/tsconfig.json",
    "frontend/eslint.config.js",
    "frontend/playwright.config.ts",
    "frontend/.npmrc",
)
SOURCE_TREE_ROOTS = (
    "entrypoints",
    "backend/app",
    "backend/migrations",
    "backend/entrypoints",
    "backend/tests",
    "configs",
    "docs",
    "scripts",
    "frontend/src",
    "frontend/scripts",
    "frontend/configs",
    "frontend/e2e",
    "frontend/public",
)


LEGACY_SERVICE_ENTRY = Path("backend/entrypoints/service.sh")


def _is_ignored_source(relative: Path) -> bool:
    if relative == LEGACY_SERVICE_ENTRY or LEGACY_SERVICE_ENTRY in relative.parents:
        return True
    if any(
        part.startswith(".") or part in {"__pycache__", ".pytest_cache", ".ruff_cache"}
        for part in relative.parts
    ):
        return True
    if relative.suffix in {".pyc", ".pyo"}:
        return True
    return relative.parts[0] == "configs" and ".local." in relative.name


def check_project_files(target: Path) -> None:
    entrypoints = target / "entrypoints"
    if entrypoints.is_symlink():
        raise ValueError("Root entrypoints must be a real directory")
    if entrypoints.is_dir():
        unexpected = sorted(
            path.name
            for path in entrypoints.iterdir()
            if path.name != "service.sh" or not path.is_file() or path.is_symlink()
        )
        if unexpected:
            raise ValueError(
                "Root entrypoints contains unsupported files: " + ", ".join(unexpected)
            )
    legacy = target / LEGACY_SERVICE_ENTRY
    if legacy.exists() or legacy.is_symlink():
        raise ValueError("Generated project contains obsolete backend/entrypoints/service.sh")
    missing_roots = [
        root_name for root_name in SOURCE_TREE_ROOTS if not (PROJECT_ROOT / root_name).is_dir()
    ]
    if missing_roots:
        raise ValueError(f"Template source roots are missing: {', '.join(missing_roots)}")

    relative_files = set(ROOT_PROJECT_FILES)
    for root_name in SOURCE_TREE_ROOTS:
        source_root = PROJECT_ROOT / root_name
        for source_file in source_root.rglob("*"):
            if not source_file.is_file():
                continue
            relative = source_file.relative_to(PROJECT_ROOT)
            if not _is_ignored_source(relative):
                relative_files.add(relative.as_posix())

    missing = sorted(name for name in relative_files if not (target / name).is_file())
    if missing:
        raise ValueError(f"Generated project is missing required files: {', '.join(missing)}")


def copy_source(target: Path, excluded: list[Path]) -> None:
    if shutil.which("rsync") is None:
        raise ValueError("rsync is required to create a project.")
    command = [
        "rsync",
        "-a",
        "--exclude=.git",
        "--exclude=.venv",
        "--exclude=node_modules",
        "--exclude=.pnpm-store",
        # 记录可能缺失或残留，始终排除整个目录，也不继承旧版本的运行锁。
        "--exclude=/.run/",
        f"--exclude=/{LEGACY_SERVICE_ENTRY.as_posix()}",
        "--exclude=.env*",
        "--exclude=.secrets*",
        f"--exclude-from={PROJECT_ROOT / '.gitignore'}",
    ]
    for path in excluded:
        pattern = re.sub(r"([\\*?\[\]])", r"\\\1", path.as_posix())
        command.append(f"--exclude=/{pattern}")
    subprocess.run([*command, f"{PROJECT_ROOT}/", f"{target}/"], check=True)
    for path in target.rglob("*"):
        if path.is_symlink() and not PATH_POLICY.path_is_relative_to(path.resolve(), target):
            raise ValueError(f"Copied symlink points outside the new project: {path}")


def ignore_runtime_paths(target: Path, directories: list[Path]) -> None:
    paths = [(Path(".run"), "/"), *((path, "/") for path in directories)]
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


def update_documents(target: Path, name: str, old_title: str, ports: dict[int, int]) -> None:
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
    template_port = read_service_port()
    settings = read_toml(PROJECT_ROOT / "configs/app.toml")
    validate_template_shape(settings)
    validate_template_paths(settings)
    try:
        vite_text = (PROJECT_ROOT / VITE_CONFIG).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"Template is missing required files: {VITE_CONFIG}") from exc
    vite = tomllib.loads(vite_text)
    template_vite_port = vite.get("port")
    if type(template_vite_port) is not int or not 1 <= template_vite_port <= 65535:
        raise ValueError(f"Template {VITE_CONFIG} port must be an integer from 1 to 65535")
    proxy_target = vite.get("proxy_target")
    if not isinstance(proxy_target, str):
        raise ValueError(f"Template {VITE_CONFIG} proxy_target must be a string")
    if vite_port is None:
        vite_port = template_vite_port
    if port == vite_port:
        raise ValueError("Backend and Vite ports must be different.")
    if template_port == template_vite_port:
        raise ValueError("Template backend and Vite ports must be different.")
    if os.path.lexists(target):
        raise ValueError(f"Target already exists; nothing was overwritten: {target}")
    target = target.resolve()
    if PATH_POLICY.path_is_relative_to(target, PROJECT_ROOT):
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
    }
    testing_directory = (PROJECT_ROOT / settings["testing"]["temporary_directory"]).resolve()
    if PATH_POLICY.path_is_relative_to(testing_directory, PROJECT_ROOT):
        paths[("testing", "temporary_directory")] = relative_runtime_path(
            settings["testing"]["temporary_directory"], "testing.temporary_directory"
        )
    changes = {field: path.as_posix() for field, path in paths.items()}
    changes[("application", "title")] = name
    origin_ports = {
        template_port: port,
        template_vite_port: vite_port,
    }
    changes[("allowed_origins",)] = [
        with_port(origin, origin_ports[urlsplit(origin).port])
        if urlsplit(origin).port in origin_ports
        else origin
        for origin in settings["allowed_origins"]
    ]
    config = update_toml((PROJECT_ROOT / "configs/app.toml").read_text(encoding="utf-8"), changes)
    vite_config = update_toml(
        vite_text,
        {("port",): vite_port, ("proxy_target",): with_port(proxy_target, port)},
    )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    try:
        copy_source(target, list(paths.values()))
        check_project_files(target)
        (target / "configs/app.toml").write_text(config, encoding="utf-8")
        (target / VITE_CONFIG).write_text(vite_config, encoding="utf-8")
        service_entry = target / "entrypoints/service.sh"
        service_entry.write_text(
            re.sub(
                r"^server_port=[0-9]+$",
                f"server_port={port}",
                service_entry.read_text(),
                count=1,
                flags=re.MULTILINE,
            ),
            encoding="utf-8",
        )
        ignore_runtime_paths(target, list(paths.values()))
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
        update_documents(target, name, settings["application"]["title"], origin_ports)
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
        "--vite-port", type=port_number, help=f"Otherwise inherit port from {VITE_CONFIG}"
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
    print("  uv run --directory backend python -m entrypoints.cli db-check")
    print("  uv run --directory backend python -m entrypoints.cli db-upgrade")
    print("  sh entrypoints/service.sh run")


if __name__ == "__main__":
    main()
