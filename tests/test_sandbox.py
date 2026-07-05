import subprocess
import pytest

from agent.config import SandboxConfig
from agent.policy import SafetyPolicy, PolicyError
from agent.sandbox import DockerSandbox


def test_workspace_command_runs_with_docker(monkeypatch, tmp_path):
    policy = SafetyPolicy(tmp_path)
    sandbox = DockerSandbox(tmp_path, SandboxConfig(), policy)

    def fake_run(args, **kwargs):
        assert "docker" == args[0]
        assert "/workspace" in args
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = sandbox.run("python -c 'print(1)'", timeout=30)
    assert result.ok
    assert result.stdout == "ok\n"


def test_timeout_is_reported(monkeypatch, tmp_path):
    policy = SafetyPolicy(tmp_path)
    sandbox = DockerSandbox(tmp_path, SandboxConfig(), policy)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1, output="", stderr="late")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = sandbox.run("python slow.py", timeout=1)
    assert result.timed_out
    assert result.returncode == 124


def test_timeout_can_be_disabled(monkeypatch, tmp_path):
    policy = SafetyPolicy(tmp_path)
    sandbox = DockerSandbox(tmp_path, SandboxConfig(), policy)
    seen = {}

    def fake_run(args, **kwargs):
        seen["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox.run("python ok.py", timeout=-1)
    assert seen["timeout"] is None


def test_workspace_outside_file_rejected(tmp_path):
    policy = SafetyPolicy(tmp_path)
    sandbox = DockerSandbox(tmp_path, SandboxConfig(), policy)
    with pytest.raises(PolicyError):
        sandbox.run("cat /etc/passwd")


def test_dangerous_command_rejected(tmp_path):
    policy = SafetyPolicy(tmp_path)
    sandbox = DockerSandbox(tmp_path, SandboxConfig(), policy)
    with pytest.raises(PolicyError):
        sandbox.run("sudo echo nope")


def test_resource_limits_added_to_docker_command(tmp_path):
    policy = SafetyPolicy(tmp_path)
    config = SandboxConfig(memory_limit="512m", cpu_limit="0.5", pids_limit=64)
    sandbox = DockerSandbox(tmp_path, config, policy)
    cmd = sandbox._docker_command("python -V")
    assert "--memory" in cmd and "512m" in cmd
    assert "--cpus" in cmd and "0.5" in cmd
    assert "--pids-limit" in cmd and "64" in cmd


def test_resource_limits_can_be_disabled(tmp_path):
    policy = SafetyPolicy(tmp_path)
    config = SandboxConfig(memory_limit="-1", cpu_limit="-1", pids_limit=-1)
    sandbox = DockerSandbox(tmp_path, config, policy)
    cmd = sandbox._docker_command("python -V")
    assert "--memory" not in cmd
    assert "--cpus" not in cmd
    assert "--pids-limit" not in cmd
