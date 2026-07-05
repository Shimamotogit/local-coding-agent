"""検証済み action を実行するモジュール。"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .config import AppConfig
from .git_manager import GitManager
from .policy import SafetyPolicy
from .sandbox import DockerSandbox
from .schemas import AgentAction
from .searxng import SearxngClient
from .logger import JsonlLogger


class ActionExecutor:
    def __init__(
        self,
        config: AppConfig,
        policy: SafetyPolicy,
        git: GitManager,
        sandbox: DockerSandbox,
        search_client: SearxngClient,
        logger: JsonlLogger,
    ) -> None:
        self.config = config
        self.policy = policy
        self.git = git
        self.sandbox = sandbox
        self.search_client = search_client
        self.logger = logger
        self.finished = False

    def execute(self, action: AgentAction) -> dict[str, Any]:
        """実行エージェントが選んだ action を実行して observation を返す。"""

        handler = getattr(self, f"_{action.action}")
        self.logger.log("action", action=action.action, args=action.args, thought_summary=action.thought_summary)
        try:
            result = handler(**action.args)
            observation = {"ok": True, "action": action.action, "result": result}
        except Exception as exc:
            observation = {"ok": False, "action": action.action, "error": f"{type(exc).__name__}: {exc}"}
        self.logger.log("observation", **observation)
        return observation

    def _read_file(self, path: str) -> dict[str, str]:
        resolved = self.policy.validate_path(path, allow_missing=False)
        if not resolved.is_file():
            raise FileNotFoundError(path)
        return {"path": path, "content": resolved.read_text(encoding="utf-8")}

    def _write_file(self, path: str, content: str) -> dict[str, Any]:
        resolved = self.policy.validate_path(path, allow_missing=True)
        self.policy.validate_file_content_for_commit(path, content)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        existed = resolved.exists()
        resolved.write_text(content, encoding="utf-8")
        return {"path": path, "bytes": len(content.encode("utf-8")), "overwrote": existed}

    def _append_file(self, path: str, content: str) -> dict[str, Any]:
        resolved = self.policy.validate_path(path, allow_missing=True)
        existing = resolved.read_text(encoding="utf-8") if resolved.exists() else ""
        self.policy.validate_file_content_for_commit(path, existing + content)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with resolved.open("a", encoding="utf-8") as f:
            f.write(content)
        return {"path": path, "bytes_appended": len(content.encode("utf-8"))}

    def _list_files(self, path: str = ".") -> dict[str, Any]:
        resolved = self.policy.validate_path(path, allow_missing=False)
        if not resolved.is_dir():
            raise NotADirectoryError(path)
        entries: list[str] = []
        for item in sorted(resolved.rglob("*")):
            rel = item.relative_to(self.config.workspace.resolve()).as_posix()
            if ".git" in item.parts or self.policy.is_secret_path(rel):
                continue
            entries.append(rel + ("/" if item.is_dir() else ""))
        return {"path": path, "entries": entries}

    def _run_command(self, command: str) -> dict[str, Any]:
        before = self.git.status_short()
        result = self.sandbox.run(command, timeout=self.config.limits.command_timeout)
        after = self.git.status_short()
        return {**asdict(result), "changed_files": before != after, "git_status": after}

    def _search_web(self, query: str) -> dict[str, Any]:
        """検索結果と、取得できたページ本文の抜粋を返す。"""

        results = self.search_client.search(query, limit=5, fetch_pages=True)
        shaped = [asdict(item) for item in results]
        self.logger.log("search", query=query, results=shaped)
        return {
            "query": query,
            "results": shaped,
            "note": "result.page_content には実ページ本文から抽出した抜粋が入ります。必要なら fetch_url で個別URLを追加確認してください。",
        }

    def _fetch_url(self, url: str) -> dict[str, Any]:
        """指定 URL の本文抜粋を返す。"""

        content = self.search_client.fetch_url(url)
        self.logger.log("fetch_url", url=url, chars=len(content))
        return {"url": url, "content": content, "chars": len(content)}

    def _git_diff(self) -> dict[str, str]:
        return {"status": self.git.status_short(), "diff": self.git.diff()}

    def _commit_changes(self, message: str) -> dict[str, Any]:
        # commit 前の diff 確認をこの action 内でも必ず行う。
        diff = self.git.diff()
        info = self.git.commit(message)
        if info is None:
            return {"committed": False, "reason": "diff is empty"}
        return {"committed": True, "commit": asdict(info), "diff_reviewed": diff}

    def _finish(self, summary: str, tests: str = "", changed_files: list[str] | None = None) -> dict[str, Any]:
        final_diff = self.git.diff()
        self.finished = True
        return {
            "summary": summary,
            "tests": tests,
            "changed_files": changed_files or [],
            "git_status": self.git.status_short(),
            "git_log": self.git.log_oneline(),
            "final_diff": final_diff,
            "warning": "uncommitted changes remain" if self.git.has_uncommitted_changes() else "",
        }

    def _ask_user(self, question: str) -> dict[str, str]:
        # CLI mode では隠れたブロッキングを避けるため、質問を observation に出して停止扱いにする。
        self.finished = True
        return {"question": question, "note": "人間の確認が必要です。"}
