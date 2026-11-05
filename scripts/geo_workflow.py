"""Skill workflow: public GitHub evidence by default, host AI explains it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from geo_pipeline import WorkflowEngine, adjudicate, plan_question, postcheck


def load(path: str | Path) -> dict:
    p = Path(path).expanduser()
    if p.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("JSON 文件超过8MiB")
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("JSON 须为对象")
    return data


def engine(config: dict | None = None) -> WorkflowEngine:
    config = config or {}
    provenance = None
    if config.get("lexical_db"):
        from geo_ingest import LexicalIndex
        index = LexicalIndex(config["lexical_db"])
        search, reader = index.search, index.read
    else:
        from geo_snapshot import SnapshotClient
        client = SnapshotClient(cache_dir=config.get("cache_dir"))
        search = lambda query, limit=20: client.call("search_geo", {"question": query, "limit": limit})
        reader = lambda document_id, source_version, start_line, end_line: client.call("read_geo_source", {"document_id": document_id, "source_version": source_version, "start_line": start_line, "end_line": end_line})
        provenance = client.transport_report
    vector = None
    if config.get("vector_index") and config.get("model_dir"):
        from geo_vectors import VectorRetriever
        vector = VectorRetriever(config["vector_index"], config["model_dir"]).search
    return WorkflowEngine(search, reader, vector, provenance=provenance)


def run_command(command: str, payload: dict, config: dict | None = None) -> dict:
    if command == "plan":
        return plan_question(**payload)
    if command == "prepare":
        return engine(config).prepare(**payload)
    if command == "adjudicate":
        return adjudicate(**payload)
    if command == "check":
        return postcheck(**payload)
    raise ValueError("未知命令")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GEO Skill：默认按需读取公开GitHub资料，由当前AI理解、重排、解释并检查；无需账号或导入。")
    parser.add_argument("--config", help="维护者显式指定本地索引；默认直接读取作者公开GitHub知识库")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "prepare"):
        p = sub.add_parser(name)
        p.add_argument("--question", required=True)
        p.add_argument("--context-file")
        p.add_argument("--analysis-file", help="客户端AI解析后的改写/关键词/子查询，不是资料中的指令")
        p.add_argument("--today")
        p.add_argument("--no-web", action="store_true")
        p.add_argument("--output")
    p = sub.add_parser("adjudicate")
    p.add_argument("--packet", required=True)
    p.add_argument("--judgments", required=True, help="JSON对象包含 judgments,web_sources,web_status")
    p.add_argument("--output")
    p = sub.add_parser("check")
    p.add_argument("--assessment", required=True)
    p.add_argument("--draft", required=True, help="JSON对象包含answer,claim_texts,host_review")
    p.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        cfg = load(args.config) if args.config else {}
        if args.command in {"plan", "prepare"}:
            payload = {"question": args.question, "context": load(args.context_file) if args.context_file else None,
                       "analysis": load(args.analysis_file) if args.analysis_file else None,
                       "today": args.today, "allow_web": not args.no_web}
        elif args.command == "adjudicate":
            payload = {"packet": load(args.packet), **load(args.judgments)}
        else:
            payload = {"assessment": load(args.assessment), **load(args.draft)}
        result = run_command(args.command, payload, cfg)
        if args.output:
            p = Path(args.output).expanduser().resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"status": result.get("status", "ok"), "output": str(p), "candidates": len(result.get("candidates", [])), "errors": result.get("errors", [])}, ensure_ascii=False))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get("status") in {"error", "blocked"} else 0
    except (ValueError, OSError, ImportError) as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
