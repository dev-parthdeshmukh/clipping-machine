import json

import pytest

from gta6clip import claude, config
from gta6clip.live import clipper, record


def test_source_urls():
    assert record.stream_url("twitch:KaiCenat") == ("https://twitch.tv/kaicenat", "twitch", "kaicenat")
    assert record.stream_url("youtube:@IShowSpeed") == ("https://www.youtube.com/@IShowSpeed/live", "youtube", "IShowSpeed")
    assert record.stream_url("https://www.twitch.tv/xqc")[1:] == ("twitch", "xqc")


def test_streamlink_command_with_cookies(tmp_path):
    ck = tmp_path / "cookies.txt"
    ck.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\n"
                  ".google.com\tTRUE\t/\tTRUE\t0\tNID\tzzz\n", encoding="utf-8")
    cmd = record.command("streamlink", "https://www.youtube.com/@x/live", tmp_path / "s.ts", cookies_file=ck)
    assert cmd[:3] == ["streamlink", "https://www.youtube.com/@x/live", "best"]
    assert ["--http-cookie", "SID=abc"] == cmd[cmd.index("--http-cookie"):cmd.index("--http-cookie") + 2]
    assert "NID=zzz" not in cmd                       # only cookies for the stream's site
    assert "--retry-streams" in cmd and "--force" in cmd


def test_plan_window_clamps_to_recording():
    assert clipper.plan_window(spike_wall=1100.0, start_wall=1000.0) == (100.0, 25.0, 190.0)
    assert clipper.plan_window(spike_wall=1030.0, start_wall=1000.0)[1] == 0.0


W = [{"s": i * 0.5, "e": i * 0.5 + 0.4, "w": ("go." if i % 20 == 19 else "word")} for i in range(330)]


def test_claude_pick_constrained_to_window(monkeypatch):
    reply = json.dumps({"start": 10.0, "end": 120.0, "hook_text": "Kai *Loses* It 😭", "score": 88,
                        "post_title": "Kai loses it", "description": "d", "hashtags": ["kai"],
                        "captions": {"tiktok": "t"}})
    monkeypatch.setattr(claude, "ask", lambda p, cfg, timeout=600: reply)
    m = clipper.pick(W, spike_rel=75.0, streamer="Kai", cfg=config.load())
    assert 9.0 <= m["start"] <= 10.0 and m["hook_text"] == "Kai *Loses* It 😭"
    assert m["post_title"] == "Kai loses it" and "#gta6" in m["hashtags"] and m["source"] == "claude"


def test_pick_falls_back_without_claude(monkeypatch):
    def boom(p, cfg, timeout=600):
        raise RuntimeError("OAuth session expired")
    monkeypatch.setattr(claude, "ask", boom)
    m = clipper.pick(W, spike_rel=75.0, streamer="Kai", cfg=config.load())
    assert m["source"] == "fallback" and m["start"] < 75.0 < m["end"]
    assert m["hook_text"] == "Kai *Can't* Believe This 😭" and m["end"] - m["start"] >= 45


def test_pick_prompt_has_house_rules(monkeypatch):
    sent = []
    monkeypatch.setattr(claude, "ask", lambda p, cfg, timeout=600: sent.append(p) or "{}")
    clipper.pick(W, spike_rel=75.0, streamer="Kai", cfg=config.load())
    for rule in ("whole topic", "*asterisks*", "Title Case", "75.0", "60-120"):
        assert rule in sent[0]


def test_worker_clips_ready_spikes_and_writes_post(tmp_path, monkeypatch):
    import threading
    from gta6clip.live import detect, run as live_run
    monkeypatch.setattr(config, "HOME", tmp_path)
    sess = record.Session(tmp_path / "s.ts", start_wall=1000.0, end_wall=2000.0)

    (tmp_path / "s.ts").write_bytes(b"x")

    class Rec:
        name, platform, url = "kaicenat", "twitch", "https://twitch.tv/kaicenat"
        lock, sessions = threading.Lock(), [sess]
        def session_at(self, wall):
            return sess if 1000 <= wall <= 2000 else None

    book = detect.EventBook()
    book.add(detect.Event("kaicenat-1500", "kaicenat", 1500.0, 1505.0, {"source": "chat"}))
    book.add(detect.Event("kaicenat-9000", "kaicenat", 9000.0, 9000.0, {"source": "audio"}))   # no recording
    rec_made = {"file": "01_x.mp4", "hook_text": "Kai *Wins* 😭", "kind": "live", "duration": 70.0, "score": 80,
                "captions": {}, "hashtags": ["#gta6"], "reason": "r", "stream_start": 450.0}
    monkeypatch.setattr(clipper, "make_clip", lambda ev, s, i, w, o, cfg, name: dict(rec_made))
    stop = threading.Event(); stop.set()
    made = live_run._worker({"kaicenat": Rec()}, book, stop, config.load(), tmp_path / "day")
    assert len(made["kaicenat"]) == 1 and book.pending() == []
    assert "Kai *Wins* 😭" in (tmp_path / "day" / "kaicenat__live" / "POST.md").read_text(encoding="utf-8")
    assert not (tmp_path / "s.ts").exists()                            # clipped and ended -> deleted


