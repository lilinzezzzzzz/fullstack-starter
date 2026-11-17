import json
import os
import shlex
import shutil
import subprocess
import sys
import time

import pytest

from tests.helpers import read_config, save_config, write_config
from tests.service_helpers import command, read_instance, write_instance


def test_configuration_export_has_only_application_configuration(service_project, tmp_path):
    config = write_config(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "entrypoints.cli",
            "--config",
            str(config),
            "export-service-settings",
        ],
        cwd=service_project / "backend",
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    exported = json.loads(result.stdout)
    assert set(exported) == {"config", "log", "startup_timeout", "stop_timeout"}
    assert exported["config"] == str(config)
    assert exported["log"] == str(tmp_path / "logs/app.log")
    assert exported["startup_timeout"] == read_config(config)["service"]["startup_timeout_seconds"]
    assert exported["stop_timeout"] == read_config(config)["service"]["stop_timeout_seconds"]
    assert not (tmp_path / "logs").exists()
    assert not (tmp_path / "data").exists()


def test_shell_validates_stop_budget_against_fixed_shutdown_timeout(service_project):
    config = service_project / "configs/app.toml"
    data = read_config(config)
    data["service"]["stop_timeout_seconds"] = 0.5
    save_config(config, data)
    result = command(service_project, "start")
    assert result.returncode == 1
    assert "must exceed" in result.stderr
    assert not (service_project / ".run/instance.json").exists()


@pytest.mark.parametrize("name", ["instance.json", "instance.json.pending", "console.log"])
def test_runtime_files_reject_symbolic_links(service_project, tmp_path, name):
    directory = service_project / ".run"
    directory.mkdir(exist_ok=True)
    target = tmp_path / "untouched"
    target.write_text("original")
    path = directory / name
    path.symlink_to(target)
    try:
        result = command(service_project, "status")
        assert result.returncode == 1
        assert "symlink" in result.stderr
        assert target.read_text() == "original"
    finally:
        path.unlink()


def test_runtime_directory_rejects_symbolic_link(service_project, tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    path = service_project / ".run"
    path.symlink_to(target, target_is_directory=True)
    try:
        result = command(service_project, "status")
        assert result.returncode == 1
        assert "real directory" in result.stderr
    finally:
        path.unlink()


def test_absent_record_does_not_infer_processes_from_other_files(service_project):
    assert command(service_project, "status").returncode == 3
    assert command(service_project, "stop").returncode == 0


@pytest.mark.integration
@pytest.mark.parametrize("insecure", [False, True])
def test_pending_publication_during_metadata_check_validates_final_record(
    service_project, tmp_path, monkeypatch, insecure
):
    directory = service_project / ".run"
    directory.mkdir()
    record = directory / "instance.json"
    pending = directory / "instance.json.pending"
    pending.write_text(
        json.dumps(
            {
                "format": 3,
                "pid": 2147483647,
                "started_at": "exited test target",
                "config": "/synthetic.toml",
                "url": "http://127.0.0.1:1",
                "log": "/synthetic.log",
                "stop_timeout": 1.0,
            }
        )
    )
    pending.chmod(0o600)
    real_stat = shutil.which("stat")
    assert real_stat is not None
    tools = tmp_path / "tools"
    tools.mkdir()
    wrapper = tools / "stat"
    wrapper.write_text(
        "#!/bin/sh\n"
        'case "$*" in *instance.json.pending)\n'
        f"    mv {shlex.quote(str(pending))} {shlex.quote(str(record))}\n"
        + (f"    chmod 644 {shlex.quote(str(record))}\n" if insecure else "")
        + "    ;;\nesac\n"
        f'exec {shlex.quote(real_stat)} "$@"\n'
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    result = command(service_project, "status")
    assert result.returncode == (1 if insecure else 3), result.stdout + result.stderr
    if insecure:
        assert "0600" in result.stderr
        record.chmod(0o600)
    assert record.is_file()
    assert not pending.exists()


@pytest.mark.integration
@pytest.mark.parametrize("action", ["stop", "restart"])
@pytest.mark.parametrize("fail_from", [1, 2, 3])
def test_process_inspection_failure_preserves_target_and_record(
    service_project, tmp_path, monkeypatch, action, fail_from
):
    release = tmp_path / "release"
    ready = tmp_path / "ready"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal, sys, time\n"
            "from pathlib import Path\n"
            "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
            "Path(sys.argv[1]).touch()\n"
            "while not Path(sys.argv[2]).exists(): time.sleep(0.02)\n",
            str(ready),
            str(release),
        ],
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.02)
        write_instance(service_project, process.pid)
        record = service_project / ".run/instance.json"
        original = record.read_bytes()
        real_ps = shutil.which("ps")
        assert real_ps is not None
        tools = tmp_path / "tools"
        tools.mkdir()
        counter = shlex.quote(str(tools / "calls"))
        wrapper = tools / "ps"
        wrapper.write_text(
            "#!/bin/sh\n"
            f'if [ "$2" = "{process.pid}" ] && [ "$4" = "lstart=" ]; then\n'
            f"    calls=0; if [ -f {counter} ]; then calls=$(cat {counter}); fi\n"
            f"    calls=$((calls + 1)); printf '%s' \"$calls\" > {counter}\n"
            f'    if [ "$calls" -ge {fail_from} ]; then exit 2; fi\n'
            "fi\n"
            f'exec {shlex.quote(real_ps)} "$@"\n'
        )
        wrapper.chmod(0o755)
        monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
        result = command(service_project, action)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "Cannot inspect process" in result.stderr
        assert process.poll() is None
        assert record.read_bytes() == original
        assert not (service_project / ".run/console.log").exists()
    finally:
        release.touch()
        process.wait(timeout=5)


