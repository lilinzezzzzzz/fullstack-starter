#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
project_dir=$(CDPATH= cd "$script_dir/.." && pwd)
python_version=$(cat "$project_dir/backend/.python-version")

# 创建项目仅需指定版本的 Python 标准库，无需安装应用依赖。
exec uv run --no-project --no-env-file --python "$python_version" \
  python "$script_dir/create_project.py" "$@"
