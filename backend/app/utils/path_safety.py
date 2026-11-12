"""供配置校验和项目创建共用的标准库路径策略。

比较路径时刻意忽略大小写。项目支持 macOS，其默认文件系统不区分大小写，
而 ``Path.resolve`` 会保留调用方提供的大小写。若将仅大小写不同的路径视为
不同路径，源代码目录或运行时目录就可能绕过下方的保护检查。
"""

from pathlib import Path

SOURCE_DIRECTORIES = (
    "backend",
    "frontend",
    "scripts",
    "configs",
    "docs",
    "e2e",
    ".git",
    ".agents",
    ".codex",
    ".aws",
)
SOURCE_FILES = ("AGENTS.md", "README.md", ".gitignore", ".editorconfig", ".node-version")
RESERVED_RUNTIME_DIRECTORIES = (
    "data",
    ".data",
    "logs",
    ".run",
    ".venv",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
)
DEPENDENCY_DIRECTORIES = (".venv", "node_modules", ".pytest_cache", ".ruff_cache")


def _folded_parts(path: str | Path) -> tuple[str, ...]:
    return tuple(part.casefold() for part in Path(path).resolve().parts)


def paths_equal(first: str | Path, second: str | Path) -> bool:
    """比较解析后的路径，防止仅大小写不同的别名绕过策略。"""
    return _folded_parts(first) == _folded_parts(second)


def path_is_relative_to(path: str | Path, parent: str | Path) -> bool:
    """忽略大小写，判断 ``path`` 是否为 ``parent`` 本身或其子路径。"""
    child_parts = _folded_parts(path)
    parent_parts = _folded_parts(parent)
    return (
        len(child_parts) >= len(parent_parts) and child_parts[: len(parent_parts)] == parent_parts
    )


def paths_overlap(first: str | Path, second: str | Path) -> bool:
    return path_is_relative_to(first, second) or path_is_relative_to(second, first)


def same_entry(first: str | Path, second: str | Path) -> bool:
    """文件系统条目存在时比较条目，否则精确比较路径。"""
    first_path = Path(first).resolve()
    second_path = Path(second).resolve()
    try:
        return first_path.samefile(second_path)
    except OSError:
        return first_path == second_path


def validate_runtime_paths(
    project_root: Path,
    *,
    frontend_dir: str | Path,
    frontend_clean_output: bool,
    data_dir: str | Path,
    backup_directory: str | Path,
    logging_directory: str | Path,
    temporary_directory: str | Path,
    database_filename: str,
    logging_filename: str,
) -> None:
    project_root = project_root.resolve()
    public = (project_root / frontend_dir).resolve()
    raw_default_output = project_root / "frontend/dist"
    default_output = raw_default_output.resolve()
    if frontend_clean_output and (
        raw_default_output.is_symlink()
        or not path_is_relative_to(default_output, project_root)
        or not (path_is_relative_to(public, default_output) and same_entry(public, default_output))
    ):
        raise ValueError("Automatic output cleaning is only allowed for frontend/dist")

    private_paths = {
        "data_dir": (project_root / data_dir).resolve(),
        "backup_directory": (project_root / backup_directory).resolve(),
        "logging.directory": (project_root / logging_directory).resolve(),
    }
    source_paths = [project_root / name for name in (*SOURCE_DIRECTORIES, *SOURCE_FILES)]
    protected_paths = [
        *source_paths,
        *(project_root / name for name in RESERVED_RUNTIME_DIRECTORIES),
    ]
    for field, path in {"frontend_dir": public, **private_paths}.items():
        candidates = protected_paths if field == "frontend_dir" else source_paths
        for protected in candidates:
            # frontend/ 内仅允许实际的 frontend/dist 子树存放公开构建产物。
            if field == "frontend_dir" and paths_equal(protected, project_root / "frontend"):
                if path_is_relative_to(path, default_output):
                    continue
            if paths_overlap(path, protected):
                raise ValueError(
                    f"{field} overlaps protected project source or runtime path: {protected.name}"
                )

    for field, path in private_paths.items():
        if paths_overlap(public, path):
            raise ValueError("Frontend output must not overlap private data or runtime paths")
        for dependency in DEPENDENCY_DIRECTORIES:
            if paths_overlap(path, project_root / dependency):
                raise ValueError(f"{field} overlaps protected dependency directory: {dependency}")

    database_path = Path(private_paths["data_dir"]) / database_filename
    file_paths = {
        "database": database_path,
        "database lock": database_path.with_suffix(database_path.suffix + ".lock"),
        "application log": Path(private_paths["logging.directory"]) / logging_filename,
    }
    items = list(file_paths.items())
    for index, (first_name, first_path) in enumerate(items):
        for second_name, second_path in items[index + 1 :]:
            if paths_equal(first_path, second_path):
                raise ValueError(f"{first_name} and {second_name} must not use the same file path")

    temporary = (project_root / temporary_directory).resolve()
    # 此处是 mkdtemp 的父目录，不由运行器管理或删除。
    # /tmp 等外部父目录中可能包含已生成的项目。
    if paths_equal(temporary, project_root) or any(
        path_is_relative_to(temporary, source) for source in source_paths
    ):
        raise ValueError("testing.temporary_directory must not be inside project source")
    if path_is_relative_to(temporary, public):
        raise ValueError("Testing artifacts must not be inside the public frontend directory")
