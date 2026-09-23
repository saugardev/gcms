"""Synchronous, bounded ZIP-in/report-out API; one active request per process."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore
from time import perf_counter
from typing import Annotated, Literal

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from . import __version__
from .io import (
    DEFAULT_LIBRARY,
    DEFAULT_SAMPLE,
    MAX_UPLOAD_BYTES,
    extract_sample,
    read_library,
    read_run,
)
from .models import AnalysisReport, Parameters, ProcessingError, ReviewReport
from .pipeline import analyze
from .report import render_report
from .review import build_review


class UploadParameters(Parameters):
    output: Literal["json", "html"] = "json"
    engine: Literal["python", "rust"] = "python"
    review: bool = False


def _analyze_sample(sample, library, options):
    started = perf_counter()
    params = Parameters.model_validate(options.model_dump(exclude={"output", "engine", "review"}))
    run = read_run(sample)
    review = None
    if options.review:
        review = build_review(run, library, params, engine=options.engine)
        report = review.analysis
    else:
        report = analyze(run, library, params, engine=options.engine)
    if options.output == "html":
        html = render_report(report, review=review)
        return HTMLResponse(
            html, headers={"Server-Timing": f"processing;dur={(perf_counter() - started) * 1000:.3f}"}
        )
    return review if review is not None else report


def create_app(library_path: Path | None = None, sample_path: Path | None = None):
    @asynccontextmanager
    async def lifespan(app):
        path = library_path or DEFAULT_LIBRARY
        if path is None:
            raise ProcessingError(
                "library_not_configured", "Set GCMS_LIBRARY to an MSP file before starting the API."
            )
        app.state.library = read_library(path)
        app.state.sample_path = sample_path or DEFAULT_SAMPLE
        app.state.slot = BoundedSemaphore(1)
        # ponytail: one active request per process; add a job queue only if throughput requires it.
        yield

    app = FastAPI(
        title="Mafer GC-MS screening API",
        version=__version__,
        lifespan=lifespan,
        description="Upload a ZIP containing one complete ChemStation .D/data.ms. "
        "Results are screening candidates, not confirmed identities. Times are seconds.",
    )

    @app.exception_handler(ProcessingError)
    async def processing_error(request, exc):
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": exc.message}},
            headers={"Retry-After": "2"} if exc.code == "busy" else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_parameters",
                    "message": "Check processing parameter names and bounds.",
                    "details": [
                        {"location": list(e["loc"]), "message": e["msg"]} for e in exc.errors()
                    ],
                }
            },
        )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard(request: Request):
        return (
            Path(__file__)
            .with_name("dashboard.html")
            .read_text()
            .replace("__SAMPLE_AVAILABLE__", "true" if request.app.state.sample_path else "false")
        )

    @app.get(
        "/v1/sample",
        response_model=AnalysisReport | ReviewReport,
        responses={
            200: {"content": {"text/html": {"schema": {"type": "string"}}}},
            503: {"description": "Another request is active; retry later"},
        },
        summary="Analyze the optional GCMS_SAMPLE acquisition using the configured library",
    )
    async def sample_dashboard(request: Request, options: Annotated[UploadParameters, Query()]):
        if request.app.state.sample_path is None:
            raise ProcessingError(
                "sample_not_configured",
                "Upload a ZIP or set GCMS_SAMPLE before starting the API.",
                503,
            )
        if not request.app.state.slot.acquire(blocking=False):
            raise ProcessingError("busy", "Another analysis is active; retry in 2 seconds.", 503)
        try:
            return await run_in_threadpool(
                _analyze_sample, request.app.state.sample_path, request.app.state.library, options
            )
        finally:
            request.app.state.slot.release()

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": __version__}

    @app.get("/v1/library")
    async def library_info(request: Request):
        library = request.app.state.library
        return {"sha256": library.sha256, **library.audit}

    @app.post(
        "/v1/analyze",
        response_model=AnalysisReport | ReviewReport,
        responses={
            200: {"content": {"text/html": {"schema": {"type": "string"}}}},
            408: {"description": "Upload did not complete within 60 seconds"},
            413: {"description": "Upload or expanded data exceeds documented limits"},
            415: {"description": "Use Content-Type: application/zip"},
            422: {"description": "Invalid ZIP, acquisition format or processing parameters"},
            503: {"description": "Another request is active; retry later"},
        },
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
            }
        },
    )
    async def analyze_upload(request: Request, options: Annotated[UploadParameters, Query()]):
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/zip":
            raise ProcessingError(
                "unsupported_media_type", "Send the ZIP body as application/zip.", 415
            )
        if not request.app.state.slot.acquire(blocking=False):
            raise ProcessingError("busy", "Another analysis is active; retry in 2 seconds.", 503)
        try:
            with TemporaryDirectory(prefix="gcms-upload-") as tmp:
                root = Path(tmp)
                archive = root / "input.zip"
                total = 0
                try:
                    async with asyncio.timeout(60):
                        with archive.open("wb") as stream:
                            async for chunk in request.stream():
                                total += len(chunk)
                                if total > MAX_UPLOAD_BYTES:
                                    raise ProcessingError(
                                        "upload_too_large", "ZIP upload exceeds 64 MiB.", 413
                                    )
                                stream.write(chunk)
                except TimeoutError as exc:
                    raise ProcessingError(
                        "upload_timeout", "Complete the upload within 60 seconds.", 408
                    ) from exc

                def process():
                    sample = extract_sample(archive, root)
                    return _analyze_sample(sample, request.app.state.library, options)

                return await run_in_threadpool(process)
        finally:
            request.app.state.slot.release()

    return app


app = create_app()