def _rec_with(sessions):
    r = record.Recorder("twitch:kaicenat", ".", "streamlink")
    r.sessions = sessions
    return r


def test_cleanup_deletes_finished_recordings_only(tmp_path):
    from gta6clip.live import detect, run as live_run
    done = tmp_path / "done.ts"; done.write_bytes(b"x")
    live = tmp_path / "live.ts"; live.write_bytes(b"x")
    waiting = tmp_path / "waiting.ts"; waiting.write_bytes(b"x")
    failed = tmp_path / "failed.ts"; failed.write_bytes(b"x")
    s_done = record.Session(done, 1000.0, 2000.0)
    s_live = record.Session(live, 5000.0, None)                       # still recording
    s_wait = record.Session(waiting, 3000.0, 4000.0)                  # a spike not clipped yet
    s_fail = record.Session(failed, 6000.0, 7000.0)                   # a clip from it failed
    rec = _rec_with([s_done, s_live, s_wait, s_fail])
    book = detect.EventBook()
    book.add(detect.Event("kaicenat-3500", "kaicenat", 3500.0, 3500.0, {}))
    deleted = live_run.cleanup(rec, book, failed={str(failed)})
    assert deleted == [done] and not done.exists()
    assert live.exists() and waiting.exists() and failed.exists()
    assert rec.sessions == [s_live, s_wait, s_fail]


def test_stopping_waits_for_recorders_to_close(monkeypatch, tmp_path):
    import threading, time as _t
    from gta6clip.live import run as live_run
    monkeypatch.setattr(config, "HOME", tmp_path)
    closed = []

    class FakeRec:
        def __init__(self, src, out_dir, streamlink, cookies, stop):
            self.name, self.platform, self.url, self.stop = "x", "youtube", "u", stop
            self.sessions, self.lock = [], threading.Lock()
        def run_forever(self):
            self.stop.wait()
            _t.sleep(0.3)                      # closing streamlink takes a moment
            closed.append(True)
        def current(self):
            return None
        def session_at(self, wall):
            return None

    monkeypatch.setattr(live_run.record, "Recorder", FakeRec)
    monkeypatch.setattr(live_run.shutil, "which", lambda n: "streamlink")
    live_run.main(["youtube:@x"], duration=0.2)
    assert closed == [True]


def test_kill_tree_uses_taskkill_on_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(record.os, "name", "nt")
    monkeypatch.setattr(record.subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    class P:
        pid = 4242
        def poll(self):
            return None
        def wait(self, timeout=None):
            return 0
    record.kill_tree(P())
    assert calls and calls[0][:4] == ["taskkill", "/PID", "4242", "/T"]


def test_recording_without_spikes_is_deleted_after_stop(monkeypatch, tmp_path):
    import threading, time as _t
    from gta6clip.live import run as live_run
    monkeypatch.setattr(config, "HOME", tmp_path)
    ts = tmp_path / "rec.ts"
    ts.write_bytes(b"x")

    class FakeRec:
        def __init__(self, src, out_dir, streamlink, cookies, stop):
            self.name, self.platform, self.url, self.stop = "x", "youtube", "u", stop
            self.sessions, self.lock = [record.Session(ts, 1000.0, None)], threading.Lock()
        def run_forever(self):
            self.stop.wait()
            _t.sleep(0.2)
            self.sessions[0].end_wall = 1100.0     # the session ends only once streamlink stops
        def current(self):
            return None
        def session_at(self, wall):
            return None

    monkeypatch.setattr(live_run.record, "Recorder", FakeRec)
    monkeypatch.setattr(live_run.shutil, "which", lambda n: "streamlink")
    live_run.main(["youtube:@x"], duration=0.2)
    assert not ts.exists()
