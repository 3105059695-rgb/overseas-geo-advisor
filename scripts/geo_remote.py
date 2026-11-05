"""Anonymous remote MCP client using only Python's standard library.

No local corpus, index, account, or API key is required. This module retrieves
evidence; it does not generate answers or fall back to model knowledge.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


DEFAULT_URL = "https://fangmu-geo-knowledge.airy-duck-6432.chatgpt.site/api/mcp"
CLIENT_VERSION = "0.4.0"
PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOLS = {"2025-11-25", "2025-06-18", "2025-03-26"}
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_REQUEST_BYTES = 128 * 1024


class RemoteError(Exception):
    def __init__(self, code: str, message: str, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A login/interception page must never be mistaken for successful MCP.
        return None


def validate_url(value: str) -> str:
    parts = urlsplit(value)
    loopback = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("MCP URL 必须是无凭据、无查询参数的服务地址。")
    if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
        raise ValueError("远程 MCP 必须使用 HTTPS；HTTP 仅限本机测试。")
    return value.rstrip("/")


def remote_config(url: str | None = None) -> dict:
    target = validate_url(url or os.environ.get("GEO_MCP_URL") or DEFAULT_URL)
    return {"mcpServers": {"overseas-geo-advisor": {"type": "http", "url": target}}}


class RemoteClient:
    def __init__(self, url: str | None = None, timeout: float = 60):
        self.url = validate_url(url or os.environ.get("GEO_MCP_URL") or DEFAULT_URL)
        if not 1 <= timeout <= 120:
            raise ValueError("超时必须在 1 至 120 秒之间。")
        self.timeout = timeout
        self.opener = build_opener(NoRedirect())
        self.session_id: str | None = None
        self.protocol = PROTOCOL_VERSION
        self.counter = 0
        self.initialized = False

    def _request(self, method: str, params: dict | None = None, notification: bool = False) -> Any:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notification:
            self.counter += 1
            payload["id"] = self.counter
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError("请求过大；只发送问题、必要业务条件和引用。")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.protocol,
            "User-Agent": "overseas-geo-advisor/" + CLIENT_VERSION,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = Request(self.url, data=encoded, headers=headers, method="POST")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                status = response.status
                body = response.read(MAX_RESPONSE_BYTES + 1)
                content_type = response.headers.get("Content-Type", "").lower()
                if response.headers.get("Mcp-Session-Id"):
                    self.session_id = response.headers["Mcp-Session-Id"]
        except HTTPError as exc:
            code = exc.code
            exc.close()
            raise RemoteError("http_error", f"远程服务返回 HTTP {code}；本次未完成知识库查询。", code) from None
        except (URLError, TimeoutError, OSError):
            raise RemoteError("network_error", "无法连接远程知识库或请求超时；本次未完成查询。") from None
        if len(body) > MAX_RESPONSE_BYTES:
            raise RemoteError("response_too_large", "远程结果超过读取上限；请缩小检索数量或原文行号范围。")
        if notification and status in (202, 204) and not body:
            return None
        if notification:
            raise RemoteError("invalid_notification_response", "远程 MCP 未确认初始化通知；本次没有完成查询。")
        try:
            decoded = body.decode("utf-8")
            if "text/event-stream" in content_type:
                events = decoded.replace("\r\n", "\n").split("\n\n")
                messages = []
                for event in events:
                    data = "\n".join(line[5:].lstrip() for line in event.splitlines() if line.startswith("data:"))
                    if data:
                        messages.append(json.loads(data))
                result = next((item for item in messages if isinstance(item, dict) and item.get("id") == payload["id"]), None)
            else:
                result = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RemoteError("invalid_response", "远程地址没有返回有效 MCP JSON，可能是登录页或网络拦截页。") from None
        if not isinstance(result, dict) or result.get("jsonrpc") != "2.0" or result.get("id") != payload["id"]:
            raise RemoteError("invalid_response", "远程响应与本次 MCP 请求不匹配。")
        if "error" in result:
            error = result["error"]
            code = error.get("code", "unknown") if isinstance(error, dict) else "unknown"
            raise RemoteError("rpc_error", f"远程 MCP 报告协议错误（{code}）；本次未完成查询。")
        if "result" not in result:
            raise RemoteError("invalid_response", "远程 MCP 响应缺少结果。")
        return result["result"]

    def initialize(self) -> dict:
        result = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "overseas-geo-advisor-cli", "version": CLIENT_VERSION},
        })
        if not isinstance(result, dict) or result.get("protocolVersion") not in SUPPORTED_PROTOCOLS:
            raise RemoteError("invalid_handshake", "远程 MCP 握手缺少有效协议版本。")
        self.protocol = result["protocolVersion"]
        self._request("notifications/initialized", notification=True)
        self.initialized = True
        return result

    def call(self, name: str, arguments: dict) -> dict:
        if not self.initialized:
            self.initialize()
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict):
            raise RemoteError("invalid_tool_result", "远程工具没有返回有效结果。")
        value = result.get("structuredContent")
        if not isinstance(value, dict):
            for block in result.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    try:
                        candidate = json.loads(block.get("text", ""))
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(candidate, dict):
                        value = candidate
                        break
        if not isinstance(value, dict):
            raise RemoteError("invalid_tool_result", "远程工具未返回可读取的证据对象。")
        if result.get("isError") and value.get("status") not in {"error", "unavailable", "not_found"}:
            raise RemoteError("tool_error", "远程工具执行失败；不能将其当作查询成功。")
        return value


class KnowledgeClient:
    """MCP first, then a verified public snapshot, without changing knowledge owners."""

    FALLBACK_ERRORS = {
        "http_error", "network_error", "invalid_response", "invalid_handshake",
        "invalid_notification_response", "invalid_tool_result", "tool_error",
    }

    def __init__(self, url: str | None = None, timeout: float = 60,
                 transport: str = "auto", cache_dir: str | Path | None = None):
        if transport not in {"auto", "mcp", "github"}:
            raise ValueError("transport 必须为 auto、mcp 或 github。")
        self.url = validate_url(url or os.environ.get("GEO_MCP_URL") or DEFAULT_URL)
        if not 1 <= timeout <= 120:
            raise ValueError("超时必须在 1 至 120 秒之间。")
        self.timeout = timeout
        self.transport = transport
        self.cache_dir = cache_dir
        self.auto_fallback = transport == "auto" and self.url == DEFAULT_URL.rstrip("/")

    @staticmethod
    def failure(code: str, message: str, transport: dict) -> dict:
        return {"status": "unavailable", "error_code": code, "message": message,
                "answer_markdown": "", "citations": [],
                "knowledge_lookup_completed": False, "transport": transport}

    def snapshot(self, name: str, arguments: dict, reason: dict | None = None) -> dict:
        info = {"requested": self.transport, "used": "github_snapshot",
                "mcp_connected": False, "fallback_reason": reason,
                "attempted": ["mcp", "github_snapshot"] if reason else ["github_snapshot"]}
        try:
            from geo_snapshot import SnapshotClient, SnapshotError
        except ImportError:
            return self.failure("fallback_runtime_missing", "缺少配套 GitHub 快照查询脚本，请完整更新 Skill。",
                                {**info, "used": None})
        try:
            result = SnapshotClient(timeout=self.timeout, cache_dir=self.cache_dir).call(name, arguments)
        except SnapshotError as exc:
            return self.failure(exc.code, str(exc), {**info, "used": None,
                                "snapshot_error": {"code": exc.code, "message": str(exc)}})
        if not isinstance(result, dict):
            return self.failure("invalid_snapshot_result", "快照没有返回有效证据对象。", {**info, "used": None})
        return {**result, "transport": info,
                "knowledge_lookup_completed": result.get("status") not in {"error", "unavailable", "not_found"}}

    def call(self, name: str, arguments: dict) -> dict:
        if self.transport == "github":
            return self.snapshot(name, arguments)
        info = {"requested": self.transport, "used": "mcp", "mcp_connected": True,
                "attempted": ["mcp"]}
        try:
            result = RemoteClient(self.url, min(self.timeout, 12) if self.auto_fallback else self.timeout).call(name, arguments)
        except RemoteError as exc:
            reason = {"code": exc.code, "message": str(exc)}
            if exc.http_status is not None:
                reason["http_status"] = exc.http_status
            if self.auto_fallback and exc.code in self.FALLBACK_ERRORS:
                return self.snapshot(name, arguments, reason)
            info.update(used=None, mcp_connected=False, fallback_reason=reason)
            if self.transport == "auto" and not self.auto_fallback:
                info["fallback_disabled_reason"] = "自定义 MCP 地址失败时，不自动改查维护者的另一个知识库；可显式选择 --transport github。"
            return self.failure(exc.code, str(exc), info)
        if result.get("status") == "unavailable" and self.auto_fallback:
            return self.snapshot(name, arguments, {
                "code": result.get("error_code", "mcp_tool_unavailable"),
                "message": result.get("message", "MCP 没有完成资料查询。"),
            })
        return {**result, "transport": info,
                "knowledge_lookup_completed": result.get("status") not in {"error", "unavailable", "not_found"}}


def _object_file(path: str, max_bytes: int = MAX_REQUEST_BYTES) -> dict:
    value = Path(path)
    if value.stat().st_size > max_bytes:
        raise ValueError("JSON 文件过大。")
    data = json.loads(value.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("JSON 文件必须包含一个对象。")
    return data


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="免登录查询共享 GEO 知识库，无需导入资料或安装 MCP SDK。")
    parser.add_argument("--url", help="替代远程 MCP 地址；默认使用维护者公开服务")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--transport", choices=("auto", "mcp", "github"), default="auto",
                        help="auto 优先 MCP，默认服务不可用时查询已校验的 GitHub 快照；github 直接使用备用通道")
    parser.add_argument("--cache-dir", help="快照自动缓存目录；无需手动导入资料")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "browse", "mcp-config"):
        commands.add_parser(name)
    for name in ("ask", "search"):
        sub = commands.add_parser(name)
        sub.add_argument("--question", required=True)
        sub.add_argument("--as-of")
        if name == "search":
            sub.add_argument("--limit", type=int, default=10)
        else:
            context = sub.add_mutually_exclusive_group()
            context.add_argument("--context-file")
            context.add_argument("--context-json")
            sub.add_argument("--detail", choices=("auto", "brief", "detailed"), default="auto")
            sub.add_argument("--previous-answer-id")
            sub.add_argument("--focus-citation-id")
    sub = commands.add_parser("read")
    sub.add_argument("--document-id", required=True)
    sub.add_argument("--source-version", required=True)
    sub.add_argument("--start-line", type=int, default=1)
    sub.add_argument("--end-line", type=int)
    sub = commands.add_parser("check")
    sub.add_argument("--bundle-file", required=True)
    return parser


def execute(args: argparse.Namespace) -> dict:
    if args.command == "mcp-config":
        return remote_config(args.url)
    names = {"status": "browse_geo_topics", "browse": "browse_geo_topics", "ask": "ask_geo", "search": "search_geo", "read": "read_geo_source", "check": "check_geo_answer"}
    values: dict[str, Any] = {}
    if args.command in {"ask", "search"}:
        if not args.question.strip() or len(args.question) > 8000:
            raise ValueError("问题必须为 1 至 8000 个字符。")
        values["question"] = args.question
        if args.as_of:
            from datetime import date
            if date.fromisoformat(args.as_of).isoformat() != args.as_of:
                raise ValueError("日期必须为 YYYY-MM-DD。")
            values["as_of"] = args.as_of
    if args.command == "search":
        if not 1 <= args.limit <= 20:
            raise ValueError("远程检索 limit 必须在 1 至 20 之间。")
        values["limit"] = args.limit
    elif args.command == "ask":
        context = _object_file(args.context_file, 16000) if args.context_file else json.loads(args.context_json) if args.context_json else None
        if context is not None:
            if not isinstance(context, dict) or len(json.dumps(context, ensure_ascii=False).encode("utf-8")) > 16000:
                raise ValueError("context 必须是 16000 字节以内的 JSON 对象。")
            values["context"] = context
        values["detail"] = args.detail
        if args.previous_answer_id:
            values["previous_answer_id"] = args.previous_answer_id
        if args.focus_citation_id:
            values["focus_citation_id"] = args.focus_citation_id
    elif args.command == "read":
        if args.start_line < 1 or (args.end_line is not None and args.end_line < args.start_line):
            raise ValueError("行号必须为正整数，结束行不能小于起始行。")
        values = {"document_id": args.document_id, "source_version": args.source_version, "start_line": args.start_line}
        if args.end_line is not None:
            values["end_line"] = args.end_line
    elif args.command == "check":
        values["bundle"] = _object_file(args.bundle_file)
    return KnowledgeClient(args.url, args.timeout, args.transport, args.cache_dir).call(names[args.command], values)


def main(argv: list[str] | None = None) -> int:
    try:
        args = make_parser().parse_args(argv)
        result = execute(args)
        code = 2 if result.get("status") in {"error", "unavailable", "not_found"} else 0
    except RemoteError as exc:
        result = {"status": "unavailable", "error_code": exc.code, "message": str(exc), "answer_markdown": "", "citations": [], "knowledge_lookup_completed": False}
        code = 2
    except (ValueError, OSError, TypeError) as exc:
        result = {"status": "error", "error_code": "invalid_argument", "message": str(exc), "citations": [], "knowledge_lookup_completed": False}
        code = 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
