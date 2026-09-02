#!/usr/bin/env python3
"""WeChat Agent Bridge — 核心服务（agent 无关）。

微信消息 → OneBot 入站 → 白名单过滤（私聊/群）→ 状态机（AI/真人）→ Agent Provider 回复
→ OneBot 出站（私聊/群）。另提供 REST 管理端点，供 MCP server 或任意脚本管理
白名单/群/发送/模式切换。

配置见 config.example.json。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import pathlib
import time
from collections import OrderedDict
from typing import Optional, Protocol

from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("wx-agent-bridge")

HOME = pathlib.Path.home()
BASE_DIR = pathlib.Path(__file__).resolve().parent

# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------
CFG_PATH = pathlib.Path(os.environ.get("WXAB_CONFIG", str(BASE_DIR / "config.json")))


def _load_config() -> dict:
    if not CFG_PATH.exists():
        raise SystemExit(f"缺少配置 {CFG_PATH}，请先 cp config.example.json config.json")
    return json.loads(CFG_PATH.read_text())


CFG = _load_config()
LISTEN_HOST = CFG.get("listen_host", "127.0.0.1")
LISTEN_PORT = int(CFG.get("listen_port", 36060))
ONEBOT_TOKEN = CFG.get("onebot_token", "MuseBot")
ONEBOT_SEND = CFG.get("onebot_send_url", "http://127.0.0.1:58080")
WHITELIST_FILE = pathlib.Path(os.path.expanduser(CFG.get("whitelist_file", str(HOME / ".wechat-agent/whitelist.json"))))
GROUPS_FILE = pathlib.Path(os.path.expanduser(CFG.get("groups_file", str(HOME / ".wechat-agent/groups.json"))))
HUMAN_TIMEOUT_SECONDS = int(CFG.get("human_timeout_seconds", 600))
# 群回复模式: off(关闭) | all(群白名单内所有消息都回) | mention(仅 @ 机器人)
GROUP_REPLY_MODE = CFG.get("group_reply_mode", "mention")
PROVIDER = CFG.get("provider", "hermes")
PROVIDER_CFG = CFG.get("providers", {}).get(PROVIDER, {})

_prev_response: dict[str, str] = {}
_user_locks: dict[str, asyncio.Lock] = {}
_dedup: "OrderedDict[str, float]" = OrderedDict()
DEDUP_MAX = 2000
MODE_STATE: dict = {"mode": "ai", "human_ts": 0.0}
START_TS = time.time()
_whitelist_state: dict = {"ts": 0.0, "set": set()}
_groups_state: dict = {"ts": 0.0, "set": set()}


# --------------------------------------------------------------------------
# Provider 抽象
# --------------------------------------------------------------------------
class AgentProvider(Protocol):
    async def reply(self, session_id: str, text: str) -> str: ...


def _load_provider() -> AgentProvider:
    if PROVIDER == "hermes":
        from providers.hermes import HermesProvider
        return HermesProvider(PROVIDER_CFG)
    if PROVIDER == "claude":
        from providers.claude import ClaudeProvider
        return ClaudeProvider(PROVIDER_CFG)
    if PROVIDER in ("openai", "openai_compat"):
        from providers.openai_compat import OpenAiCompatProvider
        return OpenAiCompatProvider(PROVIDER_CFG)
    mod = PROVIDER_CFG.get("module")
    if mod:
        import importlib
        return importlib.import_module(mod).make_provider(PROVIDER_CFG)
    raise SystemExit(f"未知 provider: {PROVIDER}")


AGENT: AgentProvider = _load_provider()


# --------------------------------------------------------------------------
# 白名单 / 群列表（文件热更新）
# --------------------------------------------------------------------------
def _read_list_file(path: pathlib.Path) -> set[str]:
    try:
        data = json.loads(path.read_text())
        arr = data.get("items", data if isinstance(data, list) else [])
        return set(str(x) for x in arr)
    except OSError:
        return set()


def _write_list_file(path: pathlib.Path, items: set[str], key: str = "items") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({key: sorted(items)}, ensure_ascii=False, indent=2))


def _cached_set(state: dict, path: pathlib.Path) -> set[str]:
    now = time.time()
    if now - state["ts"] > 30:
        state["set"] = _read_list_file(path)
        state["ts"] = now
    return state["set"]


def _is_whitelisted(wxid: str) -> bool:
    return wxid in _cached_set(_whitelist_state, WHITELIST_FILE)


def _is_group_allowed(group_id: str) -> bool:
    return group_id in _cached_set(_groups_state, GROUPS_FILE)


def _dedup_seen(message_id: str) -> bool:
    if not message_id:
        return False
    now = time.time()
    last = _dedup.get(message_id)
    _dedup[message_id] = now
    while len(_dedup) > DEDUP_MAX:
        _dedup.popitem(last=False)
    return last is not None and now - last < 300


# --------------------------------------------------------------------------
# 状态机
# --------------------------------------------------------------------------
def _on_human_signal() -> None:
    MODE_STATE["mode"] = "human"
    MODE_STATE["human_ts"] = time.time()
    log.info("HUMAN signal -> 真人模式（AI 暂停接待）")


def _on_ai_signal() -> None:
    MODE_STATE["mode"] = "ai"
    MODE_STATE["human_ts"] = 0.0
    log.info("AI 模式（手动切换）")


async def _mode_watcher() -> None:
    while True:
        await asyncio.sleep(20)
        if MODE_STATE["mode"] == "human":
            idle = time.time() - MODE_STATE["human_ts"]
            if idle >= HUMAN_TIMEOUT_SECONDS:
                MODE_STATE["mode"] = "ai"
                log.info("AI 唤醒：真人 %d 秒未回复（>%ds），恢复 AI 接待", int(idle), HUMAN_TIMEOUT_SECONDS)


# --------------------------------------------------------------------------
# OneBot 解析与发送
# --------------------------------------------------------------------------
def _segments(payload: dict) -> list[dict]:
    return [s for s in (payload.get("message") or []) if isinstance(s, dict)]


def _text_of(payload: dict) -> str:
    # 只取 text 段；系统消息（sys/XML/appmsg 等）没有 text 段 → 返回空并被忽略。
    texts = [(s.get("data") or {}).get("text", "") for s in _segments(payload)
             if s.get("type") == "text"]
    texts = [t for t in texts if t.strip()]
    return "\n".join(texts)


def _is_mentioned(payload: dict) -> bool:
    self_id = str(payload.get("self_id") or "")
    for s in _segments(payload):
        if s.get("type") == "at" and str((s.get("data") or {}).get("qq", "")) == self_id:
            return True
    return False


async def _onebot_send(path: str, body: dict) -> bool:
    import aiohttp
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
        async with s.post(f"{ONEBOT_SEND}{path}", json=body) as r:
            ok = r.status == 200
            if not ok:
                log.error("onebot %s -> %s: %s", path, r.status, (await r.text())[:200])
            return ok


async def _send_private(wxid: str, text: str) -> bool:
    return await _onebot_send("/send_private_msg",
                              {"user_id": wxid, "message": [{"type": "text", "data": {"text": text}}]})


async def _send_group(group_id: str, text: str) -> bool:
    return await _onebot_send("/send_group_msg",
                              {"group_id": group_id, "message": [{"type": "text", "data": {"text": text}}]})


# --------------------------------------------------------------------------
# 消息处理
# --------------------------------------------------------------------------
async def handle_private(wxid: str, text: str) -> None:
    await _dispatch(wxid, text, lambda t: _send_private(wxid, t))


async def handle_group(group_id: str, text: str) -> None:
    await _dispatch(group_id, text, lambda t: _send_group(group_id, t))


async def _dispatch(session_id: str, text: str, sender) -> None:
    if MODE_STATE["mode"] == "human":
        log.info("human mode: AI paused, skip %s", session_id)
        return
    lock = _user_locks.setdefault(session_id, asyncio.Lock())
    async with lock:
        try:
            reply = await AGENT.reply(session_id, text)
        except Exception as exc:  # noqa: BLE001
            log.error("agent reply error for %s: %s", session_id, exc)
            return
        if not reply:
            return
        ok = await sender(reply)
        if ok:
            log.info("replied %s (%d chars): %s...", session_id, len(reply), reply[:40])
        else:
            log.error("send FAILED for %s (reply dropped): %s...", session_id, reply[:60])


# --------------------------------------------------------------------------
# HTTP 路由
# --------------------------------------------------------------------------
async def onebot_handler(request: web.Request) -> web.Response:
    raw = await request.read()
    sig = request.headers.get("X-Signature", "")
    expect = "sha1=" + hmac.new(ONEBOT_TOKEN.encode(), raw, hashlib.sha1).hexdigest()
    if sig and sig != expect:
        return web.Response(status=403, text="signature mismatch")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return web.Response(status=400, text="bad json")

    marker = str(payload.get("raw_message", "")) or str(payload.get("show_content", ""))
    if marker.startswith("[HUMAN_SEND]"):
        _on_human_signal()
        return web.Response(status=200, text="ok")
    if payload.get("post_type", "message") != "message":
        return web.Response(status=200, text="ignored")

    group_id = str(payload.get("group_id") or "")
    text = _text_of(payload)
    if not text.strip():
        return web.Response(status=200, text="empty")

    if group_id:  # 群聊
        if GROUP_REPLY_MODE == "off":
            return web.Response(status=200, text="group off")
        if not _is_group_allowed(group_id):
            return web.Response(status=200, text="group not allowed")
        if GROUP_REPLY_MODE == "mention" and not _is_mentioned(payload):
            return web.Response(status=200, text="not mentioned")
        if _dedup_seen(str(payload.get("message_id") or "")):
            return web.Response(status=200, text="dedup")
        log.info("inbound group=%s msg='%s...'", group_id, text[:60])
        asyncio.create_task(handle_group(group_id, text))
        return web.Response(status=200, text="ok")

    # 私聊
    wxid = str(payload.get("user_id") or "")
    if not wxid or wxid == "weixin":
        return web.Response(status=200, text="empty")
    if not _is_whitelisted(wxid):
        log.info("not whitelisted: %s", wxid)
        return web.Response(status=200, text="ignored")
    if _dedup_seen(str(payload.get("message_id") or "")):
        return web.Response(status=200, text="dedup")
    log.info("inbound wxid=%s msg='%s...'", wxid, text[:60])
    asyncio.create_task(handle_private(wxid, text))
    return web.Response(status=200, text="ok")


# ---- 管理端点（供 MCP / 脚本调用）----
async def health(_: web.Request) -> web.Response:
    return web.json_response({
        "ok": True, "uptime": time.time() - START_TS,
        "mode": MODE_STATE["mode"], "provider": PROVIDER,
        "group_reply_mode": GROUP_REPLY_MODE,
        "whitelist": sorted(_cached_set(_whitelist_state, WHITELIST_FILE)),
        "groups": sorted(_cached_set(_groups_state, GROUPS_FILE)),
        "human_idle_seconds": round(time.time() - MODE_STATE["human_ts"], 1)
        if MODE_STATE["mode"] == "human" else 0,
        "human_timeout_seconds": HUMAN_TIMEOUT_SECONDS,
    })


def _list_route(state, path: pathlib.Path):
    def handler(_: web.Request) -> web.Response:
        return web.json_response({"items": sorted(_cached_set(state, path))})
    return handler


def _add_route(state, path: pathlib.Path, key: str):
    async def handler(request: web.Request) -> web.Response:
        data = await request.json()
        val = str(data.get(key) or "").strip()
        if not val:
            return web.json_response({"ok": False, "error": "missing value"}, status=400)
        items = _read_list_file(path) | {val}
        _write_list_file(path, items)
        state["ts"] = 0.0  # 强制下次热更新
        return web.json_response({"ok": True, "items": sorted(items)})
    return handler


def _remove_route(state, path: pathlib.Path, key: str):
    async def handler(request: web.Request) -> web.Response:
        data = await request.json()
        val = str(data.get(key) or "").strip()
        items = _read_list_file(path) - {val}
        _write_list_file(path, items)
        state["ts"] = 0.0
        return web.json_response({"ok": True, "items": sorted(items)})
    return handler


async def send_route(request: web.Request) -> web.Response:
    data = await request.json()
    wxid = str(data.get("wxid") or "").strip()
    text = str(data.get("text") or "").strip()
    if not wxid or not text:
        return web.json_response({"ok": False, "error": "wxid/text required"}, status=400)
    ok = await _send_private(wxid, text)
    return web.json_response({"ok": ok})


async def send_group_route(request: web.Request) -> web.Response:
    data = await request.json()
    group_id = str(data.get("group_id") or "").strip()
    text = str(data.get("text") or "").strip()
    if not group_id or not text:
        return web.json_response({"ok": False, "error": "group_id/text required"}, status=400)
    ok = await _send_group(group_id, text)
    return web.json_response({"ok": ok})


def main() -> None:
    for f in (WHITELIST_FILE, GROUPS_FILE):
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"items": []}, ensure_ascii=False, indent=2))
            log.warning("已创建列表文件: %s", f)

    async def _start_watcher(app: web.Application) -> None:
        app["watcher"] = asyncio.create_task(_mode_watcher())

    app = web.Application()
    app.on_startup.append(_start_watcher)
    app.router.add_post("/onebot", onebot_handler)
    app.router.add_get("/health", health)
    app.router.add_post("/human_signal", lambda r: (_on_human_signal(), web.json_response({"ok": True, "mode": "human"}))[1])
    app.router.add_post("/ai_signal", lambda r: (_on_ai_signal(), web.json_response({"ok": True, "mode": "ai"}))[1])
    app.router.add_get("/whitelist", _list_route(_whitelist_state, WHITELIST_FILE))
    app.router.add_post("/whitelist", _add_route(_whitelist_state, WHITELIST_FILE, "wxid"))
    app.router.add_post("/whitelist/remove", _remove_route(_whitelist_state, WHITELIST_FILE, "wxid"))
    app.router.add_get("/groups", _list_route(_groups_state, GROUPS_FILE))
    app.router.add_post("/groups", _add_route(_groups_state, GROUPS_FILE, "group_id"))
    app.router.add_post("/groups/remove", _remove_route(_groups_state, GROUPS_FILE, "group_id"))
    app.router.add_post("/send", send_route)
    app.router.add_post("/send_group", send_group_route)

    log.info("WeChat Agent Bridge: listen=%s:%d provider=%s group_reply=%s human_timeout=%ds",
             LISTEN_HOST, LISTEN_PORT, PROVIDER, GROUP_REPLY_MODE, HUMAN_TIMEOUT_SECONDS)
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT)


if __name__ == "__main__":
    main()
