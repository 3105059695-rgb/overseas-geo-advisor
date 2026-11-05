#!/usr/bin/env python3
"""Add local image/PDF attachments to an exported GEO snapshot, without editing text.

Run after export_remote.py: --vault SOURCE --output SNAPSHOT/data [--report FILE].
An optional --source-map JSON object maps document IDs to vault-relative Markdown
paths. Otherwise IDs are derived from the UTF-8 POSIX relative path, as in GeoKB.
External URLs are recorded only; this helper never downloads network resources.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import tempfile
from typing import Any
from urllib.parse import unquote, urlsplit

MIMES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff",
    ".avif": "image/avif", ".ico": "image/x-icon", ".heic": "image/heic",
    ".heif": "image/heif", ".pdf": "application/pdf",
}
TEMPLATE = "/data/attachments/{document_id}/{source_version}.json"


def encode(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def document_id(relative: str) -> str:
    return "doc-" + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:20]


def _is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def safe_path(root: Path, path: Path) -> Path:
    """Reject traversal and all symlink/junction/reparse components, including files."""
    # Inspect the original components before normalizing: link/../file must not
    # hide a link traversal. Also reject any lexical escape before filesystem IO.
    path = path if path.is_absolute() else root / path
    try:
        raw_parts = path.relative_to(root).parts
    except ValueError as exc:
        raise ValueError("outside_vault") from exc
    current = root
    for part in raw_parts:
        current = current.parent if part == ".." else current / part
        if not current.is_relative_to(root):
            raise ValueError("outside_vault")
        try:
            if _is_link(current):
                raise ValueError("symlink_or_reparse")
        except FileNotFoundError:
            pass
    normalized = Path(os.path.abspath(path))
    if not normalized.is_relative_to(root):
        raise ValueError("outside_vault")
    if not normalized.resolve().is_relative_to(root):
        raise ValueError("outside_vault")
    return normalized


def _root(path: str | Path) -> Path:
    path = Path(os.path.abspath(Path(path).expanduser()))
    if _is_link(path):
        raise ValueError("Root must not be a symlink or reparse point")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("Root must be a directory")
    return resolved


def _digest(path: Path) -> dict:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return {"sha256": digest.hexdigest(), "bytes": size}


def _write(root: Path, relative: str, payload: bytes) -> None:
    target = safe_path(root, Path(relative))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.read_bytes() == payload:
        return
    # Only generated files are replaced; source documents are never passed here.
    fd, name = tempfile.mkstemp(prefix=".asset-export-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _mask_code(text: str) -> str:
    chars = list(text)
    offset = 0
    fence = None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        masked = bool(fence or marker)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        if masked:
            chars[offset:offset + len(line)] = ["\n" if c == "\n" else " " for c in line]
        offset += len(line)
    masked_text = "".join(chars)
    for match in re.finditer(r"(`+)([^`\n]*?)\1", masked_text):
        chars[match.start():match.end()] = " " * len(match[0])
    return "".join(chars)


def _closing(text: str, start: int, opener: str, closer: str) -> int | None:
    depth = 1
    i = start + 1
    angle = False
    quote = None
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if opener == "(" and char == "<" and i == start + 1:
            angle = True
        elif angle and char == ">":
            angle = False
        elif not angle:
            if quote:
                if char == quote:
                    quote = None
            elif opener == "(" and char in "\"'" and text[i - 1].isspace():
                quote = char
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return None


def _destination(value: str) -> str:
    value = value.strip()
    if value.startswith("<") and ">" in value:
        return value[1:value.index(">")]
    # Permit spaces/balanced parentheses in local names as used by Obsidian,
    # while removing a conventional optional Markdown title.
    value = re.sub(r"\s+([\"'])(?:\\.|[^\\])*?\1\s*$", "", value)
    title = re.search(r"\s+\([^()]*\)\s*$", value)
    if title and _extension(value[:title.start()]) in MIMES:
        value = value[:title.start()]
    return value.strip()


def _extension(target: str) -> str:
    clean = unquote(html.unescape(target).split("#", 1)[0].split("?", 1)[0])
    return Path(clean.replace("\\", "/")).suffix.lower()


def extract_references(text: str) -> list[dict]:
    """Extract inline/reference Markdown images, PDF links and Obsidian embeds."""
    visible = _mask_code(text)
    definitions = {}
    for match in re.finditer(r"(?m)^ {0,3}\[([^\]\n]+)\]:[ \t]*(.+)$", visible):
        definitions[" ".join(match[1].split()).casefold()] = _destination(match[2])
    found = []
    i = 0
    while i < len(visible):
        if visible[i] == "\\":
            i += 2
            continue
        begin = i
        image = visible.startswith("![", i)
        bracket = i + 1 if image else i
        if visible.startswith("[[", bracket):
            end = visible.find("]]", bracket + 2)
            if end < 0:
                i += 1
                continue
            target = text[bracket + 2:end].split("|", 1)[0].strip()
            stop = end + 2
            kind = "obsidian_image" if _extension(target) != ".pdf" else "obsidian_pdf"
            keep = _extension(target) in MIMES
        elif visible[bracket:bracket + 1] == "[":
            close = _closing(visible, bracket, "[", "]")
            if close is None:
                i += 1
                continue
            cursor = close + 1
            while cursor < len(visible) and visible[cursor] in " \t":
                cursor += 1
            target = None
            stop = close + 1
            if visible[cursor:cursor + 1] == "(":
                end = _closing(visible, cursor, "(", ")")
                if end is not None:
                    target = _destination(text[cursor + 1:end])
                    stop = end + 1
            elif visible[cursor:cursor + 1] == "[":
                end = visible.find("]", cursor + 1)
                if end >= 0:
                    label = visible[cursor + 1:end] or visible[bracket + 1:close]
                    target = definitions.get(" ".join(label.split()).casefold())
                    stop = end + 1
            elif image:
                label = " ".join(visible[bracket + 1:close].split()).casefold()
                target = definitions.get(label)
            kind = "markdown_image" if image else "markdown_pdf"
            keep = target is not None and (image or _extension(target) == ".pdf")
        else:
            i += 1
            continue
        if keep:
            found.append({"reference": text[begin:stop], "target": target, "kind": kind,
                          "line_start": text.count("\n", 0, begin) + 1,
                          "line_end": text.count("\n", 0, stop) + 1})
        # A normal link may wrap an image: [![alt](local.png)](https://...).
        # Keep looking inside skipped outer links rather than losing the image.
        i = max(stop, i + 1) if keep or image else i + 1
    return found


class VaultIndex:
    def __init__(self, vault: Path, source_map: dict[str, str] | None = None):
        self.root = vault
        self.documents = {}
        self.names = defaultdict(list)
        self.skipped_links = 0
        self.errors = []
        self._scan(vault)
        for key, relative in (source_map or {}).items():
            path = safe_path(vault, Path(relative))
            if not path.is_file() or path.suffix.lower() != ".md":
                raise ValueError("Source mapping must identify a Markdown file inside the vault")
            self.documents[key] = path

    def _scan(self, directory: Path) -> None:
        with os.scandir(directory) as stream:
            entries = sorted(stream, key=lambda e: e.name)
        for entry in entries:
            path = Path(entry.path)
            try:
                if _is_link(path):
                    self.skipped_links += 1
                    continue
                if entry.is_dir(follow_symlinks=False):
                    self._scan(path)
                elif entry.is_file(follow_symlinks=False):
                    relative = path.relative_to(self.root).as_posix()
                    if path.suffix.lower() == ".md":
                        self.documents[document_id(relative)] = path
                    if path.suffix.lower() in MIMES:
                        self.names[path.name.casefold()].append(path)
            except OSError as exc:
                self.errors.append({"path": path.relative_to(self.root).as_posix(),
                                    "reason": type(exc).__name__})

    def resolve(self, reference: dict, doc_id: str) -> tuple[Path | None, dict]:
        target = html.unescape(reference["target"]).strip()
        # Windows drives are local paths, not one-letter URL schemes.
        windows_absolute = bool(PureWindowsPath(target).drive)
        parsed = urlsplit(target) if not windows_absolute else None
        if parsed and (parsed.scheme and parsed.scheme.lower() != "file" or target.startswith("//")):
            return None, {"status": "external", "url": target,
                          "mime": MIMES.get(_extension(target))}
        if parsed and parsed.scheme.lower() == "file":
            target = parsed.path
            if parsed.netloc and parsed.netloc.lower() != "localhost":
                return None, {"status": "missing", "reason": "outside_vault"}
            if os.name == "nt" and re.match(r"^/[A-Za-z]:", target):
                target = target[1:]
        else:
            target = target.split("#", 1)[0].split("?", 1)[0]
        target = unquote(target)
        target = re.sub(r"\\([ !\"#$%&'()*+,\-./:;<=>?@\[\]^_`{|}~])", r"\1", target)
        target = target.replace("\\", "/")
        extension = Path(target).suffix.lower()
        details = {"mime": MIMES.get(extension)}
        if extension not in MIMES:
            return None, {**details, "status": "missing", "reason": "unsupported_file_type"}
        if "\x00" in target:
            return None, {**details, "status": "missing", "reason": "invalid_path"}
        source = self.documents.get(doc_id)
        is_wiki = reference["kind"].startswith("obsidian")
        candidates = []
        if Path(target).is_absolute() or PureWindowsPath(target).drive:
            candidates = [Path(target)]
        else:
            if source:
                candidates.append(source.parent / target)
            if is_wiki:
                candidates.append(self.root / target)
        for candidate in candidates:
            try:
                safe = safe_path(self.root, candidate)
                if safe.is_file():
                    return safe, {**details, "status": "available"}
            except (OSError, ValueError) as exc:
                reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                return None, {**details, "status": "missing", "reason": reason}
        if is_wiki and "/" not in target:
            matches = self.names.get(target.casefold(), [])
            if len(matches) == 1:
                try:
                    return safe_path(self.root, matches[0]), {**details, "status": "available"}
                except ValueError as exc:
                    return None, {**details, "status": "missing", "reason": str(exc)}
            if len(matches) > 1:
                return None, {**details, "status": "ambiguous", "reason": "basename_not_unique",
                              "candidate_count": len(matches)}
        reason = "source_document_unmapped" if not source and not is_wiki else "file_not_found"
        return None, {**details, "status": "missing", "reason": reason}


def _copy_asset(source: Path, vault: Path, output: Path) -> dict:
    source = safe_path(vault, source)
    media = safe_path(output, Path("media"))
    media.mkdir(exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".asset-export-", dir=media)
    temporary = Path(name)
    try:
        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as reader, os.fdopen(fd, "wb") as writer:
            before = os.fstat(reader.fileno())
            safe_path(vault, source)
            for block in iter(lambda: reader.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
                writer.write(block)
            after = os.fstat(reader.fileno())
        safe_path(vault, source)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("Attachment changed during export")
        relative = "media/" + digest.hexdigest() + source.suffix.lower()
        target = safe_path(output, Path(relative))
        info = {"sha256": digest.hexdigest(), "bytes": size}
        if not target.is_file() or _digest(target) != info:
            temporary.replace(target)
        return {"path": relative, **info}
    finally:
        temporary.unlink(missing_ok=True)


def export_assets(vault: str | Path, output: str | Path,
                  source_map: dict[str, str] | None = None) -> dict:
    vault, output = _root(vault), _root(output)
    if output.is_relative_to(vault):
        raise ValueError("Snapshot output must be outside the source vault")
    catalog_path = safe_path(output, Path("catalog.json"))
    manifest_path = safe_path(output, Path("manifest.json"))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Preserve every existing source/index entry, and fail on changed inputs.
    files = {name: value for name, value in manifest["files"].items()
             if name != "manifest.json" and not name.startswith(("media/", "attachments/"))}
    for name, info in files.items():
        if _digest(safe_path(output, Path(name))) != info:
            raise ValueError("Snapshot manifest mismatch: " + name)
    documents = []
    for doc_id, meta in sorted(catalog["documents"].items()):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", doc_id):
            raise ValueError("Unsafe document identifier")
        for version in sorted(meta["versions"]):
            if not re.fullmatch(r"[0-9a-f]{64}", version):
                raise ValueError("Invalid source version")
            name = f"documents/{doc_id}/{version}.json"
            if name not in files:
                raise ValueError("Document is absent from snapshot manifest: " + name)
            doc = json.loads(safe_path(output, Path(name)).read_text(encoding="utf-8"))
            if (doc["document_id"] != doc_id or doc["source_version"] != version or
                    hashlib.sha256(doc["text"].encode("utf-8")).hexdigest() != version):
                raise ValueError("Source identity/hash mismatch: " + name)
            documents.append((doc_id, version, extract_references(doc["text"])))
    index = VaultIndex(vault, source_map)
    status_counts = Counter()
    media_files = {}
    copy_cache = {}
    unresolved = []
    docs_with_refs = set()
    for doc_id, version, references in documents:
        if references:
            docs_with_refs.add(doc_id)
        attachments = []
        for reference in references:
            source, details = index.resolve(reference, doc_id)
            attachment = {**reference, "mime": None, "path": None, "sha256": None,
                          "bytes": None, **details}
            if source is not None:
                if source not in copy_cache:
                    copy_cache[source] = _copy_asset(source, vault, output)
                attachment.update(copy_cache[source])
                media_files[attachment["path"]] = {"sha256": attachment["sha256"],
                                                     "bytes": attachment["bytes"]}
            status_counts[attachment["status"]] += 1
            if attachment["status"] in {"missing", "ambiguous"}:
                unresolved.append({"document_id": doc_id, "source_version": version, **attachment})
            attachments.append(attachment)
        name = f"attachments/{doc_id}/{version}.json"
        payload = encode({"document_id": doc_id, "source_version": version, "attachments": attachments})
        _write(output, name, payload)
        files[name] = {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    summary = {"references": sum(status_counts.values()), "files": len(media_files),
               "bytes": sum(x["bytes"] for x in media_files.values()),
               "document_versions": len(documents), "documents_with_attachments": len(docs_with_refs),
               **{key: status_counts[key] for key in ("available", "missing", "ambiguous", "external")}}
    catalog["attachment_path_template"] = TEMPLATE
    catalog["attachment_summary"] = summary
    catalog.setdefault("counts", {}).update(attachments=len(media_files),
                                             attachment_references=summary["references"],
                                             attachment_mappings=len(documents))
    payload = encode(catalog)
    _write(output, "catalog.json", payload)
    files["catalog.json"] = {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    files.update(media_files)
    manifest["files"] = dict(sorted(files.items()))
    _write(output, "manifest.json", encode(manifest))
    return {"status": "ok", "attachment_summary": summary, "manifest_files": len(files),
            "unresolved": unresolved, "scan_errors": index.errors, "skipped_links": index.skipped_links,
            "source_text_modified": False, "source_versions_modified": False,
            "external_resources_downloaded": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="Existing snapshot data directory")
    parser.add_argument("--source-map", type=Path, help="JSON object: document_id -> vault-relative Markdown path")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    mapping = json.loads(args.source_map.read_text(encoding="utf-8-sig")) if args.source_map else None
    report = export_assets(args.vault, args.output, mapping)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_bytes(encode(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
