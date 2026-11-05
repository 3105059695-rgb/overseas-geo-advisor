"""No-model workflow regressions using immutable source and host-judgment fixtures."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from geo_pipeline import WorkflowEngine, adjudicate, candidate_id, digest, plan_question, postcheck, time_profile

TODAY = "2026-11-05"
STUDY = "In our 2024 study, ChatGPT cited Reddit in 28% of 100 English travel responses."
CHANNEL = "ChatGPT searches public web pages and includes citations to original sources."
CONDITIONS = {"observed_period": "2024-05", "product_mode": "ChatGPT consumer search", "model": "not disclosed",
              "industry": "travel", "sample": "100 English responses", "denominator": "all 100 responses",
              "scope": "作者的英语旅行问题样本，不能外推全部用户"}
HOST_REVIEW = {"answers_question": True, "all_factual_claims_mapped": True, "dates_and_scopes_preserved": True,
               "conflicts_not_merged": True, "beginner_readable": True, "no_source_instructions_followed": True,
               "reason": "逐条核对原文、来源、时间和适用范围，保留缺失信息。"}


def source(number=1, text=STUDY, **changes):
    ref = {"document_id": "doc-" + f"{number:020x}", "source_version": hashlib.sha256(text.encode()).hexdigest(),
           "work_id": f"work-{number}", "line_start": 1, "line_end": len(text.splitlines()), "excerpt": text,
           "title": f"来源 {number}", "original_url": f"https://research.example.org/study-{number}",
           "published_at": "2024-06-01", "observed_at": "2024-05-31", "collected_at": TODAY,
           "source_type": "research_report"}
    ref.update(changes)
    ref["citation_id"] = candidate_id(ref)
    return ref


class Corpus:
    """Records real route invocations; does not impersonate an embedding model."""
    def __init__(self, refs):
        self.refs = refs
        self.lexical_calls, self.vector_calls, self.read_calls = [], [], []

    def lexical(self, query, limit=20):
        self.lexical_calls.append((query, limit))
        return {"citations": deepcopy(self.refs)}

    def vector_fixture(self, query, limit=20):
        self.vector_calls.append((query, limit))
        return deepcopy(self.refs)

    def read(self, document_id, version, start, end):
        self.read_calls.append((document_id, version, start, end))
        return deepcopy(next(r for r in self.refs if r["document_id"] == document_id
                             and r["source_version"] == version and r["line_start"] == start))


def packet(refs=None, question="ChatGPT 喜欢哪些信源？", allow_web=False, reader=None):
    corpus = Corpus(refs if refs is not None else [source()])
    return WorkflowEngine(corpus.lexical, reader or corpus.read).prepare(question, today=TODAY, allow_web=allow_web)


def judgment(ref, **changes):
    result = {"citation_id": ref["citation_id"], "relevance": "direct", "claim": "作者在2024年的100条英语旅行回答样本中观察到 ChatGPT 引用 Reddit 的比例为28%。",
              "exact_quote": ref["excerpt"], "kind": "author_report", "platforms": ["ChatGPT"],
              "relation": "observed_preference", "conditions": deepcopy(CONDITIONS),
              "reason": "原文明确描述所问平台在指定样本中的引用分布，只作为作者观察。"}
    result.update(changes)
    return result


def web_source(url="https://openai.com/index/search/", text=CHANNEL, checked_at=TODAY, **changes):
    result = {"url": url, "excerpt": text, "read_status": "completed", "content_type": "full_page_excerpt",
              "checked_at": checked_at, "published_at": "2026-11-01"}
    result.update(changes)
    return result


def web_citation_id(ref):
    return "web-" + digest({"url": ref["url"], "excerpt": ref["excerpt"]})[:24]


class QueryPlanTests(unittest.TestCase):
    def test_all_host_subquestions_survive_without_fallback_crowding(self):
        queries = ["Claude official search", "Grok official search", "Claude citation domains",
                   "Grok citation domains", "Claude observation sample", "Grok observation sample"]
        plan = plan_question("Claude 和 Grok 喜欢什么信源？", analysis={"queries": queries}, today=TODAY)
        self.assertEqual(plan["queries"], queries)
        for invalid in ("Claude", [], ["query"] * 7):
            with self.assertRaises(ValueError):
                plan_question("Claude", analysis={"queries": invalid}, today=TODAY)

    def test_twelve_user_questions_followups_and_paraphrases(self):
        cases = json.loads((Path(__file__).parent / "fixtures/workflow_questions.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 12)
        for case in cases:
            with self.subTest(case=case["id"]):
                plan = plan_question(case["question"], context=case.get("context"), today=TODAY)
                understanding = plan["understanding"]
                self.assertEqual(understanding["task"], case["expected_task"])
                self.assertEqual(understanding["platforms"], case["expected_platforms"])
                self.assertEqual(understanding["freshness"], case["expected_freshness"])
                if "expected_tasks" in case:
                    self.assertEqual(understanding["tasks"], case["expected_tasks"])
                for old in case.get("absent_platforms", []):
                    self.assertNotIn(old, plan["resolved_question"])

    def test_gpt_alias_must_not_rewrite_api_or_model_research(self):
        for question in ("GPT API 的来源是什么？", "GPT 模型研究的来源是什么？", "GPT-4 训练数据来源"):
            with self.subTest(question=question):
                plan = plan_question(question, today=TODAY)
                self.assertNotIn("ChatGPT", plan["resolved_question"])
                self.assertNotIn("ChatGPT", plan["understanding"]["platforms"])

    def test_recent_request_queues_live_search_but_does_not_claim_it_ran(self):
        prepared = packet(question="最近 ChatGPT 的来源偏好是什么？", allow_web=True)
        self.assertEqual(prepared["web"]["status"], "pending_host_search")
        self.assertTrue(all("2026" in q for q in prepared["web"]["queries"]))
        self.assertEqual(prepared["stages"]["semantic_reranking"], "pending_host_ai")
        self.assertEqual(prepared["stages"]["generation"], "pending_host_ai")
        self.assertEqual(prepared["stages"]["postcheck"], "pending")

    def test_host_rewrite_cannot_replace_explicit_current_platform(self):
        with self.assertRaises(ValueError):
            plan_question("Claude 喜欢哪些来源？", analysis={"resolved_question": "ChatGPT 喜欢哪些来源？"}, today=TODAY)

    def test_historical_year_remains_in_every_subquery(self):
        plan = plan_question("2024年 ChatGPT 的信源偏好有哪些研究？", today=TODAY,
                             analysis={"queries": ["ChatGPT citation study", "ChatGPT 来源分布"]})
        self.assertEqual(plan["understanding"]["requested_period"], {"start": "2024-01-01", "end": "2024-12-31"})
        self.assertTrue(all("2024" in q for q in plan["queries"]))


class RetrievalTests(unittest.TestCase):
    def test_compound_question_retains_formula_without_platform_name(self):
        # Popular platform-specific passages recur in every broad query. A
        # formula relevant to only the definition subquery must survive them.
        formula = source(100, text="目标URL引用率 = 引用了目标URL的回答数 ÷ 全部有效回答数。")
        action = source(101, text="ChatGPT 优化可先固定问题面板，再改一页内容并重复测量；不能保证提升。")
        broad = [source(i, text=f"ChatGPT citation observation {i}: examples and platform notes.") for i in range(1, 21)]
        corpus = Corpus(broad + [formula, action])
        definition_query = "目标URL引用率 分子 分母"
        method_query = "ChatGPT 优化 对照 复测"

        def lexical(query, limit=20):
            corpus.lexical_calls.append((query, limit))
            if query == definition_query:
                return {"citations": deepcopy([formula] + broad[:19])}
            if query == method_query:
                return {"citations": deepcopy([action] + broad[:19])}
            return {"citations": deepcopy(broad)}

        prepared = WorkflowEngine(lexical, corpus.read).prepare(
            "ChatGPT 引用率怎么计算，并说明怎么提高？", today=TODAY, allow_web=True, limit=6,
            analysis={"queries": [definition_query, method_query]})
        ids = {c["citation_id"] for c in prepared["candidates"]}
        self.assertIn(formula["citation_id"], ids)
        self.assertIn(action["citation_id"], ids)
        self.assertEqual(len(ids), len(prepared["candidates"]))
        self.assertLessEqual(len(ids), 6)
        self.assertEqual(prepared["plan"]["understanding"]["tasks"], ["metric_definition", "practical_method"])
        self.assertEqual(prepared["web"]["status"], "pending_host_search")
        retained = next(c for c in prepared["candidates"] if c["citation_id"] == formula["citation_id"])
        self.assertIn({"route": "keyword", "query": definition_query, "rank": 1}, retained["retrieval_hits"])

    def test_nested_source_metadata_is_flattened_for_identity_and_citation(self):
        for url, official in (("https://help.openai.com/en/articles/search", True),
                              ("https://help.openai.com.evil.example/report", False)):
            with self.subTest(url=url):
                ref = source(text=CHANNEL, original_url=None, published_at=None, observed_at=None, collected_at=None,
                             metadata={"original_url": url, "published_at": "2026-10-01", "collected_at": TODAY})
                read = packet([ref], question="ChatGPT 搜索渠道是什么？")["candidates"][0]
                self.assertEqual(read["original_url"], url)
                self.assertEqual(read["published_at"], "2026-10-01")
                self.assertEqual(read["authority"]["is_official_for_question"], official)
                self.assertFalse(read["time"]["observed_at_known"])

    def test_routes_report_only_invoked_retrievers_and_deduplicate(self):
        corpus = Corpus([source()])
        prepared = WorkflowEngine(corpus.lexical, corpus.read).prepare("GPT 来源偏好", today=TODAY, allow_web=False)
        self.assertEqual(len(prepared["candidates"]), 1)
        self.assertEqual(len(corpus.read_calls), 1)
        traces = prepared["retrieval_trace"]
        self.assertEqual(sum(t["route"] == "keyword" and t["status"] == "completed" for t in traces), len(corpus.lexical_calls))
        for route in ("query_embedding", "keyword_embedding"):
            self.assertEqual([t["status"] for t in traces if t["route"] == route], ["unavailable"])
        vector_corpus = Corpus([source()])
        with_vector = WorkflowEngine(vector_corpus.lexical, vector_corpus.read, vector_corpus.vector_fixture).prepare(
            "GPT 来源偏好", today=TODAY, allow_web=False)
        self.assertEqual(len(vector_corpus.vector_calls), 2)
        self.assertEqual(len(with_vector["candidates"]), 1)
        self.assertEqual({t["route"] for t in with_vector["retrieval_trace"] if t["status"] == "completed"},
                         {"keyword", "query_embedding", "keyword_embedding"})

    def test_source_identity_version_and_line_range_must_survive_readback(self):
        original = source()
        mutations = ({"document_id": "doc-" + "f" * 20}, {"source_version": "0" * 64}, {"source_version": None},
                     {"line_start": 2, "line_end": 2}, {"status": "error"})
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                prepared = packet([original], reader=lambda *args: {**original, **mutation})
                self.assertEqual(prepared["candidates"], [])
                self.assertEqual(prepared["excluded"][0]["reason"], "source_read_failed")

    def test_shorter_read_is_never_relabelled_as_the_full_requested_range(self):
        ref = source(text="first line\nsecond line\nthird line")
        prepared = packet([ref], question="解释来源", reader=lambda *args: {**ref, "excerpt": "first line", "line_end": 1})
        # Failing closed or retaining the actual shorter range both preserve
        # provenance. Claiming that unread lines were read does not.
        if prepared["candidates"]:
            self.assertEqual(prepared["candidates"][0]["line_end"], 1)
            self.assertTrue(prepared["candidates"][0]["citation_id"].endswith(":L1-L1"))
        else:
            self.assertEqual(prepared["excluded"][0]["reason"], "source_read_failed")

    def test_same_text_and_same_work_cannot_fill_candidate_budget(self):
        refs = [source(1), source(2)]  # exact copied excerpt, distinct documents
        refs += [source(i, text=f"ChatGPT study number {i} cites Reddit in {i}% of responses.", work_id="shared") for i in range(3, 9)]
        corpus = Corpus(refs)
        prepared = WorkflowEngine(corpus.lexical, corpus.read).prepare("ChatGPT 喜欢哪些信源？", today=TODAY, allow_web=False)
        self.assertEqual(sum(r["excerpt"] == STUDY for r in prepared["candidates"]), 1)
        self.assertLessEqual(sum(r["work_id"] == "shared" for r in prepared["candidates"]), 3)
        self.assertEqual(prepared["sources_read"], len({r[0] for r in corpus.read_calls}))
        self.assertEqual(prepared["candidate_documents_returned"], len({r["document_id"] for r in prepared["candidates"]}))

    def test_source_versions_never_fall_back_and_failed_routes_are_visible(self):
        corpus = Corpus([source()])
        def broken_read(*args):
            raise FileNotFoundError("requested immutable version missing")
        prepared = WorkflowEngine(corpus.lexical, broken_read).prepare("ChatGPT 来源偏好", today=TODAY)
        self.assertEqual(prepared["candidates"], [])
        self.assertEqual(prepared["status"], "insufficient_evidence")
        def broken_search(*args, **kwargs):
            raise ConnectionError("fixture transport failure")
        failed = WorkflowEngine(broken_search, corpus.read).prepare("ChatGPT 来源偏好", today=TODAY)
        self.assertTrue(any(t["route"] == "keyword" and t["status"] == "failed" for t in failed["retrieval_trace"]))


class EvidenceGatesTests(unittest.TestCase):
    def test_mixed_platform_relation_gaps_cannot_be_filled_by_other_relation(self):
        refs = [source(1, text="Our study found Claude cited Reddit in 28% of answers."),
                source(2, text="Grok searches public X posts and the Internet.")]
        prepared = packet(refs, question="Claude 和 Grok 的来源偏好与搜索渠道分别是什么？")
        self.assertEqual(set(prepared["plan"]["understanding"]["requested_relations"]),
                         {"observed_preference", "retrieval_channel"})
        by_doc = {r["document_id"]: r for r in prepared["candidates"]}
        claims = [judgment(by_doc[refs[0]["document_id"]], platforms=["Claude"],
                           conditions={**CONDITIONS, "product_mode": "Claude consumer search"}),
                  judgment(by_doc[refs[1]["document_id"]], platforms=["Grok"], relation="retrieval_channel",
                           conditions={"scope": "作者记载的Grok渠道"})]
        result = adjudicate(prepared, claims)
        self.assertEqual(len(result["accepted_claims"]), 2)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(any("Claude" in g and "搜索渠道" in g for g in result["gaps"]))
        self.assertTrue(any("Grok" in g and "引用偏好" in g for g in result["gaps"]))

    def test_publication_year_cannot_replace_requested_observation_year(self):
        ref = source(text="Our 2026 study found ChatGPT cited news sites in 28% of answers.",
                     published_at="2026-10-01", observed_at="2026-09-30")
        prepared = packet([ref], question="2024年 ChatGPT 的信源偏好有哪些研究？")
        claim = judgment(prepared["candidates"][0], kind="historical_report",
                         conditions={**CONDITIONS, "observed_period": "2026-09"})
        result = adjudicate(prepared, [claim])
        self.assertEqual(result["accepted_claims"], [])
        self.assertIn("observation_does_not_address_requested_historical_period", result["rejected_claims"][0]["rejection_reasons"])
        # A later publication that explicitly reports a 2024 observation can
        # answer a 2024 question; publication year alone is not a discard rule.
        delayed = packet([source(published_at="2026-10-01")], question="2024年 ChatGPT 的信源偏好有哪些研究？")
        accepted = adjudicate(delayed, [judgment(delayed["candidates"][0], kind="historical_report")])
        self.assertEqual(len(accepted["accepted_claims"]), 1)

    def test_historical_report_is_retained_but_not_promoted_by_collection_date(self):
        prepared = packet()
        ref = prepared["candidates"][0]
        self.assertEqual(ref["time"]["observed_at"], "2024-05-31")
        self.assertEqual(ref["time"]["collected_at"], TODAY)
        accepted = adjudicate(prepared, [judgment(ref)])
        self.assertEqual(len(accepted["accepted_claims"]), 1)
        rejected = adjudicate(prepared, [judgment(ref, kind="current_fact")])
        self.assertEqual(rejected["accepted_claims"], [])
        self.assertIn("current_fact_needs_this_run_live_read", rejected["rejected_claims"][0]["rejection_reasons"])
        self.assertFalse(time_profile({"published_at": TODAY, "collected_at": TODAY}, TODAY)["observed_at_known"])

    def test_search_channel_cannot_answer_preference(self):
        prepared = packet([source(text=CHANNEL)])
        result = adjudicate(prepared, [judgment(prepared["candidates"][0], relation="retrieval_channel")])
        self.assertEqual(result["accepted_claims"], [])
        self.assertIn("channel_or_background_does_not_answer_preference", result["rejected_claims"][0]["rejection_reasons"])

    def test_third_party_official_label_and_non_exact_quote_are_rejected(self):
        prepared = packet()
        ref = prepared["candidates"][0]
        for change, error in (({"source_label": "official"}, "third_party_mislabeled_official"),
                              ({"exact_quote": "ChatGPT always prefers Reddit."}, "quote_not_in_source")):
            with self.subTest(change=change):
                result = adjudicate(prepared, [judgment(ref, **change)])
                self.assertEqual(result["accepted_claims"], [])
                self.assertIn(error, result["rejected_claims"][0]["rejection_reasons"])

    def test_live_primary_channel_fact_requires_current_read_date(self):
        prepared = packet([], question="ChatGPT 联网时有哪些搜索渠道？", allow_web=True)
        for checked, expected_count in ((TODAY, 1), ("2024-01-01", 0)):
            with self.subTest(checked=checked):
                web = web_source(checked_at=checked)
                claim = judgment({"citation_id": web_citation_id(web), "excerpt": CHANNEL}, kind="current_fact",
                                 claim="ChatGPT 可以搜索公开网页并展示来源引用。", relation="retrieval_channel", source_label="official")
                result = adjudicate(prepared, [claim], [web], web_status="completed")
                self.assertEqual(len(result["accepted_claims"]), expected_count)

    def test_new_weak_report_cannot_establish_current_preference_ranking(self):
        prepared = packet([], allow_web=True)
        web = web_source(url="https://research.example.org/new", text=STUDY)
        j = judgment({"citation_id": web_citation_id(web), "excerpt": STUDY}, kind="current_fact")
        result = adjudicate(prepared, [j], [web], web_status="completed")
        self.assertEqual(result["accepted_claims"], [])
        self.assertIn("preference_study_must_remain_attributed_report", result["rejected_claims"][0]["rejection_reasons"])
        weak = adjudicate(prepared, [{**j, "kind": "author_report", "conditions": {"scope": "作者报告"}}], [web], web_status="completed")
        self.assertIn("missing_study_sample", weak["rejected_claims"][0]["rejection_reasons"])

    def test_incompatible_observations_stay_separate(self):
        prepared = packet([source(), source(2, text="Our 2026 study found ChatGPT cited news sites in 45% of finance responses.")])
        judgments = [judgment(prepared["candidates"][0]), judgment(prepared["candidates"][1],
                     conditions={**CONDITIONS, "observed_period": "2026-10", "industry": "finance", "sample": "300 finance responses"})]
        result = adjudicate(prepared, judgments)
        self.assertEqual(len(result["accepted_claims"]), 2)
        self.assertEqual(result["comparability"][0]["status"], "not_comparable_without_review")
        self.assertIn("observed_period", result["comparability"][0]["different_fields"])
        self.assertIn("sample", result["comparability"][0]["different_fields"])

    def test_search_snippets_and_modified_evidence_packets_are_rejected(self):
        prepared = packet([], allow_web=True)
        with self.assertRaises(ValueError):
            adjudicate(prepared, [], [web_source(content_type="search_snippet")], web_status="completed")
        modified = deepcopy(prepared)
        modified["plan"]["understanding"]["platforms"] = ["Grok"]
        with self.assertRaises(ValueError):
            adjudicate(modified, [])


class PostcheckTests(unittest.TestCase):
    def setUp(self):
        prepared = packet()
        self.assessment = adjudicate(prepared, [judgment(prepared["candidates"][0])])
        self.claim = self.assessment["accepted_claims"][0]

    def test_bounded_draft_can_pass_without_claiming_independent_validation(self):
        answer = self.claim["claim"] + " [研究原文](" + self.claim["source"]["original_url"] + ")"
        result = postcheck(self.assessment, answer, [{"citation_id": self.claim["citation_id"], "text": self.claim["claim"]}], HOST_REVIEW)
        self.assertEqual(result["status"], "process_pass")
        self.assertFalse(result["answer_approved"])
        self.assertEqual(result["semantic_validation"], "host_ai_declared_not_independent")

    def test_broader_generated_claim_is_not_approved_by_reusing_citation(self):
        broader = "ChatGPT 现在对所有行业都最偏好 Reddit。"
        answer = broader + " [来源](" + self.claim["source"]["original_url"] + ")"
        result = postcheck(self.assessment, answer, [{"citation_id": self.claim["citation_id"], "text": broader}], HOST_REVIEW)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["answer_markdown"], "")
        self.assertTrue(any("已核对陈述不同" in e for e in result["errors"]))

    def test_missing_source_link_or_host_review_blocks_delivery(self):
        mapping = [{"citation_id": self.claim["citation_id"], "text": self.claim["claim"]}]
        result = postcheck(self.assessment, self.claim["claim"], mapping, HOST_REVIEW)
        self.assertEqual(result["status"], "blocked")
        answer = self.claim["claim"] + " [来源](" + self.claim["source"]["original_url"] + ")"
        incomplete = postcheck(self.assessment, answer, mapping, {**HOST_REVIEW, "dates_and_scopes_preserved": False})
        self.assertEqual(incomplete["status"], "blocked")

    def test_live_search_failure_must_remain_visible_in_final_answer(self):
        prepared = packet(allow_web=True)
        assessed = adjudicate(prepared, [judgment(prepared["candidates"][0])], web_status="failed")
        answer = self.claim["claim"] + " [来源](" + self.claim["source"]["original_url"] + ")"
        mapping = [{"citation_id": self.claim["citation_id"], "text": self.claim["claim"]}]
        self.assertEqual(postcheck(assessed, answer, mapping, HOST_REVIEW)["status"], "blocked")
        self.assertEqual(postcheck(assessed, answer + " 本次无法完成联网核查，不能确认当前偏好。", mapping, HOST_REVIEW)["status"], "process_pass")


if __name__ == "__main__":
    unittest.main()
