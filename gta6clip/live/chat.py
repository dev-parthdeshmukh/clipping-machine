"""Read a Twitch channel's chat without an account, and without ever being able to post.

Twitch lets anyone read chat over IRC with a "justinfan<number>" nickname. Each line is logged to
chat.log as JSON: {"type": "msg" | "connect" | "heartbeat" | "disconnect", "t": <local time>}.
`t` is this PC's clock, the same clock the recorder stamps the video with."""

import json
import random
import re
import socket
import ssl
import threading
import time
from types import SimpleNamespace

from ..util import log

HOST, PORT = "irc.chat.twitch.tv", 6697
SENDABLE = ("CAP", "PASS", "NICK", "JOIN", "PING", "PONG")   # nothing that can write in chat
_LINE = re.compile(r"^(?:@(?P<tags>\S+) )?(?::(?P<prefix>\S+) )?(?P<cmd>\S+)(?P<args>.*)$")
_TAG_ESCAPES = {r"\s": " ", r"\:": ";", r"\\": "\\", r"\r": "\r", r"\n": "\n"}


def parse_irc(line):
    """One IRC line -> object with .tags (dict), .nick, .command, .params, .trailing."""
    m = _LINE.match(line.strip("\r\n"))
    if not m:
        return SimpleNamespace(tags={}, nick="", command="", params=[], trailing="")
    tags = {}
    for item in (m.group("tags") or "").split(";"):
        if item:
            key, _, val = item.partition("=")
            tags[key] = re.sub(r"\\[s:\\rn]", lambda e: _TAG_ESCAPES[e.group(0)], val)
    head, _, trailing = m.group("args").partition(" :")
    params = head.split() + ([trailing] if " :" in m.group("args") else [])
    prefix = m.group("prefix") or ""
    return SimpleNamespace(tags=tags, nick=prefix.split("!")[0], command=m.group("cmd").upper(),
                           params=params, trailing=params[-1] if params else "")


class ChatReader:
    def __init__(self, channel, log_path, stop=None):
        self.channel, self.log_path = channel.lower(), log_path
        self.stop = stop or threading.Event()
        self.conn, self.file = None, None

    def _send(self, text):
        if text.split(" ")[0].upper() not in SENDABLE:
            raise PermissionError(f"this reader never sends {text.split(' ')[0]!r}")
        self.conn.sendall(text.encode("utf-8") + b"\r\n")

    def _log(self, kind, **extra):
        self.file.write(json.dumps({"type": kind, "t": round(time.time(), 3), **extra}, ensure_ascii=False) + "\n")
        self.file.flush()

    def _listen(self):
        sock = socket.create_connection((HOST, PORT), timeout=15)
        self.conn = ssl.create_default_context().wrap_socket(sock, server_hostname=HOST)
        self.conn.settimeout(1.0)
        self._send("CAP REQ :twitch.tv/tags twitch.tv/commands")
        self._send(f"NICK justinfan{random.randint(10000, 99999)}")
        pending, in_room = b"", False
        heard = pinged = time.time()
        beat = 0.0
        while not self.stop.is_set():
            try:
                data = self.conn.recv(65536)
                if not data:
                    raise ConnectionError("Twitch closed the connection")
                pending += data
                heard = time.time()
            except (socket.timeout, TimeoutError):
                pass
            *lines, pending = pending.split(b"\r\n")
            for raw in lines:
                m = parse_irc(raw.decode("utf-8", errors="replace"))
                if m.command == "PING":
                    self._send(f"PONG :{m.trailing}")
                elif m.command == "001":
                    self._send(f"JOIN #{self.channel}")
                elif m.command in ("ROOMSTATE", "JOIN") and not in_room:
                    in_room = True
                    self._log("connect")
                    log(f"chat: reading #{self.channel} (no account, read-only)", "ok")
                elif m.command == "PRIVMSG" and in_room:
                    self._log("msg", user=m.nick, text=m.trailing)
                elif m.command == "RECONNECT":
                    raise ConnectionError("Twitch asked for a reconnect")
            now = time.time()
            if in_room and now - beat >= 5:
                self._log("heartbeat")
                beat = now
            if now - pinged >= 60:
                self._send("PING :tmi.twitch.tv")
                pinged = now
            if now - heard > 180:
                raise ConnectionError("Twitch went quiet for 3 minutes")

    def run_forever(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        wait = 1.0
        with open(self.log_path, "a", encoding="utf-8") as self.file:
            while not self.stop.is_set():
                began, why = time.time(), "stopped"
                try:
                    self._listen()
                except (OSError, ConnectionError) as exc:
                    why = str(exc)
                    log(f"chat: dropped ({why[:80]}), reconnecting", "warn")
                finally:
                    if self.conn is not None:
                        try:
                            self.conn.close()
                        except OSError:
                            pass
                        self.conn = None
                    self._log("disconnect", reason=why)
                wait = 1.0 if time.time() - began > 60 else min(wait * 2, 60.0)
                self.stop.wait(wait)


def read_new(path, offset):
    """Records added to chat.log since byte `offset` -> (records, next offset).
    A last line that is still being written is left for next time."""
    if not path.exists():
        return [], offset
    with open(path, "rb") as fh:
        fh.seek(offset)
        data = fh.read()
    complete = data[:data.rfind(b"\n") + 1]
    out = []
    for raw in complete.splitlines():
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out, offset + len(complete)


def read_window(path, t0, t1):
    """Chat messages with t0 <= t < t1."""
    recs, _ = read_new(path, 0)
    return [r for r in recs if r.get("type") == "msg" and t0 <= r.get("t", 0) < t1]
