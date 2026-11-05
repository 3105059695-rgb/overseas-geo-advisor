"""Source-preserving RAG workflow. The host AI supplies semantic judgments.

No model/API calls, automatic web requests or paid services live in this module.
Retrieval is executable; host tasks are explicitly pending until submitted.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
import hashlib
import json
import re
from typing import Callable
from urllib.parse import urlsplit

from geo_relevance import platforms_in, query_intent, passage_relevance

VERSION = "0.5.2"
OFFICIAL_DOMAINS = {
    "ChatGPT": ("openai.com",), "Claude": ("anthropic.com", "claude.com"),
    "Grok": ("x.ai", "help.x.com"), "Perplexity": ("perplexity.ai",),
    "Gemini": ("ai.google.dev", "developers.google.com", "support.google.com", "blog.google"),
    "Google AI Overviews": ("developers.google.com", "support.google.com", "blog.google"),
    "Google AI Mode": ("developers.google.com", "support.google.com", "blog.google"),
    "Copilot": ("microsoft.com", "bing.com"),
}
PREFERENCE = r"喜欢|偏好|偏向|更常|采信|引用最多|哪些平台布局|prefer|citation share|source distribution"
CHANNEL = r"搜索渠道|搜索引擎|搜索供应|从哪里找|从哪找|联网|web search|search provider"
METRIC = r"提及率|引用份额|分子|分母|怎么算|怎么计算|metric|denominator"
ACTION = r"怎么做|如何做|怎么操作|如何操作|布局|实操|优先|优化|不引用|没引用|不推荐|提升|提高|监测|监控|操作|strategy|optimi[sz]"


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def iso(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("日期必须为 YYYY-MM-DD")
    short = value[:10]
    if date.fromisoformat(short).isoformat() != short:
        raise ValueError("日期必须为 YYYY-MM-DD")
    return short


def _known_date(value: object) -> str | None:
    try:
        return iso(value)
    except (ValueError, TypeError):
        return None


def _text(value: object, name: str, maximum: int = 8000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} 需要 1–{maximum} 字符")
    return value.strip()


def plan_question(question: str, context: dict | None = None, analysis: dict | None = None,
                  today: str | None = None, allow_web: bool = True) -> dict:
    """Deterministic fallback plus explicit host understanding; never claims LLM use."""
    question = _text(question, "question")
    context, analysis = context or {}, analysis or {}
    if not isinstance(context, dict) or not isinstance(analysis, dict):
        raise ValueError("context/analysis 必须为对象")
    now = iso(today) or date.today().isoformat()
    initial_intent = query_intent(question)
    explicit = initial_intent["platforms"] if initial_intent.get("platform_selection") == "explicit" else platforms_in(question)
    resolved = (re.sub(r"(?<![A-Za-z0-9])GPT(?![A-Za-z0-9-])", "ChatGPT", question, flags=re.I)
                if "ChatGPT" in explicit else question)
    previous = str(context.get("question", ""))[:2000]
    previous_intent = query_intent(previous)
    short_followup = bool(re.search(r"^(那|那么|它|他们|这些|这个|还有)|呢[?？]?$", question))
    # Carry the relation, not the previous product, into '那 Claude 呢'.
    if short_followup and previous:
        if explicit and not re.search(PREFERENCE + "|信源|来源|" + CHANNEL + "|" + ACTION, question, re.I):
            relation = "更常引用哪些网站和来源" if re.search(PREFERENCE, previous, re.I) else "信源和搜索渠道" if previous_intent["kind"] == "platform_sources" else previous
            resolved = "、".join(explicit) + " " + relation
        elif not explicit and previous_intent["platforms"]:
            resolved = "、".join(previous_intent["platforms"]) + " " + question + "；前文问题：" + previous
    if analysis.get("resolved_question"):
        proposed = _text(analysis["resolved_question"], "resolved_question")
        proposed_platforms = platforms_in(proposed)
        if explicit and not set(explicit).issubset(proposed_platforms):
            raise ValueError("改写不得丢失当前问题明确指定的平台")
        resolved = proposed
    intent = query_intent(resolved)
    platforms = explicit or intent["platforms"]
    if re.search(PREFERENCE, resolved, re.I):
        task = "source_preference"
    elif re.search(CHANNEL, resolved, re.I):
        task = "source_channels"
    elif re.search(METRIC, resolved, re.I):
        task = "metric_definition"
    elif re.search(ACTION, resolved, re.I):
        task = "practical_method"
    elif re.search(r"分类|怎么分|类型|类别", resolved):
        task = "source_classification"
    elif intent["kind"] == "platform_sources":
        task = "source_channels"
    else:
        task = "knowledge_explanation"
    if analysis.get("task"):
        if analysis["task"] not in {"source_preference", "source_channels", "metric_definition", "practical_method", "source_classification", "knowledge_explanation", "product_landscape"}:
            raise ValueError("未知的问题类型")
        task = analysis["task"]
    requested_relations = []
    if task == "source_preference":
        requested_relations.append("observed_preference")
        if re.search(CHANNEL, resolved, re.I):
            requested_relations.append("retrieval_channel")
    elif task == "source_channels":
        requested_relations.append("retrieval_channel")
    # Dates aren't a crude discard cutoff. Current preference requires evidence
    # of observation conditions; a newly collected old paper remains historical.
    years = re.findall(r"(?<!\d)(20\d{2})(?:\s*年|(?=\s))", question)
    historical = bool(re.search(r"历史|当时|那年|截至|\b20\d{2}\s*年", question))
    requested_period = {"start": years[0] + "-01-01", "end": years[-1] + "-12-31"} if historical and years else None
    mixed_tasks = bool(re.search(METRIC, resolved, re.I) and re.search(ACTION, resolved, re.I))
    freshness = "historical" if historical else "current" if mixed_tasks or task in {"source_preference", "source_channels", "practical_method"} or re.search(r"最近|最新|现在|目前|今天", question) else "stable"
    if analysis.get("freshness"):
        if analysis["freshness"] not in {"historical", "current", "stable"}:
            raise ValueError("未知的时效要求")
        if re.search(r"最近|最新|现在|目前|今天", question) and analysis["freshness"] != "current":
            raise ValueError("不能将用户明确的当前问题改为非当前")
        freshness = analysis["freshness"]
    aliases = {"source_preference": "citation sources domain distribution study 引用 来源 网站 偏好 统计",
               "source_channels": "web search sources official 搜索渠道 官方 文档",
               "practical_method": "GEO method case steps 实操 方法 案例",
               "metric_definition": "定义 分子 分母 calculation",
               "source_classification": "信源 分类 品牌自有 第三方 社区 owned earned social sources"}
    queries = [resolved]
    if not analysis.get("queries"):
        parts = [p.strip() for p in re.split(r"[？?；;，,]", resolved) if p.strip()]
        if len(parts) > 1 and re.search(METRIC, resolved, re.I) and re.search(ACTION, resolved, re.I):
            queries += [("、".join(platforms) + " " + part).strip() for part in parts[:3]]
    for platform in (platforms or [""])[:6]:
        queries.append((platform + " " + aliases.get(task, resolved)).strip())
    supplied_queries = analysis.get("queries")
    if supplied_queries is not None:
        if not isinstance(supplied_queries, list) or not 1 <= len(supplied_queries) <= 6:
            raise ValueError("queries 必须为1至6条查询的数组")
        # Explicit host subquestions take precedence over fallback expansions.
        # Otherwise the last platform/facet silently falls off the six-query cap.
        queries = [_text(query, "query", 1000) for query in supplied_queries] + [resolved]
    # A six-platform comparison needs all six platform routes. The complete
    # question remains in the plan even when it has no additional query slot.
    if not supplied_queries and len(platforms) == 6:
        queries = queries[-6:]
    queries = list(dict.fromkeys(queries))[:6]
    if requested_period:
        year_query = " ".join(dict.fromkeys(years))
        queries = [q if any(y in q for y in years) else year_query + " " + q for q in queries]
    keywords = analysis.get("keywords") or [*platforms, *aliases.get(task, "GEO 知识").split()]
    if not isinstance(keywords, list) or any(not isinstance(v, str) for v in keywords):
        raise ValueError("keywords 必须为文本数组")
    keywords = list(dict.fromkeys(keywords))[:20]
    scope = analysis.get("source_scope")
    if scope is not None:
        if not isinstance(scope, dict) or set(scope) - {"document_id", "source_version", "start_line", "end_line"}:
            raise ValueError("source_scope 只能包含文档、版本和可选行范围")
        scope = dict(scope)
        for field in ("document_id", "source_version"):
            scope[field] = _text(scope.get(field), "source_scope." + field, 240)
        for field in ("start_line", "end_line"):
            if field in scope and (type(scope[field]) is not int or scope[field] < 1):
                raise ValueError("source_scope 行号必须为正整数")
        if scope.get("end_line", 1_000_000) < scope.get("start_line", 1):
            raise ValueError("source_scope 结束行不能早于开始行")
    return {"version": VERSION, "question": question, "resolved_question": resolved,
            "understanding": {"method": "host_ai_submitted" if analysis else "deterministic_fallback",
                              "platforms": platforms, "task": task, "freshness": freshness,
                              "requested_relations": requested_relations,
                              "requested_period": requested_period,
                              "tasks": ["metric_definition", "practical_method"] if mixed_tasks else [task],
                              "industry": context.get("industry"), "as_of": now,
                              "need": "当前引用来源的观察及适用范围；搜索能力说明不能替代偏好证据" if task == "source_preference" else task},
            "queries": queries, "keywords": keywords, "source_scope": scope, "allow_web": bool(allow_web),
            "risk": {"source_instructions": "untrusted_data", "no_source_mutation": True},
            "routes": [{"name": "keyword", "executor": "retriever"},
                       {"name": "query_embedding", "executor": "local_optional_encoder"},
                       {"name": "keyword_embedding", "executor": "local_optional_encoder"},
                       {"name": "web", "executor": "host_ai", "required_if": "current_or_unanswered"}],
            "host_tasks": ["核对改写是否保留原意", "回读候选，按问题关系做语义重排", "必要时联网核查当前资料", "逐条提交结论与连续原文", "生成中文解释并运行后置检查"]}


def authority(ref: dict, platforms: list[str]) -> dict:
    url = ref.get("original_url") or ref.get("url") or ref.get("metadata", {}).get("original_url") or ref.get("metadata", {}).get("source_url") or ""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        host = ""
    owners = [p for p, domains in OFFICIAL_DOMAINS.items() if any(host == d or host.endswith("." + d) for d in domains)]
    return {"host": host, "official_for": owners, "is_official_for_question": bool(set(owners) & set(platforms)),
            "classification": "official_origin" if owners else "third_party", "note": "域名身份，不代表内容必然正确"}


def time_profile(ref: dict, now: str) -> dict:
    meta = {**ref.get("metadata", {}), **{k: v for k, v in ref.items() if v is not None}}
    out = {k: _known_date(meta.get(k)) for k in ("published_at", "updated_at", "observed_at", "collected_at", "checked_at")}
    # published_at may signal age, never substitutes for observed_at.
    out["observed_at_known"] = out["observed_at"] is not None
    out["age_since_publication_days"] = (date.fromisoformat(now) - date.fromisoformat(out["published_at"])).days if out["published_at"] else None
    out["current_validity"] = "requires_live_or_observation_review"
    out["future_date"] = any(v and v > now for k, v in out.items() if k in {"published_at", "updated_at", "observed_at", "checked_at"})
    return out


def candidate_id(ref: dict) -> str:
    return f"{ref['document_id']}@{ref['source_version']}:L{ref['line_start']}-L{ref['line_end']}"


class WorkflowEngine:
    def __init__(self, lexical: Callable, reader: Callable, vector: Callable | None = None,
                 provenance: Callable | None = None):
        self.lexical, self.reader, self.vector = lexical, reader, vector
        self.provenance = provenance

    def prepare(self, question: str, context: dict | None = None, analysis: dict | None = None,
                today: str | None = None, allow_web: bool = True, limit: int = 16) -> dict:
        if not 1 <= limit <= 30:
            raise ValueError("limit 必须在 1–30 之间")
        plan = plan_question(question, context, analysis, today, allow_web)
        pool, traces = {}, []
        calls = [("keyword", q, self.lexical) for q in plan["queries"]]
        if self.vector:
            calls += [("query_embedding", plan["resolved_question"], self.vector),
                      ("keyword_embedding", " ".join(plan["keywords"]), self.vector)]
        else:
            traces += [{"route": name, "status": "unavailable", "reason": "未配置本地向量模型/索引；未伪装成已执行"} for name in ("query_embedding", "keyword_embedding")]
        for route, query, search in calls:
            try:
                scope = plan.get("source_scope") if route == "keyword" else None
                result = search(query, limit=20, **scope) if scope else search(query, limit=20)
                items = result.get("citations", []) + result.get("background_citations", []) if isinstance(result, dict) else result
                if not isinstance(items, list):
                    raise ValueError("检索结果不是列表")
                traces.append({"route": route, "query": query, "status": "completed", "hits": len(items)})
                for rank, raw in enumerate(items, 1):
                    ref = dict(raw)
                    requested_scope = plan.get("source_scope")
                    if requested_scope and (
                        ref.get("document_id") != requested_scope["document_id"]
                        or ref.get("source_version") != requested_scope["source_version"]
                        or ref.get("line_start", 0) < requested_scope.get("start_line", 1)
                        or ref.get("line_end", 1_000_001) > requested_scope.get("end_line", 1_000_000)
                    ):
                        continue
                    key = candidate_id(ref)
                    if key not in pool:
                        pool[key] = {**ref, "citation_id": key, "rrf_score": 0.0, "retrieval_routes": [], "retrieval_hits": []}
                    pool[key]["rrf_score"] += 1 / (60 + rank)
                    pool[key]["retrieval_routes"].append(route)
                    pool[key]["retrieval_hits"].append({"route": route, "query": query, "rank": rank})
            except Exception as exc:
                traces.append({"route": route, "query": query, "status": "failed", "error_type": type(exc).__name__})
        intent = query_intent(plan["resolved_question"])
        if plan["understanding"]["requested_relations"] == ["observed_preference"]:
            intent["source_aspects"] = ["observed_preferences"]
        candidates, excluded, counts, seen_text, seen_ranges = [], [], Counter(), set(), {}
        read_documents = set()
        # Read a bounded wider pool before reranking. Different query routes
        # must not let repeated translations crowd out other source works.
        for ref in sorted(pool.values(), key=lambda r: -r["rrf_score"])[:80]:
            group = ref.get("work_id") or ref["document_id"]
            if counts[group] >= 3:
                continue
            ranges = seen_ranges.setdefault(ref["document_id"], [])
            a, b = ref["line_start"], ref["line_end"]
            if any(max(0, min(b, y) - max(a, x) + 1) / max(1, min(b-a+1, y-x+1)) > .7 for x, y in ranges):
                continue
            try:
                read = self.reader(ref["document_id"], ref["source_version"], a, min(b, a + 399))
                text = read.get("excerpt", read.get("text", ""))
                if not text:
                    raise ValueError("原文为空")
                if read.get("status") in {"error", "unavailable", "not_found"}:
                    raise ValueError("原文回读失败")
                if read.get("document_id") != ref["document_id"]:
                    raise ValueError("回读文档发生变化")
                if read.get("source_version") != ref["source_version"]:
                    raise ValueError("回读版本发生变化")
                if read.get("line_start") != a or read.get("line_end") != min(b, a + 399):
                    raise ValueError("回读行号范围发生变化")
                ref = {**ref, **read, "excerpt": text, "citation_id": ref["citation_id"], "read_status": "completed"}
                meta = ref.get("metadata", {})
                for field in ("original_url", "reading_url", "published_at", "updated_at", "observed_at", "collected_at", "checked_at", "author", "original_title", "attachments", "retrieval_role"):
                    if not ref.get(field) and meta.get(field):
                        ref[field] = meta[field]
                if not ref.get("reading_url"):
                    from geo_snapshot import BLOB_BASE
                    ref["reading_url"] = f"{BLOB_BASE}documents/{ref['document_id']}/{ref['source_version']}.json"
                ref["line_start"], ref["line_end"] = a, min(b, a + 399)
                ref["citation_id"] = candidate_id(ref)
                read_documents.add(ref["document_id"])
            except Exception as exc:
                excluded.append({"citation_id": ref["citation_id"], "reason": "source_read_failed", "error_type": type(exc).__name__})
                continue
            normalized = re.sub(r"\s+", " ", text).strip()
            if ref.get("retrieval_role") == "navigation":
                excluded.append({"citation_id": ref["citation_id"], "reason": "navigation_not_evidence"})
                continue
            key = digest(normalized)
            if key in seen_text:
                continue
            seen_text.add(key)
            body_lines = [line.strip() for line in text.splitlines() if line.strip() and not re.match(r"^#{1,6}\s", line.strip())]
            if body_lines and all(re.match(r"^[-*]?\s*(?:[^\[]*[,，:]\s*)?\[[^]]+\]\(", line) for line in body_lines):
                excluded.append({"citation_id": ref["citation_id"], "reason": "link_directory_not_evidence"})
                continue
            ref["relevance"] = passage_relevance(intent, ref.get("title", ""), text)
            ref["authority"] = authority(ref, plan["understanding"]["platforms"])
            ref["time"] = time_profile(ref, plan["understanding"]["as_of"])
            ref["semantic_review"] = "pending_host_ai"
            candidates.append(ref)
            ranges.append((a, b))
            counts[group] += 1
        # Direct relationship first, but keep history with its conditions;
        # lexical matching is not falsely reported as semantic reranking.
        candidates.sort(key=lambda r: (r["relevance"].get("tier") != "direct_candidate", -r["rrf_score"]))
        if len(plan["understanding"]["tasks"]) > 1:
            # A compound question needs candidate coverage for each subquery;
            # a platform-specific action passage must not crowd out a general
            # formula merely because the formula doesn't repeat a product name.
            selected, chosen = [], set()
            for query in plan["queries"]:
                ranked = sorted((r for r in candidates if any(h["route"] == "keyword" and h["query"] == query for h in r["retrieval_hits"])),
                                key=lambda r: min(h["rank"] for h in r["retrieval_hits"] if h["route"] == "keyword" and h["query"] == query))
                for r in ranked[:2]:
                    if r["citation_id"] not in chosen and len(selected) < limit:
                        selected.append(r)
                        chosen.add(r["citation_id"])
            candidates = (selected + [r for r in candidates if r["citation_id"] not in chosen])[:limit]
        else:
            candidates = candidates[:limit]
        current = plan["understanding"]["freshness"] == "current"
        web_pending = bool(allow_web and (current or not candidates))
        web_queries = []
        if web_pending:
            for p in plan["understanding"]["platforms"] or ["GEO"]:
                suffix = "citation sources study methodology sample observation period" if plan["understanding"]["task"] == "source_preference" else "official documentation"
                web_queries.append(f"{p} {suffix} {plan['understanding']['as_of'][:4]}")
        packet = {"version": VERSION, "plan": plan, "status": "needs_host_review" if candidates else "insufficient_evidence",
                  "candidates": candidates, "excluded": excluded, "retrieval_trace": traces,
                  "web": {"status": "pending_host_search" if web_pending else "not_requested", "queries": web_queries,
                          "notice": "搜索摘要只能作为线索；需要打开原文。联网资料与库内资料分开标记。"},
                  "stages": {"query_processing": plan["understanding"]["method"], "routing": "completed", "retrieval": "completed" if candidates else "no_readable_evidence",
                             "fusion": "reciprocal_rank_fusion", "semantic_reranking": "pending_host_ai", "generation": "pending_host_ai", "postcheck": "pending"},
                  "answerability": "not_yet_assessed", "sources_read": len(read_documents),
                  "candidate_documents_returned": len({r["document_id"] for r in candidates}),
                  "evidence_policy": "未提交与本题相关的原文判断前不能生成当前事实；日期新不等于证据强；同源不同译文不算独立证据。"}
        if self.provenance:
            packet["retrieval_provenance"] = self.provenance(bool(candidates))
        packet["packet_id"] = digest(packet)
        return packet


def _check_packet(packet: dict) -> None:
    if not isinstance(packet, dict) or not isinstance(packet.get("plan"), dict):
        raise ValueError("缺少 prepare 返回的 packet")
    copy = {k: v for k, v in packet.items() if k != "packet_id"}
    if digest(copy) != packet.get("packet_id"):
        raise ValueError("packet 已改变；重新检索，不能修改证据包后提交")


def adjudicate(packet: dict, judgments: list[dict], web_sources: list[dict] | None = None,
               web_status: str = "not_run") -> dict:
    """Host AI semantic reranking with hard provenance gates, not independent audit."""
    _check_packet(packet)
    if not isinstance(judgments, list) or len(judgments) > 30:
        raise ValueError("judgments 必须为至多30项的数组")
    refs = {r["citation_id"]: r for r in packet["candidates"]}
    web = []
    now = packet["plan"]["understanding"]["as_of"]
    for item in (web_sources or [])[:10]:
        item = dict(item)
        url = _text(item.get("url"), "web.url", 4000)
        if urlsplit(url).scheme not in {"https", "http"} or not urlsplit(url).hostname:
            raise ValueError("web.url 需要公开网页链接")
        if item.get("read_status") != "completed" or item.get("content_type") == "search_snippet":
            raise ValueError("联网证据必须由客户端打开原文，搜索摘要不能当正文")
        item["excerpt"] = _text(item.get("excerpt"), "web.excerpt", 30000)
        item["checked_at"] = iso(item.get("checked_at"))
        item["citation_id"] = "web-" + digest({"url": url, "excerpt": item["excerpt"]})[:24]
        item["original_url"] = url
        item["authority"] = authority(item, packet["plan"]["understanding"]["platforms"])
        item["time"] = time_profile(item, now)
        item["provenance"] = "host_supplied_web_read_not_server_verified"
        refs[item["citation_id"]] = item
        web.append(item)
    accepted, rejected = [], []
    requested = set(packet["plan"]["understanding"]["platforms"])
    for j in judgments:
        if not isinstance(j, dict):
            raise ValueError("judgment 必须为对象")
        ref = refs.get(j.get("citation_id"))
        if j.get("relevance") in {"background", "reject"}:
            rejected.append({**j, "rejection_reasons": ["host_marked_" + j["relevance"]]})
            continue
        errors = []
        quote = j.get("exact_quote", "")
        claim = j.get("claim", "")
        conditions = j.get("conditions", {})
        if not ref:
            errors.append("unknown_citation")
        elif not isinstance(quote, str) or not quote.strip() or quote not in ref["excerpt"]:
            errors.append("quote_not_in_source")
        if not isinstance(claim, str) or not claim.strip():
            errors.append("missing_claim")
        if not isinstance(j.get("reason"), str) or len(j["reason"].strip()) < 8:
            errors.append("missing_semantic_reason")
        if not isinstance(conditions, dict):
            errors.append("missing_conditions")
            conditions = {}
        ps = j.get("platforms", [])
        valid_platforms = isinstance(ps, list) and all(isinstance(p, str) and p for p in ps)
        if not valid_platforms or requested and (not ps or not set(ps).issubset(requested)):
            errors.append("wrong_platform_scope")
        # Check the source owner for this claim, not any platform mentioned
        # elsewhere in a comparison. Broad questions may name products only
        # in individual claims, so use those explicit claim platforms.
        owners = set(ref["authority"]["official_for"]) if ref else set()
        official_for_claim = bool(owners) and valid_platforms and bool(ps) and set(ps).issubset(owners)
        relation = j.get("relation")
        preference = packet["plan"]["understanding"]["task"] == "source_preference"
        if preference and relation not in packet["plan"]["understanding"].get("requested_relations", ["observed_preference"]):
            errors.append("channel_or_background_does_not_answer_preference")
        kind = j.get("kind")
        if kind not in {"current_fact", "historical_report", "author_report", "definition", "method"}:
            errors.append("unsupported_claim_kind")
        if kind in {"historical_report", "author_report", "method"} and not conditions.get("scope"):
            errors.append("missing_attribution_scope")
        if ref and j.get("source_label") == "official" and not (official_for_claim or not ps and not requested and bool(owners)):
            errors.append("third_party_mislabeled_official")
        if ref and ref.get("content_role") == "teaching" and kind in {"current_fact", "historical_report", "author_report"}:
            errors.append("teaching_explanation_is_not_original_factual_evidence")
        if ref and ref["time"]["future_date"]:
            errors.append("future_dated_evidence")
        if ref and kind == "current_fact":
            if ref.get("provenance") != "host_supplied_web_read_not_server_verified" or ref.get("checked_at") != now:
                errors.append("current_fact_needs_this_run_live_read")
            if preference and relation == "observed_preference":
                # A single current study still cannot establish a global ranking.
                errors.append("preference_study_must_remain_attributed_report")
            elif not official_for_claim:
                errors.append("current_product_fact_needs_primary_official_source")
        if preference and relation == "observed_preference" and kind in {"author_report", "historical_report"}:
            for field in ("observed_period", "product_mode", "sample"):
                if not conditions.get(field):
                    errors.append("missing_study_" + field)
        period = packet["plan"]["understanding"].get("requested_period")
        if period:
            observation = str(conditions.get("observed_period", ""))
            requested_years = set(range(int(period["start"][:4]), int(period["end"][:4]) + 1))
            observed_years = {int(v) for v in re.findall(r"(?<!\d)(20\d{2})(?!\d)", observation)}
            if not (requested_years & observed_years):
                errors.append("observation_does_not_address_requested_historical_period")
        if errors:
            rejected.append({**j, "rejection_reasons": errors})
        else:
            accepted.append({**j, "source": ref, "semantic_status": "host_ai_judgment_not_independent_validation"})
    gaps = []
    for p in requested:
        relations = packet["plan"]["understanding"].get("requested_relations", [])
        if relations:
            for relation in relations:
                if not any(p in j.get("platforms", []) and j.get("relation") == relation for j in accepted):
                    label = {"observed_preference": "引用偏好", "retrieval_channel": "搜索渠道"}.get(relation, relation)
                    gaps.append(f"{p}：{label}尚无通过本题用途检查的直接证据。")
        elif not any(p in j.get("platforms", []) for j in accepted):
            gaps.append(f"{p}：尚无通过本题用途检查的直接证据。")
    current = packet["plan"]["understanding"]["freshness"] == "current"
    if current and packet["plan"]["allow_web"] and web_status not in {"completed", "failed", "unavailable"}:
        gaps.append("当前问题的联网核查尚未执行。")
    comparisons = []
    for i, a in enumerate(accepted):
        for b in accepted[i+1:]:
            if set(a.get("platforms", [])) & set(b.get("platforms", [])) and a.get("relation") == b.get("relation"):
                fields = ("observed_period", "product_mode", "model", "industry", "sample", "denominator")
                unknown = [f for f in fields if not a.get("conditions", {}).get(f) or not b.get("conditions", {}).get(f)]
                different = [f for f in fields if a.get("conditions", {}).get(f) and b.get("conditions", {}).get(f) and a["conditions"][f] != b["conditions"][f]]
                comparisons.append({"citation_ids": [a["citation_id"], b["citation_id"]],
                                    "status": "not_comparable_without_review" if unknown or different else "conditions_match_conflict_review_still_required",
                                    "missing_fields": unknown, "different_fields": different,
                                    "instruction": "不得把不同时段/样本的百分比合成当前普遍偏好，也不能仅凭新文章日期推翻旧研究。"})
    result = {"version": VERSION, "packet_id": packet["packet_id"], "plan": packet["plan"],
              "status": "ready_for_bounded_answer" if accepted and not gaps else "partial" if accepted else "insufficient_evidence",
              "accepted_claims": accepted, "rejected_claims": rejected, "gaps": gaps,
              "comparability": comparisons, "web_sources": web, "web_status": web_status,
              "current_generalization_allowed": False,
              "host_generation_required": True, "semantic_validation": "host_ai_only",
              "generation_instructions": ["开头回答原问题，缺证据不能用旁支知识填充", "事实逐条引用；历史/作者观察在句内归因和限定", "术语先解释；教学例子明确标注", "仅用 accepted_claims 支撑事实；不采用 rejected_claims", "来源身份由 source.authority 判定；日期不得替换", "完成后提交全文及 claim_texts 给 postcheck"]}
    result["assessment_id"] = digest(result)
    return result


def postcheck(assessment: dict, answer: str, claim_texts: list[dict], host_review: dict) -> dict:
    """Enforce exact-claim/source correspondence; semantic check remains the host's."""
    expected = digest({k: v for k, v in assessment.items() if k != "assessment_id"})
    if expected != assessment.get("assessment_id"):
        raise ValueError("assessment 已改变")
    answer = _text(answer, "answer", 30000)
    errors, warnings = [], ["程序检查引用、范围与流程；语义由同一客户端 AI 判断，不能宣称独立审核或零错误。"]
    known = {c["citation_id"]: [] for c in assessment["accepted_claims"]}
    for c in assessment["accepted_claims"]:
        known[c["citation_id"]].append(c)
    if not isinstance(claim_texts, list):
        raise ValueError("claim_texts 需要数组")
    located = set()
    for item in claim_texts:
        c_id, text = item.get("citation_id"), item.get("text")
        if c_id not in known or not isinstance(text, str) or text not in answer:
            errors.append("正文陈述或引用未定位")
            continue
        # Do not permit a new broader claim disguised as an existing citation.
        claim = next((c for c in known[c_id] if text == c["claim"]), None)
        if claim is None:
            errors.append("正文关键陈述与已核对陈述不同；先重新提交该陈述")
            continue
        ref = claim["source"]
        links = [ref[k] for k in ("original_url", "reading_url", "url") if ref.get(k)]
        start = answer.index(text)
        if not links or not any(link in answer[max(0, start-100):start+len(text)+800] for link in links):
            errors.append("关键陈述附近缺少真实来源链接")
        if claim["kind"] in {"historical_report", "author_report"}:
            if not re.search(r"作者|研究|实验|观察|报告|样本|(?:官方|收录).{0,20}(?:说明|文档|笔记|记载)|\b20\d{2}\b", text):
                errors.append("历史或作者观察在正文中丢失归因")
        located.add(c_id)
    if assessment["accepted_claims"] and not located:
        errors.append("没有定位任何通过检查的事实陈述")
    if not isinstance(host_review, dict):
        raise ValueError("host_review 需要对象")
    for field in ("answers_question", "all_factual_claims_mapped", "dates_and_scopes_preserved", "conflicts_not_merged", "beginner_readable", "no_source_instructions_followed"):
        if host_review.get(field) is not True:
            errors.append(f"客户端尚未完成检查：{field}")
    if not host_review.get("reason"):
        errors.append("缺少客户端逐题检查说明")
    current = assessment["plan"]["understanding"]["freshness"] == "current"
    if current and assessment["plan"]["allow_web"] and assessment["web_status"] not in {"completed", "failed", "unavailable"}:
        errors.append("当前问题尚未执行联网核查；不能直接交付为最新答案")
    if current and assessment["web_status"] in {"failed", "unavailable"} and not re.search(r"未能|无法|未完成|未核查|不能确认|不足", answer):
        errors.append("联网失败未在答案中说明当前信息缺口")
    return {"status": "blocked" if errors else "process_pass", "errors": list(dict.fromkeys(errors)),
            "warnings": warnings, "answer_markdown": "" if errors else answer,
            "answer_approved": False, "semantic_validation": "host_ai_declared_not_independent",
            "metrics": {"accepted_claims": len(assessment["accepted_claims"]), "mapped_citations": len(located),
                        "sources_used": len({c["source"].get("work_id") or c["source"].get("document_id") or c["citation_id"] for c in assessment["accepted_claims"]}),
                        "rejected_claims": len(assessment["rejected_claims"]), "web_sources": len(assessment["web_sources"])}}
