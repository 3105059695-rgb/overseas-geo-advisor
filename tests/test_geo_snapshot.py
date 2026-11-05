"""Direct snapshot fallback: source integrity, constrained retrieval and caching."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from geo_kb import GeoKB
from export_remote import export_database
import geo_snapshot as gs


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        vault = self.root / "vault"
        vault.mkdir()
        self.text = "# 海外引用信源分类\n\n原文链接：https://example.com/source\n发布时间：2025-01-01\n\n## 分类与限制\n引用信源可以记录品牌网站、社区和新闻来源。\ncitation sources and ChatGPT measurement require context.\n这是作者方法，不能保证推荐。\n"
        (vault / "source.md").write_text(self.text, encoding="utf-8")
        (vault / "new.md").write_text("# 新版本统计\n发布时间：2026-01-01\n\n引用信源 citation 内容。\n", encoding="utf-8")
        self.data = self.root / "data"
        kb = GeoKB(self.root / "index.sqlite3")
        kb.build(vault)
        export_database(self.root / "index.sqlite3", self.data)
        manifest_sha = hashlib.sha256((self.data / "manifest.json").read_bytes()).hexdigest()
        self.manifest_patch = patch.object(gs, "MANIFEST_SHA256", manifest_sha)
        self.manifest_patch.start()
        self.client = gs.SnapshotClient(cache_dir=self.root / "cache")
        self.fetches = []
        def fetch(name):
            self.fetches.append(name)
            return (self.data / name).read_bytes()
        self.client._fetch_bytes = fetch
        catalog = json.loads((self.data / "catalog.json").read_text(encoding="utf-8"))
        self.doc = next(d for d in catalog["documents"].values() if d["title"] == "海外引用信源分类")

    def tearDown(self):
        self.manifest_patch.stop()
        self.temp.cleanup()

    def test_chinese_english_search_exact_read_and_history(self):
        result = self.client.call("search_geo", {"question": "信源 citation", "limit": 2})
        self.assertEqual(result["status"], "ok")
        citation = next(c for c in result["citations"] if c["document_id"] == self.doc["document_id"])
        self.assertTrue(citation["reading_url"].startswith(gs.BLOB_BASE))
        self.assertNotIn("chatgpt.site", citation["reading_url"])
        self.assertNotIn("#L", citation["reading_url"])
        self.assertEqual(citation["source_version"], hashlib.sha256(self.text.encode()).hexdigest())
        read = self.client.call("read_geo_source", {"document_id": citation["document_id"], "source_version": citation["source_version"],
                                                    "start_line": citation["line_start"], "end_line": citation["line_end"]})
        self.assertEqual(read["excerpt"], "\n".join(self.text.splitlines()[read["line_start"] - 1:read["line_end"]]))
        history = self.client.call("search_geo", {"question": "引用 citation", "as_of": "2025-12-31"})
        self.assertTrue(all(c["published_at"] <= "2025-12-31" for c in history["citations"]))
        self.assertEqual(self.client.call("ask_geo", {"question": "第二个怎么做？"})["status"], "needs_clarification")
        focused = self.client.call("ask_geo", {"question": "解释这段原文", "focus_citation_id": citation["citation_id"]})
        self.assertEqual(focused["citations"][0]["source_version"], citation["source_version"])
        self.assertEqual(focused["answer_kind"], "evidence_packet")

    def test_browse_no_results_invalid_input_and_missing_version(self):
        browse = self.client.call("browse_geo_topics", {})
        self.assertEqual(browse["counts"]["documents"], 2)
        self.assertFalse(browse["snapshot_transport"]["query_uploaded"])
        self.assertEqual(self.client.call("search_geo", {"question": "zzzzunmatchedterm"})["status"], "insufficient_evidence")
        self.assertEqual(self.client.call("search_geo", {"question": "引用", "limit": True})["status"], "error")
        self.assertEqual(self.client.call("search_geo", {"question": "引用", "as_of": "2026-02-30"})["status"], "error")
        self.assertEqual(self.client.call("read_geo_source", {"document_id": self.doc["document_id"], "source_version": "0" * 64})["status"], "not_found")
        self.assertEqual(self.client.call("read_geo_source", {"document_id": "../../secret", "source_version": "0" * 64})["status"], "error")
        self.assertEqual(self.client.call("review_geo_claim", {})["status"], "error")

    def test_checks_resolve_real_quote_and_reject_unsupported_priority(self):
        ref = self.client.call("read_geo_source", {"document_id": self.doc["document_id"], "source_version": self.doc["current_version"]})
        claim = {"text": "作者提出信源分类方法", "kind": "author_report", "allowed_use": "attributed_report", "main": True,
                 "citation_ids": [ref["citation_id"]], "exact_quote": "引用信源可以记录品牌网站、社区和新闻来源。", "conditions": ["按该作者档案的分类口径"]}
        check = self.client.call("check_geo_answer", {"bundle": {"claims": [claim]}})
        self.assertEqual(check["status"], "structural_pass")
        self.assertFalse(check["answer_approved"])
        self.assertEqual(check["semantic_validation"], "not_performed")
        self.assertEqual(self.client.call("check_geo_answer", {"bundle": {"claims": [{**claim, "kind": "priority"}]}})["status"], "blocked")
        self.assertEqual(self.client.call("check_geo_answer", {"bundle": {"claims": [{**claim, "exact_quote": "a fabricated quote"}]}})["status"], "blocked")

    def test_hash_failure_stops_and_never_downloads_another_version(self):
        original = self.client._fetch_bytes
        def corrupt(name):
            value = original(name)
            return value + b" " if name == "catalog.json" else value
        self.client._fetch_bytes = corrupt
        with self.assertRaises(gs.SnapshotError) as error:
            self.client.call("browse_geo_topics", {})
        self.assertEqual(error.exception.code, "snapshot_integrity_error")
        self.assertEqual(self.fetches, ["manifest.json", "catalog.json"])
        self.assertFalse(any("latest" in p or "main" in p for p in self.fetches))

    def test_cache_is_verified_reused_bounded_and_optional(self):
        self.client.call("browse_geo_topics", {})
        second = gs.SnapshotClient(cache_dir=self.root / "cache")
        with patch.object(second, "_fetch_bytes", side_effect=AssertionError("Network must not be required")):
            self.assertEqual(second.call("browse_geo_topics", {})["counts"]["documents"], 2)
        # A cache entry is never trusted merely because it has the expected filename.
        catalog_sha = json.loads((self.data / "manifest.json").read_text())["files"]["catalog.json"]["sha256"]
        second._cache_path(catalog_sha).write_bytes(b"corrupt")
        third = gs.SnapshotClient(cache_dir=self.root / "cache")
        with self.assertRaises(gs.SnapshotError):
            third.call("browse_geo_topics", {})
        bounded = gs.SnapshotClient(cache_dir=self.root / "bounded")
        with patch.object(gs, "MAX_CACHE_BYTES", 2000):
            for i in range(8):
                raw = (str(i) * 800).encode()
                bounded._save_cached(raw, hashlib.sha256(raw).hexdigest())
            self.assertLessEqual(sum(p.stat().st_size for p in bounded.cache_dir.glob("*.json")), 2000)
        unavailable = self.root / "not-a-directory"
        unavailable.write_text("retain me")
        no_disk = gs.SnapshotClient(cache_dir=unavailable)
        no_disk._fetch_bytes = lambda name: (self.data / name).read_bytes()
        self.assertEqual(no_disk.call("browse_geo_topics", {})["status"], "ok")
        self.assertEqual(unavailable.read_text(), "retain me")

    def test_transport_403_uses_fixed_contents_api_without_auth(self):
        raw = b'{"ok":true}'
        requests = []
        class Response(io.BytesIO):
            pass
        class Opener:
            def open(self, request, timeout):
                requests.append(request)
                if len(requests) == 1:
                    raise HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO())
                return Response(raw)
        with patch.object(gs, "build_opener", return_value=Opener()):
            self.assertEqual(gs.SnapshotClient(cache_dir=self.root / "network")._fetch_bytes("catalog.json"), raw)
        self.assertTrue(requests[0].full_url.startswith(gs.RAW_BASE))
        self.assertIn("ref=" + gs.DATA_COMMIT, requests[1].full_url)
        self.assertEqual(requests[1].get_header("Accept"), "application/vnd.github.raw+json")
        self.assertTrue(all(not r.has_header("Authorization") for r in requests))


if __name__ == "__main__":
    unittest.main()
