from __future__ import annotations

from pathlib import Path

import pikepdf
from pikepdf import Name, String

from pdf_accessibility_agent.remediate import _ensure_pdfua_identification_xmp


def _as_name(value: str) -> Name:
    return Name(value if value.startswith("/") else f"/{value}")


def _ensure_mark_info(root: pikepdf.Dictionary) -> None:
    mark = root.get(Name("/MarkInfo"))
    if mark is None:
        root[Name("/MarkInfo")] = pikepdf.Dictionary(Marked=True)
        return
    mark[Name("/Marked")] = True  # type: ignore[index]


def _ensure_docinfo_and_title(pdf: pikepdf.Pdf, title: str | None) -> None:
    with pdf.open_metadata() as meta:
        if title:
            meta.title = title
        _ensure_pdfua_identification_xmp(meta)
    if title:
        di = pdf.docinfo
        if di is None:
            pdf.docinfo = pikepdf.Dictionary()
            di = pdf.docinfo
        di[Name("/Title")] = String(title)


def _ensure_minimal_structure_tree(pdf: pikepdf.Pdf) -> None:
    """
    Create a minimal structure tree when missing.

    This adds a document-level logical structure root and one top-level /Document
    StructElem. It is a best-effort local fallback and not a full semantic retagging
    engine equivalent to professional remediation tools.
    """
    root = pdf.Root
    if Name("/StructTreeRoot") in root:
        return

    parent_tree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array()))
    role_map = pikepdf.Dictionary()

    struct_root = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=Name("/StructTreeRoot"),
            ParentTree=parent_tree,
            ParentTreeNextKey=0,
            RoleMap=role_map,
            K=pikepdf.Array(),
        )
    )
    doc_elem = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=Name("/StructElem"),
            S=Name("/Document"),
            P=struct_root,
            K=pikepdf.Array(),
        )
    )
    struct_root[Name("/K")] = doc_elem
    root[Name("/StructTreeRoot")] = struct_root


def _ensure_viewer_preferences(root: pikepdf.Dictionary) -> None:
    prefs = root.get(Name("/ViewerPreferences"))
    if prefs is None:
        prefs = pikepdf.Dictionary()
        root[Name("/ViewerPreferences")] = prefs
    prefs[Name("/DisplayDocTitle")] = True  # type: ignore[index]


def local_autotag_pdf(
    input_path: str | Path,
    output_path: str | Path,
    *,
    language: str | None = None,
    title: str | None = None,
) -> None:
    """
    Apply best-effort local PDF tagging primitives without external services.

    This function intentionally avoids cloud APIs and credentials. It injects a
    minimal logical structure shell, marks the document as tagged, and sets key
    catalog metadata that PAC and PDF/UA checks commonly inspect.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    with pikepdf.open(input_path) as pdf:
        root = pdf.Root
        if language:
            root[_as_name("Lang")] = String(language)

        _ensure_mark_info(root)
        _ensure_minimal_structure_tree(pdf)
        _ensure_viewer_preferences(root)
        _ensure_docinfo_and_title(pdf, title=title)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        pdf.save(output_path)
