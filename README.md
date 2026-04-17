# PDF accessibility agent

Python toolkit for **PDF-in → PDF-out** passes that improve **catalog- and metadata-level** accessibility signals often checked by **PDF/UA-oriented validators** (for example [PAC](https://www.access-for-all.ch/en/pdf-lab/pac-pdf-accessibility-checker.html)). It is aimed at workflows where the only source file is a PDF.

This project **does not** replace a full accessibility audit. It applies a **narrow, automatable subset** of fixes (document language, marked-content flag, document title). **Tagged structure** (`StructTreeRoot`), reading order, figure alternatives, tables, and many other PAC rules require additional tooling or manual remediation.

## Features

- **Analyze** a PDF and print a JSON report: catalog snapshot (`/Lang`, `/MarkInfo`, presence of structure tree, title hint) plus heuristic issues aligned with common PDF/UA gaps.
- **Remediate** with explicit `--lang` / `--title`, or optional **OpenAI-compatible** planning via `--llm`.
- **Process** is the main **PDF-only** flow: sensible defaults when language or title are missing (default language and filename-based title), optional JSON report file.
- **Adobe Auto-Tag** (optional): `process --adobe-autotag` or `adobe-autotag` runs [Adobe PDF Accessibility Auto-Tag API](https://developer.adobe.com/document-services/docs/overview/pdf-accessibility-auto-tag-api/) to add a real tag structure, then applies local catalog fixes. This is the practical route toward **fewer PAC failures** from PDF-only sources; see **PAC zero errors** below.
- **Local Auto-Tag Bootstrap** (no login): `process --local-autotag` or `local-autotag` creates a best-effort local structure shell (`/StructTreeRoot`, `/MarkInfo`, metadata flags) without cloud credentials, then runs local catalog fixes.

## Requirements

- Python 3.10+ recommended (tested with 3.13 in development).
- Dependencies are listed in `requirements.txt` (`pikepdf`, `PyMuPDF`, `pydantic`, `httpx`).
- Optional Adobe integration: `requirements-adobe.txt` (includes `pdfservices-sdk`).

## Installation

```bash
cd pdf-to-pdf-convertor
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Optional — for Adobe Auto-Tag:
pip install -r requirements-adobe.txt
```

Run commands from the project directory so `python -m pdf_accessibility_agent.cli` resolves the package.

## Without Adobe credentials

You can still use this project; you just **cannot** use `process --adobe-autotag` or `adobe-autotag` (those need Adobe PDF Services keys).

**What still works (local, free):**

- **`process input.pdf output.pdf`** — sets `/Lang`, `/MarkInfo`, and document title (defaults or `--lang` / `--title`). This helps some checks but **does not create tags**, so PAC will usually still report structure issues on old or untagged PDFs.
- **`analyze`** — JSON snapshot of catalog flags and simple heuristics (useful before/after any other tool).

**What you need for PAC to go down on untagged PDFs:** something that adds a **logical structure** (tags). There is **no mature, fully free, open-source Python library** that reliably auto-tags arbitrary PDFs the way Acrobat or commercial APIs do. Practical options without Adobe API keys:

| Approach | Notes |
|----------|--------|
| **[PAC](https://www.access-for-all.ch/en/pdf-lab/pac-pdf-accessibility-checker.html)** | Free **checker** (Windows). Use it to see errors; it does not fix files. |
| **[veraPDF](https://openpreservation.org/tools/verapdf/)** | Free **validator** (PDF/UA, PDF/A). Good for CI or scripting; not a full remediatior. |
| **Microsoft Word** | Open the PDF in Word, then **Save As → PDF** and enable options that embed document structure (wording varies by version). Layout may shift; best when you have an original `.docx`. |
| **LibreOffice** | Sometimes used to round-trip PDFs; results vary and may not yield clean PDF/UA. |
| **Dedicated remediation / auto-tag products** | e.g. Equidox, CommonLook, axesPDF, PDFix, online services — often paid or trial-based; they target tagging and PAC-style fixes. |

**Adobe PDF Services:** Creating a developer account and project is how you obtain `PDF_SERVICES_CLIENT_ID` / `PDF_SERVICES_CLIENT_SECRET`. Pricing and free tiers change over time; see [Acrobat Services](https://developer.adobe.com/document-services/) if you later want API-based tagging.

## Companion: [Content Accessibility Utility on AWS](https://github.com/awslabs/content-accessibility-utility-on-aws)

[awslabs/content-accessibility-utility-on-aws](https://github.com/awslabs/content-accessibility-utility-on-aws) is a separate Python CLI/API that:

- Converts **PDF → HTML** using **Amazon Bedrock Data Automation (BDA)**.
- **Audits** and **remediates** that HTML against **WCAG 2.1** (web-oriented checks, often with **Bedrock** models).

It is **not** a PAC replacement and **does not** prove **PDF/UA** or **PAC** compliance on a **PDF** file.

| | **PAC** (your target checker) | **Content Accessibility Utility on AWS** |
|--|-------------------------------|-------------------------------------------|
| **Input** | PDF | PDF (then works on HTML) |
| **Primary output** | N/A (checker only) | Accessible **HTML** + reports |
| **Standard emphasis** | PDF/UA + WCAG as applied to **PDF** | WCAG **2.1** on **HTML** |

So **“zero errors in PAC”** and **“zero issues from the AWS HTML audit”** are **different goals**. If your deliverable is a **website/HTML** version of the document, the AWS utility is relevant. If your deliverable must stay a **PDF** and pass **PAC**, you still need **PDF tagging/remediation** (and you can keep using this repo’s `process` for catalog metadata, plus PAC/veraPDF on the PDF).

### Using the AWS utility (high level)

Requirements from the upstream project: **AWS account**, **S3 bucket**, **BDA project ARN**, **AWS credentials** (and Bedrock access for audit/remediation). Python **3.11+** is expected for their package.

```bash
# Typos match the PyPI package name as published upstream
pip install content-accessibilty-utility-on-aws

export BDA_S3_BUCKET=your-bucket
export BDA_PROJECT_ARN=arn:aws:bedrock:region:account:project/...

content-accessibilty-utility-on-aws process --input document.pdf --output ./cau-output/
```

See the [official README](https://github.com/awslabs/content-accessibility-utility-on-aws/blob/main/README.md) for `convert`, `audit`, `remediate`, YAML config, and batch processing.

### Suggested combined workflow (PDF + HTML)

1. **PAC / PDF:** Tag and fix the **PDF** until PAC is clean (or as clean as required).
2. **Optional HTML:** Run the **Content Accessibility Utility** on the same source PDF if you also publish an HTML version.
3. **Metadata:** Run **`python -m pdf_accessibility_agent.cli process`** on the final PDF if you still need consistent `/Lang`, title, and `/MarkInfo`.

This repository does **not** bundle or wrap the AWS package; install it in its own venv or environment if dependency versions differ.

## Command-line usage

```bash
python -m pdf_accessibility_agent.cli --help
```

### `analyze`

Prints catalog fields and a list of heuristic issues (JSON to stdout).

```bash
python -m pdf_accessibility_agent.cli analyze document.pdf
```

### `remediate`

Writes a new PDF with supported catalog/metadata updates. You must pass **`--lang` and/or `--title`**, unless you use **`--llm`**.

```bash
python -m pdf_accessibility_agent.cli remediate input.pdf output.pdf --lang en-US --title "Quarterly report"
```

With an LLM planner (requires environment variables below):

```bash
python -m pdf_accessibility_agent.cli remediate input.pdf output.pdf --llm
```

### `process` (PDF-only workflow)

Single-step pipeline: analyze → apply defaults/overrides → write output → print a JSON summary (before/after catalog and issues). If `--lang` is omitted, **`--default-lang`** is used (default `en-US`). If `--title` is omitted, the title is derived from the **input filename**.

```bash
python -m pdf_accessibility_agent.cli process input.pdf output.pdf
python -m pdf_accessibility_agent.cli process input.pdf output.pdf --lang hi-IN --title "Annual report"
python -m pdf_accessibility_agent.cli process input.pdf output.pdf --report report.json
```

With **`--llm`**, catalog-related suggestions from the API are **merged** with the PDF-only defaults (so filename-based title and default language are not dropped when the model omits them).

### `process --adobe-autotag` (best effort toward PAC)

1. Create credentials for **PDF Accessibility Auto-Tag API** at [Adobe Acrobat Services](https://acrobatservices.adobe.com/dc-integration-creation-app-cdn/main.html?api=pdf-accessibility-auto-tag-api).
2. Export:

   - `PDF_SERVICES_CLIENT_ID`
   - `PDF_SERVICES_CLIENT_SECRET`

3. Run (tags the PDF in the cloud, then sets `/Lang`, `/MarkInfo`, title locally):

```bash
python -m pdf_accessibility_agent.cli process input.pdf output.pdf --adobe-autotag \
  --adobe-report tagging-report.zip \
  --report summary.json
```

Optional: `--shift-headings` (forwarded to Adobe). Auto-tag only (no local catalog pass):

```bash
python -m pdf_accessibility_agent.cli adobe-autotag input.pdf tagged.pdf --report report.zip
```

Adobe states that tagged output may still need **further remediation** for full WCAG/PDF/UA; always re-check in **PAC**.

### `process --local-autotag` (fully local, no Adobe login)

Use this when you need a fully offline/independent pipeline:

```bash
python -m pdf_accessibility_agent.cli process input.pdf output.pdf --local-autotag --report summary.json
```

Auto-tag only (no additional catalog pass):

```bash
python -m pdf_accessibility_agent.cli local-autotag input.pdf tagged.pdf --lang en-US --title "My document"
```

This mode is a **best-effort bootstrap** for tag-related catalog entries and does **not** guarantee full semantic tagging or zero PAC errors on arbitrary PDFs.

### Internal validation + auto-fix loop

You can enforce an internal PAC-like gate after output generation:

```bash
python -m pdf_accessibility_agent.cli process input.pdf output.pdf \
  --local-autotag \
  --require-zero-check \
  --max-fix-iterations 5 \
  --report summary.json
```

What this does:

- Runs internal checks on the generated output.
- If blocking issues remain, retries local fixes iteratively.
- Fails the command (non-zero exit) if unresolved blockers remain after max iterations.

Optional strict mode:

```bash
python -m pdf_accessibility_agent.cli process input.pdf output.pdf \
  --local-autotag \
  --require-zero-check \
  --strict-zero-check
```

`--strict-zero-check` treats warnings as blockers during internal validation.

### LLM-based PAC prediction in the loop

If you want model-based validation during each iteration, enable:

```bash
python -m pdf_accessibility_agent.cli process input.pdf output.pdf \
  --local-autotag \
  --require-zero-check \
  --llm-zero-check \
  --max-fix-iterations 10 \
  --report summary.json
```

Notes:

- Requires `OPENAI_API_KEY` (and optional `OPENAI_BASE_URL`, `OPENAI_MODEL`).
- The model prediction is included in `internal_validation.llm_validation_trace`.
- This is still a **prediction gate**, not the PAC application itself; PAC remains the external source of truth.

## LLM integration (optional)

`remediate --llm` and `process --llm` call an **OpenAI-compatible** `POST .../chat/completions` endpoint using **httpx**.

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Bearer token (required for `--llm`). |
| `OPENAI_BASE_URL` | Optional. Default `https://api.openai.com/v1`. |
| `OPENAI_MODEL` | Optional. Default `gpt-4o-mini`. |

## Python API

```python
from pathlib import Path
from pdf_accessibility_agent.pdf_only import process_pdf_only, write_report

result = process_pdf_only(
    Path("input.pdf"),
    Path("output.pdf"),
    language="en-US",          # or None to use default_language
    title="My title",          # or None to use filename stem
    default_language="en-US",
    use_llm_planner=False,
)
write_report(result, "report.json")
```

Lower-level pieces live under `pdf_accessibility_agent/` (`analyzer`, `remediate`, `llm_agent`, `models`).

## PAC and limitations

- **[PAC](https://www.access-for-all.ch/en/pdf-lab/pac-pdf-accessibility-checker.html)** is a common **manual** checker on Windows. This repo does not invoke PAC; validate outputs yourself in PAC when that is your acceptance test.
- **Guaranteed zero PAC errors** is **not** something this repo can promise: PAC includes checks that need human judgment (reading order, meaning of alt text, contrast, complex tables). The **local-only** `process` command (without Adobe) fixes metadata only and **cannot** clear failures that require a **tagged structure** (`StructTreeRoot`).
- For PDF-only inputs, **`process --adobe-autotag`** (requires Adobe API credentials) is one way to add **machine-generated tags** before your local metadata pass. **Without Adobe**, use another tagging/remediation product or workflow (see **Without Adobe credentials** above), then you can still run **`process`** on the result to normalize language and title.
- For automated **machine-readable** checks in CI, consider [veraPDF](https://openpreservation.org/tools/verapdf/) or similar; results will still differ slightly from PAC wording.

### Saving and sharing PAC results

PAC is mostly a **Windows** desktop app. If you need a report you can email or attach:

- **PAC 2024:** After the check finishes, use the **PDF Report** (or similarly named export) control in the toolbar or results area to save an **accessible PDF summary** (often you can choose **PDF/UA** and/or **WCAG** style summaries). That file is meant to be shared as evidence of the run.
- **Screenshots:** Use the **Snipping Tool** / **Snip & Sketch** (Windows) or your OS screenshot tool on the **summary** panel and on one **drill-down** detail view so others can see *which* rule is failing.
- **Copy text:** In the detailed results tree, try selecting rows and **Ctrl+C**; some versions copy lines to the clipboard (depends on PAC build).

**If you cannot use PAC’s export:** Install [veraPDF](https://openpreservation.org/tools/verapdf/) and run a text/XML report, for example:

```bash
# macOS (Homebrew)
brew install verapdf
verapdf --version
verapdf --format text your.pdf > report.txt
```

If you see **`zsh: command not found: verapdf`**, Homebrew’s `bin` is not on your `PATH`. Apple Silicon is usually `/opt/homebrew/bin`; Intel Macs often `/usr/local/bin`. Add the line Homebrew printed at install time (e.g. `eval "$(/opt/homebrew/bin/brew shellenv)"`) to your `~/.zprofile`, then open a new terminal.

The wording will not match PAC exactly, but `report.txt` is easy to paste into a chat or ticket.

### Why PAC shows thousands of “content” errors

A count like **~4740 content errors** usually means PAC is flagging **many separate places** in the file (often **each piece of untagged or wrongly tagged content**), not 4740 completely different problems. Typical root causes on **old or Distiller-era PDFs** (like untagged scans or legacy exports):

- **No or incomplete tag structure** — real text and graphics are not tied to a correct **structure tree** / reading order.
- **Figures, links, or artifacts** — missing or inconsistent handling vs. PDF/UA expectations.

Fixing that is **document-wide remediation** (tagging tool or Acrobat), not a small metadata tweak. **Two font errors** are separate: often **font embedding**, **encoding**, or **ToUnicode** issues; Acrobat **Preflight** (“Embed fonts”) or recreating the PDF from a source file with fonts embedded usually addresses those.

You can still share a **rough summary** without PAC export: run **`analyze`** from this project and paste the JSON, plus PAC’s **top-level summary line** (PDF/UA pass/fail, WCAG) from a screenshot.

## Project layout

```
pdf-to-pdf-convertor/
├── README.md
├── requirements.txt
├── requirements-adobe.txt
└── pdf_accessibility_agent/
    ├── __init__.py
    ├── cli.py             # argparse entrypoint
    ├── analyzer.py        # heuristics + catalog snapshot
    ├── remediate.py      # pikepdf catalog/metadata writes
    ├── pdf_only.py       # process_pdf_only orchestration
    ├── adobe_autotag.py  # optional Adobe Auto-Tag API
    ├── llm_agent.py      # optional OpenAI-compatible JSON plan
    └── models.py         # pydantic models for issues/plans
```

## License

Add a `LICENSE` file if you distribute this project; none is bundled by default.
