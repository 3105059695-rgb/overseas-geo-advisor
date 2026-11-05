"""Document routing and line-preserving passage location; no semantic approval."""
from __future__ import annotations

from collections import Counter
import math
import re
from urllib.parse import urlsplit, urlunsplit

from geo_relevance import platforms_in


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]", "", value.casefold())


def strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for item in value for s in strings(item)]
    return []


def canonical_url(value: str) -> str:
    try:
        p = urlsplit(value.rstrip("。，,;；)）]》"))
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), p.query, ""))
    except ValueError:
        return value


def is_navigation(meta: dict) -> bool:
    return meta.get("retrieval_role") == "navigation" or meta.get("content_kind") in {"work_record", "navigation", "directory"}


def title_in_question(title: str, question: str) -> bool:
    """Punctuation may vary, but Latin word boundaries may not disappear."""
    compact = normalized(title)
    if len(compact) < 8 or compact not in normalized(question):
        return False
    return all(re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", question, re.I)
               for word in re.findall(r"[a-zA-Z][a-zA-Z0-9]*", title))


def document_routes(question: str, documents: dict) -> list[dict]:
    """Keep source identity separate from the topic being looked up inside it."""
    urls = {canonical_url(u) for u in re.findall(r"https?://[^\s<>\"']+", question)}
    identities, titles, sources, anchored = [], [], [], []
    generic = {"geo", "aeo", "ai", "seo", "llm", "the", "and", "for", "with", "what", "how", "search", "sources", "citation", "citations",
               "claude", "anthropic", "grok", "xai", "chatgpt", "openai", "perplexity", "gemini", "copilot", "deepseek", "kimi"}
    words = lambda value: set(re.findall(r"[a-z][a-z0-9_-]{2,}", value.lower()))
    query_words = words(question) - generic
    title_words = {key: set(re.findall(r"[a-z][a-z0-9_-]{2,}", str(meta.get("title", "")).lower())) for key, meta in documents.items()}
    df = Counter(word for words in title_words.values() for word in words)
    pairs = lambda value: {part[i:i + 2] for part in re.findall(r"[\u3400-\u9fff]+", value) for i in range(len(part) - 1)}
    title_pairs = {key: pairs(str(meta.get("title", ""))) for key, meta in documents.items()}
    pair_df = Counter(pair for values in title_pairs.values() for pair in values)
    question_pairs = pairs(question)
    # The public author field often includes a handle, affiliation or role.
    # Requiring its entire value to occur in the question loses ordinary
    # author-name queries. Only explicit metadata/domain tokens supply this
    # stronger identity signal; topic words in titles remain weaker hints.
    source_words = {}
    for key, meta in documents.items():
        values = [value for field in ("author", "authors", "publisher") for value in strings(meta.get(field))]
        try:
            host = urlsplit(meta.get("original_url") or "").hostname or ""
        except ValueError:
            host = ""
        source_words[key] = words(" ".join(values) + " " + re.sub(r"[.-]", " ", host)) - generic - {"com", "org", "net", "www", "https", "http", "university", "founder", "author", "content"}
    source_terms = query_words & set().union(*source_words.values()) if source_words else set()
    for key, meta in documents.items():
        reason, score, anchors = None, 0, []
        for field, value in (("document_id", key), ("source_key", meta.get("source_key")), ("work_id", meta.get("work_id"))):
            if value and re.search(r"(?<![a-z0-9_-])" + re.escape(str(value)) + r"(?![a-z0-9_-])", question, re.I):
                reason, score, anchors = field, 100, [str(value)]
                break
        if not reason and meta.get("original_url") and canonical_url(meta["original_url"]) in urls:
            reason, score, anchors = "original_url", 100, [meta["original_url"]]
        if reason:
            identities.append({"document_id": key, "match_type": reason, "score": score, "anchors": anchors})
            continue
        alternatives = strings(meta.get("title")) + strings(meta.get("original_title")) + strings(meta.get("title_aliases"))
        found = next((title for title in alternatives if title_in_question(title, question)), None)
        if found:
            titles.append({"document_id": key, "match_type": "title", "score": 90 + len(normalized(found)) / 1000, "anchors": [found]})
        source_hits = sorted(source_terms & source_words[key])
        topic_words = (words(question) - source_terms) & title_words[key]
        topic_pairs = question_pairs & title_pairs[key]
        topic_score = sum(math.log(1 + len(documents) / (df[word] + 1)) for word in topic_words)
        topic_score += sum(math.log(1 + len(documents) / (pair_df[pair] + 1)) for pair in topic_pairs)
        if source_hits:
            sources.append({"document_id": key, "match_type": "source_metadata", "score": 60 + len(source_hits) * 5 + min(topic_score, 25),
                            "anchors": source_hits})
        rare = sorted(word for word in query_words & title_words[key] if df[word] <= max(8, len(documents) * .015))
        topic_anchors = sorted(pair for pair in question_pairs & title_pairs[key] if pair_df[pair] <= max(3, len(documents) * .008))
        quoted = [name for name in re.findall(r"[《\"]([^》\"]+)[》\"]", question)
                  if len(normalized(name)) >= 4 and normalized(name) in normalized(str(meta.get("title", "")))]
        if quoted or (rare and not platforms_in(question)):
            anchored.append({"document_id": key, "match_type": "metadata_anchor", "score": 20 + len(rare) + len(quoted) * 4 + min(len(topic_anchors), 2),
                             "anchors": quoted})
    # An explicit source name is a constraint, not a removable bag of topic
    # words. A competing title about that topic cannot replace the source.
    exact_titles = [item for item in titles if normalized(item["anchors"][0]) == normalized(question)]
    routes = identities or exact_titles or sources or titles or anchored
    if titles and not identities and not sources:
        best = max(item["score"] for item in titles)
        routes = [item for item in titles if item["score"] == best]
    # Catalog records nominate their source work; they must not consume the
    # evidence slots of the full text. An explicit document ID stays exact.
    work_routes = {documents[item["document_id"]].get("work_id"): item for item in routes
                   if item["match_type"] != "document_id" and documents[item["document_id"]].get("work_id")}
    existing = {item["document_id"] for item in routes}
    for key, meta in documents.items():
        if key not in existing and meta.get("work_id") in work_routes and not is_navigation(meta):
            parent = work_routes[meta["work_id"]]
            routes.append({**parent, "document_id": key, "match_type": "same_work_" + parent["match_type"]})
    return sorted(routes, key=lambda item: (is_navigation(documents[item["document_id"]]), -item["score"],
                                           -documents[item["document_id"]].get("line_count", 0), item["document_id"]))


