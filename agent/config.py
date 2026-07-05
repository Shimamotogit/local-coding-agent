"""Configuration loading and unsafe-mode detection."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Iterable


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def parse_int_limit(value: str | int, *, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer or -1, got {value!r}") from exc
    if parsed < -1:
        raise ValueError(f"{name} must be -1 or greater, got {parsed}")
    return parsed


def parse_float_limit(value: str | float | int, *, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number or -1, got {value!r}") from exc
    if parsed < -1:
        raise ValueError(f"{name} must be -1 or greater, got {parsed}")
    return parsed


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class LLMConfig:
    base_url: str = "http://localhost:8080/v1"
    model: str = "LFM2.5-8B-A1B"
    temperature: float = 0.2
    max_tokens: int = 2048


@dataclass(frozen=True)
class AgentLimits:
    max_steps: int = 30
    command_timeout: int = 30
    max_runtime_seconds: int = 600
    max_searches: int = 5
    max_repeated_errors: int = 3
    max_consecutive_failures: int = 5

    @property
    def disabled_limit_names(self) -> list[str]:
        names: list[str] = []
        for key, value in self.__dict__.items():
            if value == -1:
                names.append(key)
        return names

    @property
    def unsafe_mode(self) -> bool:
        return bool(self.disabled_limit_names)


@dataclass(frozen=True)
class SandboxConfig:
    docker_image: str = "python:3.11-slim"
    memory_limit: str = "1g"
    cpu_limit: str = "1"
    pids_limit: int = 128
    network_disabled: bool = True
    user: str = "1000:1000"

    @property
    def disabled_limit_names(self) -> list[str]:
        disabled: list[str] = []
        if self.memory_limit == "-1":
            disabled.append("memory_limit")
        if self.cpu_limit == "-1":
            disabled.append("cpu_limit")
        if self.pids_limit == -1:
            disabled.append("pids_limit")
        return disabled

    @property
    def unsafe_mode(self) -> bool:
        return bool(self.disabled_limit_names)


@dataclass(frozen=True)
class GitConfig:
    auto_commit: bool = True
    require_diff_before_commit: bool = True
    commit_after_confirmed_output: bool = True


@dataclass(frozen=True)
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    limits: AgentLimits = field(default_factory=AgentLimits)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    git: GitConfig = field(default_factory=GitConfig)
    searxng_url: str = "http://localhost:8888"
    workspace: Path = Path("sandbox_workspace")
    logs_dir: Path = Path("logs")

    @classmethod
    def from_env(cls, *, workspace: str | Path | None = None) -> "AppConfig":
        llm = LLMConfig(
            base_url=_env("LLM_BASE_URL", "http://localhost:8080/v1").rstrip("/"),
            model=_env("LLM_MODEL", "LFM2.5-8B-A1B"),
            temperature=parse_float_limit(_env("LLM_TEMPERATURE", "0.2"), name="LLM_TEMPERATURE"),
            max_tokens=parse_int_limit(_env("LLM_MAX_TOKENS", "2048"), name="LLM_MAX_TOKENS"),
        )
        limits = AgentLimits(
            max_steps=parse_int_limit(_env("AGENT_MAX_STEPS", "30"), name="AGENT_MAX_STEPS"),
            command_timeout=parse_int_limit(_env("AGENT_COMMAND_TIMEOUT", "30"), name="AGENT_COMMAND_TIMEOUT"),
            max_runtime_seconds=parse_int_limit(_env("AGENT_MAX_RUNTIME_SECONDS", "600"), name="AGENT_MAX_RUNTIME_SECONDS"),
            max_searches=parse_int_limit(_env("AGENT_MAX_SEARCHES", "5"), name="AGENT_MAX_SEARCHES"),
            max_repeated_errors=parse_int_limit(_env("AGENT_MAX_REPEATED_ERRORS", "3"), name="AGENT_MAX_REPEATED_ERRORS"),
            max_consecutive_failures=parse_int_limit(_env("AGENT_MAX_CONSECUTIVE_FAILURES", "5"), name="AGENT_MAX_CONSECUTIVE_FAILURES"),
        )
        sandbox = SandboxConfig(
            docker_image=_env("SANDBOX_DOCKER_IMAGE", "python:3.11-slim"),
            memory_limit=_env("SANDBOX_MEMORY_LIMIT", "1g"),
            cpu_limit=_env("SANDBOX_CPU_LIMIT", "1"),
            pids_limit=parse_int_limit(_env("SANDBOX_PIDS_LIMIT", "128"), name="SANDBOX_PIDS_LIMIT"),
        )
        git = GitConfig(
            auto_commit=parse_bool(_env("GIT_AUTO_COMMIT", "true")),
            require_diff_before_commit=parse_bool(_env("GIT_REQUIRE_DIFF_BEFORE_COMMIT", "true")),
            commit_after_confirmed_output=parse_bool(_env("GIT_COMMIT_AFTER_CONFIRMED_OUTPUT", "true")),
        )
        return cls(
            llm=llm,
            limits=limits,
            sandbox=sandbox,
            git=git,
            searxng_url=_env("SEARXNG_URL", "http://localhost:8888").rstrip("/"),
            workspace=Path(workspace or _env("AGENT_WORKSPACE", "sandbox_workspace")),
            logs_dir=Path(_env("AGENT_LOGS_DIR", "logs")),
        )

    @property
    def unsafe_mode(self) -> bool:
        return self.limits.unsafe_mode or self.sandbox.unsafe_mode

    @property
    def disabled_limit_names(self) -> list[str]:
        return [
            *[f"agent.{name}" for name in self.limits.disabled_limit_names],
            *[f"sandbox.{name}" for name in self.sandbox.disabled_limit_names],
        ]


def unsafe_warning(disabled: Iterable[str]) -> str:
    disabled_list = ", ".join(disabled) or "unknown"
    return (
        "WARNING: unsafe mode is enabled.\n"
        "Some agent operational limits are disabled.\n"
        "This may cause infinite loops, excessive resource usage, or unintended long-running execution.\n"
        f"Disabled limits: {disabled_list}"
    )
