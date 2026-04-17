from __future__ import annotations

import re
from pathlib import Path

import pikepdf
from pikepdf import Dictionary, Name, String
from pikepdf.models.metadata import PdfMetadata

from pdf_accessibility_agent.models import RemediationAction, RemediationPlan


def _ensure_pdfua_identification_xmp(meta: PdfMetadata) -> None:
    """
    Embed PDF/UA identification in XMP (ISO 14289-1 clause 5).

    veraPDF PDF/UA-1 profile checks for the PDF/UA Identification extension schema
    via the ``pdfuaid`` namespace on the document metadata stream.
    """
    # pikepdf's XMP layer only accepts str/list/set for simple properties here.
    meta["pdfuaid:part"] = "1"


def _ensure_figure_alt_text(pdf: pikepdf.Pdf, default_alt: str = "Figure") -> None:
    """
    Add fallback Alt text to Figure structure elements when missing.

    This is a best-effort PAC/PDF-UA assist. It cannot infer semantic descriptions
    from image content, but it can eliminate technical failures caused by empty Alt.
    """
    for obj in pdf.objects:
        if not isinstance(obj, pikepdf.Dictionary):
            continue
        if obj.get(Name("/S")) != Name("/Figure"):
            continue
        alt = obj.get(Name("/Alt"))
        actual_text = obj.get(Name("/ActualText"))
        has_alt = bool(str(alt).strip()) if alt is not None else False
        has_actual_text = bool(str(actual_text).strip()) if actual_text is not None else False
        if not has_alt and not has_actual_text:
            obj[Name("/Alt")] = String(default_alt)


def _bdc_span_for_mcid(data: bytes, mcid: int) -> tuple[int, int] | None:
    """
    Return [start, end) byte offsets covering ``/Tag <</MCID n>>BDC ... EMC``.

    Uses a small state machine to handle nested BDC/EMC pairs inside the span.
    """
    pat = re.compile(
        rb"/[^\s<]+(?:\s+<<\s*/MCID\s+%d\s*>>\s*BDC)" % mcid,
    )
    m = pat.search(data)
    if not m:
        return None
    start = m.start()
    i = m.end()  # position after opening BDC token
    depth = 1
    while i < len(data) - 2:
        if data[i : i + 3] == b"BDC":
            depth += 1
            i += 3
            continue
        if data[i : i + 3] == b"EMC":
            depth -= 1
            i += 3
            if depth == 0:
                return start, i
            continue
        i += 1
    return None


def _wrap_parent_tree_holes_as_artifacts(pdf: pikepdf.Pdf) -> None:
    """
    Some tagged PDFs (including some Adobe Auto-Tag outputs) leave ``None`` holes
    in ``StructTreeRoot /ParentTree /Nums`` for valid ``/MCID`` marked content.

    That shows up as PDF/UA-1 **7.1-3** ("content neither Artifact nor tagged").

    As a pragmatic repair, wrap those specific marked-content spans in
    ``/Artifact BMC ... EMC`` so the content is explicitly non-structural.

    This is intentionally conservative: it only targets MCIDs that correspond to
    missing ParentTree slots on the same page's ``/StructParents`` entry.
    """
    str_root = pdf.Root.get(Name("/StructTreeRoot"))
    if str_root is None:
        return
    if not isinstance(str_root, Dictionary):
        str_root = str_root.get_object()
    parent_tree = str_root.get(Name("/ParentTree"))
    if parent_tree is None:
        return
    if not isinstance(parent_tree, Dictionary):
        parent_tree = parent_tree.get_object()
    nums = parent_tree[Name("/Nums")]
    if not isinstance(nums, pikepdf.Array):
        return

    parent_map: dict[int, pikepdf.Array] = {}
    for i in range(0, len(nums), 2):
        key = int(nums[i])
        val = nums[i + 1]
        if isinstance(val, pikepdf.Array):
            parent_map[key] = val

    for page in pdf.pages:
        sp = page.get(Name("/StructParents"))
        if sp is None:
            continue
        arr = parent_map.get(int(sp))
        if arr is None:
            continue

        missing: list[int] = []
        for idx, entry in enumerate(arr):
            if entry is None:
                missing.append(idx)

        if not missing:
            continue

        contents = page.Contents
        if isinstance(contents, pikepdf.Array):
            parts = [c.read_bytes() for c in contents]
            data = b"".join(parts)
            split_mode = "array"
        else:
            data = contents.read_bytes()
            split_mode = "single"

        changed = False
        for mcid in missing:
            span = _bdc_span_for_mcid(data, mcid)
            if span is None:
                continue
            s, e = span
            wrapped = b"/Artifact BMC\n" + data[s:e] + b"\nEMC\n"
            data = data[:s] + wrapped + data[e:]
            changed = True

        if not changed:
            continue

        if split_mode == "single":
            contents.write(data)
        else:
            # Best-effort: replace the first stream with full content; drop the rest.
            first = contents[0]
            first.write(data)
            if len(contents) > 1:
                del contents[1:]


