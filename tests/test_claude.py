import shutil
import subprocess

from gta6clip import claude


def test_argv_prefers_exe_then_cmd_then_ps1(monkeypatch):
    found = {"claude": None, "claude.exe": None, "claude.cmd": r"C:\npm\claude.cmd", "claude.ps1": r"C:\npm\claude.ps1"}
    monkeypatch.setattr(shutil, "which", lambda n: found.get(n))
    assert claude.argv() == [r"C:\npm\claude.cmd", "-p"]
    found["claude.cmd"] = None
    a = claude.argv()
    assert a[:4] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"] and a[-1] == "-p"
    assert r"C:\npm\claude.ps1" in a


def test_parse_array_variants():
    assert claude.parse_array('```json\n[{"a":1}]\n```') == [{"a": 1}]
    assert claude.parse_array('Here you go: [{"a":1}] thanks') == [{"a": 1}]
    assert claude.parse_array("no json") == []
    assert claude.parse_array('{"a":1}') == []
    assert claude.parse_array("[1, 2]") == []


def test_ask_strips_claudecode_env_and_passes_model(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, env=kw["env"], input=kw["input"], enc=kw.get("encoding"))
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(claude, "argv", lambda: ["claude.exe", "-p"])
    assert claude.ask("hi 😭", {"claude_model": "sonnet"}) == "[]"
    assert seen["cmd"] == ["claude.exe", "-p", "--model", "sonnet"] and "CLAUDECODE" not in seen["env"]
    assert seen["input"] == "hi 😭" and seen["enc"] == "utf-8"


def test_ask_raises_on_failure(monkeypatch):
    import pytest
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not logged in"))
    monkeypatch.setattr(claude, "argv", lambda: ["claude.exe", "-p"])
    with pytest.raises(RuntimeError, match="not logged in"):
        claude.ask("x", {})
