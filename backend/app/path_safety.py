"""Standard-library path policy shared by configuration and project creation.

Comparisons deliberately fold path case. The project supports macOS, whose
default filesystem is case-insensitive while ``Path.resolve`` preserves the
case supplied by the caller. Treating case-only aliases as distinct would let
a source or runtime directory bypass the protectors below.
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
    """Compare resolved paths without allowing case-only aliases to bypass policy."""
    return _folded_parts(first) == _folded_parts(second)


def path_is_relative_to(path: str | Path, parent: str | Path) -> bool:
    """Return whether ``path`` is ``parent`` or below it, ignoring path case."""
    child_parts = _folded_parts(path)
    parent_parts = _folded_parts(parent)
    return (
        len(child_parts) >= len(parent_parts) and child_parts[: len(parent_parts)] == parent_parts
    )


def paths_overlap(first: str | Path, second: str | Path) -> bool:
    return path_is_relative_to(first, second) or path_is_relative_to(second, first)


def same_entry(first: str | Path, second: str | Path) -> bool:
    """Compare filesystem entries when they exist, otherwise compare exact paths."""
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
    pid_file: str | Path,
    temporary_directory: str | Path,
    database_filename: str,
    logging_filename: str,
    bootstrap_filename: str,
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
        "service.pid_file": (project_root / pid_file).resolve(),
    }
    source_paths = [project_root / name for name in (*SOURCE_DIRECTORIES, *SOURCE_FILES)]
    protected_paths = [
        *source_paths,
        *(project_root / name for name in RESERVED_RUNTIME_DIRECTORIES),
    ]
    for field, path in {"frontend_dir": public, **private_paths}.items():
        candidates = protected_paths if field == "frontend_dir" else source_paths
        for protected in candidates:
            # Only the real frontend/dist subtree may hold public output inside frontend/.
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
        if field in {
            "data_dir",
            "backup_directory",
            "logging.directory",
            "service.pid_file",
        }:
            for dependency in DEPENDENCY_DIRECTORIES:
                if paths_overlap(path, project_root / dependency):
                    raise ValueError(
                        f"{field} overlaps protected dependency directory: {dependency}"
                    )

    pid_path = Path(private_paths["service.pid_file"])
    if any(
        paths_equal(pid_path, directory)
        for directory in (
            project_root,
            private_paths["data_dir"],
            private_paths["backup_directory"],
            private_paths["logging.directory"],
        )
    ):
        raise ValueError("service.pid_file must not point at a configured directory")

    file_paths = {
        "database": Path(private_paths["data_dir"]) / database_filename,
        "application log": Path(private_paths["logging.directory"]) / logging_filename,
        "bootstrap log": Path(private_paths["logging.directory"]) / bootstrap_filename,
        "service PID": pid_path,
    }
    items = list(file_paths.items())
    for index, (first_name, first_path) in enumerate(items):
        for second_name, second_path in items[index + 1 :]:
            if paths_equal(first_path, second_path):
                raise ValueError(f"{first_name} and {second_name} must not use the same file path")

    temporary = (project_root / temporary_directory).resolve()
    if paths_equal(pid_path, temporary):
        raise ValueError("service.pid_file must not point at the testing directory")
    # This is a parent for mkdtemp, not a directory owned or deleted by the runner.
    # An external parent such as /tmp may contain a generated project.
    if paths_equal(temporary, project_root) or any(
        path_is_relative_to(temporary, source) for source in source_paths
    ):
        raise ValueError("testing.temporary_directory must not be inside project source")
    if path_is_relative_to(temporary, public):
        raise ValueError("Testing artifacts must not be inside the public frontend directory")
