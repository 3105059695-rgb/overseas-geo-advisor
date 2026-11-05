#!/usr/bin/env python3
"""Export an immutable, portable GEO snapshot for the public remote service.

The SQLite database is opened read-only. Source text and version hashes are
unchanged; machine-specific metadata and mutable question/review history are
never exported. The output is data only and contains no credentials by design.
High-confidence credential patterns abort before any output is written.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from geo_kb import EXPANSIONS, POLICY, SESSION_REVIEW_ORIGIN, STOP_WORDS, _tokens, _metadata, _segments

SCHEMA_VERSION = 1
SHARD_COUNT = 128
SNIPPET_CHARS = 320
PUBLIC_META_FIELDS = (
    "title", "original_url", "published_at", "source_type", "group", "topic",
    "review_status", "classification_pending", "review_scope", "allowed_uses",
    "work_id", "publication_date_origin", "checked_at", "content_kind",
)
CREDENTIAL_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "api_token": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
}


def encode(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def token_shard(token: str, count: int = SHARD_COUNT) -> int:
    """FNV-1a over UTF-8 bytes; reproduce with TextEncoder/Math.imul in JS."""
    value = 2166136261
    for byte in token.encode("utf-8"):
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return value % count


def public_metadata(value: dict) -> dict:
    result = {key: value.get(key) for key in PUBLIC_META_FIELDS if key in value}
    url = result.get("original_url")
    if url and (not re.match(r"^https?://", url) or re.search(r"(?:feishu\.cn|larksuite\.com)/", url, re.I)):
        result["original_url"] = None
    return result


def scan_text(text: str, locator: str) -> list[dict]:
    """Return locators and rule names only, never matched credential material."""
    return [{"document": locator, "pattern": name, "count": len(matches)}
            for name, pattern in CREDENTIAL_PATTERNS.items()
            if (matches := pattern.findall(text))]


def export_database(database: str | Path, output: str | Path, supplement_dir: str | Path | None = None) -> dict:
    database = Path(database).resolve()
    output = Path(output).resolve()
    if not database.is_file():
        raise ValueError("Source database does not exist; no empty database was created")
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        meta = {row["key"]: row["value"] for row in connection.execute("SELECT key,value FROM meta")}
        if meta.get("schema_version") != "1":
            raise ValueError("Unsupported source schema")
        documents = list(connection.execute("SELECT * FROM documents WHERE active=1 ORDER BY document_id"))
        active_ids = {row["document_id"] for row in documents}
        versions = [row for row in connection.execute("SELECT * FROM versions ORDER BY document_id,source_version")
                    if row["document_id"] in active_ids]
        findings = []
        for row in versions:
            findings.extend(scan_text(row["text"], row["document_id"] + "@" + row["source_version"]))
            if hashlib.sha256(row["text"].encode("utf-8")).hexdigest() != row["source_version"]:
                raise ValueError("Source hash mismatch: " + row["document_id"])
            if len(row["text"].splitlines()) != row["line_count"]:
                raise ValueError("Source line count mismatch: " + row["document_id"])
        findings.extend(scan_text(meta.get("curated", "{}"), "curated"))
        if findings:
            raise ValueError("Credential pattern scan blocked export: " + json.dumps(findings, ensure_ascii=False))

        file_payloads: dict[str, bytes] = {}
        curated = json.loads(meta.get("curated", "{}"))
        relative_to_document = {row["relative_path"]: row for row in documents}
        for source in curated.get("sources", []):
            original_path = source.pop("relative_path", None)
            doc = relative_to_document.get(original_path)
            source.pop("reading_url", None)
            if doc:
                source["document_id"] = doc["document_id"]
                source["source_version"] = doc["current_version"]
        file_payloads["curated.json"] = encode(curated)

        claims_by_version: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for row in connection.execute("SELECT * FROM reviewed_claims ORDER BY document_id,source_version,claim_id"):
            claim = json.loads(row["claim_json"])
            # Public anonymous users cannot upgrade the corpus through another
            # user's session review. Only the source-curated static claims ship.
            if claim.get("review_origin") == SESSION_REVIEW_ORIGIN:
                continue
            claims_by_version[(row["document_id"], row["source_version"])].append({
                **claim, "document_id": row["document_id"], "source_version": row["source_version"],
                "line_start": row["line_start"], "line_end": row["line_end"],
            })
        versions_by_doc: dict[str, dict[str, int]] = defaultdict(dict)
        text_bytes = 0
        for row in versions:
            key = (row["document_id"], row["source_version"])
            document = {"document_id": row["document_id"], "source_version": row["source_version"],
                        "text": row["text"], "line_count": row["line_count"],
                        "metadata": public_metadata(json.loads(row["meta_json"])),
                        "reviewed_claims": claims_by_version[key]}
            file_payloads[f"documents/{key[0]}/{key[1]}.json"] = encode(document)
            versions_by_doc[key[0]][key[1]] = row["line_count"]
            text_bytes += len(row["text"].encode("utf-8"))

        public_documents = {}
        groups = Counter()
        for row in documents:
            public = public_metadata(json.loads(row["meta_json"]))
            public.update({"document_id": row["document_id"], "current_version": row["current_version"],
                           "work_id": row["work_id"], "versions": versions_by_doc[row["document_id"]],
                           "line_count": versions_by_doc[row["document_id"]][row["current_version"]]})
            public_documents[row["document_id"]] = public
            groups[public.get("group") or "unclassified"] += 1

        shards: list[dict[str, list[int]]] = [defaultdict(list) for _ in range(SHARD_COUNT)]
        chunks = []
        for row in connection.execute("""SELECT c.*,d.meta_json FROM chunks c JOIN documents d
                ON d.document_id=c.document_id WHERE d.active=1 AND c.source_version=d.current_version
                ORDER BY c.id"""):
            document_meta = json.loads(row["meta_json"])
            body = Counter(_tokens(row["excerpt"]))
            title = Counter(_tokens(document_meta["title"] + " " + row["heading"]))
            for token in sorted(body.keys() | title.keys()):
                shards[token_shard(token)][token].extend((row["id"], body.get(token, 0), title.get(token, 0)))
            chunks.append({"id": row["id"], "document_id": row["document_id"], "source_version": row["source_version"],
                           "line_start": row["line_start"], "line_end": row["line_end"], "heading": row["heading"],
                           "snippet": row["excerpt"][:SNIPPET_CHARS],
                           "content_hash": hashlib.sha256(re.sub(r"\s+", " ", row["excerpt"]).strip().encode("utf-8")).hexdigest(),
                           "token_count": sum(body.values())})
        file_payloads["chunks.json"] = encode(chunks)
        for index, shard in enumerate(shards):
            file_payloads[f"index/{index:02x}.json"] = encode(shard)

        policy = {**POLICY, "retrieval": "portable_lexical_cjk_bigram_with_aliases",
                  "anonymous_writes": False, "server_freeform_generation": False}
        counts = {"documents": len(documents), "source_versions": len(versions), "chunks": len(chunks),
                  "independent_sources": len({row["work_id"] for row in documents}),
                  "curated_claims": sum(len(claims) for key, claims in claims_by_version.items() if key[0] in active_ids),
                  "classification_pending": sum(bool(row.get("classification_pending")) for row in public_documents.values())}
        catalog = {"schema_version": SCHEMA_VERSION, "knowledge_version": meta.get("knowledge_version"),
                   "built_at": meta.get("built_at"), "counts": counts, "groups": dict(sorted(groups.items())),
                   "policy": policy, "tokenizer": {"stop_words": sorted(STOP_WORDS), "expansions": EXPANSIONS},
                   "documents": public_documents,
                   "search": {"chunks": "/data/chunks.json", "shard_count": SHARD_COUNT,
                              "shard_algorithm": "fnv1a_utf8_mod128", "shards": [f"/data/index/{i:02x}.json" for i in range(SHARD_COUNT)],
                              "posting_format": ["chunk_id", "body_tf", "title_tf"],
                              "average_token_count": sum(c["token_count"] for c in chunks) / max(len(chunks), 1)},
                   "document_path_template": "/data/documents/{document_id}/{source_version}.json",
                   "curated": "/data/curated.json"}
        added = []
        if supplement_dir is not None:
            # Add narrowly scoped, maintained source notes without editing the
            # owner's SQLite index or replacing any archived source/version.
            supplement = Path(supplement_dir).resolve(strict=True)
            if not supplement.is_dir():
                raise ValueError("Supplement path must be a directory")
            for path in sorted(supplement.glob("*.md")):
                text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
                if scan_text(text, path.name):
                    raise ValueError("Credential pattern in supplemental source: " + path.name)
                relative = "05_全流程与基础/官方信源说明/" + path.name
                doc_id = "doc-" + hashlib.sha256(relative.encode()).hexdigest()[:20]
                if doc_id in public_documents:
                    raise ValueError("Supplement would replace an indexed source: " + path.name)
                version = hashlib.sha256(text.encode()).hexdigest()
                m = _metadata(text, relative)
                if not m.get("original_url"):
                    raise ValueError("Supplement must identify its original source: " + path.name)
                checked = re.search(r"核查日期[：:]\s*(\d{4}-\d{2}-\d{2})", text)
                m.update(source_type="official_document_note", content_kind="Chinese source note, not full original",
                         checked_at=checked[1] if checked else None, group="05", topic="AI平台的信源与引用",
                         classification_pending=False, review_status="source_note_not_expert_approved",
                         review_scope=[], allowed_uses=["reading_lead"],
                         work_id="url-" + hashlib.sha256(m["original_url"].encode()).hexdigest()[:20])
                document = dict(document_id=doc_id, source_version=version, text=text,
                                line_count=len(text.splitlines()), metadata=m, reviewed_claims=[])
                file_payloads[f"documents/{doc_id}/{version}.json"] = encode(document)
                public_documents[doc_id] = dict(m, document_id=doc_id, current_version=version,
                                                versions={version: document["line_count"]}, line_count=document["line_count"])
                for start, end, excerpt, heading in _segments(text):
                    chunk_id = max((x["id"] for x in chunks), default=0) + 1
                    body, title = Counter(_tokens(excerpt)), Counter(_tokens(m["title"] + " " + heading))
                    for token in sorted(body.keys() | title.keys()):
                        shards[token_shard(token)][token].extend((chunk_id, body.get(token, 0), title.get(token, 0)))
                    chunks.append(dict(id=chunk_id, document_id=doc_id, source_version=version, line_start=start,
                                       line_end=end, heading=heading, snippet=excerpt[:SNIPPET_CHARS],
                                       content_hash=hashlib.sha256(re.sub(r"\s+", " ", excerpt).strip().encode()).hexdigest(),
                                       token_count=sum(body.values())))
                groups["05"] += 1
                text_bytes += len(text.encode("utf-8"))
                added.append(dict(file=path.name, document_id=doc_id, source_version=version, original_url=m["original_url"]))
            counts.update(documents=len(public_documents), source_versions=len(versions)+len(added), chunks=len(chunks),
                          independent_sources=len({d["work_id"] for d in public_documents.values()}))
            catalog["groups"] = dict(sorted(groups.items()))
            catalog["knowledge_version"] = hashlib.sha256(encode({"base": catalog["knowledge_version"], "supplements": added})).hexdigest()
            catalog["supplemental_notes"] = added
            catalog["search"]["average_token_count"] = sum(x["token_count"] for x in chunks) / max(len(chunks), 1)
            file_payloads["chunks.json"] = encode(chunks)
            for index, shard in enumerate(shards):
                file_payloads[f"index/{index:02x}.json"] = encode(shard)
        file_payloads["catalog.json"] = encode(catalog)
        manifest = {"schema_version": SCHEMA_VERSION, "knowledge_version": catalog["knowledge_version"],
                    "files": {name: {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
                              for name, payload in sorted(file_payloads.items())}}
        file_payloads["manifest.json"] = encode(manifest)
        output.mkdir(parents=True, exist_ok=True)
        for name, payload in sorted(file_payloads.items()):
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".tmp")
            temporary.write_bytes(payload)
            temporary.replace(target)
        return {"status": "ok", "counts": counts, "knowledge_version": catalog["knowledge_version"], "supplemental_notes": added,
                "files": len(file_payloads), "source_text_bytes": text_bytes,
                "output_bytes": sum(map(len, file_payloads.values())),
                "catalog_bytes": len(file_payloads["catalog.json"]), "chunks_bytes": len(file_payloads["chunks.json"]),
                "index_bytes": sum(len(file_payloads[f"index/{i:02x}.json"]) for i in range(SHARD_COUNT)),
                "max_index_shard_bytes": max(len(file_payloads[f"index/{i:02x}.json"]) for i in range(SHARD_COUNT)),
                "credential_pattern_scan": {"matched": 0, "rules": list(CREDENTIAL_PATTERNS),
                                            "scope": "all_exported_source_text_and_curated_metadata", "complete_secret_audit": False},
                "excluded": ["answer_history", "session_review_claims", "absolute_machine_paths_in_metadata", "private_reading_urls_in_metadata"],
                "source_text_modified": False}
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Directory that becomes the public /data directory")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--supplement-dir", type=Path, help="Maintained Markdown source notes to add without changing SQLite")
    args = parser.parse_args()
    report = export_database(args.db, args.output, args.supplement_dir)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_bytes(encode(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
