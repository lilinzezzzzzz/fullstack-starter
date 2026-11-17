#!/bin/sh
# 唯一服务入口；运维负责串行执行，不提供并发锁。
set -eu
umask 077
# 固定启动参数；创建器和隔离测试只修改各自副本中的端口常量。
server_host=127.0.0.1
server_port=18001
graceful_shutdown_seconds=10
project_dir=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
state_dir=$project_dir/.run
record_file=$state_dir/instance.json
system=$(uname -s)
file_owner=$(id -u)
fail() { echo "Error: $*" >&2; exit 1; }
case "${1-}" in
    run|start|status|stop|restart) action=$1; shift ;;
    *) echo 'Usage: service.sh run|start|status|stop|restart [--config FILE]' >&2; exit 2 ;;
esac
config=$project_dir/configs/app.toml
while [ "$#" -gt 0 ]; do
    case "$1" in
        --config)
            [ "$#" -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
            case "$2" in /*) path=$2 ;; *) path=$project_dir/$2 ;; esac
            config=$path
            shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done
command -v jq >/dev/null || fail 'jq is required'
check_files() {
    [ ! -L "$state_dir" ] && { [ ! -e "$state_dir" ] || [ -d "$state_dir" ]; } || fail '.run must be a real directory'
    for file in "$state_dir/instance.json.pending" "$state_dir/console.log" "$record_file"; do
        [ ! -L "$file" ] || fail "Runtime file must not be a symlink: $file"
        if [ -e "$file" ]; then
            metadata=
            if [ -f "$file" ]; then
                case "$system" in
                    Darwin) metadata=$(stat -f '%u %Lp' "$file" 2>/dev/null) || metadata= ;;
                    Linux) metadata=$(stat -c '%u %a' "$file" 2>/dev/null) || metadata= ;;
                    *) fail "Unsupported platform: $system" ;;
                esac
            fi
            if [ "$metadata" != "$file_owner 600" ]; then
                # 子进程可在父进程轮询时发布 pending；最终记录随后单独检查。
                if [ "$file" = "$state_dir/instance.json.pending" ] && [ ! -e "$file" ] && [ ! -L "$file" ]; then continue; fi
                fail "Runtime file must be regular, owned by this user with mode 0600: $file"
            fi
        fi
    done
}
process_started_at() {
    if process_info=$(LC_ALL=C TZ=UTC ps -p "$1" -o lstart= -o stat= 2>/dev/null); then :
    else code=$?; [ "$code" -eq 1 ] && return 3; fail 'Cannot inspect process'; fi
    read -r weekday month day clock year state <<EOF
$process_info
EOF
    [ -n "$state" ] || return 3
    case "$state" in Z*) return 3 ;; esac
    printf '%s %s %s %s %s\n' "$weekday" "$month" "$day" "$clock" "$year"
}
load_record() {
    check_files
    [ -f "$record_file" ] || return 3
    [ "$(wc -c <"$record_file" | tr -d ' ')" -le 16384 ] || fail 'Instance record is too large'
    record=$(jq -ce '
        select(type == "object" and keys == (["format","pid","started_at","config","url","log","stop_timeout"]|sort))
        | select(.format == 3 and (.pid|type) == "number" and .pid > 1 and .pid == (.pid|floor))
        | select(all(.started_at,.config,.url,.log; type == "string") and (.started_at|length) > 0)
        | select((.stop_timeout|type) == "number" and .stop_timeout > 0 and (.stop_timeout|isfinite))
        | select(.url|test("^http://[^/@?#\\s]+:[0-9]+$"))
    ' "$record_file") || fail 'Invalid or obsolete instance record; no signal sent'
    record_pid=$(printf '%s' "$record" | jq -r '.pid')
    record_started=$(printf '%s' "$record" | jq -r '.started_at')
}
read_record() {
    load_record || return "$?"
    if actual_started=$(process_started_at "$record_pid"); then :; else return "$?"; fi
    [ "$actual_started" = "$record_started" ] || fail 'Instance startup time mismatch; no signal sent'
}
describe() { printf '%s' "$record" | jq -r '"PID \(.pid); \(.url)/\nConfig: \(.config)\nLog: \(.log)"'; }
healthy() {
    url=$(printf '%s' "$record" | jq -r '.url')
    port=${url##*:}
    listeners=$(lsof -nP -a -p "$record_pid" -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null) || return 1
    printf '%s\n' "$listeners" | grep -qx "$record_pid" || return 1
    body=$(curl --silent --fail --noproxy '*' --connect-timeout 1 --max-time 1 "$url/api/health") || return 1
    printf '%s' "$body" | jq -e '. == {"status":"ok","database":"ok"}' >/dev/null
}
timer_pid=
child_pid=
child_started=
stop_timeout=1
stop_timer() {
    if [ -n "$timer_pid" ]; then
        parent=$(ps -p "$timer_pid" -o ppid= 2>/dev/null | tr -d ' ') || parent=
        if [ "$parent" = "$$" ]; then kill -TERM "$timer_pid" 2>/dev/null || :; fi
        wait "$timer_pid" 2>/dev/null || :
        timer_pid=
    fi
}
start_timer() { stop_timer; sleep "$1" & timer_pid=$!; }
expired() { ! kill -0 "$timer_pid" 2>/dev/null; }
wait_for_exit() {
    start_timer "$3"
    while :; do
        if actual_started=$(process_started_at "$1"); then
            [ "$actual_started" = "$2" ] || break
        else
            code=$?
            [ "$code" -eq 3 ] || { stop_timer; fail 'Cannot confirm process exit after inspection failure'; }
            break
        fi
        if expired; then stop_timer; return 1; fi
        sleep 0.1
    done
    stop_timer
}
cancel_child() {
    [ -n "$child_pid" ] || return 0
    parent=$(ps -p "$child_pid" -o ppid= 2>/dev/null | tr -d ' ') || parent=
    if [ "$parent" = "$$" ]; then
        if [ -z "$child_started" ]; then child_started=$(process_started_at "$child_pid") || child_started=; fi
        kill -TERM "$child_pid" 2>/dev/null || :
        wait_for_exit "$child_pid" "$child_started" "$stop_timeout" || echo "Startup cleanup timed out; PID $child_pid retained without SIGKILL" >&2
    fi
    # 未确认退出时不阻塞 wait，也不强杀。
    if ! kill -0 "$child_pid" 2>/dev/null; then wait "$child_pid" 2>/dev/null || :; fi
}
on_interrupt() { trap '' INT TERM; exit "$1"; }
on_exit() {
    trap '' INT TERM
    stop_timer
    if [ -n "$child_pid" ]; then cancel_child || :; fi
}
trap on_exit EXIT
trap 'on_interrupt 130' INT
trap 'on_interrupt 143' TERM
stop_service() {
    if read_record; then :; else code=$?; [ "$code" -eq 3 ] || return "$code"; echo stopped; return 0; fi
    target_pid=$record_pid
    target_started=$record_started
    target_timeout=$(printf '%s' "$record" | jq -r '.stop_timeout')
    # 检查与发信号之间仍有 PID 复用竞态；不按端口或孤立 PID 操作。
    if actual_started=$(process_started_at "$target_pid"); then
        [ "$actual_started" = "$target_started" ] || fail 'Instance startup time mismatch; no signal sent'
        kill -INT "$target_pid" 2>/dev/null || { kill -0 "$target_pid" 2>/dev/null && return 1; }
    else
        code=$?
        [ "$code" -eq 3 ] || return "$code"
    fi
    wait_for_exit "$target_pid" "$target_started" "$target_timeout" || fail 'Stop timed out; no force kill or restart performed'
    if load_record; then
        if [ "$record_pid" = "$target_pid" ] && [ "$record_started" = "$target_started" ]; then rm -f "$record_file"; fi
    else code=$?; [ "$code" -eq 3 ] || return "$code"; fi
    echo stopped
}
load_configuration() {
    python_executable=$(uv run --no-sync --directory "$project_dir/backend" python -c 'import sys; print(sys.executable)')
    settings=$(cd "$project_dir/backend" && "$python_executable" -m entrypoints.cli --config "$config" export-service-settings)
    printf '%s' "$settings" | jq -e --argjson grace "$graceful_shutdown_seconds" '.stop_timeout > $grace' >/dev/null || fail 'Stop timeout must exceed the Uvicorn graceful shutdown timeout'
    case "$server_host" in
        0.0.0.0) health_host=127.0.0.1 ;; ::) health_host='[::1]' ;;
        *:*) health_host="[$server_host]" ;; *) health_host=$server_host ;;
    esac
    settings=$(printf '%s' "$settings" | jq --arg url "http://$health_host:$server_port" '. + {url:$url}')
    config=$(printf '%s' "$settings" | jq -r '.config')
    startup_timeout=$(printf '%s' "$settings" | jq -r '.startup_timeout')
    stop_timeout=$(printf '%s' "$settings" | jq -r '.stop_timeout')
}
run_server() {
    # 清除继承入口，尤其是不传 --limit-concurrency 时，禁止环境变量设置上限。
    for key in $(env | sed -n 's/^\(UVICORN_[A-Z0-9_]*\)=.*/\1/p'); do unset "$key"; done
    unset WEB_CONCURRENCY FORWARDED_ALLOW_IPS
    export APP_CONFIG_FILE=$config
    # 前台 Shell 与 exec 后的 Uvicorn 保持同一 PID 和系统启动时间。
    started=$(process_started_at "$$") || fail 'Cannot establish service startup time'
    check_files
    mkdir -p "$state_dir"
    rm -f "$state_dir/instance.json.pending"
    ( set -C; printf '%s' "$settings" | jq --argjson pid "$$" --arg started "$started" \
        '{format:3,pid:$pid,started_at:$started,config:.config,url:.url,log:.log,stop_timeout:.stop_timeout}' \
        >"$state_dir/instance.json.pending" ) || fail 'Cannot write instance record'
    mv -f "$state_dir/instance.json.pending" "$record_file"
    cd "$project_dir/backend"
    exec "$python_executable" -m uvicorn entrypoints.api:app \
        --host "$server_host" --port "$server_port" --workers 1 \
        --timeout-graceful-shutdown "$graceful_shutdown_seconds" \
        --timeout-keep-alive 5 --backlog 2048 \
        --lifespan on --no-access-log --no-proxy-headers
}
case "$action" in
    status)
        if read_record; then describe; else code=$?; [ "$code" -eq 3 ] && echo stopped; exit "$code"; fi
        if healthy; then echo healthy; exit 0; else echo unhealthy; exit 1; fi ;;
    stop) stop_service; exit 0 ;;
    run|start)
        if read_record; then echo 'Service is already running'; describe; exit 0
        else code=$?; [ "$code" -eq 3 ] || exit "$code"; fi ;;
esac
load_configuration
if [ "$action" = run ]; then run_server; fi
if [ "$action" = restart ]; then stop_service; fi
check_files
mkdir -p "$state_dir"
( set -C; : >"$state_dir/console.log" ) 2>/dev/null || [ -f "$state_dir/console.log" ]
nohup sh "$project_dir/entrypoints/service.sh" run --config "$config" \
    </dev/null >>"$state_dir/console.log" 2>&1 &
child_pid=$!
child_started=$(process_started_at "$child_pid") || child_started=
start_timer "$startup_timeout"
while [ -n "$child_started" ] && actual_started=$(process_started_at "$child_pid"); do
    [ "$actual_started" = "$child_started" ] || break
    expired && break
    if read_record; then
        if [ "$record_pid" = "$child_pid" ] && healthy; then
            expired && break
            stop_timer; child_pid=; echo started; exit 0
        fi
    else code=$?; [ "$code" -eq 3 ] || break; fi
    expired && break
    sleep 0.1
done
trap '' INT TERM
fail "Service failed to start; inspect $state_dir/console.log and the configured application log"
