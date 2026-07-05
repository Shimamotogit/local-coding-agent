from agent.config import AppConfig
from agent.loop import AgentLoop


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.messages = []

    def chat(self, messages):
        self.calls += 1
        self.messages.append(messages)
        if self.responses:
            return self.responses.pop(0)
        return '{"requirements_met":true,"assessment":"完了","next_instruction":"","should_finish":true}'


def monitor_done():
    return '{"requirements_met":true,"assessment":"要件を満たしています","next_instruction":"","should_finish":true}'


def monitor_continue(instruction="次の作業を続けてください"):
    return '{"requirements_met":false,"assessment":"まだ未完了です","next_instruction":"' + instruction + '","should_finish":false}'


def test_finish_action_stops_after_monitor_approval(tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    loop = AgentLoop(
        config,
        llm=FakeLLM([
            '{"action":"finish","args":{"summary":"done","tests":"n/a"}}',
            monitor_done(),
        ]),
    )
    result = loop.run("finish")
    assert result.stop_reason == "finish"
    assert result.shared_history[-1]["agent"] == "monitor"


def test_monitor_can_reject_early_finish_and_instruct_next_step(tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    llm = FakeLLM(
        [
            '{"action":"finish","args":{"summary":"done too early"}}',
            monitor_continue("テストを実行してください"),
            '{"action":"run_command","args":{"command":"python -c \\"print(1)\\""}}',
            monitor_done(),
        ]
    )
    result = AgentLoop(config, llm=llm).run("do more than finish")
    assert result.stop_reason == "finish"
    assert "テストを実行してください" in llm.messages[2][1]["content"]


def test_max_steps_stops(tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    from dataclasses import replace

    config = replace(config, limits=replace(config.limits, max_steps=1))
    llm = FakeLLM([
        '{"action":"list_files","args":{"path":"."}}',
        monitor_continue(),
    ])
    result = AgentLoop(config, llm=llm).run("loop")
    assert result.stop_reason == "max_steps"


def test_max_steps_minus_one_does_not_stop_by_steps(tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    from dataclasses import replace

    config = replace(config, limits=replace(config.limits, max_steps=-1, max_runtime_seconds=30))
    llm = FakeLLM([
        '{"action":"list_files","args":{"path":"."}}',
        monitor_continue(),
        '{"action":"finish","args":{"summary":"done"}}',
        monitor_done(),
    ])
    result = AgentLoop(config, llm=llm).run("loop")
    assert result.stop_reason == "finish"


def test_repeated_error_stops(tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    from dataclasses import replace

    config = replace(config, limits=replace(config.limits, max_repeated_errors=2, max_consecutive_failures=-1, max_steps=10))
    llm = FakeLLM([
        "not json",
        monitor_continue(),
        "not json",
        monitor_continue(),
        '{"action":"finish","args":{"summary":"ok"}}',
        monitor_done(),
    ])
    result = AgentLoop(config, llm=llm).run("bad")
    assert result.stop_reason == "max_repeated_errors"


def test_repeated_error_minus_one_does_not_stop(tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    from dataclasses import replace

    config = replace(config, limits=replace(config.limits, max_repeated_errors=-1, max_consecutive_failures=3, max_steps=10))
    llm = FakeLLM([
        "not json",
        monitor_continue(),
        '{"action":"finish","args":{"summary":"ok"}}',
        monitor_done(),
    ])
    result = AgentLoop(config, llm=llm).run("bad then ok")
    assert result.stop_reason == "finish"


def test_consecutive_failures_stops(tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    from dataclasses import replace

    config = replace(config, limits=replace(config.limits, max_consecutive_failures=2, max_repeated_errors=-1, max_steps=10))
    llm = FakeLLM([
        "not json",
        monitor_continue(),
        "still not json",
        monitor_continue(),
        '{"action":"finish","args":{"summary":"ok"}}',
        monitor_done(),
    ])
    result = AgentLoop(config, llm=llm).run("bad")
    assert result.stop_reason == "max_consecutive_failures"


def test_run_command_observation_goes_back_to_both_agents(monkeypatch, tmp_path):
    from agent.sandbox import DockerSandbox, CommandResult

    def fake_run(self, command, timeout=30):
        return CommandResult(command=command, returncode=0, stdout="hello\n", stderr="")

    monkeypatch.setattr(DockerSandbox, "run", fake_run)
    config = AppConfig.from_env(workspace=tmp_path)
    llm = FakeLLM(
        [
            '{"action":"run_command","args":{"command":"python -c \\"print(1)\\""}}',
            monitor_done(),
        ]
    )
    result = AgentLoop(config, llm=llm).run("run")
    assert result.observations[0]["observation"]["result"]["stdout"] == "hello\n"
    assert "hello" in llm.messages[1][1]["content"]


def test_monitor_history_is_visible_to_executor(monkeypatch, tmp_path):
    from agent.sandbox import DockerSandbox, CommandResult

    def fake_run(self, command, timeout=30):
        return CommandResult(command=command, returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(DockerSandbox, "run", fake_run)
    config = AppConfig.from_env(workspace=tmp_path)
    llm = FakeLLM(
        [
            '{"action":"run_command","args":{"command":"echo ok"}}',
            monitor_continue("次は git_diff を確認してください"),
            '{"action":"git_diff","args":{}}',
            monitor_done(),
        ]
    )
    result = AgentLoop(config, llm=llm).run("history")
    assert result.stop_reason == "finish"
    second_executor_prompt = llm.messages[2][1]["content"]
    assert "次は git_diff を確認してください" in second_executor_prompt
    assert '"agent": "monitor"' in second_executor_prompt


def test_unsafe_mode_warning_is_printed(capsys, tmp_path):
    config = AppConfig.from_env(workspace=tmp_path)
    from dataclasses import replace

    config = replace(config, limits=replace(config.limits, max_steps=-1))
    result = AgentLoop(
        config,
        llm=FakeLLM([
            '{"action":"finish","args":{"summary":"done"}}',
            monitor_done(),
        ]),
    ).run("warn")
    captured = capsys.readouterr()
    assert "unsafe mode is enabled" in captured.out
    assert result.stop_reason == "finish"
