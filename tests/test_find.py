from gta6clip import config, find


def test_parse_watchlist():
    txt = "# c\ntwitch:xqc\n\nyoutube:@kai # note\nkick:x\nbad\n"
    assert find.parse_watchlist(txt) == [("twitch", "xqc"), ("youtube", "@kai"), ("kick", "x")]


def _s(n, v, t="GTA 6 day 1"):
    return {"url": n, "platform": "youtube", "name": n, "title": t,
            "views": v, "duration": 9000, "live": False, "source": "x"}


def test_find_ranks_dedupes_and_filters(monkeypatch):
    monkeypatch.setattr(find, "twitch_top", lambda cfg: [_s("A", 50)])
    monkeypatch.setattr(find, "watchlist", lambda cfg: [_s("a", 90), _s("B", 70, "Just Chatting")])
    monkeypatch.setattr(find, "youtube_today", lambda q: [_s("C", 10)])
    out = find.find(config.load(), limit=5)
    assert [x["name"] for x in out] == ["a", "C"]


def test_find_drops_live_youtube(monkeypatch):
    live = dict(_s("L", 999), live=True)
    monkeypatch.setattr(find, "twitch_top", lambda cfg: [])
    monkeypatch.setattr(find, "watchlist", lambda cfg: [])
    monkeypatch.setattr(find, "youtube_today", lambda q: [live, _s("C", 10)])
    assert [x["name"] for x in find.find(config.load(), limit=5)] == ["C"]


def test_find_limit(monkeypatch):
    monkeypatch.setattr(find, "twitch_top", lambda cfg: [])
    monkeypatch.setattr(find, "watchlist", lambda cfg: [])
    monkeypatch.setattr(find, "youtube_today", lambda q: [_s(str(i), i) for i in range(9)])
    assert [x["name"] for x in find.find(config.load(), limit=2)] == ["8", "7"]
