from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdf_accessibility_agent.analyzer import analyze_pdf, catalog_snapshot
from pdf_accessibility_agent.llm_agent import (
    plan_from_openai_compatible,
    predict_pac_zero_from_openai_compatible,
)
from pdf_accessibility_agent.local_autotag import local_autotag_pdf
from pdf_accessibility_agent.models import RemediationAction, RemediationPlan, Severity
from pdf_accessibility_agent.remediate import apply_plan, rules_plan_from_gaps


@dataclass
class PdfOnlyProcessResult:
    """Outcome of a PDF-only accessibility pass (catalog/metadata layer)."""

    input_path: Path
    output_path: Path
    assumed_default_lang: bool
    assumed_title_from_filename: bool
    catalog_before: dict[str, str]
    catalog_after: dict[str, str]
    issues_before: list[dict[str, Any]]
    issues_after: list[dict[str, Any]]

    def to_json(self) -> dict[str, Any]:
        return {
            "input": str(self.input_path),
            "output": str(self.output_path),
            "assumed_default_lang": self.assumed_default_lang,
            "assumed_title_from_filename": self.assumed_title_from_filename,
            "catalog_before": self.catalog_before,
            "catalog_after": self.catalog_after,
            "issues_before": self.issues_before,
            "issues_after": self.issues_after,
        }


def _stem_title(path: Path) -> str:
    return path.stem.replace("_", " ").strip() or "Document"


def process_pdf_only(
    src: str | Path,
    dst: str | Path,
    *,
    language: str | None = None,
    title: str | None = None,
    default_language: str = "en-US",
    use_llm_planner: bool = False,
    report_baseline: str | Path | None = None,
    title_baseline_path: str | Path | None = None,
) -> PdfOnlyProcessResult:
    """
    PDF-in → PDF-out: analyze, apply supported catalog fixes, re-analyze.

    When ``language`` is omitted, ``default_language`` is written and
    ``assumed_default_lang`` is True in the result (typical for PDF-only inputs
    with no /Lang). When ``title`` is omitted, the input filename stem is used.

    ``report_baseline``: if set, ``catalog_before`` / ``issues_before`` in the result
    come from this file (e.g. original PDF) while remediation still runs on ``src``
    (e.g. Adobe-tagged intermediate).

    ``title_baseline_path``: when ``title`` is None, use this path's stem for the
    document title instead of ``src``'s stem (defaults to ``report_baseline`` then ``src``).
    """
    src_p, dst_p = Path(src), Path(dst)
    baseline_p = Path(report_baseline) if report_baseline is not None else src_p
    snap_before = catalog_snapshot(baseline_p)
    issues_before = [i.model_dump() for i in analyze_pdf(baseline_p)]

    assumed_lang = language is None
    assumed_title = title is None
    lang = language if language is not None else default_language
    title_src = Path(title_baseline_path) if title_baseline_path is not None else (
        Path(report_baseline) if report_baseline is not None else src_p
    )
    doc_title = title if title is not None else _stem_title(title_src)

    snap_for_plan = catalog_snapshot(src_p)
    issues_for_plan = [i.model_dump() for i in analyze_pdf(src_p)]

    if use_llm_planner:
        plan = plan_from_openai_compatible(
            issues=issues_for_plan,
            catalog=snap_for_plan,
        )
        merged: dict[str, object] = {"set_marked": True, "language": lang, "title": doc_title}
        for step in plan.actions:
            if step.action == "set_catalog":
                for key, val in step.params.items():
                    if val not in (None, ""):
                        merged[key] = val
        plan = RemediationPlan(
            summary=plan.summary or "Merged LLM plan with PDF-only defaults.",
            actions=[RemediationAction(action="set_catalog", params=merged)],
        )
    else:
        plan = rules_plan_from_gaps(language=lang, title=doc_title)

    apply_plan(src_p, dst_p, plan)

    snap_after = catalog_snapshot(dst_p)
    issues_after = [i.model_dump() for i in analyze_pdf(dst_p)]

    display_input = baseline_p if report_baseline is not None else src_p

    return PdfOnlyProcessResult(
        input_path=display_input,
        output_path=dst_p,
        assumed_default_lang=assumed_lang,
        assumed_title_from_filename=assumed_title,
        catalog_before=snap_before,
        catalog_after=snap_after,
        issues_before=issues_before,
        issues_after=issues_after,
    )


