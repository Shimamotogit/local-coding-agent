"""Validation for LLM JSON actions."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping


class ActionValidationError(ValueError):
    """Raised when an LLM action is malformed."""


ACTION_ARG_REQUIREMENTS: dict[str, set[str]] = {
    "read_file": {"path"},
    "write_file": {"path", "content"},
    "append_file": {"path", "content"},
    "list_files": set(),
    "run_command": {"command"},
    "search_web": {"query"},
    "git_diff": set(),
    "commit_changes": {"message"},
    "finish": {"summary"},
    "ask_user": {"question"},
}


@dataclass(frozen=True)
class AgentAction:
    action: str
    args: dict[str, Any]
    thought_summary: str = ""


def parse_action(raw: str | Mapping[str, Any]) -> AgentAction:
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


def _validate_arg_types(action: str, args: dict[str, Any]) -> None:
    string_fields = {
        "read_file": ["path"],
        "write_file": ["path", "content"],
        "append_file": ["path", "content"],
        "list_files": ["path"],
        "run_command": ["command"],
        "search_web": ["query"],
        "commit_changes": ["message"],
        "finish": ["summary"],
        "ask_user": ["question"],
    }.get(action, [])
    for field in string_fields:
        if field in args and not isinstance(args[field], str):
            raise ActionValidationError(f"{action}.{field} must be a string")
    if action == "finish" and "changed_files" in args and not isinstance(args["changed_files"], list):
        raise ActionValidationError("finish.changed_files must be a list when provided")
