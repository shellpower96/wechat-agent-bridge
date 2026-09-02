"""Hermes Agent Provider。

对接 Hermes API server（OpenAI 风格 /v1/responses，多轮用 previous_response_id）。
config 示例:
  {"base_url": "http://127.0.0.1:18645", "api_key_file": "~/.hermes/profiles/wechat-cs/.api_server_key",
   "model": "wechat-cs"}
"""
from __future__ import annotations

import os
import pathlib

import aiohttp


class HermesProvider:
    def __init__(self, cfg: dict) -> None:
        self.base_url = str(cfg.get("base_url", "http://127.0.0.1:18645")).rstrip("/")
        key_file = os.path.expanduser(str(cfg.get("api_key_file", "~/.hermes/profiles/wechat-cs/.api_server_key")))
        try:
            self.api_key = pathlib.Path(key_file).read_text().strip()
        except OSError:
            self.api_key = cfg.get("api_key", "")
        self.model = cfg.get("model", "wechat-cs")
        self.timeout = int(cfg.get("timeout_seconds", 150))
        self._prev: dict[str, str] = {}

    async def reply(self, session_id: str, text: str) -> str:
        body: dict = {"model": self.model, "input": text}
        prev = self._prev.get(session_id)
        if prev:
            body["previous_response_id"] = prev
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as s:
            async with s.post(f"{self.base_url}/v1/responses", json=body, headers=headers) as r:
                if r.status != 200:
                    raise RuntimeError(f"Hermes {r.status}: {(await r.text())[:200]}")
                data = await r.json()
        rid = data.get("id")
        if rid:
            self._prev[session_id] = rid
        return _extract_text(data)


def _extract_text(data: dict) -> str:
    for out in data.get("output") or []:
        if out.get("type") == "message":
            for c in out.get("content") or []:
                if c.get("type") == "output_text" and c.get("text"):
                    return c["text"]
    t = data.get("output_text") or ""
    return t if isinstance(t, str) else str(t)