def write_report(result: PdfOnlyProcessResult, path: str | Path) -> None:
    path = Path(path)
    path.write_text(json.dumps(result.to_json(), indent=2), encoding="utf-8")


def _blocking_issues(path: str | Path, *, strict: bool) -> list[dict[str, Any]]:
    issues = analyze_pdf(path)
    blocked: list[dict[str, Any]] = []
    for issue in issues:
        if issue.severity == Severity.FAIL:
            blocked.append(issue.model_dump())
            continue
        if strict and issue.severity == Severity.WARN:
            blocked.append(issue.model_dump())
    return blocked


def _llm_validation_blockers(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    snap = catalog_snapshot(path)
    issues = [i.model_dump() for i in analyze_pdf(path)]
    prediction = predict_pac_zero_from_openai_compatible(catalog=snap, issues=issues)
    blockers = [b.model_dump() for b in prediction.blockers]
    if prediction.predicted_zero_errors:
        blockers = []
    return blockers, prediction.model_dump()


def enforce_internal_zero_check(
    *,
    input_path: str | Path,
    output_path: str | Path,
    language: str | None,
    title: str | None,
    default_language: str,
    use_llm_planner: bool,
    strict: bool = False,
    max_fix_iterations: int = 3,
    use_llm_validator: bool = False,
) -> dict[str, Any]:
    """
    Validate the generated PDF and attempt iterative local repairs.

    The check uses this package's PAC-oriented heuristic analyzer. If blocking
    issues remain after max_fix_iterations, the caller should treat the run as
    failed and inspect the returned issues.
    """
    src = Path(input_path)
    dst = Path(output_path)
    title_seed = title if title is not None else _stem_title(src)
    lang_seed = language if language is not None else default_language

    attempts = 0
    llm_trace: list[dict[str, Any]] = []

    heuristic_blocking = _blocking_issues(dst, strict=strict)
    llm_blocking: list[dict[str, Any]] = []
    if use_llm_validator:
        llm_blocking, prediction = _llm_validation_blockers(dst)
        llm_trace.append(prediction)

    while (heuristic_blocking or llm_blocking) and attempts < max_fix_iterations:
        attempts += 1
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            local_autotag_pdf(
                dst,
                tmp_path,
                language=lang_seed,
                title=title_seed,
            )
            process_pdf_only(
                tmp_path,
                dst,
                language=language,
                title=title,
                default_language=default_language,
                use_llm_planner=use_llm_planner,
                report_baseline=src,
                title_baseline_path=src,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

        heuristic_blocking = _blocking_issues(dst, strict=strict)
        if use_llm_validator:
            llm_blocking, prediction = _llm_validation_blockers(dst)
            llm_trace.append(prediction)
        else:
            llm_blocking = []

    remaining = heuristic_blocking.copy()
    for item in llm_blocking:
        if item not in remaining:
            remaining.append(item)

    return {
        "passed": len(remaining) == 0,
        "strict": strict,
        "use_llm_validator": use_llm_validator,
        "max_fix_iterations": max_fix_iterations,
        "fix_iterations_used": attempts,
        "remaining_issues": remaining,
        "heuristic_remaining_issues": heuristic_blocking,
        "llm_remaining_blockers": llm_blocking,
        "llm_validation_trace": llm_trace,
        "check_note": (
            "Internal PAC-like gate combining rule checks and optional LLM PAC prediction. "
            "PAC desktop validator is still the final authority."
        ),
    }
