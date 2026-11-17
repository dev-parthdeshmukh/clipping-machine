import json
import shutil

import pytest

from gta6clip import config, fetch, find


def test_base_args_cookies_and_node(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda n: r"C:\node.exe" if n == "node" else None)
    assert fetch.base_args("https://youtu.be/x", "chrome") == [
        "--js-runtimes", r"node:C:\node.exe", "--cookies-from-browser", "chrome"]
    assert fetch.base_args("https://twitch.tv/v/1") == []


def test_info_cached_and_named(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(fetch, "run", lambda cmd, timeout=None: calls.append(cmd) or json.dumps(
        {"id": "x", "title": "GTA 6 🔥", "uploader": "xQc", "duration": 9000, "live_status": "was_live"}))
    a = fetch.info("u", [], tmp_path)
    b = fetch.info("u", [], tmp_path)
    assert a["name"] == "xQc" and a == b and len(calls) == 1
    assert "🔥" in (tmp_path / "info.json").read_text(encoding="utf-8")


@pytest.mark.slow
def test_find_live():
    out = find.find(config.load(), 3)
    assert out and out[0]["url"].startswith("https://")


def test_base_args_cookie_file(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda n: None)
    f = tmp_path / "cookies.txt"
    f.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    assert fetch.base_args("https://twitch.tv/v/1", cookies_file=str(f)) == ["--cookies", str(f)]