def body_text(text: str) -> str:
    lines = []
    frontmatter = False
    for number, line in enumerate(text.splitlines()):
        value = line.strip()
        if number == 0 and value == "---":
            frontmatter = True
            continue
        if frontmatter:
            if value == "---":
                frontmatter = False
            continue
        if not value or re.match(r"^#{1,6}\s", value):
            continue
        if re.match(r"^<!--.*-->$", value):
            continue
        without_links = re.sub(r"!?\[\[.*?\]\]|!?\[[^]]*\]\([^)]*\)", "", value)
        if not re.search(r"[a-zA-Z0-9\u3400-\u9fff]", without_links):
            continue
        if re.match(r"^(?:[-*]\s*)?(?:\[\[.*\]\]|\[[^]]+\]\([^)]*\))\s*$", value):
            continue
        if re.match(r"^(?:[-*]\s*)?(?:原文|来源|原标题|原帖|source|original_url|title|发布时间)\s*[:：]", value, re.I):
            continue
        lines.append(value)
    return "\n".join(lines)


def passage_windows(text: str, start_line: int = 1, end_line: int | None = None):
    """Split on actual headings, retaining section context and original lines."""
    lines = text.splitlines()
    end_line = min(end_line or len(lines), len(lines))
    section_start, heading = start_line, ""
    sections = []
    for number in range(start_line, end_line + 1):
        if re.match(r"^#{1,6}\s", lines[number - 1].strip()):
            if number > section_start:
                sections.append((section_start, number - 1, heading))
            section_start, heading = number, re.sub(r"^#{1,6}\s*", "", lines[number - 1].strip())
    sections.append((section_start, end_line, heading))
    for a, b, heading in sections:
        while a <= b:
            # Also bound characters so the read endpoint never silently
            # shortens a passage chosen by the search endpoint.
            end, size = a - 1, 0
            while end < b and end < a + 59 and size + len(lines[end]) + 1 <= 28000:
                size += len(lines[end]) + 1
                end += 1
            if end < a:
                a += 1
                continue
            excerpt = "\n".join(lines[a - 1:end])
            if body_text(excerpt):
                yield {"line_start": a, "line_end": end, "heading": heading, "text": excerpt}
            a = end + 1


def rank_passages(text: str, terms: list[str], tokenize, start_line: int = 1, end_line: int | None = None) -> list[dict]:
    passages = list(passage_windows(text, start_line, end_line))
    for item in passages:
        item["body_tokens"] = Counter(tokenize(body_text(item["text"])))
        item["heading_tokens"] = set(tokenize(item["heading"]))
    df = Counter(term for item in passages for term in set(item["body_tokens"]) | item["heading_tokens"])
    for item in passages:
        matches = [term for term in terms if term in item["body_tokens"] or term in item["heading_tokens"]]
        score = sum(math.log(1 + (len(passages) + 1) / (df[term] + 1)) *
                    (math.log1p(item["body_tokens"].get(term, 0)) / (1 + math.log1p(sum(item["body_tokens"].values())) / 6)
                     + (3 if term in item["heading_tokens"] else 0)) for term in matches)
        item["score"] = score * (1 + len(matches) / max(1, len(terms)))
        item["matched_terms"] = matches
    return sorted((item for item in passages if item["score"] > 0 or not terms),
                  key=lambda item: (-item["score"], item["line_start"]))
