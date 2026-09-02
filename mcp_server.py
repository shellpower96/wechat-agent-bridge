#!/usr/bin/env python3
"""WeChat Agent Bridge · MCP Server（stdio JSON-RPC 2.0）。

把 bridge 的 REST 管理端点封装成 MCP tools，供 Hermes / Claude Code 等 agent 调用，
实现"反过来管理微信客服"：查状态、增删白名单/群、切换真人/AI、主动发消息。

用法（stdio，由 MCP 客户端拉起）：
  python mcp_server.py          # 默认 WXAB_BRIDGE_URL=http://127.0.0.1:36060
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

BRIDGE_URL = os.environ.get("WXAB_BRIDGE_URL", "http://127.0.0.1:36060").rstrip("/")
SERVER_NAME = "wechat-agent-bridge"
SERVER_VERSION = "1.0.0"


# --------------------------------------------------------------------------
# bridge REST 调用
# --------------------------------------------------------------------------
def _call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(f"{BRIDGE_URL}{path}", method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=15) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------------
# Tool 定义与实现
# --------------------------------------------------------------------------
TOOLS = [
    {"name": "wx_status", "description": "查看微信客服桥接运行状态（模式、白名单、群、provider）",
     "properties": {}},
    {"name": "wx_list_whitelist", "description": "列出私聊白名单 wxid", "properties": {}},
    {"name": "wx_add_whitelist", "description": "把某个好友加入私聊白名单（AI 才会自动回复）",
     "properties": {"wxid": {"type": "string", "description": "微信 user_id，形如 wxid_xxx"}},
     "required": ["wxid"]},
    {"name": "wx_remove_whitelist", "description": "从私聊白名单移除 wxid",
     "properties": {"wxid": {"type": "string"}}, "required": ["wxid"]},
    {"name": "wx_list_groups", "description": "列出群白名单", "properties": {}},
    {"name": "wx_add_group", "description": "把某个群加入群白名单",
     "properties": {"group_id": {"type": "string", "description": "群 id，形如 xxx@chatroom"}},
     "required": ["group_id"]},
    {"name": "wx_remove_group", "description": "从群白名单移除",
     "properties": {"group_id": {"type": "string"}}, "required": ["group_id"]},
    {"name": "wx_set_human_mode", "description": "切到真人模式（AI 暂停接待）", "properties": {}},
    {"name": "wx_set_ai_mode", "description": "切到 AI 模式（AI 接管接待）", "properties": {}},
    {"name": "wx_send_message", "description": "以客服身份给好友发私聊消息",
     "properties": {"wxid": {"type": "string"}, "text": {"type": "string"}},
     "required": ["wxid", "text"]},
    {"name": "wx_send_group_message", "description": "给群发消息",
     "properties": {"group_id": {"type": "string"}, "text": {"type": "string"}},
     "required": ["group_id", "text"]},
]


def _run_tool(name: str, args: dict) -> str:
    if name == "wx_status":
        return json.dumps(_call("GET", "/health"), ensure_ascii=False)
    if name == "wx_list_whitelist":
        return json.dumps(_call("GET", "/whitelist"), ensure_ascii=False)
    if name == "wx_add_whitelist":
        return json.dumps(_call("POST", "/whitelist", {"wxid": args["wxid"]}), ensure_ascii=False)
    if name == "wx_remove_whitelist":
        return json.dumps(_call("POST", "/whitelist/remove", {"wxid": args["wxid"]}), ensure_ascii=False)
    if name == "wx_list_groups":
        return json.dumps(_call("GET", "/groups"), ensure_ascii=False)
    if name == "wx_add_group":
        return json.dumps(_call("POST", "/groups", {"group_id": args["group_id"]}), ensure_ascii=False)
    if name == "wx_remove_group":
        return json.dumps(_call("POST", "/groups/remove", {"group_id": args["group_id"]}), ensure_ascii=False)
    if name == "wx_set_human_mode":
        return json.dumps(_call("POST", "/human_signal"), ensure_ascii=False)
    if name == "wx_set_ai_mode":
        return json.dumps(_call("POST", "/ai_signal"), ensure_ascii=False)
    if name == "wx_send_message":
        return json.dumps(_call("POST", "/send", {"wxid": args["wxid"], "text": args["text"]}), ensure_ascii=False)
    if name == "wx_send_group_message":
        return json.dumps(_call("POST", "/send_group", {"group_id": args["group_id"], "text": args["text"]}), ensure_ascii=False)
    return json.dumps({"ok": False, "error": f"unknown tool {name}"})


# --------------------------------------------------------------------------
# JSON-RPC
# --------------------------------------------------------------------------
def _send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _handle(req: dict) -> None:
    mid = req.get("id")
    method = req.get("method")

    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": req.get("params", {}).get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }})
        return
    if method == "notifications/initialized" or method is None:
        return  # 通知，无需响应
    if method == "ping":
        _send({"jsonrpc": "2.0", "id": mid, "result": {}})
        return
    if method == "tools/list":
        tools = [{
            "name": t["name"], "description": t["description"],
            "inputSchema": {"type": "object", "properties": t["properties"],
                            "required": t.get("required", [])},
        } for t in TOOLS]
        _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}})
        return
    if method == "tools/call":
        name = req.get("params", {}).get("name", "")
        args = req.get("params", {}).get("arguments", {}) or {}
        try:
            text = _run_tool(name, args)
            _send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": False}})
        except Exception as e:  # noqa: BLE001
            _send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}})
        return
    _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}})


def _read_loop() -> None:
    """读取 stdio 消息：支持 newline-delimited JSON 与 Content-Length 头两种 framing。"""
    buf = ""
    while True:
        line = sys.stdin.readline()
        if not line:
            return
        line = line.rstrip("\n")
        if line.startswith("Content-Length:"):
            length = int(line.split(":", 1)[1].strip())
            while True:  # 跳过直到空行
                h = sys.stdin.readline()
                if h in ("", "\n", "\r\n"):
                    break
            body = sys.stdin.read(length)
            _handle(json.loads(body))
            continue
        buf += line
        if not line.strip():
            if buf.strip():
                _handle(json.loads(buf))
            buf = ""
        elif _looks_like_json(line):
            _handle(json.loads(line))
            buf = ""


def _looks_like_json(s: str) -> bool:
    s = s.strip()
    return s.startswith("{") and s.endswith("}")


def main() -> None:
    _read_loop()


if __name__ == "__main__":
    main()
