#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
project_dir=$(CDPATH= cd "$script_dir/../.." && pwd)

exec uv run --directory "$project_dir/backend" python -m entrypoints.service "$@"
