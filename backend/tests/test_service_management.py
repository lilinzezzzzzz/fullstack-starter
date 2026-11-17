import json
import os
import signal
import subprocess
import time

import pytest

from migrations.operations import upgrade_database
from tests.helpers import read_config, save_config
from tests.service_helpers import (
    command,
    insert_before_lifespan_yield,
    process_started_at,
    read_instance,
)

pytestmark = pytest.mark.integration


def ready_project(project):
    config = project / "configs/app.toml"
    upgrade_database()
    return config


def test_five_commands_and_configuration_independent_management(service_project):
    config = ready_project(service_project)
    assert command(service_project, "status").returncode == 3
    assert command(service_project, "stop").returncode == 0
    result = command(service_project, "start")
    assert result.returncode == 0, result.stdout + result.stderr
    initial = read_instance(service_project)
    assert command(service_project, "start", "--config", "missing.toml").returncode == 0
    assert command(service_project, "run", "--config", "missing.toml").returncode == 0
    assert read_instance(service_project) == initial
    assert command(service_project, "restart").returncode == 0
    assert read_instance(service_project)["pid"] != initial["pid"]
    config.unlink()
    assert command(service_project, "status").returncode == 0
    assert command(service_project, "stop").returncode == 0
    assert command(service_project, "status").returncode == 3


def test_invalid_restart_preserves_current_instance(service_project):
    config = ready_project(service_project)
    assert command(service_project, "start").returncode == 0
    initial = read_instance(service_project)
    original = config.read_text()
    config.write_text("bad = true\n")
    assert command(service_project, "restart").returncode == 1
    assert read_instance(service_project) == initial
    config.write_text(original)
    assert command(service_project, "status").returncode == 0


def test_restart_can_select_application_file(service_project, tmp_path):
    config = ready_project(service_project)
    assert command(service_project, "start").returncode == 0
    initial = read_instance(service_project)
    other = tmp_path / "alternate.toml"
    data = read_config(config)
    data["application"]["title"] = "new application"
    save_config(other, data)
    result = command(service_project, "restart", "--config", str(other))
    assert result.returncode == 0, result.stdout + result.stderr
    current = read_instance(service_project)
    assert current["config"] == str(other)
    assert current["url"] == initial["url"]
    assert command(service_project, "restart").returncode == 0
    assert read_instance(service_project)["config"] == str(config)


@pytest.mark.parametrize("field", ["pid", "started_at", "format"])
def test_identity_or_format_mismatch_never_signals(service_project, field):
    ready_project(service_project)
    assert command(service_project, "start").returncode == 0
    path = service_project / ".run/instance.json"
    original = path.read_bytes()
    record = json.loads(original)
    record[field] = {"pid": 1, "started_at": "different startup time", "format": 2}[field]
    try:
        path.write_text(json.dumps(record))
        assert command(service_project, "stop").returncode == 1
        assert command(service_project, "start").returncode == 1
    finally:
        path.write_bytes(original)
    assert command(service_project, "status").returncode == 0


def test_unknown_command_and_missing_arguments_are_usage_errors(service_project):
    for arguments in [("unknown",), ("api",), ("",), ("start", "--config"), ("start", "--unknown")]:
        assert command(service_project, *arguments).returncode == 2


