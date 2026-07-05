import pytest

from agent.git_manager import GitManager, GitError
from agent.policy import SafetyPolicy


def make_git(tmp_path):
    policy = SafetyPolicy(tmp_path)
    git = GitManager(tmp_path, policy)
    git.init_repo()
    return git


def test_git_init_and_initial_commit(tmp_path):
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
    git = make_git(tmp_path)
    assert (tmp_path / ".git").exists()
    assert git.has_commits()


def test_git_diff_after_file_change(tmp_path):
    git = make_git(tmp_path)
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    diff = git.diff()
    assert "hello.txt" in git.status_short()
    assert "hello" in diff


def test_empty_diff_does_not_commit(tmp_path):
    git = make_git(tmp_path)
    git.diff()
    assert git.commit("No changes") is None


def test_diff_required_before_commit(tmp_path):
    git = make_git(tmp_path)
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    with pytest.raises(GitError):
        git.commit("Add x")


def test_commit_changes_creates_commit_hash(tmp_path):
    git = make_git(tmp_path)
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    git.diff()
    info = git.commit("Add x")
    assert info is not None
    assert len(info.hash) >= 7
    assert "x.txt" in info.changed_files


def test_finish_can_detect_uncommitted_changes(tmp_path):
    git = make_git(tmp_path)
    (tmp_path / "left.txt").write_text("left", encoding="utf-8")
    assert git.has_uncommitted_changes()
