from __future__ import annotations

from pathlib import Path

import pikepdf
from pikepdf import Name, String

from pdf_accessibility_agent.models import RemediationAction, RemediationPlan


def apply_catalog_fixes(
    src: str | Path,
    dst: str | Path,
    *,
    language: str | None = None,
    title: str | None = None,
    set_marked: bool = True,
) -> None:
    """
    Apply safe, loss-minimizing catalog/metadata fixes.

    Does not build a structure tree from scratch (required for many PAC rules).
    """
    src, dst = Path(src), Path(dst)
    with pikepdf.open(src) as pdf:
        root = pdf.Root
        if language:
            root[Name("/Lang")] = String(language)
        if set_marked:
            mark = root.get(Name("/MarkInfo"))
            if mark is None:
                root[Name("/MarkInfo")] = pikepdf.Dictionary(Marked=True)
            else:
                mark[Name("/Marked")] = True  # type: ignore[index]
        if title:
            with pdf.open_metadata() as meta:
                meta.title = title
            di = pdf.docinfo
            if di is None:
                pdf.docinfo = pikepdf.Dictionary()
                di = pdf.docinfo
            di[Name("/Title")] = String(title)
        pdf.save(dst)


def apply_plan(src: str | Path, dst: str | Path, plan: RemediationPlan) -> None:
    """Apply a sequence of remediation actions supported by this package."""
    src_p, dst_p = Path(src), Path(dst)
    language: str | None = None
    title: str | None = None
    set_marked = True
    for step in plan.actions:
        if step.action != "set_catalog":
            raise ValueError(f"Unsupported remediation action: {step.action}")
        if step.params.get("language"):
            language = str(step.params["language"])
        if step.params.get("title"):
            title = str(step.params["title"])
        set_marked = bool(step.params.get("set_marked", set_marked))
    apply_catalog_fixes(
        src_p,
        dst_p,
        language=language,
        title=title,
        set_marked=set_marked,
    )


def rules_plan_from_gaps(
    *,
    language: str | None = None,
    title: str | None = None,
) -> RemediationPlan:
    """Deterministic plan for catalog-level gaps."""
    if not language and not title:
        return RemediationPlan(summary="No catalog actions requested.", actions=[])
    params: dict[str, object] = {"set_marked": True}
    if language:
        params["language"] = language
    if title:
        params["title"] = title
    return RemediationPlan(
        summary="Catalog/metadata fixes supported by this tool.",
        actions=[
            RemediationAction(
                action="set_catalog",
                params=params,
                rationale="Set /Lang, optional title, and /MarkInfo /Marked where applicable.",
            )
        ],
    )
