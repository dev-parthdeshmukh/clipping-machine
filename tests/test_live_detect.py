from gta6clip.live import chat, detect

D = detect.CHAT_DEFAULTS


def _feed_rate(det, t0, seconds, per_bucket):
    """Feed `per_bucket` messages per 10 s bucket from t0 for `seconds`; returns events."""
    events = []
    t = t0
    while t < t0 + seconds:
        for i in range(per_bucket):
            events += det.feed({"type": "msg", "t": t + i * (10 / max(per_bucket, 1)) * 0.9})
        events += det.feed({"type": "heartbeat", "t": t + 9.5})
        t += 10
    return events


def test_chat_spike_after_warmup():
    det = detect.ChatSpikeDetector("xqc", D)
    det.feed({"type": "connect", "t": 1000.0})
    assert _feed_rate(det, 1000.0, 310, 4) == []              # 5 min warm-up (first bucket is partial)
    ev = _feed_rate(det, 1310.0, 20, 20) + _feed_rate(det, 1330.0, 30, 4)
    assert len(ev) == 1 and ev[0].spike_ts == 1310.0 and ev[0].stats["peak_count"] == 20


def test_no_spike_before_history_or_below_min_messages():
    det = detect.ChatSpikeDetector("x", D)
    det.feed({"type": "connect", "t": 0.0})
    assert _feed_rate(det, 0.0, 60, 30) == []                 # no history yet
    det2 = detect.ChatSpikeDetector("x", D)
    det2.feed({"type": "connect", "t": 0.0})
    _feed_rate(det2, 0.0, 300, 1)
    assert _feed_rate(det2, 300.0, 30, 5) + _feed_rate(det2, 330.0, 20, 1) == []   # 5 < 8 msgs


def test_disconnect_resets_baseline():
    det = detect.ChatSpikeDetector("x", D)
    det.feed({"type": "connect", "t": 0.0})
    _feed_rate(det, 0.0, 300, 4)
    det.feed({"type": "disconnect", "t": 301.0})
    det.feed({"type": "connect", "t": 400.0})
    assert _feed_rate(det, 400.0, 30, 30) == []               # history cleared


def test_audio_spike_needs_rise_floor_and_duration():
    det = detect.AudioSpikeDetector("x", detect.AUDIO_DEFAULTS)
    ev = []
    for t in range(300):
        ev += det.feed(float(t), -35.0)
    ev += det.feed(300.0, -10.0)                              # 1 s blip: too short
    for t in range(301, 330):
        ev += det.feed(float(t), -35.0)
    for t in range(330, 334):
        ev += det.feed(float(t), -12.0)                       # 4 s scream: +23 dB
    for t in range(334, 340):
        ev += det.feed(float(t), -35.0)
    assert [e.spike_ts for e in ev] == [330.0]


def test_merge_events():
    q = detect.EventBook(merge_window=45)
    assert q.add(detect.Event("x-100", "x", 100.0, 105.0, {"source": "chat"}))
    assert not q.add(detect.Event("x-130", "x", 130.0, 131.0, {"source": "audio"}))
    assert q.add(detect.Event("x-200", "x", 200.0, 201.0, {"source": "audio"}))
    assert [e.event_id for e in q.pending()] == ["x-100", "x-200"]


def test_irc_parse_and_read_only():
    m = chat.parse_irc("@display-name=Kai;tmi-sent-ts=1700000000000 :kai!kai@kai.tmi.twitch.tv PRIVMSG #xqc :LMAO 😭")
    assert m.command == "PRIVMSG" and m.trailing == "LMAO 😭" and m.tags["display-name"] == "Kai"
    r = chat.ChatReader("xqc", None)
    try:
        r._send("PRIVMSG #xqc :hi")
        assert False, "must refuse to send chat"
    except PermissionError:
        pass


def test_read_new_leaves_partial_line(tmp_path):
    p = tmp_path / "chat.log"
    p.write_bytes(b'{"type": "msg", "t": 1}\n{"type": "msg", "t": 2}\n{"type": "ms')
    recs, off = chat.read_new(p, 0)
    assert [r["t"] for r in recs] == [1, 2]
    with open(p, "ab") as fh:
        fh.write(b'g", "t": 3}\n')
    recs, off2 = chat.read_new(p, off)
    assert [r["t"] for r in recs] == [3] and off2 == p.stat().st_size


def test_irc_parse_tag_escapes_and_ping():
    m = chat.parse_irc(r"@display-name=a\sb;emotes= :x!x@x PRIVMSG #c :hello world")
    assert m.tags["display-name"] == "a b" and m.trailing == "hello world" and m.nick == "x"
    assert chat.parse_irc("PING :tmi.twitch.tv").command == "PING"
