# PDF accessibility agent

Python toolkit for **PDF-in → PDF-out** passes that improve **catalog- and metadata-level** accessibility signals often checked by **PDF/UA-oriented validators** (for example [PAC](https://www.access-for-all.ch/en/pdf-lab/pac-pdf-accessibility-checker.html)). It is aimed at workflows where the only source file is a PDF.

This project **does not** replace a full accessibility audit. It applies a **narrow, automatable subset** of fixes (document language, marked-content flag, document title). **Tagged structure** (`StructTreeRoot`), reading order, figure alternatives, tables, and many other PAC rules require additional tooling or manual remediation.

## Features

- **Analyze** a PDF and print a JSON report: catalog snapshot (`/Lang`, `/MarkInfo`, presence of structure tree, title hint) plus heuristic issues aligned with common PDF/UA gaps.
- **Remediate** with explicit `--lang` / `--title`, or optional **OpenAI-compatible** planning via `--llm`.
- **Process** is the main **PDF-only** flow: sensible defaults when language or title are missing (default language and filename-based title), optional JSON report file.

## Requirements

- Python 3.10+ recommended (tested with 3.13 in development).
- Dependencies are listed in `requirements.txt` (`pikepdf`, `PyMuPDF`, `pydantic`, `httpx`).

## Installation

```bash
cd pdf-to-pdf-convertor
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Run commands from the project directory so `python -m pdf_accessibility_agent.cli` resolves the package.

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
- **Zero PAC errors** on arbitrary PDF-only inputs usually requires a **properly tagged** PDF, correct reading order, alternatives for figures, accessible tables, and more. That is **outside** the scope of the current automated fixes.
- For automated **machine-readable** checks in CI, consider [veraPDF](https://openpreservation.org/tools/verapdf/) or similar; results will still differ slightly from PAC wording.

## Project layout

```
pdf-to-pdf-convertor/
├── README.md
├── requirements.txt
└── pdf_accessibility_agent/
    ├── __init__.py
    ├── cli.py           # argparse entrypoint
    ├── analyzer.py      # heuristics + catalog snapshot
    ├── remediate.py     # pikepdf catalog/metadata writes
    ├── pdf_only.py      # process_pdf_only orchestration
    ├── llm_agent.py     # optional OpenAI-compatible JSON plan
    └── models.py        # pydantic models for issues/plans
```

## License

Add a `LICENSE` file if you distribute this project; none is bundled by default.
