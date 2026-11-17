"""Spike detection for live streams.

Chat: messages are counted in 10 s windows. A window is "hot" when it holds at least 3x the
average of the windows in the 5 minutes before it (that average never includes the window being
judged), never less than 1 message per window, and at least 8 messages. Detection starts after
5 minutes of history; a chat disconnect or a long silence in the log starts the history over.
Back-to-back hot windows are one event; after an event there is a 90 s cooldown.

Audio: one loudness value per second. A second is hot when it is 12 dB above the average of
the previous 5 minutes and louder than -24 dBFS; an event needs 2 hot seconds in a row.
Near-silence (below -70 dBFS) is left out of the average.

EventBook keeps one event per moment: a spike within 45 s of an existing one is folded into it."""

import threading
from collections import deque
from dataclasses import dataclass, field

CHAT_DEFAULTS = {"bucket_seconds": 10, "window_seconds": 300, "threshold": 3.0,
                 "min_history_seconds": 300, "min_baseline": 1.0, "min_spike_messages": 8,
                 "cooldown_seconds": 90, "max_run_buckets": 6, "gap_seconds": 20}
AUDIO_DEFAULTS = {"window_seconds": 300, "min_history_seconds": 120, "rise_db": 12.0,
                  "floor_db": -24.0, "min_seconds": 2, "cooldown_seconds": 90,
                  "max_run_seconds": 20, "gap_seconds": 5}


@dataclass
class Event:
    event_id: str
    channel: str
    spike_ts: float
    peak_ts: float
    stats: dict = field(default_factory=dict)


class _Hot:
    """Collects consecutive hot samples and turns them into one Event."""

    def __init__(self, channel, source, cooldown, max_len, min_len=1):
        self.channel, self.source = channel, source
        self.cooldown, self.max_len, self.min_len = cooldown, max_len, min_len
        self.samples, self.quiet_until = [], 0.0

    def push(self, t, value, extra):
        """A hot sample. Returns a finished event when the run is full."""
        if not self.samples and t < self.quiet_until:
            return []
        self.samples.append((t, value, extra))
        return self.close(t) if len(self.samples) >= self.max_len else []

    def close(self, end):
        run, self.samples = self.samples, []
        if len(run) < self.min_len:
            return []
        self.quiet_until = end + self.cooldown
        top = max(run, key=lambda s: s[1])
        stats = {"source": self.source, "samples": len(run), **run[0][2], **top[2]}
        return [Event(f"{self.channel}-{int(run[0][0])}", self.channel, run[0][0], top[0], stats)]


class ChatSpikeDetector:
    def __init__(self, channel, d=CHAT_DEFAULTS):
        self.size = float(d["bucket_seconds"])
        n = max(1, round(d["window_seconds"] / self.size))
        self.counts = deque(maxlen=n)
        self.need = min(n, max(1, -(-d["min_history_seconds"] // self.size)))
        self.k, self.floor, self.min_msgs = float(d["threshold"]), float(d["min_baseline"]), int(d["min_spike_messages"])
        self.gap = float(d["gap_seconds"])
        self.hot = _Hot(channel, "chat", float(d["cooldown_seconds"]), int(d["max_run_buckets"]))
        self.window, self.count, self.complete, self.seen = None, 0, False, None

    def _restart(self, t):
        out = self.hot.close(self.window + self.size) if self.hot.samples and self.window is not None else []
        self.counts.clear()
        self.window = None if t is None else t - t % self.size
        self.count, self.complete = 0, False                    # a window cut by a restart is partial
        return out

    def _judge(self, start, n):
        if len(self.counts) >= self.need:
            avg = sum(self.counts) / len(self.counts)
            bar = max(avg, self.floor)
            self.counts.append(n)
            if n >= self.k * bar and n >= self.min_msgs:
                return self.hot.push(start, n, {"baseline": round(avg, 2), "peak_count": n,
                                                "peak_ratio": round(n / bar, 2), "first_count": n})
        else:
            self.counts.append(n)
        return self.hot.close(start) if self.hot.samples else []

    def feed(self, rec):
        kind, t = rec.get("type"), rec.get("t")
        if t is None:
            return []
        out = []
        if kind == "disconnect":
            while self.window is not None and self.seen is not None and t >= self.window + self.size:
                out += self._close_window()
            out += self._restart(None)
            self.seen = t
            return out
        if kind == "connect" or self.window is None or (self.seen is not None and t - self.seen > self.gap):
            out += self._restart(t)
        while t >= self.window + self.size:
            out += self._close_window()
        self.seen = t
        if kind == "msg":
            self.count += 1
        return out

    def _close_window(self):
        out = self._judge(self.window, self.count) if self.complete else []
        self.window += self.size
        self.count, self.complete = 0, True
        return out


class AudioSpikeDetector:
    def __init__(self, channel, a=AUDIO_DEFAULTS):
        self.levels = deque(maxlen=int(a["window_seconds"]))
        self.need, self.rise, self.floor = int(a["min_history_seconds"]), float(a["rise_db"]), float(a["floor_db"])
        self.gap, self.last = float(a["gap_seconds"]), None
        self.hot = _Hot(channel, "audio", float(a["cooldown_seconds"]), int(a["max_run_seconds"]),
                        int(a["min_seconds"]))

    def feed(self, t, db):
        out = []
        if self.last is not None and t - self.last > self.gap:      # recording gap: start over
            out += self.hot.close(self.last + 1)
            self.levels.clear()
        self.last = t
        loud_enough = db > -70
        hot = False
        if len(self.levels) >= self.need and loud_enough:
            avg = sum(self.levels) / len(self.levels)
            hot = db >= avg + self.rise and db >= self.floor
        if loud_enough:
            self.levels.append(db)
        if hot:
            out += self.hot.push(t, db, {"baseline_db": round(avg, 1), "peak_db": round(db, 1),
                                         "rise_db": round(db - avg, 1)})
        elif self.hot.samples:
            out += self.hot.close(t)
        if out:
            for e in out:
                e.stats["seconds"] = e.stats.pop("samples")
        return out


class EventBook:
    """Thread-safe list of events; a spike near an existing one is merged into it."""

    def __init__(self, merge_window=45):
        self.merge, self.events, self.lock, self.taken = merge_window, [], threading.Lock(), set()
        self.failed = set()          # recordings with a failed clip: never deleted

    def add(self, ev):
        with self.lock:
            for e in self.events:
                if e.channel == ev.channel and abs(e.spike_ts - ev.spike_ts) <= self.merge:
                    e.stats.setdefault("also", []).append(ev.stats)
                    return False
            self.events.append(ev)
            return True

    def pending(self):
        with self.lock:
            return [e for e in self.events if e.event_id not in self.taken]

    def take(self, ev):
        with self.lock:
            self.taken.add(ev.event_id)