@pytest.mark.integration
def test_stop_timeout_never_force_kills_and_restart_never_launches(service_project, tmp_path):
    # 自有合成进程忽略 SIGINT，通过文件协作退出，不使用服务锁。
    marker = tmp_path / "release"
    ready = tmp_path / "ready"
    code = """
import os, signal, time
from pathlib import Path
signal.signal(signal.SIGINT, signal.SIG_IGN)
Path(os.environ['TARGET_READY']).touch()
while not Path(os.environ['RELEASE_FILE']).exists(): time.sleep(0.02)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=service_project / "backend",
        env={**os.environ, "RELEASE_FILE": str(marker), "TARGET_READY": str(ready)},
        start_new_session=True,
    )
    try:
        import time

        deadline = time.monotonic() + 5
        while not ready.exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.02)
        record = write_instance(service_project, process.pid)
        assert command(service_project, "stop").returncode == 1
        assert process.poll() is None
        assert command(service_project, "restart").returncode == 1
        assert read_instance(service_project) == record
    finally:
        marker.touch()
        process.wait(timeout=5)


@pytest.mark.integration
def test_stop_waits_for_target_even_when_record_disappears(service_project, tmp_path):
    import time

    release = tmp_path / "release target"
    ready = tmp_path / "ready"
    code = """
import os, signal, time
from pathlib import Path
def interrupt(*args):
    Path(os.environ['INSTANCE_FILE']).unlink(missing_ok=True)
signal.signal(signal.SIGINT, interrupt)
Path(os.environ['TARGET_READY']).touch()
while not Path(os.environ['RELEASE_TARGET']).exists(): time.sleep(0.02)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=service_project / "backend",
        env={
            **os.environ,
            "RELEASE_TARGET": str(release),
            "TARGET_READY": str(ready),
            "INSTANCE_FILE": str(service_project / ".run/instance.json"),
        },
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.02)
        write_instance(service_project, process.pid)
        result = command(service_project, "stop")
        assert result.returncode == 1
        assert "timed out" in result.stderr
        assert process.poll() is None
        assert not (service_project / ".run/instance.json").exists()
    finally:
        release.touch()
        process.wait(timeout=5)
