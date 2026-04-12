from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
import pikepdf
from pikepdf import Pdf

from pdf_accessibility_agent.models import AccessibilityIssue, Severity


def _root_dict(pdf: Pdf) -> pikepdf.Dictionary:
    return pdf.Root  # type: ignore[return-value]


def analyze_pdf(path: str | Path) -> list[AccessibilityIssue]:
    """
    Heuristic checks commonly surfaced by PDF/UA validators (including PAC-style rules).

    This is not a full ISO 14289 implementation; use PAC/veraPDF for authoritative results.
    """
    path = Path(path)
    issues: list[AccessibilityIssue] = []

    with pikepdf.open(path) as pdf:
        root = _root_dict(pdf)

        if "/Lang" not in root or not str(root.get("/Lang", "")).strip():
            issues.append(
                AccessibilityIssue(
                    code="DOC_LANG",
                    message="Document /Lang is missing or empty (PDF/UA-1 7.1).",
                    severity=Severity.FAIL,
                )
            )

        mark = root.get("/MarkInfo")
        if mark is None:
            issues.append(
                AccessibilityIssue(
                    code="MARKINFO_MISSING",
                    message="/MarkInfo missing; PDF should declare marked content usage.",
                    severity=Severity.WARN,
                )
            )
        else:
            marked = mark.get("/Marked")  # type: ignore[union-attr]
            if marked is not True:
                issues.append(
                    AccessibilityIssue(
                        code="MARKINFO_NOT_MARKED",
                        message="/MarkInfo /Marked should be true for tagged PDF workflows.",
                        severity=Severity.WARN,
                    )
                )

        if "/StructTreeRoot" not in root:
            issues.append(
                AccessibilityIssue(
                    code="NO_STRUCT_TREE",
                    message="No /StructTreeRoot — document is not a tagged PDF (PDF/UA-1 7.1).",
                    severity=Severity.FAIL,
                )
            )

        metadata = pdf.docinfo
        title = metadata.get("/Title") if metadata else None
        if title is None or not str(title).strip():
            issues.append(
                AccessibilityIssue(
                    code="METADATA_TITLE",
                    message="Document title missing in metadata (WCAG 2.x 2.4.2 / PDF mapping).",
                    severity=Severity.WARN,
                )
            )

    doc = fitz.open(path)
    try:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            if not page.get_text("dict").get("blocks"):
                continue
            # Images without embedded descriptions are a common PAC failure when tagged.
            for img in page.get_images(full=True):
                xref = img[0]
                issues.append(
                    AccessibilityIssue(
                        code="IMAGE_XREF",
                        message="Image detected; verify Figure structure and Alt/ActualText in tagged PDF.",
                        severity=Severity.INFO,
                        page=i + 1,
                        details={"xref": int(xref)},
                    )
                )
    finally:
        doc.close()

    # Deduplicate IMAGE_XREF by xref per page for cleaner output
    deduped: list[AccessibilityIssue] = []
    seen_img: set[tuple[int, int]] = set()
    for issue in issues:
        if issue.code == "IMAGE_XREF":
            key = (issue.page or 0, int(issue.details.get("xref", 0)))
            if key in seen_img:
                continue
            seen_img.add(key)
        deduped.append(issue)
    return deduped


def catalog_snapshot(path: str | Path) -> dict[str, str]:
    """Small JSON-serializable view of catalog flags for LLM context."""
    path = Path(path)
    with pikepdf.open(path) as pdf:
        root = _root_dict(pdf)
        lang = str(root.get("/Lang", "")) if "/Lang" in root else ""
        marked = ""
        if "/MarkInfo" in root:
            m = root["/MarkInfo"]
            marked = str(m.get("/Marked", ""))  # type: ignore[index]
        struct = "yes" if "/StructTreeRoot" in root else "no"
        title = ""
        if pdf.docinfo and "/Title" in pdf.docinfo:
            title = str(pdf.docinfo["/Title"])
        return {
            "lang": lang,
            "markinfo_marked": marked,
            "struct_tree_root": struct,
            "title": title,
        }
