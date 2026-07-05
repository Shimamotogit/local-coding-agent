"""LLM が出力する JSON の検証ロジック。"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping


class ActionValidationError(ValueError):
    """実行エージェントの action JSON が不正な場合に送出する例外。"""


class MonitorValidationError(ValueError):
    """監視エージェントの判定 JSON が不正な場合に送出する例外。"""


ACTION_ARG_REQUIREMENTS: dict[str, set[str]] = {
    "read_file": {"path"},
    "write_file": {"path", "content"},
    "append_file": {"path", "content"},
    "list_files": set(),
    "run_command": {"command"},
    "search_web": {"query"},
    "fetch_url": {"url"},
    "git_diff": set(),
    "commit_changes": {"message"},
    "finish": {"summary"},
    "ask_user": {"question"},
}


@dataclass(frozen=True)
class AgentAction:
    """実行エージェントが 1 ステップで実行したい操作。"""

    action: str
    args: dict[str, Any]
    thought_summary: str = ""


@dataclass(frozen=True)
class MonitorDecision:
    """監視エージェントが共有履歴を確認した結果。

    requirements_met:
        ユーザー要件が満たされたと判断した場合のみ True。
    next_instruction:
        未達の場合に、次の実行エージェントへ渡す具体的な指示。
    assessment:
        監視結果の日本語要約。ログと次ステップの判断材料に使う。
    should_finish:
        requirements_met と同じ意味で使える補助フラグ。古い/曖昧な出力にも
        耐えるために残しているが、停止判定では requirements_met を優先する。
    """

    requirements_met: bool
    next_instruction: str
    assessment: str = ""
    should_finish: bool = False


def parse_action(raw: str | Mapping[str, Any]) -> AgentAction:
    """実行エージェントの JSON を AgentAction に変換する。"""

    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ActionValidationError(f"LLM output is not valid JSON: {exc.msg}") from exc
    elif isinstance(raw, Mapping):
        data = dict(raw)
    else:
        raise ActionValidationError("action must be JSON text or a mapping")

    if not isinstance(data, dict):
        raise ActionValidationError("action JSON must be an object")
    action = data.get("action")
    if not isinstance(action, str):
        raise ActionValidationError("action must be a string")
    if action not in ACTION_ARG_REQUIREMENTS:
        raise ActionValidationError(f"unknown action: {action}")
    args = data.get("args", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ActionValidationError("args must be an object")
    missing = ACTION_ARG_REQUIREMENTS[action] - set(args)
    if missing:
        raise ActionValidationError(f"missing required args for {action}: {', '.join(sorted(missing))}")
    thought_summary = data.get("thought_summary", "")
    if not isinstance(thought_summary, str):
        raise ActionValidationError("thought_summary must be a string")
    _validate_arg_types(action, args)
    return AgentAction(action=action, args=args, thought_summary=thought_summary[:500])


def parse_monitor_decision(raw: str | Mapping[str, Any]) -> MonitorDecision:
    """監視エージェントの JSON を MonitorDecision に変換する。"""

    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MonitorValidationError(f"monitor output is not valid JSON: {exc.msg}") from exc
    elif isinstance(raw, Mapping):
        data = dict(raw)
    else:
        raise MonitorValidationError("monitor decision must be JSON text or a mapping")

    if not isinstance(data, dict):
        raise MonitorValidationError("monitor decision JSON must be an object")

    requirements_met = data.get("requirements_met", data.get("should_finish", False))
    if not isinstance(requirements_met, bool):
        raise MonitorValidationError("requirements_met must be a boolean")

    should_finish = data.get("should_finish", requirements_met)
    if not isinstance(should_finish, bool):
        raise MonitorValidationError("should_finish must be a boolean when provided")

    next_instruction = data.get("next_instruction", "")
    if not isinstance(next_instruction, str):
        raise MonitorValidationError("next_instruction must be a string")

    assessment = data.get("assessment", "")
    if not isinstance(assessment, str):
        raise MonitorValidationError("assessment must be a string")

    if not requirements_met and not next_instruction.strip():
        raise MonitorValidationError("next_instruction is required when requirements are not met")

    return MonitorDecision(
        requirements_met=requirements_met,
        should_finish=should_finish,
        next_instruction=next_instruction[:2000],
        assessment=assessment[:2000],
    )


def _validate_arg_types(action: str, args: dict[str, Any]) -> None:
    string_fields = {
        "read_file": ["path"],
        "write_file": ["path", "content"],
        "append_file": ["path", "content"],
        "list_files": ["path"],
        "run_command": ["command"],
        "search_web": ["query"],
        "fetch_url": ["url"],
        "commit_changes": ["message"],
        "finish": ["summary"],
        "ask_user": ["question"],
    }.get(action, [])
    for field in string_fields:
        if field in args and not isinstance(args[field], str):
            raise ActionValidationError(f"{action}.{field} must be a string")
    if action == "finish" and "changed_files" in args and not isinstance(args["changed_files"], list):
        raise ActionValidationError("finish.changed_files must be a list when provided")
