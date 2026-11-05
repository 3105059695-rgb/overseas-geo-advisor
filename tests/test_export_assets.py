"""Attachment export: source immutability, safe resolution, dedupe and manifests."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from export_assets import document_id, encode, export_assets, extract_references, safe_path


class ExportAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.vault = self.root / "vault"
        self.output = self.root / "data"
        self.vault.mkdir()
        self.output.mkdir()
        # Small synthetic fixtures; no network or actual vault assets are used.
        self.png = b"\x89PNG\r\n\x1a\nsynthetic-image"
        self.pdf = b"%PDF-1.4\nsynthetic-pdf\n%%EOF\n"
        self.documents = {}

    def tearDown(self):
        self.temporary.cleanup()

    def asset(self, relative, payload=None):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.png if payload is None else payload)
        return path

    def source(self, relative, text, *, source_relative=None):
        path = self.vault / (source_relative or relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        doc_id = document_id(relative)
        version = hashlib.sha256(text.encode()).hexdigest()
        name = f"documents/{doc_id}/{version}.json"
        target = self.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encode({"document_id": doc_id, "source_version": version,
                                  "text": text, "line_count": len(text.splitlines())}))
        self.documents.setdefault(doc_id, {"document_id": doc_id, "versions": {}})
        self.documents[doc_id]["versions"][version] = len(text.splitlines())
        self.documents[doc_id]["current_version"] = version
        return doc_id, version

    def snapshot(self):
        (self.output / "catalog.json").write_bytes(encode({
            "knowledge_version": "test-snapshot", "documents": self.documents,
            "counts": {"documents": len(self.documents)},
        }))
        (self.output / "chunks.json").write_bytes(encode([{"id": 1, "text": "unchanged"}]))
        (self.output / "index").mkdir(exist_ok=True)
        (self.output / "index" / "00.json").write_bytes(encode({"test": [1, 1, 0]}))
        files = {p.relative_to(self.output).as_posix(): {
            "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        } for p in self.output.rglob("*.json") if p.name != "manifest.json"}
        (self.output / "manifest.json").write_bytes(encode({
            "schema_version": 1, "knowledge_version": "test-snapshot", "files": files,
        }))

    def sidecar(self, key):
        doc_id, version = key
        return json.loads((self.output / f"attachments/{doc_id}/{version}.json").read_text("utf-8"))

    def all_bytes(self):
        return {p.relative_to(self.output).as_posix(): p.read_bytes()
                for p in self.output.rglob("*") if p.is_file()}

    def test_formats_line_numbers_external_and_deduplication(self):
        self.asset("notes/asset image (1).png")
        self.asset("attachments/copy.png")
        self.asset("attachments/论文.pdf", self.pdf)
        self.asset("attachments/ref.png", self.png + b"ref")
        text = ("# 附件\n"
                "![有空格](<asset image (1).png>)\n"
                "![URL编码](asset%20image%20%281%29.png)\n"
                "![括号](asset image (1).png \"图示\")\n"
                "![[copy.png|300]]\n"
                "![[论文.pdf#page=2|论文]]\n"
                "[论文](../attachments/论文.pdf)\n"
                "![站外](https://example.test/image.png)\n"
                "![引用图片][配图]\n\n[配图]: ../attachments/ref.png '配图标题'\n"
                "`![示例](not-an-asset.png)`\n"
                "```markdown\n![[fake.png]]\n```\n")
        key = self.source("notes/source.md", text)
        empty_key = self.source("empty.md", "# 没有附件\n")
        self.snapshot()
        before = self.all_bytes()
        with patch("urllib.request.urlopen", side_effect=AssertionError("No network allowed")):
            report = export_assets(self.vault, self.output)
        attachments = self.sidecar(key)["attachments"]
        self.assertEqual(len(attachments), 8)
        self.assertEqual([a["line_start"] for a in attachments], list(range(2, 10)))
        self.assertEqual([a["status"] for a in attachments], ["available"] * 6 + ["external", "available"])
        self.assertEqual(len({a["path"] for a in attachments[:4]}), 1)
        self.assertEqual(attachments[4]["path"], attachments[5]["path"])
        self.assertEqual(attachments[4]["mime"], "application/pdf")
        self.assertEqual(attachments[6]["url"], "https://example.test/image.png")
        self.assertIsNone(attachments[6]["path"])
        self.assertEqual(self.sidecar(empty_key)["attachments"], [])
        self.assertEqual(report["attachment_summary"]["files"], 3)
        self.assertEqual(report["attachment_summary"]["available"], 7)
        self.assertEqual(report["external_resources_downloaded"], 0)
        for name, payload in before.items():
            if name not in {"catalog.json", "manifest.json"}:
                self.assertEqual((self.output / name).read_bytes(), payload)
        catalog = json.loads((self.output / "catalog.json").read_text("utf-8"))
        self.assertEqual(catalog["knowledge_version"], "test-snapshot")
        self.assertEqual(catalog["counts"]["attachments"], 3)
        self.assertEqual(catalog["attachment_summary"], report["attachment_summary"])
        self.assertEqual(catalog["attachment_path_template"], "/data/attachments/{document_id}/{source_version}.json")
        manifest = json.loads((self.output / "manifest.json").read_text("utf-8"))
        after = self.all_bytes()
        self.assertEqual(set(manifest["files"]), set(after) - {"manifest.json"})
        for name, entry in manifest["files"].items():
            self.assertEqual(entry, {"bytes": len(after[name]), "sha256": hashlib.sha256(after[name]).hexdigest()})
        export_assets(self.vault, self.output)
        self.assertEqual(self.all_bytes(), after)

    def test_missing_ambiguous_traversal_and_absolute_outside_paths(self):
        self.asset("one/duplicate.png")
        self.asset("two/duplicate.png", self.png + b"different")
        outside = self.root / "private.png"
        outside.write_bytes(self.png + b"PRIVATE")
        text = ("![[duplicate.png]]\n![[missing.pdf]]\n"
                "![traversal](../../private.png)\n"
                "![encoded](%2E%2E/%2E%2E/private.png)\n"
                f"![absolute](<{outside.as_posix()}>)\n"
                "![unsupported](secret.txt)\n")
        key = self.source("notes/source.md", text)
        self.snapshot()
        report = export_assets(self.vault, self.output)
        attachments = self.sidecar(key)["attachments"]
        self.assertEqual(attachments[0]["status"], "ambiguous")
        self.assertEqual(attachments[0]["candidate_count"], 2)
        self.assertEqual(attachments[1]["reason"], "file_not_found")
        self.assertEqual([a["reason"] for a in attachments[2:5]], ["outside_vault"] * 3)
        self.assertEqual(attachments[5]["reason"], "unsupported_file_type")
        self.assertEqual(report["attachment_summary"]["files"], 0)
        self.assertEqual(len(report["unresolved"]), 6)
        self.assertFalse((self.output / "media").exists())

    def test_retains_each_version_and_supports_explicit_source_map(self):
        self.asset("renamed/one.png")
        self.asset("renamed/two.pdf", self.pdf)
        first = self.source("original.md", "![one](one.png)\n", source_relative="renamed/actual.md")
        second = self.source("original.md", "![[two.pdf]]\n", source_relative="renamed/actual.md")
        self.snapshot()
        export_assets(self.vault, self.output, {first[0]: "renamed/actual.md"})
        self.assertEqual(self.sidecar(first)["source_version"], first[1])
        self.assertEqual(self.sidecar(second)["source_version"], second[1])
        self.assertEqual(self.sidecar(first)["attachments"][0]["status"], "available")
        self.assertEqual(self.sidecar(second)["attachments"][0]["status"], "available")

    def test_rejects_changed_snapshot_before_writes(self):
        self.asset("photo.png")
        self.source("source.md", "![[photo.png]]\n")
        self.snapshot()
        (self.output / "chunks.json").write_text("[]", encoding="utf-8")
        before = self.all_bytes()
        with self.assertRaisesRegex(ValueError, "Snapshot manifest mismatch"):
            export_assets(self.vault, self.output)
        self.assertEqual(self.all_bytes(), before)

    def test_refuses_symlink_even_when_lexically_inside_vault(self):
        outside = self.root / "private"
        outside.mkdir()
        (outside / "secret.png").write_bytes(self.png)
        link = self.vault / "escape"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest("Host cannot create symlinks: " + str(exc))
        key = self.source("source.md", "![outside](escape/secret.png)\n")
        self.snapshot()
        export_assets(self.vault, self.output)
        attachment = self.sidecar(key)["attachments"][0]
        self.assertEqual(attachment["status"], "missing")
        self.assertEqual(attachment["reason"], "symlink_or_reparse")
        self.assertIsNone(attachment["path"])
        with self.assertRaisesRegex(ValueError, "symlink_or_reparse"):
            safe_path(self.vault, link / ".." / "source.md")

    def test_reparse_components_rejected_without_windows_privileges(self):
        self.asset("junction/secret.png")
        original_lstat = Path.lstat

        def lstat(path, *args, **kwargs):
            value = original_lstat(path, *args, **kwargs)
            if path == self.vault / "junction":
                class ReparseInfo:
                    st_mode = value.st_mode
                    st_file_attributes = 0x400
                return ReparseInfo()
            return value

        with patch.object(Path, "lstat", lstat):
            with self.assertRaisesRegex(ValueError, "symlink_or_reparse"):
                safe_path(self.vault, self.vault / "junction" / "secret.png")

    def test_parser_escaped_parentheses_pdf_alias_and_multiple_per_line(self):
        references = extract_references(
            r"![a](image\(2\).png) [[论文.pdf#page=1|描述]] ![b](<space (2).png>)" + "\n")
        self.assertEqual(len(references), 3)
        self.assertEqual([r["line_start"] for r in references], [1, 1, 1])
        self.assertEqual(references[1]["target"], "论文.pdf#page=1")

    def test_linked_image_parenthesized_title_and_url_encoded_filename(self):
        self.asset("name#one.png")
        self.asset("title (one).png", self.png + b"two")
        key = self.source("source.md", (
            "[![linked](name%23one.png)](https://example.test/article)\n"
            "![title](title (one).png (Optional title))\n"))
        self.snapshot()
        export_assets(self.vault, self.output)
        attachments = self.sidecar(key)["attachments"]
        self.assertEqual(len(attachments), 2)
        self.assertEqual([a["status"] for a in attachments], ["available", "available"])
        self.assertEqual(attachments[0]["reference"], "![linked](name%23one.png)")
        self.assertEqual(attachments[1]["target"], "title (one).png")


if __name__ == "__main__":
    unittest.main()
