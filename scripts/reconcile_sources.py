#!/usr/bin/env python3
"""Audit vault/manifest/snapshot drift and write a separate reproducible build list.

No source, original mapping, database or snapshot is modified. New Markdown is
auto-added only in content directories with an explicit source URL. Uncertain
files remain visible review candidates; navigation and sync files stay separate.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import unquote

from geo_kb import GeoKB, _hash, _metadata
from source_metadata import source_role


def registered_paths(manifest):
    paths = {str(item.get("source_path", "")).replace("\\", "/")
             for page in manifest.get("pages", []) for item in page.get("items", []) if item.get("source_path")}
    paths.update(str(p[field]).replace("\\", "/") for p in manifest.get("papers", [])
                 for field in ("source_path", "learning_note_path", "translation_path") if p.get(field))
    return paths


def classify(relative):
    path = Path(relative)
    if any(part.startswith(".") for part in path.parts):
        return "hidden_sync_file"
    if path.name.startswith("详细教学样章"):
        return "superseded_partial_teaching_sample"
    if GeoKB._excluded(relative):
        return "navigation_or_alias"
    if source_role(relative) == "navigation":
        return "work_record"
    return "source_candidate"


def infer_new_source_mapping(relative):
    """Classify new sources by directory meaning, never legacy folder numbers.

    Existing manifest entries and maintained supplements bypass this function.
    Narrower case-study subdirectories take precedence over a monitoring root.
    """
    directories = [re.sub(r"^\d+[_\s-]*", "", part)
                   for part in Path(relative).parts[:-1]]
    names = "/".join(directories)
    if "案例" in names:
        return {"group": "06", "topic": "品牌增长"}
    if any(word in names for word in ("全流程", "入门", "基础")):
        return {"group": "01", "topic": "完整实操流程"}
    if any(word in names for word in ("监测", "可见度审计")):
        return {"group": "05", "topic": "可见度审计"}
    if any(word in names for word in ("选问题", "选题", "查询扇出")):
        return {"group": "02", "topic": "问题与选题"}
    if any(word in names for word in ("写内容", "写作", "页面结构")):
        return {"group": "03", "topic": "内容与页面优化"}
    if any(word in names for word in ("站外曝光", "外链", "公关")):
        return {"group": "04", "topic": "站外曝光与引用"}
    return None


def asset_inventory(vault, documents):
    extensions = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif"}
    names = defaultdict(list)
    for path in vault.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            names[path.name].append(path)
    refs, unique, unresolved = [], {}, []
    pattern = re.compile(r"!?\[[^\]]*\]\((<[^>]+>|(?:[^()\n]|\([^()\n]*\))+)\)|!?\[\[([^\]\n]+)\]\]")
    for document in documents:
        source = vault / document["relative_path"]
        for number, line in enumerate(source.read_text("utf-8-sig").splitlines(), 1):
            for match in pattern.finditer(line):
                target = unquote((match[1] or match[2]).split("|")[0].strip().strip("<>").strip())
                if target.startswith(("https:", "http:", "data:")):
                    continue
                target = target.split("#")[0].split("?")[0]
                if Path(target).suffix.lower() not in extensions:
                    continue
                row = dict(document_id=document["document_id"], relative_path=document["relative_path"], line=number, target=target)
                path = (source.parent / target).resolve()
                if not path.is_file():
                    candidates = names.get(Path(target).name, [])
                    path = candidates[0] if len(candidates) == 1 else None
                if path and path.is_file() and path.is_relative_to(vault):
                    relative = path.relative_to(vault).as_posix()
                    row["resolved"] = relative
                    unique[relative] = dict(path=relative, bytes=path.stat().st_size, suffix=path.suffix.lower())
                else:
                    unresolved.append(row)
                refs.append(row)
    suffixes = sorted({row["suffix"] for row in unique.values()})
    return dict(documents_scanned=len(documents), reference_occurrences=len(refs),
                referencing_documents=len({r["document_id"] for r in refs}), unique_assets=len(unique),
                total_bytes=sum(row["bytes"] for row in unique.values()),
                by_suffix={ext: dict(count=sum(r["suffix"] == ext for r in unique.values()),
                                    bytes=sum(r["bytes"] for r in unique.values() if r["suffix"] == ext)) for ext in suffixes},
                largest=sorted(unique.values(), key=lambda row: row["bytes"], reverse=True)[:15],
                unresolved=unresolved, assets=sorted(unique.values(), key=lambda row: row["path"]), references=refs)


def reconcile(vault, manifest_path, snapshot=None, include_assets=False):
    vault = Path(vault).resolve(strict=True)
    manifest_path = Path(manifest_path).resolve(strict=True)
    manifest = json.loads(manifest_path.read_text("utf-8-sig"))
    registered = registered_paths(manifest)
    catalog = json.loads((Path(snapshot) / "catalog.json").read_text("utf-8")) if snapshot else {}
    previous = catalog.get("documents", {})
    supplement_ids = {d["document_id"] for d in catalog.get("supplemental_notes", [])}
    inventory, additions, candidates = [], [], []
    for path in sorted(vault.rglob("*.md")):
        if not path.resolve().is_relative_to(vault):
            continue
        relative = path.relative_to(vault).as_posix()
        text = path.read_text("utf-8-sig").replace("\r\n", "\n")
        did, version = "doc-" + _hash(relative)[:20], _hash(text)
        metadata = _metadata(text, relative)
        category = classify(relative)
        row = dict(relative_path=relative, document_id=did, source_version=version, category=category,
                   registered=relative in registered, in_snapshot=did in previous, bytes=path.stat().st_size,
                   original_url=metadata["original_url"], published_at=metadata["published_at"])
        if did in previous:
            row["previous_version"] = previous[did]["current_version"]
            row["text_unchanged"] = version == row["previous_version"]
        if did in supplement_ids:
            row["category"] = "maintained_supplement"
        elif relative not in registered and category == "source_candidate":
            mapping = infer_new_source_mapping(relative)
            # Unknown directory meanings stay explicit review candidates.
            if metadata["original_url"] and mapping:
                row["decision"] = "include_explicit_source"
                row["inferred_mapping"] = mapping
                additions.append(row)
            else:
                row["decision"] = "needs_classification"
                candidates.append(row)
        inventory.append(row)
    derived = json.loads(json.dumps(manifest, ensure_ascii=False))
    for row in additions:
        mapping = row["inferred_mapping"]
        derived.setdefault("pages", []).append(dict(group=mapping["group"], title=mapping["topic"],
            items=[dict(source_path=row["relative_path"], discovery_origin="vault_reconciliation")]))
    derived["derived_from"] = dict(manifest_sha256=_hash(manifest_path.read_text("utf-8-sig")),
                                   added_source_paths=[row["relative_path"] for row in additions],
                                   supplements=catalog.get("supplemental_notes", []))
    report = dict(scanned_at=datetime.now(timezone.utc).isoformat(), source_files_modified=False,
                  original_mapping_modified=False, date_policy="Only explicit publication fields; filesystem dates are not publication dates",
                  source_manifest_sha256=derived["derived_from"]["manifest_sha256"],
                  counts=dict(local_markdown=len(inventory), registered=len(registered), added_sources=len(additions),
                              candidates=len(candidates), categories=dict(Counter(row["category"] for row in inventory))),
                  additions=additions, classification_candidates=candidates,
                  changed_existing=[r for r in inventory if r.get("text_unchanged") is False],
                  missing_registered=sorted(registered - {r["relative_path"] for r in inventory}),
                  snapshot_without_local=sorted(set(previous) - {r["document_id"] for r in inventory}),
                  navigation_documents=[r for r in inventory if r["category"] == "work_record" and (r["registered"] or r["in_snapshot"])],
                  inventory=inventory)
    if include_assets:
        report["assets"] = asset_inventory(vault, [r for r in inventory if r["in_snapshot"] or r in additions])
    return derived, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--assets", action="store_true", help="Measure local referenced image/PDF files; no copies")
    args = parser.parse_args()
    derived, report = reconcile(args.vault, args.manifest, args.snapshot, args.assets)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (("derived-manifest.json", derived), ("reconciliation.json", report)):
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"inventory", "assets"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
