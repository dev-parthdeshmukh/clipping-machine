import pytest

from gta6clip import config, fetch, narrator, run, scan


def test_parse_flags():
    o = run.parse(["u1", "--clips", "4", "--bar", "60", "--cookies", "chrome", "--no-narrator"])
    assert o.urls == ["u1"] and o.clips == 4 and o.bar == 60 and o.cookies == "chrome" and o.no_narrator


def test_age_restricted_message_and_others_continue(monkeypatch, capsys):
    def fake(url, cfg, opts):
        if url == "bad":
            raise RuntimeError("Sign in to confirm your age")
        return {"finals": [], "url": url}
    monkeypatch.setattr(run, "analyse_stream", fake)
    monkeypatch.setattr(run, "_require_tools", lambda: None)
    run.main(["bad", "good", "--no-narrator"])
    out = capsys.readouterr().out
    assert "--cookies chrome" in out and "0 clip(s) from 1 stream(s)" in out


def test_narrator_crash_still_makes_clips(monkeypatch, capsys):
    made = []
    monkeypatch.setattr(run, "analyse_stream",
                        lambda url, cfg, opts: {"finals": [{"narrator_line": "x", "start": 0, "end": 20}], "url": url})
    monkeypatch.setattr(run, "_require_tools", lambda: None)
    monkeypatch.setattr(scan, "unload", lambda: None)
    monkeypatch.setattr(narrator, "synth", lambda lines, outdir, cfg: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(run, "make_clips", lambda s, voices, cfg, opts: made.append(voices) or [])
    run.main(["a", "--voice", "voxcpm2"])
    assert made == [{}] and "narration skipped" in capsys.readouterr().out


def test_live_youtube_is_skipped_with_message(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(fetch, "info", lambda url, args, work, refresh=False:
                        {"name": "x", "title": "t", "live_status": "is_live", "extractor_key": "Youtube"})
    with pytest.raises(RuntimeError, match="still live"):
        run.analyse_stream("https://youtube.com/watch?v=1", config.load(), run.parse(["u"]))


def test_live_twitch_refreshes_cached_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "HOME", tmp_path)
    seen = {}

    def info(url, args, work, refresh=False):
        seen["info"] = refresh
        return {"name": "x", "title": "t", "live_status": "is_live", "extractor_key": "TwitchVod"}

    def aud(url, args, work, refresh=False):
        seen["audio"] = refresh
        raise RuntimeError("stop here")
    monkeypatch.setattr(fetch, "info", info)
    monkeypatch.setattr(fetch, "audio", aud)
    with pytest.raises(RuntimeError, match="stop here"):
        run.analyse_stream("https://www.twitch.tv/videos/1", config.load(), run.parse(["u"]))
    assert seen == {"info": True, "audio": True}


def test_cookie_advice_mentions_firefox():
    msg = run._friendly("https://youtube.com/x", "Sign in to confirm your age")
    assert "--cookies firefox" in msg and "--cookies chrome" in msg
    assert "--cookies firefox" in run._friendly("u", "ERROR: Could not copy Chrome cookie database")


def test_narration_runs_once_for_all_streams_after_unload(monkeypatch, capsys):
    order = []
    finals = lambda tag: [{"narrator_line": f"line {tag}{i}", "start": 0, "end": 20} for i in range(2)]
    monkeypatch.setattr(run, "analyse_stream", lambda url, cfg, opts: {"finals": finals(url), "url": url})
    monkeypatch.setattr(run, "_require_tools", lambda: None)
    monkeypatch.setattr(scan, "unload", lambda: order.append("unload"))
    monkeypatch.setattr(narrator, "synth", lambda lines, outdir, cfg: order.append(len(lines)) or {})
    monkeypatch.setattr(run, "make_clips", lambda s, voices, cfg, opts: order.append("render") or [])
    run.main(["a", "b", "--voice", "voxcpm2"])
    assert order == ["unload", 4, "render", "render"]


def test_parse_cookies_file():
    assert run.parse(["u", "--cookies-file", "cookies.txt"]).cookies_file == "cookies.txt"


def test_no_narration_by_default(monkeypatch):
    called = []
    monkeypatch.setattr(run, "analyse_stream",
                        lambda url, cfg, opts: {"finals": [{"narrator_line": "x", "start": 0, "end": 70}], "url": url})
    monkeypatch.setattr(run, "_require_tools", lambda: None)
    monkeypatch.setattr(scan, "unload", lambda: None)
    monkeypatch.setattr(narrator, "synth", lambda lines, outdir, cfg: called.append(1) or {})
    monkeypatch.setattr(run, "make_clips", lambda s, voices, cfg, opts: [])
    run.main(["a"])
    assert called == []


def test_live_flag_dispatches(monkeypatch):
    seen = {}
    from gta6clip.live import run as live_run
    monkeypatch.setattr(run, "_require_tools", lambda: None)
    monkeypatch.setattr(live_run, "main", lambda sources, cookies_file=None, duration=None: seen.update(
        s=sources, c=cookies_file, d=duration))
    run.main(["--live", "twitch:kaicenat", "youtube:@x", "--for", "600", "--cookies-file", "cookies.txt"])
    assert seen == {"s": ["twitch:kaicenat", "youtube:@x"], "c": "cookies.txt", "d": 600}
