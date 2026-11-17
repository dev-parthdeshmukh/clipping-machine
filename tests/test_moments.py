import numpy as np
import pytest

from gta6clip import claude, config, moments

W = [{"s": i * 0.5, "e": i * 0.5 + 0.4, "w": ("go." if i % 20 == 19 else "word")} for i in range(400)]
STREAM = {"name": "xQc", "title": "GTA 6", "url": "u"}


def test_lines_mark_loud():
    loud = np.zeros(200)
    loud[20] = 9
    ls = moments.lines(W, loud, [], config.load())
    assert any("[LOUD +9dB]" in t for _, t in ls) and not ls[0][1].startswith("[LOUD")


def test_lines_mark_chat():
    chat = [2] * 40
    chat[10] = 10
    ls = moments.lines(W, np.zeros(200), chat, config.load())
    assert any("[CHAT x5]" in t for _, t in ls)


def test_snap_enforces_limits():
    cfg = config.load()
    m = moments.snap({"start": 10.2, "end": 190.0}, W, cfg)
    assert cfg["min_duration"] <= m["end"] - m["start"] <= cfg["max_duration"] and m["start"] == pytest.approx(9.4, abs=0.01)
    assert moments.snap({"start": 10.0, "end": 12.0}, W[:30], cfg) is None


def test_dedupe_keeps_higher_score():
    a = {"start": 0, "end": 30, "score": 50}
    b = {"start": 5, "end": 35, "score": 90}
    c = {"start": 100, "end": 130, "score": 10}
    assert moments.dedupe([a, b, c]) == [b, c]


def test_candidates_uses_prompt_rules_and_caches(tmp_path, monkeypatch):
    prompts = []
    reply = ('[{"start": 20, "end": 50, "kind": "reaction", "title": "t", "hook_text": "h", '
             '"caption": "c", "hashtags": ["#gta6"], "score": 80, "reason": "r"}]')
    monkeypatch.setattr(claude, "ask", lambda p, cfg, timeout=600: prompts.append(p) or reply)
    out = moments.candidates({"words": W, "language": "en"}, np.zeros(200), None, tmp_path, config.load(), STREAM)
    assert out and (tmp_path / "candidates.json").exists()
    p = prompts[0]
    for rule in ("first_reaction", "uh so yeah", "60-120", "whole topic", "zero context", "payoff", "*asterisks*"):
        assert rule in p
    monkeypatch.setattr(claude, "ask", lambda p, cfg, timeout=600: pytest.fail("cache not used"))
    assert moments.candidates({"words": W, "language": "en"}, np.zeros(200), None, tmp_path, config.load(), STREAM) == out


def test_failed_window_is_skipped(tmp_path, monkeypatch):
    def boom(p, cfg, timeout=600):
        raise RuntimeError("claude -p failed")
    monkeypatch.setattr(claude, "ask", boom)
    assert moments.candidates({"words": W, "language": "en"}, np.zeros(200), None, tmp_path, config.load(), STREAM) == []
