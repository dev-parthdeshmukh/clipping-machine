"""Ask Claude through the user's own `claude -p` (their subscription, no API key).
On Windows `claude` may be an .exe, an npm .cmd shim or an npm .ps1 shim."""

import json
import os
import shutil
import subprocess


def argv():
    """The command prefix that runs `claude -p` on this machine."""
    for name in ("claude.exe", "claude", "claude.cmd"):
        path = shutil.which(name)
        if path:
            return [path, "-p"]
    ps1 = shutil.which("claude.ps1")
    if ps1:
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, "-p"]
    raise RuntimeError("Claude Code ('claude') not found on PATH")


def ask(prompt, cfg, timeout=600):
    """Send `prompt` on stdin and return the reply text."""
    cmd = argv()
    if cfg.get("claude_model"):
        cmd += ["--model", cfg["claude_model"]]
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed: {(proc.stderr or proc.stdout or '').strip()[:300]}")
    return proc.stdout


def parse_array(raw):
    """The list of objects in a reply, wherever it sits (inside a ```json fence, after some
    prose, or bare). Anything else -> []."""
    text = (raw or "").strip()
    if "```" in text:
        inside = text.split("```")[1]
        text = inside[4:] if inside.lower().startswith("json") else inside
    begin, end = text.find("["), text.rfind("]")
    if begin < 0 or end <= begin:
        return []
    try:
        out = json.loads(text[begin:end + 1])
    except json.JSONDecodeError:
        return []
    return out if isinstance(out, list) and all(isinstance(x, dict) for x in out) else []
