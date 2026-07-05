"""Agent loop orchestration."""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from .actions import ActionExecutor
from .config import AppConfig, unsafe_warning
from .git_manager import GitManager
from .llm_client import LLMClient
from .logger import JsonlLogger
from .policy import SafetyPolicy
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .sandbox import DockerSandbox
from .schemas import parse_action, ActionValidationError
from .searxng import SearxngClient


@dataclass(frozen=True)
class AgentRunResult:
    stop_reason: str
    observations: list[dict[str, Any]]
    log_file: str


class AgentLoop:
    def __init__(self, config: AppConfig, llm: LLMClient | None = None) -> None:
        self.config = config
        self.config.workspace.mkdir(parents=True, exist_ok=True)
        self.policy = SafetyPolicy(self.config.workspace)
        self.logger = JsonlLogger(self.config.logs_dir)
        self.git = GitManager(self.config.workspace, self.policy)
        self.sandbox = DockerSandbox(self.config.workspace, self.config.sandbox, self.policy)
        self.search = SearxngClient(self.config.searxng_url, max_searches=self.config.limits.max_searches)
        self.llm = llm or LLMClient(self.config.llm)
        self.executor = ActionExecutor(self.config, self.policy, self.git, self.sandbox, self.search, self.logger)

    def run(self, task: str) -> AgentRunResult:
        self.git.init_repo()
        observations: list[dict[str, Any]] = []
        start = time.monotonic()
        repeated_errors: dict[str, int] = {}
        consecutive_failures = 0
        if self.config.unsafe_mode:
            warning = unsafe_warning(self.config.disabled_limit_names)
            print(warning)
            self.logger.log("unsafe_mode", warning=warning, disabled=self.config.disabled_limit_names)
        self.logger.log("task", task=task)

        step = 0
        while True:
            step += 1
            stop = self._stop_reason(step, start, repeated_errors, consecutive_failures)
            if stop:
                self.logger.log("stop", reason=stop)
                return AgentRunResult(stop_reason=stop, observations=observations, log_file=str(self.logger.path))

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(task, observations, self.git.status_short())},
            ]
            self.logger.log("llm_request", step=step, messages=messages)
            raw = self.llm.chat(messages)
            self.logger.log("llm_response", step=step, raw=raw)
            try:
                action = parse_action(raw)
            except ActionValidationError as exc:
                observation = {"ok": False, "action": "parse_action", "error": str(exc)}
            else:
                observation = self.executor.execute(action)
            observations.append(observation)

            if observation.get("ok"):
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                err = str(observation.get("error", ""))
                repeated_errors[err] = repeated_errors.get(err, 0) + 1
            if self.executor.finished:
                self.logger.log("stop", reason="finish")
                return AgentRunResult(stop_reason="finish", observations=observations, log_file=str(self.logger.path))

    def _stop_reason(self, step: int, start: float, repeated_errors: dict[str, int], consecutive_failures: int) -> str | None:
        limits = self.config.limits
        if limits.max_steps != -1 and step > limits.max_steps:
            return "max_steps"
        if limits.max_runtime_seconds != -1 and time.monotonic() - start > limits.max_runtime_seconds:
            return "max_runtime_seconds"
        if limits.max_repeated_errors != -1:
            for error, count in repeated_errors.items():
                if error and count >= limits.max_repeated_errors:
                    return "max_repeated_errors"
        if limits.max_consecutive_failures != -1 and consecutive_failures >= limits.max_consecutive_failures:
            return "max_consecutive_failures"
        return None
