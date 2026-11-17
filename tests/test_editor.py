import json

import pytest

from gta6clip import claude, config, editor

ST = {"name": "Kai", "title": "t", "url": "u"}


def _c(i, s):
    return {"start": i * 100.0, "end": i * 100 + 30.0, "kind": "reaction", "title": f"t{i}",
            "hook_text": "h", "caption": "c", "hashtags": [], "score": s, "reason": "r"}


def _reply(ids_scores):
    return json.dumps([{"id": i, "score": s, "hooks": ["A", "B", "C"], "best_hook": 1,
                        "narrator_line": "Kai Cenat was NOT ready for this GTA 6 moment.",
                        "captions": {"tiktok": "t", "shorts": "s", "reels": "r"}, "hashtags": ["#gta6"]}
                       for i, s in ids_scores])


def test_finalize_bar_order_and_limit(tmp_path, monkeypatch):
    cands = [_c(i, 60 + i) for i in range(12)]
    monkeypatch.setattr(claude, "ask", lambda p, cfg, timeout=600: _reply([(0, 95), (1, 72), (2, 69), (3, 88)]))
    out = editor.finalize(cands, [], config.load(), ST, tmp_path)
    assert [round(m["score"]) for m in out] == [95, 88, 72]
    assert out[0]["hook_text"] == "B" and out[0]["narrator_line"].startswith("Kai")
    assert out[0]["captions"]["reels"] == "r" and out[0]["hooks"] == ["A", "B", "C"]
    assert (tmp_path / "moments.json").exists()


def test_ids_map_to_finalists_by_pass1_rank(tmp_path, monkeypatch):
    cands = [_c(0, 10), _c(1, 99)]                    # id 0 = best pass-1 candidate = _c(1)
    monkeypatch.setattr(claude, "ask", lambda p, cfg, timeout=600: _reply([(0, 90)]))
    out = editor.finalize(cands, [], config.load(), ST, tmp_path)
    assert out[0]["start"] == 100.0


def test_finalize_sends_top_finalists_only(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(claude, "ask", lambda p, cfg, timeout=600: sent.append(p) or "[]")
    editor.finalize([_c(i, i) for i in range(30)], [], config.load(), ST, tmp_path)
    assert sent[0].count('"id":') == 10


def test_nothing_above_bar_logs_best(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(claude, "ask", lambda p, cfg, timeout=600: _reply([(0, 55)]))
    assert editor.finalize([_c(0, 50)], [], config.load(), ST, tmp_path) == []
    out = capsys.readouterr().out
    assert "best was 55" in out and "--bar 60" in out


def test_pass2_failure_falls_back_to_pass1(tmp_path, monkeypatch, capsys):
    def boom(p, cfg, timeout=600):
        raise RuntimeError("claude -p failed")
    monkeypatch.setattr(claude, "ask", boom)
    out = editor.finalize([_c(0, 80)], [], config.load(), ST, tmp_path)
    assert out[0]["score"] == 80 and out[0]["narrator_line"] == "Look what Kai just did in GTA 6..."
    assert out[0]["captions"]["tiktok"] == "c"


def test_narrator_line_rules_in_prompt(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(claude, "ask", lambda p, cfg, timeout=600: sent.append(p) or "[]")
    words = [{"s": 5.0, "e": 5.5, "w": "insane"}]
    editor.finalize([_c(0, 80)], words, config.load(), ST, tmp_path)
    for rule in ("12 words", "never spoil", "name the streamer", "different", "insane"):
        assert rule in sent[0]


def test_non_numeric_score_does_not_crash(tmp_path, monkeypatch):
    reply = json.dumps([
        {"id": 0, "score": "high", "hooks": ["A"], "best_hook": 0, "narrator_line": "n", "captions": {}, "hashtags": []},
        {"id": 1, "score": 90, "hooks": ["B"], "best_hook": 0, "narrator_line": "m", "captions": {}, "hashtags": []}])
    monkeypatch.setattr(claude, "ask", lambda p, cfg, timeout=600: reply)
    out = editor.finalize([_c(0, 80), _c(1, 75)], [], config.load(), ST, tmp_path)
    assert [m["hook_text"] for m in out] == ["B", "A"]          # "high" falls back to pass-1 score 75
    assert all(isinstance(m["score"], float) for m in out)


def test_title_description_hashtags(tmp_path, monkeypatch):
    reply = json.dumps([{"id": 0, "score": 90, "hooks": ["A"], "best_hook": 0, "narrator_line": "n", "captions": {},
                         "hashtags": ["gta6", "#Speed"], "post_title": "Speed finds SCUBA in GTA 6 🤯",
                         "description": "Speed loses it over a hidden GTA 6 feature."}])
    monkeypatch.setattr(claude, "ask", lambda p, cfg, timeout=600: reply)
    m = editor.finalize([_c(0, 80)], [], config.load(), ST, tmp_path)[0]
    assert m["post_title"] == "Speed finds SCUBA in GTA 6 🤯"
    assert m["description"].startswith("Speed loses it")
    assert m["hashtags"][:2] == ["#gta6", "#Speed"] and "#shorts" in m["hashtags"]


def test_title_rules_in_prompt(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(claude, "ask", lambda p, cfg, timeout=600: sent.append(p) or "[]")
    editor.finalize([_c(0, 80)], [], config.load(), ST, tmp_path)
    for rule in ('"post_title"', "70 characters", '"description"', "5-8 hashtags"):
        assert rule in sent[0]


def test_fallback_has_title_and_description(tmp_path, monkeypatch):
    def boom(p, cfg, timeout=600):
        raise RuntimeError("down")
    monkeypatch.setattr(claude, "ask", boom)
    m = editor.finalize([_c(0, 80)], [], config.load(), ST, tmp_path)[0]
    assert m["post_title"] == "h" and m["description"] == "c" and "#gta6" in m["hashtags"]


def test_empty_candidates(tmp_path):
    assert editor.finalize([], [], config.load(), ST, tmp_path) == []


def test_hook_style_rules_in_prompt(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(claude, "ask", lambda p, cfg, timeout=600: sent.append(p) or "[]")
    editor.finalize([_c(0, 80)], [], config.load(), ST, tmp_path)
    for rule in ("Title Case", "2-5 words", "*asterisks*", "one emoji at the end"):
        assert rule in sent[0]


def test_post_title_has_no_asterisks(tmp_path, monkeypatch):
    reply = json.dumps([{"id": 0, "score": 90, "hooks": ["Speed Finds *Scuba* 🤯"], "best_hook": 0,
                         "narrator_line": "", "captions": {}, "hashtags": []}])
    monkeypatch.setattr(claude, "ask", lambda p, cfg, timeout=600: reply)
    m = editor.finalize([_c(0, 80)], [], config.load(), ST, tmp_path)[0]
    assert m["hook_text"] == "Speed Finds *Scuba* 🤯" and m["post_title"] == "Speed Finds Scuba 🤯"
