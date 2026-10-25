#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
project_dir=$(CDPATH= cd "$script_dir/.." && pwd)

case "${1:-}" in
    start|stop|restart|status) ;;
    *) echo "Usage: sh scripts/service.sh {start|stop|restart|status} [--config FILE]" >&2; exit 2 ;;
esac

exec uv run --directory "$project_dir/backend" python -m tools.service_control "$@"
