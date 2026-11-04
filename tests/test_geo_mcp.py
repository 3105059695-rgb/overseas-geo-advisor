"""Real SDK stdio round trips, not GUI/client-product acceptance tests."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SERVER = SCRIPTS / "geo_mcp.py"
sys.path.insert(0, str(SCRIPTS))

HAS_MCP = importlib.util.find_spec("mcp") is not None
if HAS_MCP:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client


def result_body(result):
    if result.structuredContent is not None:
        return result.structuredContent
    for block in result.content:
        if getattr(block, "type", None) == "text":
            try:
                return json.loads(block.text)
            except json.JSONDecodeError:
                pass
    raise AssertionError("MCP result did not contain JSON")


@asynccontextmanager
async def sdk_session(db_path: Path):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-B", "-X", "utf8", str(SERVER), "--db", str(db_path)],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    # Successful protocol round trips also demonstrate stdout carries protocol
    # messages instead of startup banners or incidental print diagnostics.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
        async with stdio_client(parameters, errlog=errors) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=20)) as session:
                initialized = await session.initialize()
                yield session, initialized


@unittest.skipUnless(HAS_MCP, "MCP SDK is not installed in this interpreter")
class StdioMCPTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="geo-mcp-test-")
        self.base = Path(self.tmp.name)
        self.db = self.base / "kb.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    async def test_config_prints_concrete_command_without_writing_database(self):
        process = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-B", "-X", "utf8", str(SERVER), "--db", str(self.db), "--print-config"],
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        config = json.loads(process.stdout)
        value = config["mcpServers"]["overseas-geo-advisor"]
        self.assertEqual(value["command"], sys.executable)
        self.assertIn(str(self.db.resolve()), value["args"])
        self.assertFalse(self.db.exists())

    async def test_handshake_schema_missing_index_and_invalid_arguments(self):
        async with sdk_session(self.db) as (session, initialized):
            self.assertTrue(initialized.protocolVersion)
            self.assertEqual(initialized.serverInfo.name, "overseas-geo-advisor")
            self.assertEqual(initialized.serverInfo.version, "0.1.0")
            tools = (await session.list_tools()).tools
            self.assertEqual(
                {tool.name for tool in tools},
                {"ask_geo", "search_geo", "read_geo_source", "browse_geo_topics", "check_geo_answer", "review_geo_claim"},
            )
            review_tool = next(tool for tool in tools if tool.name == "review_geo_claim")
            self.assertFalse(review_tool.annotations.readOnlyHint)
            search_schema = next(tool.inputSchema for tool in tools if tool.name == "search_geo")
            self.assertEqual(search_schema["properties"]["limit"]["maximum"], 50)
            unavailable = result_body(await session.call_tool("browse_geo_topics", {}))
            self.assertEqual(unavailable["status"], "unavailable")
            self.assertEqual(unavailable["error_code"], "database_missing")
            self.assertFalse(self.db.exists())
            invalid_limit = await session.call_tool("search_geo", {"question": "GEO", "limit": 51})
            self.assertTrue(invalid_limit.isError)
            missing_argument = await session.call_tool("search_geo", {})
            self.assertTrue(missing_argument.isError)
            invalid_date = await session.call_tool("ask_geo", {"question": "GEO", "as_of": "2026-02-31"})
            self.assertTrue(invalid_date.isError)
            invalid_range = await session.call_tool("read_geo_source", {
                "document_id": "anything", "source_version": "anything", "start_line": 10, "end_line": 1,
            })
            self.assertTrue(invalid_range.isError)
            missing_again = result_body(await session.call_tool("ask_geo", {"question": "海外信源怎么分？"}))
            self.assertEqual(missing_again["status"], "unavailable")
            self.assertFalse(missing_again["citations"])

    async def test_corrupt_database_never_reports_success(self):
        self.db.write_text("not a SQLite database", encoding="utf-8")
        async with sdk_session(self.db) as (session, _):
            output = result_body(await session.call_tool("browse_geo_topics", {}))
            self.assertIn(output["status"], {"unavailable", "error"})
            self.assertFalse(output.get("citations"))
            self.assertEqual(self.db.read_text(encoding="utf-8"), "not a SQLite database")

    async def test_search_versioned_read_followup_and_guard_roundtrip(self):
        if not (SCRIPTS / "geo_kb.py").is_file():
            self.skipTest("retrieval module has not been produced yet")
        from geo_kb import GeoKB

        vault = self.base / "vault"
        vault.mkdir()
        assets = self.base / "assets"
        assets.mkdir()
        (assets / "curated.json").write_text(json.dumps({
            "schema_version": 1, "sources": [], "claims": [], "catalogs": {}, "answers": [],
        }), encoding="utf-8")
        source = vault / "source.md"
        original = "# 版本引用对齐\n\n发布时间：2026-10-01\n\n版本引用对齐必须保留原始时间与条件。\n\n## 信源分类\n\n自有、竞品和第三方属于品牌关系分类。\n"
        source.write_text(original, encoding="utf-8")
        kb = GeoKB(self.db, assets_dir=assets)
        kb.build(vault)

        async with sdk_session(self.db) as (session, _):
            searched = result_body(await session.call_tool("search_geo", {"question": "版本引用对齐", "limit": 10}))
            citations = searched["citations"]
            self.assertTrue(citations)
            citation = citations[0]
            read = result_body(await session.call_tool("read_geo_source", {
                "document_id": citation["document_id"], "source_version": citation["source_version"],
            }))
            self.assertIn("版本引用对齐", json.dumps(read, ensure_ascii=False))
            first = result_body(await session.call_tool("ask_geo", {
                "question": "怎样保留版本引用对齐的条件？", "detail": "brief",
                "context": {"observations": ["用户报告某站点只测试过一次；尚未核实。"]},
            }))
            self.assertIn(first["status"], {"answered", "partial", "insufficient_evidence"})
            self.assertTrue(first.get("answer_id"))
            self.assertEqual(first["user_observations"]["kind"], "user_provided")
            self.assertIn("只测试过一次", json.dumps(first["user_observations"], ensure_ascii=False))
            self.assertNotIn("只测试过一次", json.dumps(first["citations"], ensure_ascii=False))
            followup = result_body(await session.call_tool("ask_geo", {
                "question": "刚才这个来源具体写了什么？",
                "previous_answer_id": first["answer_id"],
                "focus_citation_id": citation["citation_id"],
            }))
            self.assertNotEqual(followup.get("status"), "unavailable")
            self.assertTrue(followup.get("answer_id") or followup.get("status") == "needs_clarification")
            invalid_read = result_body(await session.call_tool("read_geo_source", {
                "document_id": "../../private.txt", "source_version": "made-up-version",
            }))
            self.assertIn(invalid_read.get("status"), {"not_found", "error", "unavailable"})
            checked = result_body(await session.call_tool("check_geo_answer", {"bundle": {
                "claims": [{
                    "text": "未经核实的材料保证排名第一。", "kind": "fact", "main": True,
                    "citation_ids": ["fabricated-citation"], "allowed_use": "verified_fact", "conditions": [],
                }],
                "citations": [{"citation_id": "fabricated-citation", "review_scope": ["verified"]}],
            }}))
            serialized = json.dumps(checked, ensure_ascii=False)
            self.assertNotIn('"status": "approved"', serialized)
            self.assertTrue(checked.get("issues") or checked.get("errors") or checked.get("status") in {"invalid", "blocked", "error"})

        source.write_text(original.replace("版本引用对齐必须", "新版本内容必须"), encoding="utf-8")
        kb.build(vault)
        async with sdk_session(self.db) as (session, _):
            historical = result_body(await session.call_tool("read_geo_source", {
                "document_id": citation["document_id"], "source_version": citation["source_version"],
            }))
            historical_text = json.dumps(historical, ensure_ascii=False)
            self.assertIn("版本引用对齐必须", historical_text)
            self.assertNotIn("新版本内容必须", historical_text)

    async def test_limited_claim_review_records_origin_and_rejects_escalation(self):
        from geo_kb import GeoKB

        vault = self.base / "review-vault"
        vault.mkdir()
        assets = self.base / "review-assets"
        assets.mkdir()
        (assets / "curated.json").write_text(json.dumps({
            "schema_version": 1, "sources": [], "claims": [], "catalogs": {}, "answers": [],
        }), encoding="utf-8")
        source = vault / "review.md"
        quote = "作者将观察到的引用域名分为自有域名、竞争对手域名和第三方域名。"
        original = "# 信源分类核对\n\n" + quote + "\n\n这是一份方法说明，没有证明所有行业渠道的投入顺序。\n"
        source.write_text(original, encoding="utf-8")
        kb = GeoKB(self.db, assets_dir=assets)
        kb.build(vault)

        async with sdk_session(self.db) as (session, _):
            found = result_body(await session.call_tool("search_geo", {"question": "信源分类核对"}))
            citation = found["citations"][0]
            statement = "作者采用自有、竞品和第三方的域名分类。"
            arguments = {
                "document_id": citation["document_id"], "source_version": citation["source_version"],
                "statement": statement, "exact_quote": quote,
                "allowed_use": "attributed_report", "conditions": ["仅复述该作者的分类方法"],
                "review_note": "已阅读版本原文与限制；核对文字支持，不代表独立验证方法有效性。",
            }
            missing_quote = result_body(await session.call_tool("review_geo_claim", {
                **arguments, "exact_quote": "这句话在对应原文中不存在。",
            }))
            self.assertEqual(missing_quote["status"], "error")
            escalated = await session.call_tool("review_geo_claim", {
                **arguments, "allowed_use": "verified_current_fact",
            })
            self.assertTrue(escalated.isError)
            reviewed = result_body(await session.call_tool("review_geo_claim", arguments))
            self.assertEqual(reviewed["status"], "recorded")
            self.assertEqual(reviewed["review_origin"], "AI_session_review_not_independent_verification")
            self.assertEqual(reviewed["semantic_validation"], "declared_by_answering_AI_not_programmatically_verified")
            checked = result_body(await session.call_tool("check_geo_answer", {"bundle": {
                "claims": [{
                    "text": statement, "kind": "author_report", "main": True,
                    "reviewed_claim_id": reviewed["claim_id"],
                    "citation_ids": [reviewed["citation"]["citation_id"]],
                    "allowed_use": reviewed["claim"]["allowed_use"],
                    "conditions": reviewed["claim"]["conditions"],
                }],
                "citations": [reviewed["citation"]],
            }}))
            self.assertEqual(checked["status"], "structural_pass")
            self.assertEqual(checked["semantic_validation"], "not_performed")
            self.assertFalse(checked["answer_approved"])
            priority = result_body(await session.call_tool("check_geo_answer", {"bundle": {
                "claims": [{
                    "text": statement, "kind": "priority", "main": True,
                    "reviewed_claim_id": reviewed["claim_id"],
                    "citation_ids": [reviewed["citation"]["citation_id"]],
                    "allowed_use": reviewed["claim"]["allowed_use"],
                    "conditions": reviewed["claim"]["conditions"],
                }], "citations": [reviewed["citation"]],
            }}))
            self.assertEqual(priority["status"], "blocked")
            self.assertEqual(source.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
