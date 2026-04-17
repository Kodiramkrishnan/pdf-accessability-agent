from __future__ import annotations

import os
from pathlib import Path


def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(
            f"Missing environment variable {name}. "
            "Adobe Auto-Tag needs PDF_SERVICES_CLIENT_ID and PDF_SERVICES_CLIENT_SECRET "
            '(see README section "Without Adobe credentials" for alternatives), or '
            "use `process` without `--adobe-autotag` for local metadata fixes only."
        )
    return val


def adobe_autotag_pdf(
    input_path: str | Path,
    output_path: str | Path,
    *,
    report_path: str | Path | None = None,
    shift_headings: bool = False,
) -> None:
    """
    Run Adobe PDF Accessibility Auto-Tag API and write a tagged PDF.

    Adobe explicitly states the output is **not** guaranteed to meet WCAG/PDF/UA without
    further remediation; it is still the most practical way to obtain a structure tree
    from an arbitrary PDF in Python.

    Requires: ``pip install -r requirements-adobe.txt`` and Adobe credentials in the environment.
    """
    try:
        from adobe.pdfservices.operation.auth.service_principal_credentials import (
            ServicePrincipalCredentials,
        )
        from adobe.pdfservices.operation.exception.exceptions import (
            SdkException,
            ServiceApiException,
            ServiceUsageException,
        )
        from adobe.pdfservices.operation.io.cloud_asset import CloudAsset
        from adobe.pdfservices.operation.io.stream_asset import StreamAsset
        from adobe.pdfservices.operation.pdf_services import PDFServices
        from adobe.pdfservices.operation.pdf_services_media_type import PDFServicesMediaType
        from adobe.pdfservices.operation.pdfjobs.jobs.autotag_pdf_job import AutotagPDFJob
        from adobe.pdfservices.operation.pdfjobs.params.autotag_pdf.autotag_pdf_params import (
            AutotagPDFParams,
        )
        from adobe.pdfservices.operation.pdfjobs.result.autotag_pdf_result import AutotagPDFResult
    except ImportError as e:
        raise RuntimeError(
            "Adobe PDF Services SDK is not installed. Run: pip install -r requirements-adobe.txt"
        ) from e

    input_path = Path(input_path)
    output_path = Path(output_path)
    gen_report = report_path is not None

    client_id = _require_env("PDF_SERVICES_CLIENT_ID")
    client_secret = _require_env("PDF_SERVICES_CLIENT_SECRET")

    credentials = ServicePrincipalCredentials(
        client_id=client_id,
        client_secret=client_secret,
    )
    pdf_services = PDFServices(credentials=credentials)

    pdf_bytes = input_path.read_bytes()
    input_asset = pdf_services.upload(
        input_stream=pdf_bytes,
        mime_type=PDFServicesMediaType.PDF,
    )

    params = AutotagPDFParams(
        shift_headings=shift_headings,
        generate_report=gen_report,
    )
    job = AutotagPDFJob(input_asset, autotag_pdf_params=params)

    try:
        location = pdf_services.submit(job)
        response = pdf_services.get_job_result(location, AutotagPDFResult)
    except (ServiceApiException, ServiceUsageException, SdkException):
        raise

    result = response.get_result()
    tagged = result.get_tagged_pdf()
    stream: StreamAsset = pdf_services.get_content(tagged)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(stream.get_input_stream())

    if gen_report and report_path is not None:
        report_path = Path(report_path)
        report_asset = result.get_report()
        if report_asset is None:
            return
        rstream: StreamAsset = pdf_services.get_content(report_asset)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_bytes(rstream.get_input_stream())
