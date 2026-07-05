"""Safety policy for paths, commands, and commit contents."""
from __future__ import annotations

from dataclasses import dataclass
import re
import shlex
from pathlib import Path
from typing import Iterable


class PolicyError(ValueError):
    """Raised when an action violates the safety policy."""


SECRET_FILE_NAMES = {
    ".env",
    ".env.local",
    ".envrc",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "credentials",
    "credentials.json",
    "secrets.json",
}

SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
DANGEROUS_BINARIES = {
    "sudo",
    "su",
    "ssh",
    "scp",
    "sftp",
    "docker",
    "podman",
    "kubectl",
    "mount",
    "umount",
    "mkfs",
    "dd",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "chown",
}
DANGEROUS_COMMAND_PATTERNS = [
    re.compile(r"\brm\s+[^\n;|&]*-r[f]?[^\n;|&]*/"),
    re.compile(r"\brm\s+[^\n;|&]*-f[r]?[^\n;|&]*/"),
    re.compile(r"\bchmod\s+777\b"),
    re.compile(r"\b(curl|wget)\b[^\n|;]+\|\s*(sh|bash)\b"),
    re.compile(r">\s*/"),
    re.compile(r"<\s*/"),
]
SECRET_CONTENT_PATTERNS = [
    re.compile(r"-----BEGIN (RSA |DSA |EC |OPENSSH |)PRIVATE KEY-----"),
    re.compile(r"(?i)aws_secret_access_key\s*="),
    re.compile(r"(?i)api[_-]?key\s*=\s*['\"]?[A-Za-z0-9_\-]{24,}"),
    re.compile(r"(?i)token\s*=\s*['\"]?[A-Za-z0-9_\-]{32,}"),
]


@dataclass(frozen=True)
class SafetyPolicy:
    workspace: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace", self.workspace.resolve())

    def resolve_workspace_path(self, path: str | Path, *, allow_missing: bool = True) -> Path:
        raw_path = Path(path)
        if raw_path.is_absolute():
            raise PolicyError(f"absolute paths are not allowed: {path}")
        if any(part == ".." for part in raw_path.parts):
            raise PolicyError(f"path traversal is not allowed: {path}")
        if self.is_secret_path(raw_path):
            raise PolicyError(f"secret files are not allowed: {path}")
        candidate = (self.workspace / raw_path).resolve(strict=False)
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise PolicyError(f"path escapes workspace: {path}") from exc
        if not allow_missing and not candidate.exists():
            raise PolicyError(f"path does not exist: {path}")
        return candidate

    def validate_path(self, path: str | Path, *, allow_missing: bool = True) -> Path:
        return self.resolve_workspace_path(path, allow_missing=allow_missing)

    @staticmethod
    def is_secret_path(path: str | Path) -> bool:
        p = Path(path)
        lowered_parts = {part.lower() for part in p.parts}
        if lowered_parts.intersection(SECRET_FILE_NAMES):
            return True
        if p.suffix.lower() in SECRET_SUFFIXES:
            return True
        return False

    def validate_file_content_for_commit(self, path: str | Path, content: str) -> None:
        if self.is_secret_path(path):
            raise PolicyError(f"secret path cannot be committed: {path}")
        for pattern in SECRET_CONTENT_PATTERNS:
            if pattern.search(content):
                raise PolicyError(f"possible secret detected in {path}")

    def validate_command(self, command: str) -> None:
        if not command or not command.strip():
            raise PolicyError("empty command is not allowed")
        for pattern in DANGEROUS_COMMAND_PATTERNS:
            if pattern.search(command):
                raise PolicyError(f"dangerous command pattern rejected: {pattern.pattern}")
        tokens = _safe_split(command)
        for token in tokens:
            bare = Path(token).name
            if bare in DANGEROUS_BINARIES:
                raise PolicyError(f"dangerous command rejected: {bare}")
            if token.startswith("/") and not token.startswith("/workspace"):
                raise PolicyError(f"absolute host-like path rejected: {token}")
            if ".." in Path(token).parts:
                raise PolicyError(f"path traversal in command rejected: {token}")
        if _contains_shell_with_external_script(tokens):
            raise PolicyError("downloading and executing scripts is not allowed")


def _safe_split(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _contains_shell_with_external_script(tokens: Iterable[str]) -> bool:
    token_list = list(tokens)
    for idx, token in enumerate(token_list[:-1]):
        if Path(token).name in {"sh", "bash"} and token_list[idx + 1].startswith(("http://", "https://")):
            return True
    return False
