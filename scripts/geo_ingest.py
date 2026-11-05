#!/usr/bin/env python3
"""Local, source-preserving Markdown ingestion and SQLite FTS5 passage retrieval.

Only the explicitly selected output directory is written. Snapshot documents are
authoritative; an optional vault supplies original paths/byte hashes. This is a
structural parser, not visual layout recognition, OCR, or semantic deduplication.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / ".runtime" / "ingest-v05"
DEFAULT_DB = DEFAULT_OUTPUT / "index.sqlite3"
SCHEMA_VERSION = 5
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
URL = re.compile(r"https?://[^\s<>\]\)\"']+")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^\n]+?)\)|!\[\[([^\]\n]+)\]\]")
DATE = re.compile(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _tokens(text: str) -> list[str]:
    result = []
    for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*|\d+(?:\.\d+)?|[\u3400-\u9fff]+", text.lower()):
        if re.fullmatch(r"[\u3400-\u9fff]+", word):
            result.extend(word[i:i+2] for i in range(len(word)-1))
            if len(word) == 1:
                result.append(word)
        else:
            result.append(word)
    return result


def _date_value(value: str) -> str | None:
    match = DATE.search(value)
    if match:
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError:
            pass
    return None


def source_metadata(text: str, supplied: dict | None = None) -> dict:
    """Read explicit metadata labels; filesystem timestamps are never dates."""
    meta = dict(supplied or {})
    for key in ("published_at", "collected_at", "checked_at", "observed_at"):
        meta.setdefault(key, None)
    evidence = dict(meta.get("date_evidence", {}))
    fields = {
        "published_at": r"(?:原帖|原文|原始)?(?:发布时间|发布日期|发表时间|发表日期)|发帖时间|published(?:_at| date)?|publication date",
        "collected_at": r"收藏日期|收集日期|采集日期|整理日期|归档日期|collected_at",
        "checked_at": r"核查日期|核验日期|核对日期|checked_at|verified_at",
        "observed_at": r"观察日期|观测日期|读取日期|抓取日期|访问日期|observed_at|accessed_at",
    }
    for number, line in enumerate(text.splitlines()[:100], 1):
        if re.match(r"^#{2,6}\s", line):
            break
        clean = re.sub(r"^\s*[-*>]\s*", "", line).replace("**", "").strip()
        for key, labels in fields.items():
            match = re.match(r"^(?:" + labels + r")\s*[:：]\s*(.*)$", clean, re.I)
            if match and _date_value(match[1]):
                if not meta.get(key):
                    meta[key] = _date_value(match[1])
                evidence.setdefault(key, {"line": number, "label": clean.split(":")[0].split("：")[0], "raw": match[1]})
        if not meta.get("original_url") and re.match(r"^(?:原帖|原帖链接|原文链接|原文|来源|来源链接|source_url|original_url)\s*[:：]", clean, re.I):
            urls = URL.findall(clean)
            if urls:
                meta["original_url"] = urls[0].rstrip("，。")
    meta["publication_date_missing"] = not bool(meta.get("published_at"))
    meta["date_evidence"] = evidence
    meta["source_urls"] = sorted(set(URL.findall(text)))
    meta["image_refs"] = sorted(set((a or b) for a, b in IMAGE.findall(text)))
    meta["date_policy"] = "explicit_source_labels_or_catalog_only_no_filesystem_mtime"
    return meta


def _declared_role(text: str) -> tuple[str, str | None]:
    top = "\n".join(text.splitlines()[:45])
    if re.search(r"(?:资料类型|文档类型).*?(?:核查笔记|整理笔记|解读|教学)", top):
        return "source_note", "explicit_document_type"
    if re.search(r"(?:以下|下文|本文).{0,16}(?:中文全文翻译|完整中文翻译|全文翻译)", top):
        return "translation", "explicit_translation_declaration"
    if re.search(r"(?:以下|下文).{0,16}(?:原帖中文全文|原文全文)", top):
        return "source_text", "explicit_original_declaration"
    return "unclassified", None


def _role(section: list[str], fallback: str) -> tuple[str, str | None]:
    for heading in reversed(section):
        if re.search(r"OCR|光学识别|图片识别|扫描识别", heading, re.I):
            return "ocr", heading
        if re.search(r"附录|附页|页面附录|appendix", heading, re.I):
            return "page_appendix", heading
        if re.search(r"教学|讲解|给小白|模拟案例|举例|通俗解释", heading):
            return "teaching", heading
        if re.search(r"英文原文|原文正文|原文全文|原文短摘录|original text|^原文$", heading, re.I):
            return "source_text", heading
        if re.search(r"中文全文|中文翻译|全文翻译|译文|translation", heading, re.I):
            return "translation", heading
    return fallback, None


def _blocks(lines: list[str]):
    """Emit source line intervals, retaining fenced code and Markdown tables."""
    i = 0
    while i < len(lines):
        start = i
        if not lines[i].strip():
            i += 1
            continue
        if HEADING.match(lines[i]):
            yield i, i+1, "heading"
            i += 1
            continue
        fence = re.match(r"^\s*(`{3,}|~{3,})", lines[i])
        if fence:
            marker = fence[1]
            i += 1
            while i < len(lines):
                closed = re.match(r"^\s*" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*$", lines[i])
                i += 1
                if closed:
                    break
            yield start, i, "code"
            continue
        table = i+1 < len(lines) and "|" in lines[i] and bool(re.match(r"^\s*\|?\s*:?-{3,}:?\s*\|", lines[i+1]))
        if table:
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                i += 1
            yield start, i, "table"
            continue
        i += 1
        while i < len(lines) and lines[i].strip() and not HEADING.match(lines[i]) and not re.match(r"^\s*(`{3,}|~{3,})", lines[i]):
            if i+1 < len(lines) and "|" in lines[i] and re.match(r"^\s*\|?\s*:?-{3,}:?\s*\|", lines[i+1]):
                break
            i += 1
        yield start, i, "paragraph"


def segment_markdown(text: str, max_chars: int = 1400) -> list[dict]:
    """Paragraph/heading boundaries, exact source lines, explicit continuation.

    Oversized tables/code split only at source lines. Context headers/fences are
    metadata, never inserted into source text. An indivisible oversized line is
    kept whole and flagged so downstream encoders can report truncation honestly.
    """
    if max_chars < 80:
        raise ValueError("max_chars must be at least 80")
    lines = text.splitlines()
    fallback, declaration = _declared_role(text)
    section: list[str] = []
    out: list[dict] = []
    pending: dict | None = None

    def emit(value):
        if value is None:
            return
        value["text"] = "\n".join(lines[value["line_start"]-1:value["line_end"]])
        value["metadata"]["overlong_source_line"] = any(len(line) > max_chars for line in value["text"].splitlines())
        out.append(value)

    for start, end, kind in _blocks(lines):
        if kind == "heading":
            emit(pending)
            pending = None
            match = HEADING.match(lines[start])
            level = len(match[1])
            section = section[:level-1] + [match[2]]
        role, marker = _role(section, fallback)
        meta = {"block_kind": kind, "role_marker": marker or declaration, "overlap_lines": 0,
                "segmentation": "markdown_structural_boundaries_not_semantic_model"}
        if kind == "table":
            meta.update({"table_header": "\n".join(lines[start:min(start+2, end)]),
                         "table_header_line_start": start+1, "table_header_line_end": min(start+2, end)})
        if kind == "code":
            meta["code_fence"] = lines[start]
        cursor = start
        pieces = []
        while cursor < end:
            stop, size = cursor, 0
            while stop < end and (stop == cursor or size+len(lines[stop])+1 <= max_chars):
                size += len(lines[stop])+1
                stop += 1
            item = {"line_start": cursor+1, "line_end": stop, "section_path": list(section), "content_role": role, "metadata": dict(meta)}
            item["metadata"]["continued_block"] = cursor != start or stop != end
            item["metadata"]["header_repeat_required"] = kind == "table" and cursor != start
            pieces.append(item)
            cursor = stop
        for item in pieces:
            can_join = pending and kind not in {"table", "code", "heading"} and pending["metadata"]["block_kind"] not in {"table", "code"} and pending["section_path"] == item["section_path"] and pending["content_role"] == item["content_role"] and len("\n".join(lines[pending["line_start"]-1:item["line_end"]])) <= max_chars
            if can_join:
                pending["line_end"] = item["line_end"]
                pending["metadata"]["block_kind"] = "paragraph_group"
                pending["metadata"]["continued_block"] |= item["metadata"]["continued_block"]
            else:
                emit(pending)
                pending = item
    emit(pending)
    return out


def _safe_child(base: Path, relative: str) -> Path:
    result = (base / relative).resolve()
    if not result.is_relative_to(base.resolve()):
        raise ValueError("source path escapes input root")
    return result


def _read_json(path: Path, manifest: dict | None, base: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    digest = _sha(raw)
    if manifest is not None:
        relative = path.relative_to(base).as_posix()
        entry = manifest.get("files", {}).get(relative)
        if not entry or entry.get("sha256") != digest or entry.get("bytes") != len(raw):
            raise ValueError("snapshot asset manifest mismatch: " + relative)
    return json.loads(raw.decode("utf-8-sig")), digest


def load_sources(snapshot_dir: Path | None = None, vault_dir: Path | None = None,
                 include_unlisted: bool = False) -> tuple[list[dict], list[dict], dict]:
    sources, quality, inputs = [], [], {}
    vault_paths = {}
    if vault_dir:
        vault_dir = vault_dir.resolve()
        for path in sorted(vault_dir.rglob("*.md")):
            if path.is_symlink() or not path.resolve().is_relative_to(vault_dir):
                continue
            relative = path.relative_to(vault_dir).as_posix()
            vault_paths["doc-" + _sha(relative)[:20]] = (path, relative)
    catalog = {"documents": {}}
    if snapshot_dir:
        snapshot_dir = snapshot_dir.resolve()
        manifest_path = snapshot_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text("utf-8-sig")) if manifest_path.exists() else None
        if manifest:
            inputs["snapshot_manifest_sha256"] = _sha(manifest_path.read_bytes())
        catalog, inputs["catalog_sha256"] = _read_json(snapshot_dir / "catalog.json", manifest, snapshot_dir)
        inputs["knowledge_version"] = catalog.get("knowledge_version")
        for doc_id, entry in sorted(catalog["documents"].items()):
            version = entry["current_version"]
            path = _safe_child(snapshot_dir, f"documents/{doc_id}/{version}.json")
            try:
                doc, asset_hash = _read_json(path, manifest, snapshot_dir)
                text = doc.get("text")
                if not isinstance(text, str) or not text.strip():
                    quality.append({"document_id": doc_id, "reason": "missing_full_text", "source_path": str(path)})
                    continue
                if doc.get("document_id") != doc_id or doc.get("source_version") != version or _sha(text) != version:
                    raise ValueError("snapshot identity or text hash mismatch: " + doc_id)
                if doc.get("line_count") != len(text.splitlines()):
                    raise ValueError("snapshot line count mismatch: " + doc_id)
                meta = source_metadata(text, {**entry, **doc.get("metadata", {})})
                meta.pop("versions", None)
                meta["source_asset_path"] = str(path)
                meta["source_asset_sha256"] = asset_hash
                if doc_id in vault_paths:
                    original_path, relative = vault_paths[doc_id]
                    original_raw = original_path.read_bytes()
                    normalized = original_raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
                    meta.update({"original_path": str(original_path), "relative_path": relative,
                                 "original_bytes_sha256": _sha(original_raw), "original_matches_snapshot": normalized == text})
                    if normalized != text:
                        quality.append({"document_id": doc_id, "reason": "vault_newer_or_different_snapshot_kept", "source_path": str(original_path)})
                sources.append({"document_id": doc_id, "source_version": version, "work_id": meta.get("work_id", doc_id),
                                "title": meta.get("title", doc_id), "text": text, "metadata": meta})
            except (OSError, UnicodeError) as exc:
                quality.append({"document_id": doc_id, "reason": "unreadable_source", "detail": str(exc)})
    if vault_dir and (include_unlisted or snapshot_dir is None):
        for doc_id, (path, relative) in sorted(vault_paths.items()):
            if doc_id in catalog["documents"]:
                continue
            if any(part.startswith(".") for part in Path(relative).parts) or path.name.startswith("00"):
                quality.append({"relative_path": relative, "reason": "navigation_or_hidden_file_not_indexed"})
                continue
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
            except UnicodeError:
                quality.append({"relative_path": relative, "reason": "invalid_utf8"})
                continue
            if not text.strip():
                quality.append({"relative_path": relative, "reason": "missing_full_text"})
                continue
            meta = source_metadata(text, {"title": next((m[2] for line in text.splitlines() if (m := HEADING.match(line))), path.stem),
                                         "original_path": str(path), "relative_path": relative, "original_bytes_sha256": _sha(raw),
                                         "source_type": "local_markdown", "review_status": "unreviewed", "allowed_uses": ["reading_lead"]})
            work_id = "url-" + _sha(meta["original_url"])[:20] if meta.get("original_url") else "work-" + _sha(relative)[:20]
            sources.append({"document_id": doc_id, "source_version": _sha(text), "work_id": work_id,
                            "title": meta["title"], "text": text, "metadata": meta})
        for path in sorted(vault_dir.rglob("*.pdf")):
            if path.is_symlink() or not path.resolve().is_relative_to(vault_dir):
                continue
            quality.append({"relative_path": path.relative_to(vault_dir).as_posix(),
                            "reason": "pdf_native_text_or_ocr_not_attempted", "status": "needs_extraction", "indexed": False})
    inputs["mode"] = "snapshot_catalog" if snapshot_dir else "markdown_vault"
    inputs["include_unlisted"] = include_unlisted
    return sources, quality, inputs


def build_index(snapshot_dir: str | Path | None = None, vault_dir: str | Path | None = None,
                output_dir: str | Path = DEFAULT_OUTPUT, max_chars: int = 1400,
                include_unlisted: bool = False) -> dict:
    """Rebuild current derived index atomically; never delete source versions."""
    if not snapshot_dir and not vault_dir:
        raise ValueError("snapshot_dir or vault_dir is required")
    output = Path(output_dir).resolve()
    for source_root in (snapshot_dir, vault_dir):
        if source_root and output.is_relative_to(Path(source_root).resolve()):
            raise ValueError("output directory must be outside all source roots")
    sources, quality, inputs = load_sources(Path(snapshot_dir) if snapshot_dir else None,
                                          Path(vault_dir) if vault_dir else None, include_unlisted)
    output.mkdir(parents=True, exist_ok=True)
    db_path = output / "index.sqlite3"
    previous = set()
    if db_path.exists():
        old = sqlite3.connect(db_path.as_uri()+"?mode=ro", uri=True)
        try:
            previous = set(old.execute("SELECT document_id,source_version FROM sources"))
        finally:
            old.close()
    temp_db = output / "index.sqlite3.pending"
    if temp_db.exists():
        temp_db.unlink()  # only this program's incomplete derived database
    con = sqlite3.connect(temp_db)
    con.executescript("""
        CREATE TABLE sources(document_id TEXT PRIMARY KEY,source_version TEXT NOT NULL,work_id TEXT NOT NULL,
          title TEXT NOT NULL,text TEXT NOT NULL,metadata TEXT NOT NULL);
        CREATE TABLE chunks(chunk_id TEXT PRIMARY KEY,document_id TEXT NOT NULL,source_version TEXT NOT NULL,
          line_start INTEGER NOT NULL,line_end INTEGER NOT NULL,payload TEXT NOT NULL);
        CREATE INDEX chunk_source ON chunks(document_id,source_version);
        CREATE VIRTUAL TABLE passages_fts USING fts5(title_tokens,body_tokens,content='');
        CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    """)
    chunks_path = output / "chunks.jsonl.pending"
    counts = Counter()
    exact_groups: dict[str, list[str]] = {}
    for source in sources:
        exact_groups.setdefault(source["source_version"], []).append(source["document_id"])
    roles = Counter()
    provenance = []
    with chunks_path.open("w", encoding="utf-8", newline="\n") as stream:
        for source in sorted(sources, key=lambda d: d["document_id"]):
            doc_id, version, source_text = source["document_id"], source["source_version"], source["text"]
            meta = source["metadata"]
            meta["exact_duplicate_document_ids"] = exact_groups[version]
            meta["deduplication"] = "exact_text_sha256_only_no_cross_language_semantic_dedup"
            if meta["publication_date_missing"]:
                counts["documents_missing_publication_date"] += 1
                quality.append({"document_id": doc_id, "reason": "publication_date_missing", "status": "metadata_missing"})
            if re.search(r"未取得全文|正文未获取|全文待补|扫描件|待OCR|待 OCR|仅有摘要|不是全文翻译", source_text[:3500]):
                quality.append({"document_id": doc_id, "reason": "explicit_incomplete_or_non_fulltext_marker", "status": "review_source_coverage"})
            con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)", (doc_id, version, source["work_id"], source["title"], source_text, _json(meta)))
            provenance.append({"document_id": doc_id, "source_version": version, "text_sha256": _sha(source_text),
                               "source_asset_sha256": meta.get("source_asset_sha256"), "original_bytes_sha256": meta.get("original_bytes_sha256")})
            for part in segment_markdown(source_text, max_chars):
                chunk_id = "passage-" + _sha(f"v{SCHEMA_VERSION}:{max_chars}:{doc_id}:{version}:{part['line_start']}:{part['line_end']}")[:28]
                payload = {key: source[key] for key in ("document_id", "source_version", "work_id", "title")}
                payload.update(part)
                # Document metadata is preserved for direct vector/search candidates.
                payload["metadata"] = {**meta, **part["metadata"], "text_sha256": _sha(part["text"])}
                payload["chunk_id"] = chunk_id
                encoded = _json(payload)
                cursor = con.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?)", (chunk_id, doc_id, version, part["line_start"], part["line_end"], encoded))
                con.execute("INSERT INTO passages_fts(rowid,title_tokens,body_tokens) VALUES(?,?,?)",
                            (cursor.lastrowid, " ".join(_tokens(source["title"]+" "+" ".join(part["section_path"]))), " ".join(_tokens(part["text"]))))
                stream.write(encoded + "\n")
                counts["chunks"] += 1
                counts["overlong_source_line_chunks"] += bool(part["metadata"]["overlong_source_line"])
                roles[part["content_role"]] += 1
    current = {(s["document_id"], s["source_version"]) for s in sources}
    counts["documents"] = len(sources)
    counts["exact_duplicate_groups"] = sum(len(v)>1 for v in exact_groups.values())
    counts["exact_duplicate_documents"] = sum(len(v)-1 for v in exact_groups.values())
    manifest = {"schema_version": SCHEMA_VERSION, "pipeline_version": "0.5.0", "inputs": inputs,
                "segmentation": {"max_chars": max_chars, "method": "heading_paragraph_table_code_source_lines", "semantic_model": False,
                                 "long_line_policy": "retain_exact_and_flag", "synthetic_context_in_text": False},
                "counts": dict(counts), "content_roles": dict(roles), "source_manifest": provenance,
                "retired_from_generated_index_only": [{"document_id": d, "source_version": v} for d,v in sorted(previous-current)],
                "deduplication": "exact_text_sha256_only; bilingual versions remain separate",
                "quality_queue_count": len(quality), "source_mutations": 0}
    manifest["corpus_fingerprint"] = _sha(_json({"sources": provenance, "segmentation": manifest["segmentation"]}))
    con.execute("INSERT INTO metadata VALUES('manifest',?)", (_json(manifest),))
    con.commit()
    con.execute("PRAGMA optimize")
    con.close()
    os.replace(temp_db, db_path)
    os.replace(chunks_path, output / "chunks.jsonl")
    queue = "".join(_json(row)+"\n" for row in sorted(quality, key=_json))
    (output / "quality-queue.jsonl").write_text(queue, encoding="utf-8", newline="\n")
    manifest["files"] = {p.name: {"bytes": p.stat().st_size, "sha256": _sha(p.read_bytes())}
                         for p in (db_path, output / "chunks.jsonl", output / "quality-queue.jsonl")}
    (output / "manifest.json").write_text(_json(manifest)+"\n", encoding="utf-8", newline="\n")
    return manifest


class LexicalIndex:
    def __init__(self, db_path: str | Path = DEFAULT_DB):
        self.db_path = Path(db_path).resolve()

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.db_path.as_uri()+"?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()

    def search(self, query: str, limit: int = 20) -> list[dict]:
        if not isinstance(query, str) or not query.strip() or len(query) > 8000:
            raise ValueError("query must be 1-8000 characters")
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be 1-200")
        tokens = list(dict.fromkeys(_tokens(query)))[:64]
        if not tokens:
            return []
        expression = " OR ".join('"'+word.replace('"','""')+'"' for word in tokens)
        with self._connect() as con:
            rows = con.execute("SELECT c.payload,bm25(passages_fts,3.0,1.0) AS distance FROM passages_fts JOIN chunks c ON c.rowid=passages_fts.rowid WHERE passages_fts MATCH ? AND json_extract(c.payload,'$.metadata.block_kind') != 'heading' ORDER BY distance,c.chunk_id LIMIT ?", (expression, limit)).fetchall()
        return [{**json.loads(row["payload"]), "score": -row["distance"], "retrieval_channel": "lexical_fts5"} for row in rows]

    def read(self, document_id: str, source_version: str, start_line: int = 1, end_line: int | None = None) -> dict:
        with self._connect() as con:
            row = con.execute("SELECT * FROM sources WHERE document_id=? AND source_version=?", (document_id, source_version)).fetchone()
        if row is None:
            raise KeyError("source version is not in this generated index")
        lines = row["text"].splitlines()
        end_line = len(lines) if end_line is None else end_line
        if type(start_line) is not int or type(end_line) is not int or not 1 <= start_line <= end_line <= len(lines):
            raise ValueError("invalid source line range")
        excerpt = "\n".join(lines[start_line-1:end_line])
        return {"document_id": document_id, "source_version": source_version, "work_id": row["work_id"],
                "title": row["title"], "line_start": start_line, "line_end": end_line, "text": excerpt, "excerpt": excerpt,
                "metadata": json.loads(row["metadata"]), "full_source_sha256": _sha(row["text"])}


def lexical(query: str, limit: int = 20, db_path: str | Path = DEFAULT_DB) -> list[dict]:
    return LexicalIndex(db_path).search(query, limit)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--snapshot", type=Path)
    build.add_argument("--vault", type=Path)
    build.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    build.add_argument("--max-chars", type=int, default=1400)
    build.add_argument("--include-unlisted", action="store_true")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--db", type=Path, default=DEFAULT_DB)
    search.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    if args.command == "build":
        manifest = build_index(args.snapshot, args.vault, args.output, args.max_chars, args.include_unlisted)
        print(_json({key: value for key, value in manifest.items() if key != "source_manifest"}))
    else:
        print(_json(lexical(args.query, args.limit, args.db)))


if __name__ == "__main__":
    main()
