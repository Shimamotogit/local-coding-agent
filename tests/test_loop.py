from agent.config import AppConfig
from agent.loop import AgentLoop


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
    def chat(self, messages):
        self.calls += 1
        if self.responses:
            return self.responses.pop(0)
        return '{"action":"finish","args":{"summary":"done"}}'


def test_finish_action_stops(tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    loop = AgentLoop(config, llm=FakeLLM(['{"action":"finish","args":{"summary":"done","tests":"n/a"}}']))
    result = loop.run("finish")
    assert result.stop_reason == "finish"


def test_max_steps_stops(tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    from dataclasses import replace
    config = replace(config, limits=replace(config.limits, max_steps=1))
    llm = FakeLLM(['{"action":"list_files","args":{"path":"."}}'] * 5)
    result = AgentLoop(config, llm=llm).run("loop")
    assert result.stop_reason == "max_steps"


def test_max_steps_minus_one_does_not_stop_by_steps(tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    from dataclasses import replace
    config = replace(config, limits=replace(config.limits, max_steps=-1, max_runtime_seconds=30))
    llm = FakeLLM(['{"action":"list_files","args":{"path":"."}}', '{"action":"finish","args":{"summary":"done"}}'])
    result = AgentLoop(config, llm=llm).run("loop")
    assert result.stop_reason == "finish"


def test_repeated_error_stops(tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    from dataclasses import replace
    config = replace(config, limits=replace(config.limits, max_repeated_errors=2, max_consecutive_failures=-1, max_steps=10))
    llm = FakeLLM(['not json'] * 5)
    result = AgentLoop(config, llm=llm).run("bad")
    assert result.stop_reason == "max_repeated_errors"


def test_repeated_error_minus_one_does_not_stop(tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    from dataclasses import replace
    config = replace(config, limits=replace(config.limits, max_repeated_errors=-1, max_consecutive_failures=3, max_steps=10))
    llm = FakeLLM(['not json', '{"action":"finish","args":{"summary":"ok"}}'])
    result = AgentLoop(config, llm=llm).run("bad then ok")
    assert result.stop_reason == "finish"


def test_consecutive_failures_stops(tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    from dataclasses import replace
    config = replace(config, limits=replace(config.limits, max_consecutive_failures=2, max_repeated_errors=-1, max_steps=10))
    llm = FakeLLM(['not json', 'still not json', '{"action":"finish","args":{"summary":"ok"}}'])
    result = AgentLoop(config, llm=llm).run("bad")
    assert result.stop_reason == "max_consecutive_failures"


def test_run_command_observation_goes_back_to_llm(monkeypatch, tmp_path):
    from agent.sandbox import DockerSandbox, CommandResult

    def fake_run(self, command, timeout=30):
        return CommandResult(command=command, returncode=0, stdout="hello\n", stderr="")

    monkeypatch.setattr(DockerSandbox, "run", fake_run)
    config = AppConfig.from_env(workspace=tmp_path)
    llm = FakeLLM([
        '{"action":"run_command","args":{"command":"python -c \\"print(1)\\""}}',
        '{"action":"finish","args":{"summary":"done"}}',
    ])
    result = AgentLoop(config, llm=llm).run("run")
    assert result.observations[0]["result"]["stdout"] == "hello\n"


def test_unsafe_mode_warning_is_printed(capsys, tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    from dataclasses import replace
    config = replace(config, limits=replace(config.limits, max_steps=-1))
    result = AgentLoop(config, llm=FakeLLM(['{"action":"finish","args":{"summary":"done"}}'])).run("warn")
    captured = capsys.readouterr()
    assert "unsafe mode is enabled" in captured.out
    assert result.stop_reason == "finish"
