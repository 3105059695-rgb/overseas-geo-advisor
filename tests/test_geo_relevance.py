"""Regression cases for platform identity, question intent and evidence role."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from geo_kb import GeoKB
from export_remote import export_database
from geo_relevance import query_intent, passage_relevance, balanced_select, answer_brief
import geo_snapshot as gs


class IntentTests(unittest.TestCase):
    def test_query_aliases_and_source_aspects(self):
        for question in ("Claude 信源偏好 引用哪些来源", "What sources does Anthropic use?", "Claude 的信息从哪里来"):
            intent = query_intent(question)
            self.assertEqual(intent["platforms"], ["Claude"])
            self.assertEqual(intent["kind"], "platform_sources")
        self.assertEqual(query_intent("Grok 与 Claude 的信源是什么")["platforms"], ["Claude", "Grok"])
        self.assertEqual(query_intent("Grok 训练数据来源")["source_aspects"], ["training_data"])
        self.assertEqual(query_intent("Grok 引用域名占比统计")["source_aspects"], ["observed_preferences"])
        self.assertEqual(query_intent("Claude SEO 写作步骤")["kind"], "general")
        self.assertEqual(query_intent("Claude web search API pricing")["kind"], "general")
        self.assertEqual(query_intent("怎么让 Claude 引用我的网站")["kind"], "general")
        self.assertEqual(query_intent("claudette 和 grokked 的来源")["platforms"], [])

    def test_beginner_preferences_and_chinese_alias(self):
        for question, platforms in [("Claude 喜欢什么网站？", ["Claude"]),
                                     ("Grok 更喜欢 Reddit 还是官网？", ["Grok"]),
                                     ("Does Claude prefer Reddit or Wikipedia?", ["Claude"]),
                                     ("克劳德喜欢什么网站？", ["Claude"])]:
            with self.subTest(question=question):
                intent = query_intent(question)
                self.assertEqual(intent["kind"], "platform_sources")
                self.assertEqual(intent["platforms"], platforms)
                self.assertEqual(intent["source_aspects"], ["content_sources", "observed_preferences"])
        training = query_intent("Claude 训练数据来源")
        shares = query_intent("Grok 引用域名占比统计")
        self.assertIn("训练数据", answer_brief("Claude 训练数据来源", training, [])["focus"])
        self.assertIn("分母", answer_brief("Grok 引用域名占比统计", shares, [])["focus"])

    def test_mentions_and_requests_are_not_source_evidence(self):
        intent = query_intent("Claude 和 Grok 的信源是什么")
        cases = [
            ("国内官媒权威信源", "豆包与元宝的来源包括官媒。"),
            ("Grok Bot SEO", "Use Grok Bot to write SEO articles and cite sources."),
            ("建议Grok开放搜索引擎", "I think Grok could be a great search engine. Open Grok Search."),
            ("Claude SEO workflow", "把引用来源粘贴到 Claude 中，让它整理网站列表。"),
            ("Claude Web Search", "# Claude Web Search\n- source: Claude web search\n收费按请求次数计算。"),
            ("词典目录", "- [[#什么是 Claude-SearchBot]]\n- [Claude web search](https://example.com)"),
            ("编号目录", "- [[#123. Claude-SearchBot|Claude-SearchBot]]\n## 123. Claude-SearchBot"),
            ("Claude 研究", "Claude 和 Grok 的引用重合率如何？\n这份调查没有回答。"),
        ]
        for title, text in cases:
            with self.subTest(title=title):
                self.assertEqual(passage_relevance(intent, title, text)["tier"], "background")

    def test_per_platform_support_and_separate_sentences(self):
        intent = query_intent("Claude 和 Grok 的信源是什么")
        ref = passage_relevance(intent, "来源", "Claude searches the web and includes citations to original sources.\nGrok costs five dollars.")
        self.assertEqual(ref["matched_platforms"], ["Claude", "Grok"])
        self.assertEqual(ref["direct_platforms"], ["Claude"])
        grok = passage_relevance(intent, "来源", "Grok searches public web pages and X posts.")
        self.assertEqual(grok["direct_platforms"], ["Grok"])
        self.assertEqual(grok["semantic_validation"], "not_performed")

    def test_balancing_does_not_lose_less_frequent_platform(self):
        candidates = [{"id": i, "relevance": {"direct_platforms": ["Claude"]}} for i in range(5)]
        candidates.append({"id": 9, "relevance": {"direct_platforms": ["Grok"]}})
        self.assertEqual([x["id"] for x in balanced_select(candidates, ["Claude", "Grok"], 2)], [0, 9])

    def test_overseas_comparison_is_a_disclosed_scope_not_a_market_list(self):
        intent = query_intent("海外的不同 AI，他们喜欢的信源是什么？")
        self.assertEqual(intent["kind"], "platform_sources")
        self.assertEqual(intent["platform_selection"], "illustrative_overseas_scope")
        self.assertEqual(intent["platforms"], ["ChatGPT", "Claude", "Grok", "Perplexity", "Gemini", "Copilot"])
        self.assertIn("不是全部", answer_brief("海外的不同 AI，他们喜欢的信源是什么？", intent, [])["scope_note"])
        self.assertEqual(query_intent("海外信源怎么分？")["kind"], "general")
        self.assertEqual(query_intent("海外 AI 信源有哪些类别？")["kind"], "general")
        self.assertEqual(query_intent("海外不同 AI 中 Claude 喜欢什么信源？")["platforms"], ["Claude"])


class RetrievalRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        vault = self.root / "vault"
        vault.mkdir()
        texts = {
            "claude": "# Claude 联网搜索\n发布时间：2025-01-01\n原文：https://example.com/claude\n\nClaude searches the web and includes citations to original sources in its answers.\n",
            "grok": "# Grok 信源\n发布时间：2025-02-01\n原文：https://example.com/grok\n\nGrok searches public web pages and X posts.\n",
            "domestic": "# 信源引用来源信源引用来源\n发布时间：2025-01-01\n\n豆包和元宝的权威信源引用来源是国内官媒。\n",
            "opinion": "# 建议Grok开放搜索引擎\n发布时间：2025-01-01\n\nI think Grok could be a great Search Engine. Open Grok Search and let us find results.\n",
            "operator": "# Claude 和 Grok Bot SEO\n发布时间：2025-01-01\n\n把来源和引用粘贴到 Claude 中，让它整理。Use Grok Bot to write SEO posts.\n",
        }
        for name, text in texts.items():
            (vault / (name + ".md")).write_text(text, encoding="utf-8")
        db = self.root / "index.sqlite3"
        GeoKB(db).build(vault)
        self.data = self.root / "data"
        export_database(db, self.data)
        self.manifest_patch = patch.object(gs, "MANIFEST_SHA256", hashlib.sha256((self.data / "manifest.json").read_bytes()).hexdigest())
        self.manifest_patch.start()
        self.client = gs.SnapshotClient(cache_dir=self.root / "cache")
        self.client._fetch_bytes = lambda name: (self.data / name).read_bytes()

    def tearDown(self):
        self.manifest_patch.stop()
        self.temp.cleanup()

    def test_actual_question_gets_both_platforms_not_domestic_sources(self):
        found = self.client.call("ask_geo", {"question": "我想知道 Claude 或者 Grok 他们的信源到底是什么"})
        self.assertEqual({c["title"] for c in found["citations"]}, {"Claude 联网搜索", "Grok 信源"})
        self.assertTrue(all(c["direct_candidates"] == 1 for c in found["platform_coverage"]))
        self.assertEqual(found["answer_brief"]["missing_direct_evidence"], [])
        self.assertFalse(found["retrieval_scope"]["whole_corpus_reviewed"])
        self.assertTrue(all(c["relevance"]["tier"] == "background" for c in found["background_citations"]))

    def test_old_context_cannot_replace_current_engine(self):
        found = self.client.call("ask_geo", {"question": "Claude 信源偏好 引用哪些来源", "context": {"question": "豆包国内官媒信源"}})
        self.assertEqual(found["query_intent"]["platforms"], ["Claude"])
        self.assertEqual([c["title"] for c in found["citations"]], ["Claude 联网搜索"])

    def test_original_overseas_question_and_chinese_alias_keep_english_evidence(self):
        found = self.client.call("ask_geo", {"question": "海外的不同 AI，他们喜欢的信源是什么？"})
        self.assertEqual({c["title"] for c in found["citations"]}, {"Claude 联网搜索", "Grok 信源"})
        self.assertNotIn("信源引用来源信源引用来源", [c["title"] for c in found["citations"]])
        self.assertEqual(found["query_intent"]["platform_selection"], "illustrative_overseas_scope")
        aliased = self.client.call("search_geo", {"question": "克劳德的信源是什么？"})
        self.assertEqual([c["title"] for c in aliased["citations"]], ["Claude 联网搜索"])

    def test_date_filter_can_leave_only_background_and_reports_gap(self):
        found = self.client.call("ask_geo", {"question": "Grok 信源是什么", "as_of": "2025-01-15"})
        self.assertEqual(found["status"], "insufficient_evidence")
        self.assertEqual(found["citations"], [])
        self.assertEqual(found["answer_brief"]["missing_direct_evidence"], ["Grok"])
        self.assertEqual(found["platform_coverage"][0]["status"], "background_only")

    def test_read_beyond_eof_clamps_but_invalid_start_and_version_do_not(self):
        ref = self.client.call("search_geo", {"question": "Claude 信源"})["citations"][0]
        args = {"document_id": ref["document_id"], "source_version": ref["source_version"], "end_line": 500}
        read = self.client.call("read_geo_source", args)
        self.assertEqual(read["status"], "ok")
        self.assertEqual(read["line_end"], read["line_count"])
        self.assertIsNone(read["next_start_line"])
        self.assertFalse(read["truncated"])
        self.assertEqual(self.client.call("read_geo_source", {**args, "start_line": 500})["status"], "error")
        self.assertEqual(self.client.call("read_geo_source", {**args, "source_version": "0" * 64})["status"], "not_found")


if __name__ == "__main__":
    unittest.main()
