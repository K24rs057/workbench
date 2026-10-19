"""claude -p を呼ぶ共通の部分(agent.call_claude)。モッチ・1行入力・メール・自動で完了が使う。"""
import json
import subprocess
import types

import pytest

import agent


def fake_run(monkeypatch, stdout="", stderr="", exc=None):
    got = {}
    def run(cmd, **kw):
        got.update(cmd=cmd, kw=kw)
        if exc:
            raise exc
        return types.SimpleNamespace(stdout=stdout, stderr=stderr, returncode=0)
    monkeypatch.setattr(agent.subprocess, "run", run)
    return got


def test_structured_output_and_no_tools(monkeypatch):
    got = fake_run(monkeypatch, json.dumps({"is_error": False, "structured_output": {"reply": "はい", "action": None}}))
    assert agent.call_claude("sys", "質問") == {"reply": "はい", "action": None}
    cmd = got["cmd"]
    assert cmd[:2] == ["claude", "-p"] and cmd[cmd.index("--tools") + 1] == ""   # 道具は1つも渡さない
    assert "--no-session-persistence" in cmd and got["kw"]["input"] == "質問"


def test_result_text_is_read_as_json(monkeypatch):
    fake_run(monkeypatch, json.dumps({"is_error": False, "result": json.dumps({"reply": "文で来た", "action": None})}))
    assert agent.call_claude("sys", "q")["reply"] == "文で来た"


@pytest.mark.parametrize("stdout,stderr,err", [
    (json.dumps({"is_error": True, "result": "Claude AI usage limit reached|1760000000"}), "", agent.UsageLimit),
    (json.dumps({"is_error": True, "result": "うまくいかなかった"}), "", agent.AgentError),
    ("", "Error: usage limit reached", agent.UsageLimit),            # JSON でない出力でも上限を見分ける
    ("こわれた出力", "", agent.AgentError),
    (json.dumps({"is_error": False, "result": "JSON でない文"}), "", agent.AgentError),
])
def test_errors(monkeypatch, stdout, stderr, err):
    fake_run(monkeypatch, stdout, stderr)
    with pytest.raises(err) as e:
        agent.call_claude("sys", "q")
    if err is agent.AgentError:
        assert not isinstance(e.value, agent.UsageLimit)


@pytest.mark.parametrize("exc", [FileNotFoundError("claude がない"), subprocess.TimeoutExpired("claude", 120)])
def test_claude_missing_or_slow(monkeypatch, exc):
    fake_run(monkeypatch, exc=exc)
    with pytest.raises(agent.AgentError):
        agent.call_claude("sys", "q")
