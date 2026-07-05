import pytest

from agent.schemas import parse_action, ActionValidationError


def test_accepts_valid_json_action():
    action = parse_action('{"thought_summary":"check","action":"run_command","args":{"command":"pytest -q"}}')
    assert action.action == "run_command"
    assert action.args["command"] == "pytest -q"


def test_rejects_unknown_action():
    with pytest.raises(ActionValidationError):
        parse_action('{"action":"explode","args":{}}')


def test_rejects_missing_required_args():
    with pytest.raises(ActionValidationError):
        parse_action('{"action":"write_file","args":{"path":"x.py"}}')


def test_rejects_non_json_output():
    with pytest.raises(ActionValidationError):
        parse_action('```json {"action":"finish"} ```')


def test_accepts_commit_changes_action():
    action = parse_action({"action": "commit_changes", "args": {"message": "Add files"}})
    assert action.action == "commit_changes"
