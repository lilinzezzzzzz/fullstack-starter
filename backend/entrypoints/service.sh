#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
project_dir=$(CDPATH= cd "$script_dir/../.." && pwd)

# uv 仅定位预装解释器，不常驻转发信号；依赖由显式 uv sync 准备。
python_executable=$(uv run --no-sync --directory "$project_dir/backend" python -c 'import sys; print(sys.executable)')
cd "$project_dir/backend"
exec "$python_executable" -m entrypoints.service "$@"
