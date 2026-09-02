"""Claude Code Provider。

通过 headless CLI 调 Claude Code，按 session_id 保持多轮：
  首次: claude -p "<text>" --session-id <id>
  后续: claude -p "<text>" --resume <id>
config 示例:
  {"claude_bin": "claude", "timeout_seconds": 300, "extra_args": ["--model", "opus"]}
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import shlex


class ClaudeProvider:
    def __init__(self, cfg: dict) -> None:
        self.bin = cfg.get("claude_bin", "claude")
        self.timeout = int(cfg.get("timeout_seconds", 300))
        self.extra_args = cfg.get("extra_args", []) or []
        self._session_ids: dict[str, str] = {}

    async def reply(self, session_id: str, text: str) -> str:
        sid = self._session_ids.get(session_id) or _sanitize(session_id)
        if session_id in self._session_ids:
            args = [self.bin, "-p", text, "--resume", sid]
        else:
            args = [self.bin, "-p", text, "--session-id", sid]
        args += self.extra_args
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("Claude CLI 超时")
        if proc.returncode != 0:
            raise RuntimeError(f"Claude 退出码 {proc.returncode}: {(err or b'').decode(errors='ignore')[:200]}")
        self._session_ids[session_id] = sid
        return out.decode(errors="ignore").strip()


def _sanitize(s: str) -> str:
    h = hashlib.sha1(s.encode()).hexdigest()[:12]
    keep = re.sub(r"[^A-Za-z0-9_-]", "", s)[:20]
    return f"wx-{keep}-{h}" if keep else f"wx-{h}"
