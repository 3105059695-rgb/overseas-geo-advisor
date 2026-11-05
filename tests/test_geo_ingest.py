import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from geo_ingest import LexicalIndex, build_index, segment_markdown, source_metadata


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.snapshot = self.base / "snapshot"
        self.output = self.base / "output"
        self.snapshot.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def snapshot_doc(self, text, doc_id="doc-example", metadata=None):
        version = digest(text)
        metadata = {"title": "测试", "work_id": "work-example", **(metadata or {})}
        entry = {"document_id": doc_id, "current_version": version, **metadata}
        payload = {"document_id": doc_id, "source_version": version, "text": text,
                   "line_count": len(text.splitlines()), "metadata": metadata}
        path = self.snapshot / "documents" / doc_id / (version + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        (self.snapshot / "catalog.json").write_text(json.dumps({"documents": {doc_id: entry}}), encoding="utf-8")
        return version, path

    def test_explicit_dates_and_links_never_mtime(self):
        text = "# 文章\n\n- 原帖发布时间：2026-06-08 18:52\n- 收藏日期：2026-10-29\n- 核查日期：2026-11-05\n- 观察日期：2026-11-04\n- 原帖：https://x.com/user/status/123\n\n## 正文\n![图](../附件/原图.png)\n"
        metadata = source_metadata(text)
        self.assertEqual(metadata["published_at"], "2026-06-08")
        self.assertEqual(metadata["collected_at"], "2026-10-29")
        self.assertEqual(metadata["checked_at"], "2026-11-05")
        self.assertEqual(metadata["observed_at"], "2026-11-04")
        self.assertEqual(metadata["original_url"], "https://x.com/user/status/123")
        self.assertEqual(metadata["image_refs"], ["../附件/原图.png"])
        self.assertIsNone(source_metadata("# 无日期\n- 收藏日期：2026-10-29")["published_at"])
        self.assertIsNone(source_metadata("# 无日期\n\n## 正文\n发布时间：2026-10-29")["published_at"])

    def test_heading_roles_table_code_exact_lines(self):
        text = "# 原始文档\n\n## 中文全文\n\n译文段落。\n\n| 指标 | 条件 |\n| --- | --- |\n" + "".join(f"| {i} | 样本限定平台，每个条件需要保存。 |\n" for i in range(12)) + "\n## 英文原文\n\nOriginal evidence has limitations.\n\n```python\n# this is code, not a heading\nprint('evidence')\n```\n\n## 教学例子\n\n这只是教学例子。\n\n## OCR 识别\n\n待校对识别文本。\n\n## 附录\n\n附页。\n"
        parts = segment_markdown(text, 100)
        roles = {p["content_role"] for p in parts}
        self.assertTrue({"translation", "source_text", "teaching", "ocr", "page_appendix"} <= roles)
        for part in parts:
            self.assertEqual(part["text"], "\n".join(text.splitlines()[part["line_start"]-1:part["line_end"]]))
        table_parts = [p for p in parts if p["metadata"]["block_kind"] == "table"]
        self.assertGreater(len(table_parts), 1)
        self.assertTrue(table_parts[1]["metadata"]["header_repeat_required"])
        self.assertIn("| 指标 | 条件 |", table_parts[1]["metadata"]["table_header"])
        self.assertNotIn("| 指标 | 条件 |", table_parts[1]["text"])
        code_parts = [p for p in parts if p["metadata"]["block_kind"] == "code"]
        self.assertEqual(len(code_parts), 1)
        self.assertEqual(code_parts[0]["section_path"], ["原始文档", "英文原文"])
        covered = {n for p in parts for n in range(p["line_start"], p["line_end"]+1)}
        self.assertTrue(all(n in covered for n,line in enumerate(text.splitlines(),1) if line.strip()))

    def test_build_search_exact_read_rebuild_and_retirement(self):
        text = "# 来源\n\n- 发布时间：2026-01-02\n- 原帖：https://example.com/a\n\n## 中文全文\n\n引用率只适用于指定实验条件。\n\n![图](images/a.png)\n"
        version, source_path = self.snapshot_doc(text)
        source_bytes = source_path.read_bytes()
        first = build_index(self.snapshot, output_dir=self.output)
        chunks_before = (self.output / "chunks.jsonl").read_bytes()
        second = build_index(self.snapshot, output_dir=self.output)
        self.assertEqual(first["corpus_fingerprint"], second["corpus_fingerprint"])
        self.assertEqual(chunks_before, (self.output / "chunks.jsonl").read_bytes())
        self.assertEqual(source_bytes, source_path.read_bytes())
        index = LexicalIndex(self.output / "index.sqlite3")
        result = index.search("引用率 实验", 5)
        self.assertTrue(result)
        self.assertEqual(result[0]["source_version"], version)
        read = index.read("doc-example", version, result[0]["line_start"], result[0]["line_end"])
        self.assertEqual(read["excerpt"], result[0]["text"])
        self.assertEqual(read["full_source_sha256"], version)
        self.assertIn("images/a.png", read["metadata"]["image_refs"])
        with index._connect() as con:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("DELETE FROM sources")
        new_version, _ = self.snapshot_doc(text.replace("引用率", "追踪率"))
        third = build_index(self.snapshot, output_dir=self.output)
        self.assertEqual(third["retired_from_generated_index_only"], [{"document_id": "doc-example", "source_version": version}])
        self.assertTrue(source_path.exists())
        with self.assertRaises(KeyError):
            index.read("doc-example", version)
        self.assertEqual(index.read("doc-example", new_version)["full_source_sha256"], new_version)

    def test_hash_tamper_fails_without_replacing_generated_index(self):
        _, path = self.snapshot_doc("# 完整来源\n\n有效正文。\n")
        build_index(self.snapshot, output_dir=self.output)
        original_index = (self.output / "index.sqlite3").read_bytes()
        payload = json.loads(path.read_text("utf-8"))
        payload["text"] += "篡改"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ValueError):
            build_index(self.snapshot, output_dir=self.output)
        self.assertEqual(original_index, (self.output / "index.sqlite3").read_bytes())

    def test_missing_text_is_quality_queue_not_fake_source(self):
        self.snapshot_doc("")
        manifest = build_index(self.snapshot, output_dir=self.output)
        queue = (self.output / "quality-queue.jsonl").read_text("utf-8")
        self.assertEqual(manifest["counts"]["documents"], 0)
        self.assertIn("missing_full_text", queue)
        self.assertEqual((self.output / "chunks.jsonl").read_text("utf-8"), "")

    def test_markdown_original_bytes_bom_crlf_and_pdf_queue(self):
        vault = self.base / "vault"
        vault.mkdir()
        raw = b"\xef\xbb\xbf# A\r\n\r\nSource evidence.\r\n"
        source = vault / "article.md"
        source.write_bytes(raw)
        (vault / "scanned.pdf").write_bytes(b"%PDF")
        manifest = build_index(vault_dir=vault, output_dir=self.output)
        self.assertEqual(source.read_bytes(), raw)
        self.assertEqual(manifest["counts"]["documents"], 1)
        item = json.loads((self.output / "chunks.jsonl").read_text("utf-8").splitlines()[0])
        self.assertEqual(item["metadata"]["original_bytes_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertIsNone(item["metadata"]["published_at"])
        self.assertIn("pdf_native_text_or_ocr_not_attempted", (self.output / "quality-queue.jsonl").read_text("utf-8"))
        with self.assertRaises(ValueError):
            build_index(vault_dir=vault, output_dir=vault / "derived")

    def test_exact_dedup_keeps_bilingual_documents_and_versions(self):
        catalog = {"documents": {}}
        for doc_id, text in [("doc-en", "# Source\n\nOriginal conditions.\n"),
                             ("doc-copy", "# Source\n\nOriginal conditions.\n"),
                             ("doc-zh", "# 译文\n\n## 中文全文\n\n原文条件。\n")]:
            self.snapshot_doc(text, doc_id)
            catalog["documents"].update(json.loads((self.snapshot/"catalog.json").read_text("utf-8"))["documents"])
        (self.snapshot/"catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
        manifest = build_index(self.snapshot, output_dir=self.output)
        self.assertEqual(manifest["counts"]["documents"], 3)
        self.assertEqual(manifest["counts"]["exact_duplicate_groups"], 1)
        self.assertEqual(manifest["counts"]["exact_duplicate_documents"], 1)
        with (self.output/"chunks.jsonl").open(encoding="utf-8") as stream:
            chunks = [json.loads(line) for line in stream]
        translated = next(c for c in chunks if c["document_id"] == "doc-zh" and c["content_role"] == "translation")
        self.assertEqual(translated["metadata"]["exact_duplicate_document_ids"], ["doc-zh"])
        for candidate in LexicalIndex(self.output/"index.sqlite3").search("Source conditions"):
            self.assertNotEqual(candidate["metadata"]["block_kind"], "heading")

    def test_asset_manifest_integrity_and_line_breaks(self):
        _, path = self.snapshot_doc("# Source\n\nSentence with unicode\u2028line separator.\n")
        files = {}
        for source in [path, self.snapshot/"catalog.json"]:
            raw = source.read_bytes()
            files[source.relative_to(self.snapshot).as_posix()] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        (self.snapshot/"manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
        build_index(self.snapshot, output_dir=self.output)
        with (self.output/"chunks.jsonl").open(encoding="utf-8") as stream:
            self.assertTrue(all(isinstance(json.loads(line), dict) for line in stream))
        path.write_bytes(path.read_bytes()+b" ")
        with self.assertRaises(ValueError):
            build_index(self.snapshot, output_dir=self.output)


if __name__ == "__main__":
    unittest.main()
