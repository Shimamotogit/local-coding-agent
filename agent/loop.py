"""実行エージェントと監視エージェントを協調させるループ。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import time
from typing import Any

from .actions import ActionExecutor
from .config import AppConfig, unsafe_warning
from .git_manager import GitManager
from .llm_client import LLMClient
from .logger import JsonlLogger
from .policy import SafetyPolicy
from .prompts import EXECUTOR_SYSTEM_PROMPT, MONITOR_SYSTEM_PROMPT, build_executor_prompt, build_monitor_prompt
from .sandbox import DockerSandbox
from .schemas import ActionValidationError, MonitorDecision, MonitorValidationError, parse_action, parse_monitor_decision
from .searxng import SearxngClient


@dataclass(frozen=True)
class AgentRunResult:
    stop_reason: str
    observations: list[dict[str, Any]]
    log_file: str
    shared_history: list[dict[str, Any]]


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
        """タスクを実行する。

        1. 実行エージェントが action を1つ提案する
        2. harness が action を検証・実行して observation を作る
        3. 監視エージェントが共有履歴全体を読んで、完了可否と次指示を判断する
        4. 未完了なら監視エージェントの指示を次の実行エージェント prompt に渡す

        shared_history には実行側と監視側の両方の履歴を全件入れる。
        これにより、どちらのエージェントも過去の action / observation / 監視判断を
        参照できる。
        """

        self.git.init_repo()
        observations: list[dict[str, Any]] = []
        shared_history: list[dict[str, Any]] = []
        start = time.monotonic()
        repeated_errors: dict[str, int] = {}
        consecutive_failures = 0
        monitor_instruction = ""
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
                return AgentRunResult(stop_reason=stop, observations=observations, shared_history=shared_history, log_file=str(self.logger.path))

            action_observation = self._run_executor_step(task, step, shared_history, monitor_instruction)
            observations.append(action_observation)
            shared_history.append(action_observation["history_entry"])
            observation = action_observation["observation"]

            if observation.get("ok"):
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                err = str(observation.get("error", ""))
                repeated_errors[err] = repeated_errors.get(err, 0) + 1

            monitor_decision = self._run_monitor_step(task, step, shared_history)
            shared_history.append(monitor_decision["history_entry"])
            decision: MonitorDecision = monitor_decision["decision"]
            monitor_instruction = decision.next_instruction

            if decision.requirements_met:
                self.logger.log("stop", reason="finish", monitor_decision=asdict(decision))
                return AgentRunResult(stop_reason="finish", observations=observations, shared_history=shared_history, log_file=str(self.logger.path))

            # 実行エージェントが finish / ask_user しても、監視エージェントが未達と判断したら続行する。
            # これにより「早すぎる finish」を監視側が差し戻せる。
            if self.executor.finished:
                self.executor.finished = False

    def _run_executor_step(
        self,
        task: str,
        step: int,
        shared_history: list[dict[str, Any]],
        monitor_instruction: str,
    ) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": EXECUTOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_executor_prompt(task, shared_history, self.git.status_short(), monitor_instruction),
            },
        ]
        self.logger.log("llm_request", agent="executor", step=step, messages=messages)
        raw = self.llm.chat(messages)
        self.logger.log("llm_response", agent="executor", step=step, raw=raw)
        parsed_action: dict[str, Any] | None = None
        try:
            action = parse_action(raw)
        except ActionValidationError as exc:
            observation = {"ok": False, "action": "parse_action", "error": str(exc)}
        else:
            parsed_action = asdict(action)
            observation = self.executor.execute(action)

        history_entry = {
            "step": step,
            "agent": "executor",
            "monitor_instruction": monitor_instruction,
            "raw_response": raw,
            "parsed_action": parsed_action,
            "observation": observation,
            "git_status_after_action": self.git.status_short(),
        }
        return {"observation": observation, "history_entry": history_entry}

    def _run_monitor_step(self, task: str, step: int, shared_history: list[dict[str, Any]]) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": MONITOR_SYSTEM_PROMPT},
            {"role": "user", "content": build_monitor_prompt(task, shared_history, self.git.status_short())},
        ]
        self.logger.log("llm_request", agent="monitor", step=step, messages=messages)
        raw = self.llm.chat(messages)
        self.logger.log("llm_response", agent="monitor", step=step, raw=raw)
        validation_error = ""
        try:
            decision = parse_monitor_decision(raw)
        except MonitorValidationError as exc:
            validation_error = str(exc)
            # 監視エージェント自身の出力が崩れた場合も、次の実行エージェントに
            # 状況確認を促してループを継続する。これにより一時的な JSON 失敗で即停止しない。
            decision = MonitorDecision(
                requirements_met=False,
                should_finish=False,
                assessment=f"監視エージェントのJSON解析に失敗しました: {exc}",
                next_instruction="直前の observation と git status を確認し、必要な修正・テスト・diff確認・commitを続けてください。",
            )
        self.logger.log("monitor_decision", step=step, decision=asdict(decision), validation_error=validation_error)
        history_entry = {
            "step": step,
            "agent": "monitor",
            "raw_response": raw,
            "decision": asdict(decision),
            "validation_error": validation_error,
            "git_status_after_monitor": self.git.status_short(),
        }
        return {"decision": decision, "history_entry": history_entry}

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
