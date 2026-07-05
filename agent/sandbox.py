"""Docker sandbox command execution."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from .config import SandboxConfig
from .policy import SafetyPolicy


@dataclass(frozen=True)
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class DockerSandbox:
    def __init__(self, workspace: Path, config: SandboxConfig, policy: SafetyPolicy) -> None:
        self.workspace = workspace.resolve()
        self.config = config
        self.policy = policy

    def run(self, command: str, *, timeout: int = 30) -> CommandResult:
        self.policy.validate_command(command)
        self.workspace.mkdir(parents=True, exist_ok=True)
        docker_cmd = self._docker_command(command)
        timeout_value = None if timeout == -1 else timeout
        try:
            proc = subprocess.run(
                docker_cmd,
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=timeout_value,
                check=False,
            )
            return CommandResult(command=command, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                command=command,
                returncode=124,
                stdout=exc.stdout or "",
                stderr=(exc.stderr or "") + f"\nCommand timed out after {timeout} seconds.",
                timed_out=True,
            )

    def _docker_command(self, command: str) -> list[str]:
        docker_cmd: list[str] = [
            "docker",
            "run",
            "--rm",
            "--user",
            self.config.user,
            "-v",
            f"{self.workspace}:/workspace:rw",
            "-w",
            "/workspace",
        ]
        if self.config.network_disabled:
            docker_cmd.extend(["--network", "none"])
        if self.config.memory_limit != "-1":
            docker_cmd.extend(["--memory", self.config.memory_limit])
        if self.config.cpu_limit != "-1":
            docker_cmd.extend(["--cpus", self.config.cpu_limit])
        if self.config.pids_limit != -1:
            docker_cmd.extend(["--pids-limit", str(self.config.pids_limit)])
        docker_cmd.extend([self.config.docker_image, "bash", "-lc", command])
        return docker_cmd
