"""CLI entry point for the local coding agent."""
from __future__ import annotations

import argparse
import json

from .config import AppConfig
from .loop import AgentLoop


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local coding agent.")
    parser.add_argument("task", help="Development task for the agent")
    parser.add_argument("--workspace", default=None, help="Workspace directory to mount into the Docker sandbox")
    parser.add_argument("--max-steps", type=int, default=None, help="Override AGENT_MAX_STEPS; -1 disables this operational limit")
    parser.add_argument("--command-timeout", type=int, default=None, help="Override AGENT_COMMAND_TIMEOUT; -1 disables per-command timeout")
    parser.add_argument("--max-runtime", type=int, default=None, help="Override AGENT_MAX_RUNTIME_SECONDS; -1 disables runtime limit")
    parser.add_argument("--max-searches", type=int, default=None, help="Override AGENT_MAX_SEARCHES; -1 disables search limit")
    parser.add_argument("--auto-commit", action="store_true", help="Enable auto commit behavior")
    parser.add_argument("--require-diff-before-commit", action="store_true", help="Require diff checks before commits")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = AppConfig.from_env(workspace=args.workspace)
    config = _apply_cli_overrides(config, args)
    result = AgentLoop(config).run(args.task)
    print(json.dumps({"stop_reason": result.stop_reason, "log_file": result.log_file, "last_observation": result.observations[-1] if result.observations else None}, ensure_ascii=False, indent=2))
    return 0 if result.stop_reason == "finish" else 1


def _apply_cli_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    from dataclasses import replace

    limits = config.limits
    if args.max_steps is not None:
        limits = replace(limits, max_steps=args.max_steps)
    if args.command_timeout is not None:
        limits = replace(limits, command_timeout=args.command_timeout)
    if args.max_runtime is not None:
        limits = replace(limits, max_runtime_seconds=args.max_runtime)
    if args.max_searches is not None:
        limits = replace(limits, max_searches=args.max_searches)
    git = config.git
    if args.auto_commit:
        git = replace(git, auto_commit=True)
    if args.require_diff_before_commit:
        git = replace(git, require_diff_before_commit=True)
    return replace(config, limits=limits, git=git)


if __name__ == "__main__":
    raise SystemExit(main())
