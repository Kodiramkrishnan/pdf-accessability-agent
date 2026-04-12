from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdf_accessibility_agent.analyzer import analyze_pdf, catalog_snapshot
from pdf_accessibility_agent.llm_agent import plan_from_openai_compatible
from pdf_accessibility_agent.models import RemediationAction, RemediationPlan
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


def process_pdf_only(
    src: str | Path,
    dst: str | Path,
    *,
    language: str | None = None,
    title: str | None = None,
    default_language: str = "en-US",
    use_llm_planner: bool = False,
) -> PdfOnlyProcessResult:
    """
    PDF-in → PDF-out: analyze, apply supported catalog fixes, re-analyze.

    When ``language`` is omitted, ``default_language`` is written and
    ``assumed_default_lang`` is True in the result (typical for PDF-only inputs
    with no /Lang). When ``title`` is omitted, the input filename stem is used.
    """
    src_p, dst_p = Path(src), Path(dst)
    snap_before = catalog_snapshot(src_p)
    issues_before = [i.model_dump() for i in analyze_pdf(src_p)]

    assumed_lang = language is None
    assumed_title = title is None
    lang = language if language is not None else default_language
    doc_title = title if title is not None else src_p.stem.replace("_", " ").strip() or "Document"

    if use_llm_planner:
        plan = plan_from_openai_compatible(
            issues=issues_before,
            catalog=snap_before,
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

    return PdfOnlyProcessResult(
        input_path=src_p,
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
