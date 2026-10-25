#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
project_dir=$(CDPATH= cd "$script_dir/.." && pwd)
python_version=$(cat "$project_dir/backend/.python-version")

# Creation only needs the pinned Python standard library, not application dependencies.
exec uv run --no-project --no-env-file --python "$python_version" \
  python "$script_dir/create_project.py" "$@"