def test_status_does_not_import_application_dependencies(service_project):
    # 若 status 导入应用包，此探针将直接失败；同时保持真实 Shell 路径。
    (service_project / "backend/app/__init__.py").write_text(
        "raise RuntimeError('application imported')\n"
    )
    result = command(service_project, "status")
    assert result.returncode == 3, result.stdout + result.stderr


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_interrupt_during_background_start_recovers_only_its_child(
    service_project, tmp_path, signum
):
    ready_project(service_project)
    insert_before_lifespan_yield(service_project, "import asyncio\nawait asyncio.sleep(2)\n")
    output = tmp_path / "start cancellation.log"
    with output.open("w") as stream:
        process = subprocess.Popen(
            ["sh", str(service_project / "entrypoints/service.sh"), "start"],
            stdout=stream,
            stderr=stream,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 8
            while not (service_project / ".run/instance.json").exists():
                assert process.poll() is None, output.read_text()
                assert time.monotonic() < deadline
                time.sleep(0.02)
            os.kill(process.pid, signum)
            assert process.wait(timeout=10) == 128 + signum, output.read_text()
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
                process.wait(timeout=8)
    assert read_instance(service_project) is None


def test_inherited_uvicorn_settings_cannot_enable_reload_or_override_unlimited_concurrency(
    service_project, tmp_path, monkeypatch
):
    ready_project(service_project)
    marker = tmp_path / "dotenv must not execute"
    (service_project / ".env").write_text(f"SERVER_PORT=1\nUNKNOWN=$(touch '{marker}')\n")
    monkeypatch.setenv("SERVER_PORT", "1")
    monkeypatch.setenv("UVICORN_RELOAD", "true")
    monkeypatch.setenv("UVICORN_LIMIT_CONCURRENCY", "1")
    monkeypatch.setenv("UVICORN_ENV_FILE", "/missing/external.env")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    result = command(service_project, "start")
    assert result.returncode == 0, result.stdout + result.stderr
    assert command(service_project, "status").returncode == 0
    assert not {"uid", "command", "project", "identity"} & read_instance(service_project).keys()
    assert not marker.exists()


def test_record_loss_is_not_hidden_by_another_lifetime_lock(service_project):
    ready_project(service_project)
    assert command(service_project, "start").returncode == 0
    path = service_project / ".run/instance.json"
    original = path.read_bytes()
    record = read_instance(service_project)
    try:
        path.unlink()
        assert process_started_at(record["pid"]) == record["started_at"]
        assert read_instance(service_project) is None
        assert command(service_project, "status").returncode == 3
        assert not (service_project / ".run/run.lock").exists()
    finally:
        path.write_bytes(original)
        path.chmod(0o600)
    assert command(service_project, "stop").returncode == 0


def test_no_management_lock_files_are_created_during_startup(service_project, tmp_path):
    ready_project(service_project)
    release = tmp_path / "continue startup"
    insert_before_lifespan_yield(
        service_project,
        "import asyncio\nfrom pathlib import Path\n"
        f"while not Path({str(release)!r}).exists():\n"
        "    await asyncio.sleep(0.02)\n",
    )
    output = tmp_path / "startup without management locks.log"
    with output.open("w") as stream:
        process = subprocess.Popen(
            ["sh", str(service_project / "entrypoints/service.sh"), "start"],
            stdout=stream,
            stderr=stream,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 8
            while not (service_project / ".run/instance.json").exists():
                assert process.poll() is None, output.read_text()
                assert time.monotonic() < deadline
                time.sleep(0.02)
            assert not list((service_project / ".run").glob("*.lock"))
            assert process.poll() is None  # 尚在等待 lifespan/健康，服务管理不创建锁文件。
            release.touch()
            assert process.wait(timeout=8) == 0, output.read_text()
        finally:
            release.touch()
            if process.poll() is None:
                os.kill(process.pid, signal.SIGTERM)
                process.wait(timeout=8)


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_interrupting_status_does_not_stop_existing_service(service_project, tmp_path, signum):
    ready_project(service_project)
    assert command(service_project, "start").returncode == 0
    record = read_instance(service_project)
    # 替换临时 PATH 中的 curl，只延迟本次只读查询，不改应用或日常工具。
    import shutil

    tools = tmp_path / "query tools"
    tools.mkdir()
    marker = tmp_path / "checking health"
    curl = tools / "curl"
    curl.write_text(f"#!/bin/sh\n: > '{marker}'\nsleep 2\nexec '{shutil.which('curl')}' \"$@\"\n")
    curl.chmod(0o700)
    process = subprocess.Popen(
        ["sh", str(service_project / "entrypoints/service.sh"), "status"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env={**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"]},
    )
    try:
        deadline = time.monotonic() + 5
        while not marker.exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.02)
        os.killpg(process.pid, signum)
        process.communicate(timeout=5)
        assert process.returncode == 128 + signum
        assert read_instance(service_project) == record
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
            process.communicate(timeout=5)
    assert command(service_project, "status").returncode == 0


def test_status_and_stop_do_not_invoke_python_or_uv(service_project, tmp_path, monkeypatch):
    ready_project(service_project)
    assert command(service_project, "start").returncode == 0
    tools = tmp_path / "no Python tools"
    tools.mkdir()
    marker = tmp_path / "unexpected Python invocation"
    for name in ("uv", "python", "python3"):
        script = tools / name
        script.write_text(f"#!/bin/sh\n: > '{marker}'\nexit 99\n")
        script.chmod(0o700)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    assert command(service_project, "status").returncode == 0
    assert command(service_project, "stop").returncode == 0
    assert not marker.exists()


def test_status_validates_health_json_in_shell(service_project, tmp_path, monkeypatch):
    ready_project(service_project)
    assert command(service_project, "start").returncode == 0
    tools = tmp_path / "invalid health"
    tools.mkdir()
    curl = tools / "curl"
    curl.write_text('#!/bin/sh\nprintf \'%s\\n\' \'{"status":"ok","database":"bad"}\'\n')
    curl.chmod(0o700)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    assert command(service_project, "status").returncode == 1
    assert command(service_project, "stop").returncode == 0


def test_insecure_state_permissions_are_rejected_without_stopping(service_project):
    ready_project(service_project)
    assert command(service_project, "start").returncode == 0
    path = service_project / ".run/instance.json"
    record = read_instance(service_project)
    try:
        path.chmod(0o644)
        result = command(service_project, "stop")
        assert result.returncode == 1
        assert "0600" in result.stderr
        assert process_started_at(record["pid"]) == record["started_at"]
    finally:
        path.chmod(0o600)


def test_nohup_background_service_survives_sighup(service_project):
    ready_project(service_project)
    assert command(service_project, "start").returncode == 0
    record = read_instance(service_project)
    os.kill(record["pid"], signal.SIGHUP)
    time.sleep(0.1)
    assert command(service_project, "status").returncode == 0
    assert read_instance(service_project) == record


@pytest.mark.parametrize("late_health", [False, True])
def test_startup_budget_cannot_be_bypassed_by_a_late_health_response(
    service_project, tmp_path, monkeypatch, late_health
):
    import shutil

    config = ready_project(service_project)
    data = read_config(config)
    data["service"]["startup_timeout_seconds"] = 5.0 if late_health else 0.05
    save_config(config, data)
    marker = tmp_path / "health response was delayed"
    if late_health:
        tools = tmp_path / "slow health tools"
        tools.mkdir()
        curl = tools / "curl"
        curl.write_text(
            f"#!/bin/sh\n: > '{marker}'\nsleep 6\n"
            f"""exec '{shutil.which("curl")}' "$@"\n"""
        )
        curl.chmod(0o700)
        monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    result = command(service_project, "start")
    assert result.returncode == 1, result.stdout + result.stderr
    assert read_instance(service_project) is None
    if late_health:
        assert marker.exists()  # 确认到达了健康请求，而不是仅在导入阶段超时。
