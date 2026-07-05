from agent.actions import ActionExecutor
from agent.config import AppConfig
from agent.git_manager import GitManager
from agent.logger import JsonlLogger
from agent.policy import SafetyPolicy
from agent.sandbox import DockerSandbox
from agent.searxng import SearxngClient
from agent.schemas import AgentAction


def make_executor(tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    policy = SafetyPolicy(tmp_path)
    logger = JsonlLogger(tmp_path / "logs")
    git = GitManager(tmp_path, policy)
    git.init_repo()
    sandbox = DockerSandbox(tmp_path, config.sandbox, policy)
    search = SearxngClient("http://localhost:8888")
    return ActionExecutor(config, policy, git, sandbox, search, logger)


def test_write_read_and_list_files(tmp_path):
    ex = make_executor(tmp_path)
    assert ex.execute(AgentAction("write_file", {"path": "agent/main.py", "content": "print('hi')\n"}))["ok"]
    read = ex.execute(AgentAction("read_file", {"path": "agent/main.py"}))
    assert read["result"]["content"] == "print('hi')\n"
    listed = ex.execute(AgentAction("list_files", {"path": "."}))
    assert "agent/main.py" in listed["result"]["entries"]


def test_append_file(tmp_path):
    ex = make_executor(tmp_path)
    ex.execute(AgentAction("write_file", {"path": "README.md", "content": "A"}))
    ex.execute(AgentAction("append_file", {"path": "README.md", "content": "B"}))
    read = ex.execute(AgentAction("read_file", {"path": "README.md"}))
    assert read["result"]["content"] == "AB"


def test_commit_changes_action(tmp_path):
    ex = make_executor(tmp_path)
    ex.execute(AgentAction("write_file", {"path": "README.md", "content": "# hi\n"}))
    result = ex.execute(AgentAction("commit_changes", {"message": "Add README"}))
    assert result["ok"]
    assert result["result"]["committed"] is True
