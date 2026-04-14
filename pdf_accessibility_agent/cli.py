from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from pdf_accessibility_agent.adobe_autotag import adobe_autotag_pdf
from pdf_accessibility_agent.analyzer import analyze_pdf, catalog_snapshot
from pdf_accessibility_agent.llm_agent import plan_from_openai_compatible
from pdf_accessibility_agent.local_autotag import local_autotag_pdf
from pdf_accessibility_agent.pdf_only import enforce_internal_zero_check, process_pdf_only
from pdf_accessibility_agent.remediate import apply_plan, rules_plan_from_gaps


def _load_dotenv_if_present() -> None:
    """
    Load environment variables from a local .env file if present.

    Existing environment variables are not overridden.
    """
    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[1] / ".env"]
    env_path = next((p for p in candidates if p.exists()), None)
    if env_path is None:
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        k = key.strip()
        if not k or k in os.environ:
            continue
        v = value.strip()
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        os.environ[k] = v


def main() -> None:
    _load_dotenv_if_present()
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
    p_proc.add_argument(
        "--adobe-autotag",
        action="store_true",
        help="First run Adobe PDF Auto-Tag API (needs PDF_SERVICES_* env + requirements-adobe.txt), then catalog fixes.",
    )
    p_proc.add_argument(
        "--local-autotag",
        action="store_true",
        help="Run fully local best-effort auto-tag bootstrap (no cloud login), then catalog fixes.",
    )
    p_proc.add_argument(
        "--adobe-report",
        type=Path,
        default=None,
        help="Save Adobe tagging report (e.g. .zip). Implies a tagging report is requested from Adobe.",
    )
    p_proc.add_argument(
        "--shift-headings",
        action="store_true",
        help="With --adobe-autotag: pass shift_headings to Adobe AutotagPDFParams.",
    )
    p_proc.add_argument(
        "--require-zero-check",
        action="store_true",
        help="Run internal PAC-like validation against output and auto-fix iteratively; command fails if unresolved.",
    )
    p_proc.add_argument(
        "--strict-zero-check",
        action="store_true",
        help="Treat warnings as blocking in the internal validation loop.",
    )
    p_proc.add_argument(
        "--max-fix-iterations",
        type=int,
        default=3,
        help="Maximum auto-fix rounds during --require-zero-check (default: 3, use -1 for unlimited loop).",
    )
    p_proc.add_argument(
        "--llm-zero-check",
        action="store_true",
        help="Use OpenAI-compatible model to predict PAC-zero internally each iteration.",
    )
    p_proc.add_argument(
        "--zero-check-retag-mode",
        type=str,
        choices=["auto", "local", "adobe", "none"],
        default="auto",
        help=(
            "Retag strategy during --require-zero-check repair iterations: "
            "auto (adobe when --adobe-autotag else local), local, adobe, or none."
        ),
    )
    p_proc.add_argument(
        "--no-progress-limit",
        type=int,
        default=0,
        help=(
            "Stop zero-check loop if issue count does not improve for N consecutive "
            "iterations (0 disables; useful with --max-fix-iterations -1)."
        ),
    )

    p_adobe = sub.add_parser(
        "adobe-autotag",
        help="Tagged PDF via Adobe PDF Accessibility Auto-Tag API only (no local catalog pass).",
    )
    p_adobe.add_argument("input", type=Path)
    p_adobe.add_argument("output", type=Path)
    p_adobe.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Save Adobe tagging report asset to this path.",
    )
    p_adobe.add_argument(
        "--shift-headings",
        action="store_true",
        help="Shift headings in the tagged output (Adobe API).",
    )

    p_local = sub.add_parser(
        "local-autotag",
        help="Tagged PDF via fully local best-effort auto-tag bootstrap (no Adobe login).",
    )
    p_local.add_argument("input", type=Path)
    p_local.add_argument("output", type=Path)
    p_local.add_argument("--lang", type=str, default=None, help="BCP47 language tag, e.g. en-US")
    p_local.add_argument("--title", type=str, default=None, help="Document title for metadata")

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
        if args.max_fix_iterations < -1:
            parser.error("--max-fix-iterations must be >= -1.")
        if args.no_progress_limit < 0:
            parser.error("--no-progress-limit must be >= 0.")
        if args.llm_zero_check and not args.require_zero_check:
            parser.error("--llm-zero-check requires --require-zero-check.")
        if args.zero_check_retag_mode != "auto" and not args.require_zero_check:
            parser.error("--zero-check-retag-mode requires --require-zero-check.")
        if args.no_progress_limit > 0 and not args.require_zero_check:
            parser.error("--no-progress-limit requires --require-zero-check.")
        if args.adobe_report and not args.adobe_autotag:
            parser.error("--adobe-report requires --adobe-autotag.")
        if args.adobe_autotag and args.local_autotag:
            parser.error("Use only one of --adobe-autotag or --local-autotag.")

        if args.adobe_autotag:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tagged_tmp = Path(tmp.name)
            try:
                adobe_autotag_pdf(
                    args.input,
                    tagged_tmp,
                    report_path=args.adobe_report,
                    shift_headings=args.shift_headings,
                )
                result = process_pdf_only(
                    tagged_tmp,
                    args.output,
                    language=args.lang,
                    title=args.title,
                    default_language=args.default_lang,
                    use_llm_planner=args.llm,
                    report_baseline=args.input,
                    title_baseline_path=args.input,
                )
            finally:
                tagged_tmp.unlink(missing_ok=True)
        elif args.local_autotag:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tagged_tmp = Path(tmp.name)
            try:
                local_autotag_pdf(
                    args.input,
                    tagged_tmp,
                    language=args.lang or args.default_lang,
                    title=args.title or args.input.stem.replace("_", " ").strip() or "Document",
                )
                result = process_pdf_only(
                    tagged_tmp,
                    args.output,
                    language=args.lang,
                    title=args.title,
                    default_language=args.default_lang,
                    use_llm_planner=args.llm,
                    report_baseline=args.input,
                    title_baseline_path=args.input,
                )
            finally:
                tagged_tmp.unlink(missing_ok=True)
        else:
            result = process_pdf_only(
                args.input,
                args.output,
                language=args.lang,
                title=args.title,
                default_language=args.default_lang,
                use_llm_planner=args.llm,
            )
        payload = result.to_json()
        if args.adobe_autotag:
            payload["pipeline"] = "adobe_autotag+catalog"
        elif args.local_autotag:
            payload["pipeline"] = "local_autotag+catalog"
        if args.report:
            args.report.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        if args.require_zero_check:
            retag_mode = args.zero_check_retag_mode
            if retag_mode == "auto":
                retag_mode = "adobe" if args.adobe_autotag else "local"
            validation = enforce_internal_zero_check(
                input_path=args.input,
                output_path=args.output,
                language=args.lang,
                title=args.title,
                default_language=args.default_lang,
                use_llm_planner=args.llm,
                strict=args.strict_zero_check,
                max_fix_iterations=args.max_fix_iterations,
                use_llm_validator=args.llm_zero_check,
                retag_mode=retag_mode,
                shift_headings=args.shift_headings,
                no_progress_limit=args.no_progress_limit,
            )
            payload["internal_validation"] = validation
            if args.report:
                args.report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            if not validation["passed"]:
                print(json.dumps(payload, indent=2))
                raise SystemExit(
                    "Internal zero-check failed. See internal_validation.remaining_issues for unresolved blockers."
                )
        print(json.dumps(payload, indent=2))
        return

    if args.cmd == "adobe-autotag":
        adobe_autotag_pdf(
            args.input,
            args.output,
            report_path=args.report,
            shift_headings=args.shift_headings,
        )
        return

    if args.cmd == "local-autotag":
        local_autotag_pdf(
            args.input,
            args.output,
            language=args.lang,
            title=args.title,
        )
        return


if __name__ == "__main__":
    main()
