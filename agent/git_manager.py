"""Git repository management and audit-friendly commits."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from .policy import SafetyPolicy, PolicyError


class GitError(RuntimeError):
    """Raised for git command failures."""


@dataclass(frozen=True)
class GitCommitInfo:
    hash: str
    message: str
    changed_files: list[str]


class GitManager:
    def __init__(self, workspace: Path, policy: SafetyPolicy) -> None:
        self.workspace = workspace.resolve()
        self.policy = policy
        self._diff_checked = False

    def init_repo(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        if not (self.workspace / ".git").exists():
            self._run(["git", "init"])
        self._run(["git", "config", "user.email", "local-agent@example.invalid"])
        self._run(["git", "config", "user.name", "Local Coding Agent"])
        if not self.has_commits():
            self._run(["git", "add", "."])
            # Create an initial checkpoint even for an empty workspace so HEAD
            # always exists before the first LLM-driven diff.
            self._run(["git", "commit", "--allow-empty", "-m", "Initial workspace"])

    def has_commits(self) -> bool:
        proc = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=self.workspace, capture_output=True, text=True, check=False)
        return proc.returncode == 0

    def status_short(self) -> str:
        return self._run(["git", "status", "--short"])

    def diff(self) -> str:
        self._diff_checked = True
        tracked_diff = self._run(["git", "diff", "HEAD", "--"])
        return tracked_diff + self._untracked_diff()

    def has_uncommitted_changes(self) -> bool:
        return bool(self.status_short().strip())

    def commit(self, message: str) -> GitCommitInfo | None:
        self._validate_commit_message(message)
        if not self._diff_checked:
            raise GitError("git diff must be checked before commit")
        status = self.status_short()
        if not status.strip():
            self._diff_checked = False
            return None
        self._scan_commit_contents()
        changed_files = [line[3:] for line in status.splitlines() if len(line) >= 4]
        self._run(["git", "add", "."])
        self._run(["git", "commit", "-m", message])
        commit_hash = self._run(["git", "rev-parse", "HEAD"]).strip()
        self._diff_checked = False
        return GitCommitInfo(hash=commit_hash, message=message, changed_files=changed_files)

    def log_oneline(self) -> str:
        if not self.has_commits():
            return ""
        return self._run(["git", "log", "--oneline", "--decorate", "--max-count", "20"])

    def _scan_commit_contents(self) -> None:
        paths: set[str] = set()
        proc = subprocess.run(["git", "diff", "--name-only", "HEAD", "--"], cwd=self.workspace, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise GitError(proc.stderr.strip() or "git diff --name-only failed")
        paths.update(line.strip() for line in proc.stdout.splitlines() if line.strip())
        for line in self.status_short().splitlines():
            if len(line) >= 4:
                paths.add(line[3:].strip())
        for rel in sorted(paths):
            path = self.policy.validate_path(rel, allow_missing=True)
            if path.exists() and path.is_file():
                try:
                    content = path.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    raise PolicyError(f"binary or non-UTF-8 file cannot be committed: {rel}") from exc
                self.policy.validate_file_content_for_commit(rel, content)

    def _untracked_diff(self) -> str:
        status = self.status_short()
        chunks: list[str] = []
        for line in status.splitlines():
            if not line.startswith("?? "):
                continue
            rel = line[3:].strip()
            path = self.policy.validate_path(rel, allow_missing=False)
            if not path.is_file():
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                chunks.append(f"diff --git a/{rel} b/{rel}\nnew file mode 100644\nBinary files /dev/null and b/{rel} differ\n")
                continue
            chunks.append(f"diff --git a/{rel} b/{rel}\nnew file mode 100644\n--- /dev/null\n+++ b/{rel}\n@@ -0,0 +1,{len(lines)} @@\n")
            chunks.extend(f"+{line}\n" for line in lines)
        return "".join(chunks)

    @staticmethod
    def _validate_commit_message(message: str) -> None:
        if not message or not message.strip():
            raise GitError("commit message cannot be empty")
        if len(message.splitlines()[0]) > 100:
            raise GitError("commit message first line is too long")

    def _run(self, args: list[str]) -> str:
        proc = subprocess.run(args, cwd=self.workspace, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise GitError(proc.stderr.strip() or proc.stdout.strip() or f"git command failed: {' '.join(args)}")
        return proc.stdout
