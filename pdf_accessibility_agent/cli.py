from __future__ import annotations

import argparse
import json
from pathlib import Path

from pdf_accessibility_agent.analyzer import analyze_pdf, catalog_snapshot
from pdf_accessibility_agent.llm_agent import plan_from_openai_compatible
from pdf_accessibility_agent.pdf_only import process_pdf_only, write_report
from pdf_accessibility_agent.remediate import apply_plan, rules_plan_from_gaps


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PDF-only accessibility helper: analyze and apply catalog/metadata fixes (PAC-oriented).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_analyze = sub.add_parser("analyze", help="Print heuristic accessibility issues + catalog snapshot.")
    p_analyze.add_argument("pdf", type=Path)

    p_fix = sub.add_parser("remediate", help="Write a new PDF with catalog/metadata fixes.")
    p_fix.add_argument("input", type=Path)
    p_fix.add_argument("output", type=Path)
    p_fix.add_argument("--lang", type=str, default=None, help="BCP47 language tag, e.g. en-US")
    p_fix.add_argument("--title", type=str, default=None, help="Document title for metadata")
    p_fix.add_argument(
        "--llm",
        action="store_true",
        help="Use OPENAI_API_KEY and an OpenAI-compatible API to infer lang/title from analysis.",
    )

    p_proc = sub.add_parser(
        "process",
        help="PDF-in → PDF-out: apply catalog fixes with defaults for PDF-only inputs (lang/title).",
    )
    p_proc.add_argument("input", type=Path, help="Source PDF")
    p_proc.add_argument("output", type=Path, help="Destination PDF")
    p_proc.add_argument(
        "--lang",
        type=str,
        default=None,
        help="BCP47 tag; if omitted, uses --default-lang (default en-US).",
    )
    p_proc.add_argument(
        "--default-lang",
        type=str,
        default="en-US",
        help="Used when --lang is omitted (PDF-only inputs often lack /Lang).",
    )
    p_proc.add_argument(
        "--title",
        type=str,
        default=None,
        help="Document title; if omitted, derived from input filename.",
    )
    p_proc.add_argument(
        "--llm",
        action="store_true",
        help="Plan catalog fixes via OpenAI-compatible API (still writes output; falls back if plan empty).",
    )
    p_proc.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Write JSON report (catalog + issues before/after).",
    )

    args = parser.parse_args()

    if args.cmd == "analyze":
        issues = analyze_pdf(args.pdf)
        snap = catalog_snapshot(args.pdf)
        print(json.dumps({"catalog": snap, "issues": [i.model_dump() for i in issues]}, indent=2))
        return

    if args.cmd == "remediate":
        if args.llm:
            issues = analyze_pdf(args.input)
            snap = catalog_snapshot(args.input)
            plan = plan_from_openai_compatible(
                issues=[i.model_dump() for i in issues],
                catalog=snap,
            )
        else:
            if not args.lang and not args.title:
                parser.error("Provide --lang and/or --title, or use --llm for API-based planning.")
            plan = rules_plan_from_gaps(language=args.lang, title=args.title)
        apply_plan(args.input, args.output, plan)
        return

    if args.cmd == "process":
        result = process_pdf_only(
            args.input,
            args.output,
            language=args.lang,
            title=args.title,
            default_language=args.default_lang,
            use_llm_planner=args.llm,
        )
        if args.report:
            write_report(result, args.report)
        print(json.dumps(result.to_json(), indent=2))
        return


if __name__ == "__main__":
    main()
