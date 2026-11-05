"""Portable export behavior: immutability, safety, lookup and version retention."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from geo_kb import GeoKB
from export_remote import export_database, token_shard


class ExportRemoteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.db = self.root / "knowledge.sqlite3"
        self.output = self.root / "data"
        self.text = "# 引用信源\n\n- 原文链接：https://example.com/source\n- 发布时间：2026-01-01\n\n## 实操\n引用需要 citation 来源，保持条件清楚。\n"
        self.source = self.vault / "source.md"
        self.source.write_text(self.text, encoding="utf-8")
        self.kb = GeoKB(self.db)
        self.kb.build(self.vault)

    def tearDown(self):
        self.temporary.cleanup()

    def _json(self, path):
        return json.loads((self.output / path).read_text(encoding="utf-8"))

    def test_exact_versions_and_search_postings(self):
        original_hash = hashlib.sha256(self.db.read_bytes()).hexdigest()
        result = export_database(self.db, self.output)
        self.assertEqual(result["counts"]["documents"], 1)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), original_hash)
        catalog = self._json("catalog.json")
        doc = next(iter(catalog["documents"].values()))
        version = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        snapshot = self._json(f"documents/{doc['document_id']}/{version}.json")
        self.assertEqual(snapshot["text"], self.text)
        self.assertEqual(snapshot["line_count"], len(self.text.splitlines()))
        self.assertNotIn("relative_path", snapshot["metadata"])
        self.assertNotIn("reading_url", snapshot["metadata"])
        self.assertEqual(catalog["search"]["shard_count"], 128)
        self.assertEqual(catalog["search"]["shards"][-1], "/data/index/7f.json")
        postings = self._json(f"index/{token_shard('引用'):02x}.json")["引用"]
        chunk = self._json("chunks.json")[0]
        self.assertEqual(postings[0], chunk["id"])
        self.assertGreater(postings[1], 0)
        self.assertEqual(token_shard("hello", 16), 11)
        self.assertEqual(token_shard("引用", 16), 0)
        self.assertEqual(token_shard("hello"), 43)
        self.assertEqual(token_shard("引用"), 80)

    def test_history_does_not_leak_but_source_versions_survive(self):
        first_version = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        self.source.write_text(self.text + "\n新版本。\n", encoding="utf-8")
        self.kb.build(self.vault)
        connection = sqlite3.connect(self.db)
        connection.execute("INSERT INTO answers VALUES(?,?,?)", ("private-answer", '{"private":"private user question"}', "2026-01-01"))
        doc, version = connection.execute("SELECT document_id,current_version FROM documents").fetchone()
        connection.execute("INSERT INTO reviewed_claims VALUES(?,?,?,?,?,?)", ("private-review", doc, version, 1, 1,
                           json.dumps({"review_origin": "AI_session_review_not_independent_verification", "statement": "private user review"})))
        connection.commit()
        connection.close()
        result = export_database(self.db, self.output)
        self.assertEqual(result["counts"]["source_versions"], 2)
        self.assertEqual(self._json(f"documents/{doc}/{first_version}.json")["text"], self.text)
        self.assertEqual(self._json(f"documents/{doc}/{version}.json")["reviewed_claims"], [])
        for path in self.output.rglob("*.json"):
            self.assertNotIn("private user", path.read_text(encoding="utf-8"))

    def test_credential_pattern_blocks_without_echo_or_partial_write(self):
        fake = "ghp_" + "A" * 40
        self.source.write_text(self.text + "\n" + fake, encoding="utf-8")
        self.kb.build(self.vault)
        with self.assertRaises(ValueError) as error:
            export_database(self.db, self.output)
        self.assertIn("github_token", str(error.exception))
        self.assertNotIn(fake, str(error.exception))
        self.assertFalse(self.output.exists())

    def test_manifest_and_export_are_deterministic(self):
        export_database(self.db, self.output)
        before = {p.relative_to(self.output).as_posix(): p.read_bytes() for p in self.output.rglob("*.json")}
        export_database(self.db, self.output)
        after = {p.relative_to(self.output).as_posix(): p.read_bytes() for p in self.output.rglob("*.json")}
        self.assertEqual(before, after)
        for name, entry in self._json("manifest.json")["files"].items():
            self.assertEqual(hashlib.sha256(before[name]).hexdigest(), entry["sha256"])
            self.assertEqual(len(before[name]), entry["bytes"])

    def test_supplement_preserves_archive_and_keeps_verification_date_distinct(self):
        export_database(self.db, self.output)
        original = self._json("catalog.json")
        doc = next(iter(original["documents"].values()))
        name = f"documents/{doc['document_id']}/{doc['current_version']}.json"
        source_before = (self.output / name).read_bytes()
        db_before = self.db.read_bytes()
        notes = self.root / "notes"
        notes.mkdir()
        (notes / "claude.md").write_text("# Claude 的网页信源\n- 原文链接：https://support.claude.com/example\n- 核查日期：2026-11-05\n\n## 说明\nClaude 搜索互联网网页。\n", encoding="utf-8")
        report = export_database(self.db, self.output, notes)
        self.assertEqual(report["counts"]["documents"], 2)
        self.assertEqual((self.output / name).read_bytes(), source_before)
        self.assertEqual(self.db.read_bytes(), db_before)
        new = self._json("catalog.json")["documents"][report["supplemental_notes"][0]["document_id"]]
        self.assertIsNone(new["published_at"])
        self.assertEqual(new["checked_at"], "2026-11-05")
        self.assertEqual(new["source_type"], "official_document_note")
        token = self._json(f"index/{token_shard('claude'):02x}.json")["claude"]
        self.assertTrue(token)
        version = self._json("catalog.json")["knowledge_version"]
        export_database(self.db, self.output, notes)
        self.assertEqual(self._json("catalog.json")["knowledge_version"], version)


if __name__ == "__main__":
    unittest.main()
