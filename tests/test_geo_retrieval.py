"""Verified document-first search regressions, without a copied corpus."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import geo_snapshot as gs
from geo_retrieval import document_routes, title_in_question


class DocumentRetrievalTests(unittest.TestCase):
    def fixture(self, documents, extra=None):
        catalog = {"schema_version": 1, "knowledge_version": "fixture", "documents": {},
                   "tokenizer": {"stop_words": [], "expansions": {}}, "search": {"shards": []}}
        assets, keys = {}, []
        for number, (text, supplied) in enumerate(documents):
            key = "doc-" + f"{number:020x}"
            version = hashlib.sha256(text.encode()).hexdigest()
            meta = {"work_id": key, "published_at": "2024-01-01", **supplied}
            catalog["documents"][key] = {**meta, "document_id": key, "current_version": version,
                                          "versions": {version: len(text.splitlines())}, "line_count": len(text.splitlines())}
            assets[f"documents/{key}/{version}.json"] = {"document_id": key, "source_version": version,
                                                        "metadata": meta, "text": text, "line_count": len(text.splitlines())}
            keys.append((key, version))
        if extra:
            extra(catalog, assets, keys)
        assets["catalog.json"] = catalog
        raw = {name: value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode() for name, value in assets.items()}
        manifest = {"files": {name: {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()} for name, value in raw.items()}}
        raw["manifest.json"] = json.dumps(manifest).encode()
        pin = patch.object(gs, "MANIFEST_SHA256", hashlib.sha256(raw["manifest.json"]).hexdigest())
        pin.start()
        self.addCleanup(pin.stop)
        client = gs.SnapshotClient()
        client._load_cached = lambda *args: None
        client._save_cached = lambda *args: None
        client._fetch_bytes = lambda name: raw[name]
        return client, keys, raw

    def test_author_fragment_is_stronger_than_an_unrelated_exact_topic_title(self):
        source = "# Acme glossary\n## Query fan-out\nA prompt is expanded into several searches.\n## Citation share\nA proportion with an explicit denominator."
        client, keys, _ = self.fixture([
            (source, {"title": "A terminology collection", "author": "Avery Smith, Acme University editor"}),
            ("# Query fan-out 查询扇出\nA different publisher's definition.", {"title": "Query fan-out 查询扇出", "author": "Other publisher"}),
            ("# Citations\nAn API field list.", {"title": "API citation fields", "title_aliases": ["Citations"], "author": "Other publisher"}),
        ])
        for question, expected in [("Acme Query fan-out 查询扇出 定义", "expanded into several searches"),
                                   ("Acme glossary citation share", "explicit denominator")]:
            with self.subTest(question=question):
                result = client.search({"question": question})
                self.assertTrue(result["citations"])
                self.assertEqual(result["citations"][0]["document_id"], keys[0][0])
                self.assertIn(expected, result["citations"][0]["excerpt"])
                self.assertTrue(all(match["document_id"] == keys[0][0] for match in result["document_matches"]))
        self.assertFalse(title_in_question("Citations", "Acme glossary citation share"))
        self.assertTrue(title_in_question("GEO: Generative Engine Optimization", "请解释 GEO：Generative Engine Optimization"))

    def test_bilingual_document_locator_words_do_not_crowd_out_deep_terms_after_fusion(self):
        from geo_pipeline import WorkflowEngine
        title = "Acme AI 搜索术语词典｜完整中文译文与英文原文"
        intro = f"# {title}\n- 原标题：The AI Search Glossary: A definition of 300+ terms\n- 作者：Avery，Acme University 内容负责人\n本版包含术语、中文全文与英文原文。\n"
        targets = [("Grounding", "依据锚定", "Answers are tied to specific retrieved sources."),
                   ("Query fan-out", "查询扇出", "One prompt is expanded into several background searches."),
                   ("Citation share", "引用份额", "Count citations against an explicitly stated denominator."),
                   ("Hallucination", "幻觉", "A fluent answer can still contain a false assertion.")]
        text = intro + "\n".join(f"## Term {i}\nAn unrelated concept number {i}." for i in range(90))
        for term, chinese, meaning in targets:
            text += f"\n## {chinese}（{term}）\n{meaning}\n"
        text += "\n## 关于本词典／About this glossary\n这份 AI 搜索术语词典收录很多定义。This glossary explains the definition of each term.\n"
        guide = intro.replace(title, "Acme AI 搜索术语词典｜中文导读与原文入口") + "请打开完整译文。这里介绍这份搜索术语词典。\n"
        client, keys, _ = self.fixture([(text, {"title": title, "author": "Avery, Acme University editor", "work_id": "shared-glossary"}),
                                       (guide, {"title": "Acme AI 搜索术语词典｜中文导读与原文入口", "author": "Avery, Acme University editor", "work_id": "shared-glossary"})])
        worker = WorkflowEngine(lambda query, limit=20, **scope: client.search({"question": query, "limit": limit, **scope}),
                                lambda did, ver, a, b: client.read({"document_id": did, "source_version": ver, "start_line": a, "end_line": b}))
        for term, chinese, meaning in targets:
            question = f"我收藏的 Acme AI 搜索术语词典里怎么解释 {term} {chinese}？"
            queries = [f"Acme {term} AI 搜索术语 词典 {chinese}", f"Acme glossary {term} definition"]
            with self.subTest(term=term):
                result = worker.prepare(question, analysis={"resolved_question": question, "queries": queries}, allow_web=False)
                self.assertTrue(any(ref["document_id"] == keys[0][0] and meaning in ref["excerpt"] for ref in result["candidates"]))

    def test_decorated_author_handle_and_month_heading_recover_complete_instructions(self):
        source = "# 季度路线图\n## 10 月：抓取\n检查爬虫和索引。\n## 11 月：竞品对比页面\n在开头放一张比较表，包含：\n- 价格\n- 功能\n- 适用范围\n## 12 月：复查\n回读来源。"
        client, keys, _ = self.fixture([
            (source, {"title": "季度路线图", "author": "mira（@miralabs）"}),
            ("# 11月竞争对手对比页面表格\nSome unrelated advice.", {"title": "11月竞争对手对比页面表格", "author": "Another writer"}),
        ])
        result = client.search({"question": "Mira 季度路线图 11月 竞品对比 页面 表格"})
        ref = result["citations"][0]
        self.assertEqual(ref["document_id"], keys[0][0])
        self.assertIn("在开头放一张比较表，包含：\n- 价格\n- 功能\n- 适用范围", ref["excerpt"])
        self.assertEqual(ref["excerpt"], "\n".join(source.splitlines()[ref["line_start"] - 1:ref["line_end"]]))

    def test_source_hostname_routes_docs_even_when_title_omits_source_brand(self):
        client, keys, _ = self.fixture([
            ("# Methods\n## Ranking and citations\nThese are different measurements.",
             {"title": "Measurement methods", "original_url": "https://catalog.example/glossary/measurements"}),
            ("# Catalog news\nAn unrelated product launch.", {"title": "Catalog product news"}),
        ])
        result = client.search({"question": "Catalog ranking citations measurements"})
        self.assertEqual(result["citations"][0]["document_id"], keys[0][0])

    def test_author_and_topic_route_deep_definition_instead_of_title_or_directory(self):
        text = "# Atlas AI 术语词典\n\n## 目录\n- [[#grounding]]\n" + "\n".join(
            f"## Term {i}\nA completely different concept {i}." for i in range(80)) + "\n## Grounding\nAn answer tied to retrieved sources, with citations.\n"
        client, keys, _ = self.fixture([(text, {"title": "Atlas AI 术语词典", "author": "Atlas"}),
                                       ("# Another definition\nGrounding means an unrelated topic.", {"title": "Grounding notes", "author": "Another author"})])
        result = client.search({"question": "Atlas 词典里的 grounding 是什么意思？"})
        first = result["citations"][0]
        self.assertEqual(first["document_id"], keys[0][0])
        self.assertIn("An answer tied to retrieved sources", first["excerpt"])
        self.assertGreater(first["line_start"], 150)
        self.assertEqual(first["excerpt"], "\n".join(text.splitlines()[first["line_start"] - 1:first["line_end"]]))
        self.assertEqual(first["context_read"]["source_version"], keys[0][1])
        self.assertFalse(result["retrieval_scope"]["whole_corpus_reviewed"])

    def test_exact_title_url_and_work_route_body_over_navigation(self):
        client, keys, _ = self.fixture([
            ("# Foundational Engine Paper\nSee the full text.", {"title": "Foundational Engine Paper", "work_id": "paper-71", "retrieval_role": "navigation", "original_url": "https://example.com/paper"}),
            ("# 完整论文\n## Abstract\nOur model measures answer visibility.", {"title": "完整论文", "work_id": "paper-71"}),
        ])
        for query in ("Foundational Engine Paper", "https://example.com/paper", "paper-71里讲什么"):
            with self.subTest(query=query):
                found = client.search({"question": query})
                self.assertTrue(found["citations"])
                self.assertTrue(all(ref["document_id"] == keys[1][0] for ref in found["citations"]))
        scoped = client.search({"question": keys[0][0]})
        self.assertEqual(scoped["citations"], [])
        self.assertEqual(scoped["background_citations"][0]["allowed_uses"], ["navigation"])
        ref = scoped["background_citations"][0]
        check = client.check({"bundle": {"claims": [{"text": "See the full text.", "kind": "author_report",
                     "allowed_use": "attributed_report", "exact_quote": "See the full text.", "conditions": ["Historical attribution"],
                     "citation_ids": [ref["citation_id"]]}]}})
        self.assertEqual(check["status"], "blocked")
        self.assertTrue(any("导航" in error for error in check["results"][0]["errors"]))

    def test_scope_is_exact_paginated_and_does_not_substitute_a_version(self):
        text = "\n".join(f"## Section {i}\nGrounding condition {i} and its limitation." for i in range(7))
        client, keys, _ = self.fixture([(text, {"title": "A collection"})])
        did, version = keys[0]
        args = {"question": "grounding", "document_id": did, "source_version": version, "limit": 2}
        first = client.call("search_geo", args)
        second = client.call("search_geo", {**args, "offset": first["next_offset"]})
        self.assertEqual(first["next_offset"], 2)
        self.assertFalse({x["citation_id"] for x in first["citations"]} & {x["citation_id"] for x in second["citations"]})
        bounded = client.call("search_geo", {**args, "start_line": 7, "end_line": 10})
        self.assertTrue(all(7 <= ref["line_start"] <= ref["line_end"] <= 10 for ref in bounded["citations"]))
        self.assertEqual(client.call("search_geo", {**args, "source_version": "0" * 64})["status"], "not_found")
        self.assertEqual(client.call("search_geo", {"question": "grounding", "document_id": did})["status"], "error")
        self.assertEqual(client.call("search_geo", {"question": "grounding", "offset": 2})["status"], "error")
        self.assertEqual(client.call("search_geo", {**args, "start_line": 100})["status"], "error")

    def test_scoped_search_retains_hash_failure(self):
        client, keys, raw = self.fixture([("# Grounding\nA definition.", {"title": "Dictionary"})])
        did, version = keys[0]
        raw[f"documents/{did}/{version}.json"] += b" "
        with self.assertRaises(gs.SnapshotError):
            client.search({"question": "grounding", "document_id": did, "source_version": version})

    def test_historical_scope_reads_requested_version_with_its_own_dates(self):
        old_text = "# Grounding\nHistorical definition from the earlier version."
        old_version = hashlib.sha256(old_text.encode()).hexdigest()
        def extra(catalog, assets, keys):
            did, _ = keys[0]
            catalog["documents"][did]["versions"][old_version] = 2
            assets[f"documents/{did}/{old_version}.json"] = {"document_id": did, "source_version": old_version,
                    "metadata": {"title": "Dictionary", "published_at": "2020-01-01"}, "text": old_text, "line_count": 2}
        client, keys, _ = self.fixture([("# Grounding\nNew definition.", {"title": "Dictionary", "published_at": "2026-01-01"})], extra)
        result = client.search({"question": "grounding", "document_id": keys[0][0], "source_version": old_version, "as_of": "2021-01-01"})
        self.assertEqual(result["citations"][0]["source_version"], old_version)
        self.assertIn("Historical definition", result["citations"][0]["excerpt"])
        self.assertEqual(result["citations"][0]["published_at"], "2020-01-01")

    def test_attachment_mapping_is_verified_and_media_is_not_downloaded(self):
        media = b"a small fixture image"
        digest = hashlib.sha256(media).hexdigest()
        path = "media/" + digest + ".png"
        def extra(catalog, assets, keys):
            did, version = keys[0]
            catalog["attachment_path_template"] = "/data/attachments/{document_id}/{source_version}.json"
            assets[path] = media
            assets[f"attachments/{did}/{version}.json"] = {"document_id": did, "source_version": version,
                "attachments": [{"reference": "![diagram](local.png)", "line_start": 3, "kind": "image", "mime": "image/png",
                                 "path": path, "sha256": digest, "bytes": len(media), "status": "available"}]}
        client, keys, raw = self.fixture([("# Method\nText explaining method.\n![diagram](local.png)", {"title": "Method"})], extra)
        fetched = []
        client._fetch_bytes = lambda name: (fetched.append(name) or raw[name])
        did, version = keys[0]
        read = client.read({"document_id": did, "source_version": version})
        item = read["attachments"][0]
        self.assertEqual(item["url"], gs.RAW_BASE + path)
        self.assertTrue(item["manifest_verified"])
        self.assertFalse(item["binary_downloaded"])
        self.assertNotIn(path, fetched)
        self.assertEqual(client.read({"document_id": did, "source_version": version, "end_line": 2})["attachments"], [])
        # The map is integrity checked, then checked against the binary entry.
        client._manifest["files"][path]["sha256"] = "0" * 64
        with self.assertRaises(gs.SnapshotError):
            client.read({"document_id": did, "source_version": version})


if __name__ == "__main__":
    unittest.main()
