"""Meaningful behavioral tests using temporary source vaults only."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys
import sqlite3
from contextlib import closing

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "geo_kb.py"
sys.path.insert(0, str(MODULE.parent))
spec = importlib.util.spec_from_file_location("geo_kb", MODULE)
geo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(geo)


class GeoKBTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.text = ("# 引用信源分类\n\n- 发布时间：2025-01-02\n- 原文链接：https://example.org/source?x=1\n\n"
                     "## 作者分类\n作者将信源分为自己的、竞争对手的和其他来源。\n这是作者的经验，样本限于英文软件问题。\n\n"
                     "## 实验条件\n引用实验仅在英文软件问题开展，不代表所有行业。\n")
        (self.vault / "source.md").write_text(self.text, encoding="utf-8")
        self.curated = {"schema_version": 1, "reviewed_on": "2026-11-04", "sources": [
            {"source_key": "source", "relative_path": "source.md", "title": "信源", "limitations": ["未独立验证"]}],
            "claims": [{"claim_id": "claim-1", "source_key": "source", "statement": "作者分类", "exact_quote": "作者将信源分为自己的、竞争对手的和其他来源。",
                        "allowed_use": "attributed_report", "verification_scope": ["exact_excerpt_checked"], "conditions": ["限作者报告"], "topic": "source_categories"}],
            "answers": [{"id": "source-categories", "intent": "source_categories", "questions": ["海外信源怎么分"], "title": "信源分类",
                         "answer_markdown": "作者分为三类。[claim:claim-1]", "claim_ids": ["claim-1"], "conditions": ["限作者报告"], "not_supported": ["不能确定哪个渠道最好"]}],
            "catalogs": {}}
        self._write_curated()
        self.kb = geo.GeoKB(self.root / "runtime" / "kb.sqlite3", self.assets)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_curated(self):
        (self.assets / "curated.json").write_text(json.dumps(self.curated, ensure_ascii=False), encoding="utf-8")

    def test_missing_database_does_not_create_file(self):
        self.assertEqual(self.kb.search("信源")["status"], "unavailable")
        self.assertFalse(self.kb.db_path.exists())

    def test_index_is_derived_and_source_not_modified(self):
        original = (self.vault / "source.md").read_bytes()
        report = self.kb.build(self.vault)
        self.assertEqual(report["indexed"], 1)
        self.assertEqual(report["claims_valid"], 1)
        self.assertEqual(original, (self.vault / "source.md").read_bytes())
        again = self.kb.build(self.vault)
        self.assertEqual(again["new_versions"], 0)
        self.assertEqual(again["knowledge_version"], report["knowledge_version"])
        self.assertEqual(self.kb.browse()["source_versions"], 1)

    def test_cjk_search_and_original_locator(self):
        self.kb.build(self.vault)
        result = self.kb.search("信源怎么分类")
        cite = result["citations"][0]
        self.assertIn("source_version", cite)
        self.assertIn("attributed_report", cite["allowed_uses"])
        read = self.kb.read_source(cite["document_id"], cite["source_version"], cite["line_start"], cite["line_end"])
        self.assertEqual(read["excerpt"], cite["excerpt"])
        self.assertEqual(cite["original_url"], "https://example.org/source?x=1")

    def test_immutable_previous_version_after_update(self):
        self.kb.build(self.vault)
        cite = self.kb.search("信源")["citations"][0]
        (self.vault / "source.md").write_text(self.text + "\n新版本补充内容。\n", encoding="utf-8")
        self.kb.build(self.vault)
        old = self.kb.read_source(cite["document_id"], cite["source_version"], 1, len(self.text.splitlines()))
        self.assertTrue(old["is_historical_snapshot"])
        self.assertNotIn("新版本", old["excerpt"])
        self.assertEqual(self.kb.browse()["source_versions"], 2)

    def test_failed_quote_cannot_keep_old_review(self):
        self.kb.build(self.vault)
        self.curated["claims"][0]["exact_quote"] = "不存在的原文"
        self._write_curated()
        report = self.kb.build(self.vault)
        self.assertEqual(len(report["claims_invalid"]), 1)
        citation = self.kb.search("信源")["citations"][0]
        self.assertEqual(citation["allowed_uses"], ["reading_lead"])
        answer = self.kb.ask("海外信源怎么分")
        self.assertEqual(answer["answer_kind"], "evidence_packet")

    def test_review_scope_does_not_follow_changed_context(self):
        self.curated["sources"][0]["source_hash"] = geo._hash(self.text)
        self._write_curated()
        self.kb.build(self.vault)
        old = self.kb.search("信源")["citations"][0]
        (self.vault / "source.md").write_text(self.text + "\n作者后来撤回该建议。\n", encoding="utf-8")
        changed = self.kb.build(self.vault)
        self.assertEqual(changed["claims_valid"], 0)
        self.assertEqual(changed["claims_invalid"][0]["reason"], "source_version_changed_requires_review")
        current = self.kb.search("信源")["citations"][0]
        self.assertEqual(current["allowed_uses"], ["reading_lead"])
        previous = self.kb.read_source(old["document_id"], old["source_version"], old["line_start"], old["line_end"])
        self.assertIn("attributed_report", previous["allowed_uses"])

    def test_curated_answer_is_grounded_but_not_general_generation(self):
        self.kb.build(self.vault)
        answer = self.kb.ask("海外信源怎么分")
        self.assertEqual(answer["answer_kind"], "curated_answer")
        self.assertEqual(answer["status"], "partial")
        self.assertNotIn("[claim:", answer["answer_markdown"])
        self.assertFalse(answer["generation_policy"]["server_freeform_generation"])
        other = self.kb.ask("信源应该优先投什么才赚最多钱")
        self.assertEqual(other["answer_kind"], "evidence_packet")

    def test_time_constraints_exclude_future_and_unknown(self):
        (self.vault / "unknown.md").write_text("# 信源\n信源来源，没有发布时间。", encoding="utf-8")
        self.kb.build(self.vault)
        before = self.kb.search("信源", as_of="2024-12-01")
        self.assertEqual(before["citations"], [])
        after = self.kb.search("信源", as_of="2025-02-01")
        self.assertEqual(len(after["citations"]), 1)
        with self.assertRaises(ValueError):
            self.kb.search("信源", as_of="today")

    def test_followup_needs_resolvable_reference(self):
        self.kb.build(self.vault)
        self.assertEqual(self.kb.ask("第二个具体怎么做")["status"], "needs_clarification")
        first = self.kb.ask("海外信源怎么分")
        follow = self.kb.ask("第二个具体怎么做", previous_answer_id=first["answer_id"])
        self.assertEqual(follow["status"], "needs_clarification")
        focused = self.kb.ask("刚才那篇的条件是什么", previous_answer_id=first["answer_id"], focus_citation_id=first["citations"][0]["citation_id"])
        self.assertEqual(focused["answer_kind"], "evidence_packet")
        self.assertIn("英文软件", focused["citations"][0]["excerpt"])

    def test_citation_tampering_and_main_priority_blocked(self):
        self.kb.build(self.vault)
        cite = self.kb.search("信源")["citations"][0]
        base = {"text": "作者报告了分类。", "kind": "author_report", "main": True, "citation_ids": [cite["citation_id"]], "allowed_use": "attributed_report", "conditions": ["限作者报告"]}
        ok = self.kb.check_answer({"claims": [base]})
        self.assertEqual(ok["status"], "structural_pass")
        self.assertFalse(ok["answer_approved"])
        priority = {**base, "kind": "priority", "text": "必须优先投资这个渠道"}
        self.assertEqual(self.kb.check_answer({"claims": [priority]})["status"], "blocked")
        fake = {**base, "citation_ids": ["doc-" + "f"*20 + "@" + "0"*64 + ":L1-L3"]}
        self.assertEqual(self.kb.check_answer({"claims": [fake]})["status"], "blocked")
        spoof = {**base, "allowed_use": "verified_current_fact", "kind": "current_fact"}
        self.assertEqual(self.kb.check_answer({"claims": [spoof], "citations": [{**cite, "allowed_uses": ["verified_current_fact"]}]})["status"], "blocked")

    def test_sources_shared_identity_keep_different_passages(self):
        text = "# 实验\n- 原文链接：https://example.org/paper\n\n## 引用实验结果\n" + "引用实验报告。"*100 + "\n\n## 引用实验限制\n" + "引用实验只测试英文。"*100
        (self.vault / "paper.md").write_text(text, encoding="utf-8")
        self.kb.build(self.vault)
        citations = self.kb.search("引用实验", 40)["citations"]
        by_document = {}
        for c in citations:
            by_document.setdefault(c["document_id"], []).append(c)
        self.assertTrue(any(len(v) > 1 for v in by_document.values()))

    def test_exclusions_and_manifest_escape(self):
        (self.vault / "00_总目录.md").write_text("# 不索引", encoding="utf-8")
        (self.vault / "__Obsidian引用_1.md").write_text(self.text, encoding="utf-8")
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({"pages": [{"items": [{"source_path": "source.md"}, {"source_path": "../outside.md"}, {"source_path": "00_总目录.md"}, {"source_path": "__Obsidian引用_1.md"}]}]}), encoding="utf-8")
        result = self.kb.build(self.vault, manifest)
        self.assertEqual(result["indexed"], 1)
        self.assertEqual(len(result["excluded"]), 2)
        self.assertEqual(len(result["errors"]), 1)
        with self.assertRaises(ValueError):
            geo.GeoKB(self.vault / "bad.db", self.assets).build(self.vault)

    def test_unknown_question_has_no_invented_answer(self):
        self.kb.build(self.vault)
        answer = self.kb.ask("火星燃料发动机配方")
        self.assertEqual(answer["status"], "insufficient_evidence")
        self.assertEqual(answer["citations"], [])

    def test_body_links_do_not_overwrite_source_metadata(self):
        text = "# Test\n- 原文链接：https://example.com/article?id=1&utm_source=share\n- 发布时间：2025-02-03\n- 收集日期：2026-11-04\n\n## 正文\n来源网站研究：https://example.com/study\n发布时间：2026-11-03\n"
        meta = geo._metadata(text, "x.md")
        self.assertEqual(meta["original_url"], "https://example.com/article?id=1")
        self.assertEqual(meta["published_at"], "2025-02-03")
        self.assertNotEqual(geo._canonical_url("https://example.com/article?id=1"), geo._canonical_url("https://example.com/article?id=2"))
        self.assertEqual(geo._canonical_url("https://x.com/test/status/123?s=46"), "https://x.com/test/status/123")
        no_header = geo._metadata("# Test\n我看到来源：https://example.com/unrelated\n## 正文\n原文：https://example.com/other\n", "x.md")
        self.assertIsNone(no_header["original_url"])

    def test_metadata_header_variants_preserve_date_roles(self):
        text = "---\nsource: https://example.org/paper\nsource_version: 2026-10-30\n---\n# 论文\n- **原帖发布时间**：2026 年 10 月 23 日 06:11（北京时间；UTC 为 10 月 22 日 22:11）\n- 更新日期：2026-10-31\n- 采样日期：2026-10-29\n- 收录日期：2026-11-05\n- 作者：[Alice](https://example.org/alice)\n\n## 正文\n发布时间：2027-01-01\n"
        meta = geo._metadata(text, "paper.md")
        self.assertEqual(meta["original_url"], "https://example.org/paper")
        self.assertEqual(meta["published_at"], "2026-10-23")
        self.assertEqual(meta["author"], "Alice")
        self.assertIn("UTC 为 10 月 22 日", meta["metadata_provenance"]["published_at"]["raw"])
        self.assertEqual({x["kind"] for x in meta["source_dates"]}, {"published", "source_version", "updated", "sampled", "collected"})
        self.assertEqual(meta["collected_at"], "2026-11-05")
        for label in ["原帖", "原帖链接", "原论文", "原视频", "原视频链接", "Source"]:
            self.assertEqual(geo._metadata(f"# 标题\n{label}: https://example.org/original\n", "a.md")["original_url"], "https://example.org/original")
        inline = geo._metadata("# 帖子\n**社区：** SEO | **发布时间：** 2026-01-02\n", "a.md")
        self.assertEqual(inline["published_at"], "2026-01-02")
        unknown = geo._metadata("# 论文\n发布时间：2025\nsource_version: 2026-11-01\n收录日期：2026-11-05\n", "a.md")
        self.assertIsNone(unknown["published_at"])
        self.assertEqual(unknown["source_dates"][0]["date_precision"], "year")

    def test_rebuild_repairs_metadata_without_changing_text_version(self):
        self.kb.build(self.vault)
        with closing(sqlite3.connect(self.kb.db_path)) as connection:
            did, version, metadata = connection.execute("SELECT document_id,source_version,meta_json FROM versions").fetchone()
            stale = json.loads(metadata)
            stale["original_url"] = None
            connection.execute("UPDATE versions SET meta_json=?", (json.dumps(stale),))
            connection.commit()
        result = self.kb.build(self.vault)
        self.assertEqual(result["new_versions"], 0)
        read = self.kb.read_source(did, version)
        self.assertEqual(read["original_url"], "https://example.org/source?x=1")

    def test_navigation_record_is_archived_but_not_retrieved(self):
        path = self.vault / "01_检索范围与收录说明.md"
        path.write_text("# 检索与收录说明\n\n独有导航测试词导航测试词。", encoding="utf-8")
        result = self.kb.build(self.vault)
        self.assertEqual(result["indexed"], 2)
        self.assertEqual(self.kb.search("独有导航测试词")["citations"], [])
        with closing(sqlite3.connect(self.kb.db_path)) as connection:
            did, version = connection.execute("SELECT document_id,current_version FROM documents WHERE relative_path=?", (path.name,)).fetchone()
        self.assertEqual(self.kb.read_source(did, version)["allowed_uses"], ["navigation"])
        with self.assertRaisesRegex(ValueError, "导航"):
            self.kb.review_claim(did, version, "导航记录", "独有导航测试词导航测试词。", "attributed_report", [], "已阅读")

    def test_reconcile_discovers_sources_and_reports_uncertain_files(self):
        from reconcile_sources import reconcile, registered_paths
        folder = self.vault / "04_监测效果"
        folder.mkdir()
        (folder / "new.md").write_text("# 新资料\n原帖：https://x.com/user/status/123\n发布时间：2026-11-05\n正文", "utf-8")
        (folder / "unknown.md").write_text("# 待分类\n正文", "utf-8")
        (folder / "._sync.md").write_text("# 同步副本\n原帖：https://x.com/user/status/123", "utf-8")
        (folder / "详细教学样章01.md").write_text("# 旧样章", "utf-8")
        manifest = self.root / "mapping.json"
        original = json.dumps({"pages": [{"items": [{"source_path": "source.md"}]}]})
        manifest.write_text(original, "utf-8")
        derived, report = reconcile(self.vault, manifest)
        self.assertEqual(report["counts"]["added_sources"], 1)
        self.assertEqual(report["counts"]["candidates"], 1)
        self.assertIn("04_监测效果/new.md", registered_paths(derived))
        self.assertEqual(manifest.read_text("utf-8"), original)

    def test_new_source_mapping_uses_directory_names_and_preserves_registered_entries(self):
        from reconcile_sources import infer_new_source_mapping, reconcile
        examples = {
            "04_监测效果/01_引用监测与效果分析/audit.md": {"group": "05", "topic": "可见度审计"},
            "04_监测效果/02_研究与案例/case.md": {"group": "06", "topic": "品牌增长"},
            "05_全流程与基础/01_入门与综合指南/roadmap.md": {"group": "01", "topic": "完整实操流程"},
            "05_全流程与基础/01_入门与综合指南/nine-steps.md": {"group": "01", "topic": "完整实操流程"},
        }
        for relative, expected in examples.items():
            with self.subTest(relative=relative):
                self.assertEqual(infer_new_source_mapping(relative), expected)
                self.assertEqual(infer_new_source_mapping("88_" + relative[3:]), expected)
                path = self.vault / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# 新资料\n原帖：https://example.org/source\n正文", "utf-8")
        self.assertIsNone(infer_new_source_mapping("05_未知目录/new.md"))
        original_page = {"group": "04", "title": "已有分类保持", "items": [{"source_path": "source.md"}]}
        manifest = self.root / "mapping.json"
        manifest.write_text(json.dumps({"pages": [original_page]}), "utf-8")
        derived, report = reconcile(self.vault, manifest)
        self.assertEqual(derived["pages"][0], original_page)
        self.assertEqual(report["counts"]["added_sources"], 4)
        actual = {p["items"][0]["source_path"]: {"group": p["group"], "topic": p["title"]} for p in derived["pages"][1:]}
        self.assertEqual(actual, examples)

    def test_real_historical_alias_and_formula_definition_use_matrix(self):
        production = json.loads((MODULE.parent.parent / "assets" / "curated.json").read_text(encoding="utf-8"))
        history = dict(next(c for c in production["claims"] if c["claim_id"] == "historic-bing"))
        formula = dict(next(c for c in production["claims"] if c["claim_id"] == "metric-citation-formula"))
        for c in (history, formula):
            c["source_key"] = "source"
        (self.vault / "source.md").write_text("# Use matrix regression\n\n" + history["exact_quote"] + "\n\n" + formula["exact_quote"] + "\n", encoding="utf-8")
        self.curated["claims"] = [history, formula]
        self.curated["answers"] = []
        self._write_curated()
        self.kb.build(self.vault)
        cite = self.kb.search("Bing 引用份额")["citations"][0]
        base = {"text": history["statement"], "main": True, "citation_ids": [cite["citation_id"]], "conditions": history["conditions"], "allowed_use": "historical"}
        for kind in ("current_fact", "current_mechanism", "priority", "definition", "author_report"):
            result = self.kb.check_answer({"claims": [{**base, "kind": kind}]})
            self.assertEqual(result["status"], "blocked", kind)
        valid_history = self.kb.check_answer({"claims": [{**base, "kind": "historical_report"}]})
        self.assertEqual(valid_history["status"], "structural_pass")
        definition = {"text": formula["statement"], "main": True, "citation_ids": [cite["citation_id"]], "conditions": formula["conditions"], "allowed_use": "definition", "kind": "definition"}
        self.assertEqual(self.kb.check_answer({"claims": [definition]})["status"], "structural_pass")
        for kind in ("current_fact", "current_mechanism", "priority", "core_number"):
            self.assertEqual(self.kb.check_answer({"claims": [{**definition, "kind": kind}]})["status"], "blocked", kind)

    def test_current_fact_label_without_current_verification_is_blocked(self):
        self.curated["claims"][0]["allowed_use"] = "verified_current_fact"
        self._write_curated()
        self.kb.build(self.vault)
        cite = self.kb.search("信源")["citations"][0]
        claim = {"text": "伪装成现行机制", "kind": "current_fact", "main": True, "citation_ids": [cite["citation_id"]], "allowed_use": "verified_current_fact", "conditions": ["限作者报告"]}
        result = self.kb.check_answer({"claims": [claim]})
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("current_fact_checked" in e for e in result["results"][0]["errors"]))

    def test_session_review_enables_narrow_attribution_and_survives_rebuild(self):
        self.kb.build(self.vault)
        cite = self.kb.search("实验条件")["citations"][0]
        review = self.kb.review_claim(cite["document_id"], cite["source_version"], "作者实验范围为英文软件问题。", "引用实验仅在英文软件问题开展，不代表所有行业。", "attributed_report", ["仅英文软件问题"], "已阅读该版本实验段落，保留语言与行业限制。")
        self.assertEqual(review["status"], "recorded")
        self.assertEqual(review["review_origin"], geo.SESSION_REVIEW_ORIGIN)
        self.assertFalse(review["claim"]["independent_fact_verification"])
        claim = {"text": review["claim"]["statement"], "kind": "author_report", "main": True,
                 "citation_ids": [review["citation"]["citation_id"]], "reviewed_claim_id": review["claim_id"],
                 "allowed_use": "attributed_report", "conditions": review["claim"]["conditions"]}
        check = self.kb.check_answer({"claims": [claim]})
        self.assertEqual(check["status"], "structural_pass")
        self.assertFalse(check["answer_approved"])
        self.kb.build(self.vault)
        self.assertEqual(self.kb.browse()["session_review_count"], 1)
        self.assertEqual(self.kb.check_answer({"claims": [claim]})["status"], "structural_pass")
        self.assertEqual(self.kb.check_answer({"claims": [{**claim, "kind": "priority"}]})["status"], "blocked")

    def test_session_review_rejects_bad_quote_use_and_fake_id(self):
        self.kb.build(self.vault)
        cite = self.kb.search("实验条件")["citations"][0]
        args = [cite["document_id"], cite["source_version"], "作者观点", "不存在的原文", "attributed_report", ["作者观点"], "读过原文"]
        with self.assertRaises(ValueError):
            self.kb.review_claim(*args)
        args[3] = "引用实验仅在英文软件问题开展，不代表所有行业。"
        args[4] = "verified_current_fact"
        with self.assertRaises(ValueError):
            self.kb.review_claim(*args)
        args[4] = "definition"
        args[1] = "0" * 64
        with self.assertRaises(ValueError):
            self.kb.review_claim(*args)
        self.assertEqual(self.kb.browse()["session_review_count"], 0)

    def test_session_review_of_historical_snapshot_stays_on_that_version(self):
        self.kb.build(self.vault)
        cite = self.kb.search("实验条件")["citations"][0]
        (self.vault / "source.md").write_text(self.text + "\n更新：作者更换研究范围。\n", encoding="utf-8")
        self.kb.build(self.vault)
        review = self.kb.review_claim(cite["document_id"], cite["source_version"], "历史实验只涉及英文软件。", "引用实验仅在英文软件问题开展，不代表所有行业。", "historical", ["历史版本实验"], "按用户指定旧版本阅读，不当作当前情况。")
        self.assertEqual(review["citation"]["source_version"], cite["source_version"])
        claim = {"text": review["claim"]["statement"], "kind": "historical_report", "main": True, "citation_ids": [review["citation"]["citation_id"]], "reviewed_claim_id": review["claim_id"], "allowed_use": "historical", "conditions": review["claim"]["conditions"]}
        self.assertEqual(self.kb.check_answer({"claims": [claim]})["status"], "structural_pass")
        self.assertEqual(self.kb.check_answer({"claims": [{**claim, "kind": "current_fact"}]})["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
