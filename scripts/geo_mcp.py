#!/usr/bin/env python3
"""Local, stdio-only MCP adapter for the Overseas GEO evidence knowledge base.

Uses the already-installed MCP Python SDK. This entry point never builds the
index, starts an HTTP listener, or changes any client's configuration. Source
documents remain unchanged; review_geo_claim records limited local claim review
metadata. A local client runs this process as the same OS user; there is no
remote authentication.
"""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys
from typing import Annotated, Any, Literal


SERVER_NAME = "overseas-geo-advisor"
SERVER_VERSION = "0.1.0"


def client_config(db_path: str | Path) -> dict[str, Any]:
    """Return a concrete local configuration without writing it anywhere."""
    return {
        "mcpServers": {
            SERVER_NAME: {
                "command": sys.executable,
                "args": [
                    "-B", "-X", "utf8", str(Path(__file__).resolve()),
                    "--db", str(Path(db_path).expanduser().resolve()),
                ],
            }
        }
    }


def create_server(db_path: str | Path | None):
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
    from pydantic import Field

    database = Path(db_path).expanduser().resolve() if db_path else None
    server = FastMCP(
        SERVER_NAME,
        instructions=(
            "Use this local source-preserving GEO service for overseas GEO questions. "
            "Respect status, allowed_uses, review_scope, dates, conditions and gaps. "
            "An evidence_packet is NOT a verified complete answer. Never present "
            "unreviewed evidence as current product fact or core action priority. "
            "Preserve versioned citations; check_geo_answer checks structure and "
            "evidence eligibility only, NOT semantic correctness. review_geo_claim "
            "records an AI-declared limited review after exact source reading, "
            "never independent validation or current product facts. On unavailable "
            "or error, do not claim a knowledge-base lookup succeeded."
        ),
        log_level="WARNING",
    )
    # FastMCP 1.26 has no public version constructor argument; otherwise its
    # low-level server advertises the SDK version as our application version.
    server._mcp_server.version = SERVER_VERSION

    # All tools leave source documents untouched. ask_geo may save local answer
    # references inside the runtime DB so follow-ups can resolve exact citations.
    read_only = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False,
    )

    def unavailable(code: str, message: str) -> dict[str, Any]:
        return {
            "status": "unavailable", "error_code": code,
            "message": message, "answer_markdown": "",
            "citations": [], "gaps": [message],
        }

    def invoke(method: str, **kwargs: Any) -> dict[str, Any]:
        if database is None:
            return unavailable(
                "database_not_configured",
                "没有配置知识索引。请在本地使用 --db 或 GEO_KB_DB 指定已构建的数据库。",
            )
        if not database.is_file():
            return unavailable(
                "database_missing",
                "指定的知识索引不存在；本次没有完成查询，也未创建空数据库。",
            )
        try:
            from geo_kb import GeoKB
        except ImportError:
            return unavailable("runtime_missing", "缺少配套 geo_kb.py，无法查询知识库。")
        try:
            result = getattr(GeoKB(database), method)(**kwargs)
        except (ValueError, TypeError) as exc:
            # An invalid method argument is different from a successful lookup
            # with no matching evidence. Do not expose exception text/OS paths.
            return {
                "status": "error", "error_code": "invalid_argument",
                "message": "参数不满足知识库读取条件，请检查标识、版本、日期和行号范围。",
                "answer_markdown": "", "citations": [],
                "error_type": type(exc).__name__,
            }
        except Exception as exc:
            print(f"GEO tool {method} failed: {type(exc).__name__}", file=sys.stderr)
            return unavailable(
                "knowledge_read_failed",
                "知识库读取失败；请检查索引版本和本地文件，不能将本次结果视为查询成功。",
            )
        if not isinstance(result, dict):
            return unavailable("invalid_result", "知识库工具返回了无效结果。")
        return result

    def validate_date(as_of: str | None) -> None:
        if as_of is not None:
            try:
                if date.fromisoformat(as_of).isoformat() != as_of:
                    raise ValueError
            except ValueError:
                raise ValueError("as_of 必须为真实日期，格式 YYYY-MM-DD") from None

    @server.tool(annotations=read_only)
    def ask_geo(
        question: Annotated[str, Field(min_length=1, max_length=8000)],
        context: dict[str, Any] | None = None,
        previous_answer_id: Annotated[str | None, Field(max_length=240)] = None,
        focus_citation_id: Annotated[str | None, Field(max_length=512)] = None,
        as_of: Annotated[str | None, Field(max_length=10)] = None,
        detail: Literal["auto", "brief", "detailed"] = "auto",
    ) -> dict[str, Any]:
        """Answer/query overseas GEO with evidence and explicit support limits.

        context may include market/platforms/industry/goal and an observations
        list marked as user-provided data, never knowledge-base evidence.
        Pass previous_answer_id for 'the second one' follow-
        ups and focus_citation_id for a specific quoted source. as_of is the
        requested historical date, not a declaration that sources are current.
        Observe answer_kind: source-curated answer versus evidence packet.
        """
        validate_date(as_of)
        if not question.strip():
            raise ValueError("question 不能为空白")
        if context is not None and len(json.dumps(context, ensure_ascii=False)) > 16000:
            raise ValueError("context 过长；请仅发送必要业务背景和前文摘要")
        return invoke(
            "ask", question=question, context=context,
            previous_answer_id=previous_answer_id,
            focus_citation_id=focus_citation_id, as_of=as_of, detail=detail,
        )

    @server.tool(annotations=read_only)
    def search_geo(
        question: Annotated[str, Field(min_length=1, max_length=8000)],
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        as_of: Annotated[str | None, Field(max_length=10)] = None,
    ) -> dict[str, Any]:
        """Search indexed GEO text; results are evidence candidates, not truth.

        The current baseline uses lexical/CJK matching and terminology expansion.
        It does not claim vector retrieval or independently validated facts.
        """
        validate_date(as_of)
        if not question.strip():
            raise ValueError("question 不能为空白")
        return invoke("search", question=question, limit=limit, as_of=as_of)

    @server.tool(annotations=read_only)
    def read_geo_source(
        document_id: Annotated[str, Field(min_length=1, max_length=240)],
        source_version: Annotated[str, Field(min_length=1, max_length=240)],
        start_line: Annotated[int, Field(ge=1)] = 1,
        end_line: Annotated[int | None, Field(ge=1)] = None,
    ) -> dict[str, Any]:
        """Read the exact indexed document version and optional line range.

        Use document_id and source_version from a citation. This never accepts
        an arbitrary filesystem path and does not silently substitute a newer
        source. Use successive ranges for long sources when appropriate.
        """
        if end_line is not None and end_line < start_line:
            raise ValueError("end_line 不能小于 start_line")
        return invoke(
            "read_source", document_id=document_id,
            source_version=source_version, start_line=start_line, end_line=end_line,
        )

    @server.tool(annotations=read_only)
    def browse_geo_topics() -> dict[str, Any]:
        """Show actual local corpus coverage, catalogs and capability limits."""
        return invoke("browse")

    @server.tool(annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, openWorldHint=False,
        idempotentHint=False,
    ))
    def review_geo_claim(
        document_id: Annotated[str, Field(min_length=1, max_length=240)],
        source_version: Annotated[str, Field(min_length=1, max_length=240)],
        statement: Annotated[str, Field(min_length=1, max_length=4000)],
        exact_quote: Annotated[str, Field(min_length=1, max_length=16000)],
        allowed_use: Literal["attributed_report", "definition", "historical"],
        conditions: Annotated[list[str], Field(max_length=20)],
        review_note: Annotated[str, Field(min_length=1, max_length=4000)],
    ) -> dict[str, Any]:
        """Record limited AI-declared review after reading an exact source.

        This writes only local runtime review metadata, never source documents.
        The program verifies quote existence/version; semantic support remains
        the reviewing AI's declaration and requires separate checking. Only
        attributed_report, definition, historical use is allowed. It cannot
        certify current mechanisms, global ranking or action priority, or
        independent validation. Include applicable conditions and review scope.
        """
        if not statement.strip() or not exact_quote.strip() or not review_note.strip():
            raise ValueError("statement、exact_quote 和 review_note 不能为空白")
        if any(not value.strip() or len(value) > 2000 for value in conditions):
            raise ValueError("conditions 条目必须是非空、长度不超过2000的文本")
        return invoke(
            "review_claim", document_id=document_id, source_version=source_version,
            statement=statement, exact_quote=exact_quote, allowed_use=allowed_use,
            conditions=conditions, review_note=review_note,
        )

    @server.tool(annotations=read_only)
    def check_geo_answer(bundle: dict[str, Any]) -> dict[str, Any]:
        """Check versioned citations and permitted evidence use in an answer.

        bundle contains claims and citations. Claims use text/kind/main/
        citation_ids/allowed_use/conditions. This is structural and evidence-
        eligibility validation only; it cannot certify semantic entailment,
        source truth, or the reasonableness of advice. Check those separately.
        """
        if len(json.dumps(bundle, ensure_ascii=False)) > 200000:
            raise ValueError("bundle 过长；请按关键断言分批检查")
        return invoke("check_answer", bundle=bundle)

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("GEO_KB_DB"), help="Existing local SQLite index")
    parser.add_argument("--print-config", action="store_true", help="Print JSON configuration and exit; no files are changed")
    args = parser.parse_args(argv)
    if args.print_config:
        if not args.db:
            parser.error("--print-config requires --db or GEO_KB_DB")
        print(json.dumps(client_config(args.db), ensure_ascii=False, indent=2))
        return 0
    try:
        server = create_server(args.db)
    except ImportError:
        print("MCP SDK is unavailable in this Python environment. Use an existing environment with the mcp package.", file=sys.stderr)
        return 2
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