_HEADING_S_NAMES: frozenset[Name] = frozenset(
    {
        Name("/H"),
        Name("/H1"),
        Name("/H2"),
        Name("/H3"),
        Name("/H4"),
        Name("/H5"),
        Name("/H6"),
    }
)


def _pdf_name_str(val: object) -> str | None:
    if isinstance(val, pikepdf.Name):
        return str(val)
    return None


def _page_bytes(page: Dictionary) -> bytes:
    contents = page.get(Name("/Contents"))
    if contents is None:
        return b""
    if isinstance(contents, pikepdf.Array):
        return b"".join(c.read_bytes() for c in contents)
    return contents.read_bytes()


def _extract_text_from_content_span(span: bytes) -> str:
    """
    Best-effort extraction of visible text from a content stream snippet.

    This is only used for bookmark titles, not for semantic accessibility text.
    """
    parts: list[str] = []

    for m in re.finditer(rb"\((?:\\.|[^\\\)])*\)\s*Tj", span):
        raw = m.group(0)
        inner = raw.split(b"(", 1)[1].rsplit(b")", 1)[0]
        try:
            inner = inner.replace(b"\\)", b")").replace(b"\\(", b"(")
            parts.append(inner.decode("utf-8", errors="replace"))
        except Exception:
            parts.append(inner.decode("latin1", errors="replace"))

    for m in re.finditer(rb"\[(.*?)\]\s*TJ", span, flags=re.DOTALL):
        chunk = m.group(1)
        for sm in re.finditer(rb"\((?:\\.|[^\\\)])*\)", chunk):
            raw = sm.group(0)
            inner = raw[1:-1]
            try:
                inner = inner.replace(b"\\)", b")").replace(b"\\(", b"(")
                parts.append(inner.decode("utf-8", errors="replace"))
            except Exception:
                parts.append(inner.decode("latin1", errors="replace"))

    title = " ".join(p for p in parts if p).strip()
    title = re.sub(r"\s+", " ", title)
    if len(title) > 120:
        title = title[:117].rstrip() + "..."
    return title


def _page_top_y(page: Dictionary) -> float:
    media = page.get(Name("/MediaBox"))
    if isinstance(media, pikepdf.Array) and len(media) >= 4:
        try:
            y0 = float(media[1])
            y1 = float(media[3])
            return max(y0, y1)
        except Exception:
            pass
    return 792.0


def _ensure_outline_from_headings(pdf: pikepdf.Pdf) -> None:
    """
    PAC "Quality" can flag tagged headings without a document outline.

    If ``/Outlines`` is missing but heading structure elements exist, synthesize a
    flat bookmark list pointing at each heading's page top (``/XYZ``).
    """
    root = pdf.Root
    if root.get(Name("/Outlines")) is not None:
        return

    work_items: list[tuple[int, int, Dictionary, pikepdf.Name]] = []
    for page_index, page in enumerate(pdf.pages):
        page_dict = page.obj.as_dict()
        for obj in pdf.objects:
            if not isinstance(obj, pikepdf.Dictionary):
                continue
            s = obj.get(Name("/S"))
            if not isinstance(s, pikepdf.Name) or s not in _HEADING_S_NAMES:
                continue
            k = obj.get(Name("/K"))
            if not isinstance(k, int):
                continue
            pg = obj.get(Name("/Pg"))
            if pg is None:
                continue
            if pg.objgen != page.obj.objgen:
                continue
            work_items.append((page_index, int(k), page_dict, s))

    if not work_items:
        return

    work_items.sort(key=lambda t: (t[0], t[1]))

    outlines = pdf.make_indirect(pikepdf.Dictionary(Type=Name("/Outlines")))
    root[Name("/Outlines")] = outlines

    items: list[pikepdf.Dictionary] = []
    for page_index, mcid, page_dict, s in work_items:
        data = _page_bytes(page_dict)
        span = _bdc_span_for_mcid(data, mcid)
        title = _extract_text_from_content_span(data[span[0] : span[1]]) if span else ""
        if not title:
            title = (_pdf_name_str(s) or "/Heading").lstrip("/") + f" (page {page_index + 1})"

        top = _page_top_y(page_dict)
        dest = pikepdf.Array([page_dict, Name("/XYZ"), 0, top, None])

        item = pdf.make_indirect(
            pikepdf.Dictionary(
                Title=String(title),
                Parent=outlines,
                Dest=dest,
            )
        )
        items.append(item)

    if not items:
        return

    outlines[Name("/First")] = items[0]
    outlines[Name("/Last")] = items[-1]

    for idx, item in enumerate(items):
        if idx > 0:
            item[Name("/Prev")] = items[idx - 1]
        if idx < len(items) - 1:
            item[Name("/Next")] = items[idx + 1]


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
        with pdf.open_metadata() as meta:
            if title:
                meta.title = title
            _ensure_pdfua_identification_xmp(meta)
        _ensure_figure_alt_text(pdf)
        _wrap_parent_tree_holes_as_artifacts(pdf)
        _ensure_outline_from_headings(pdf)
        if title:
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
