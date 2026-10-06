# AnalyzeMyCV
# api/main.py

import os
import time
from typing import Callable, Optional

import jwt
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from api.auth import CurrentUser, decode_internal_token, get_current_user
from api.models import AnalysisResponse
from api.services.llm_analyzer import LLMAnalyzer
from api.services.pdf_parser import parse_pdf

# This API is internal (bound to localhost, called only by the Streamlit frontend),
# so the interactive docs are disabled unless DEBUG is explicitly enabled.
_debug = os.getenv("DEBUG", "false").strip().lower() == "true"
app = FastAPI(
    title="AI Resume Analyzer API",
    docs_url="/docs" if _debug else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _debug else None,
)

limiter = Limiter(key_func=get_remote_address, headers_enabled=True)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

MAX_UPLOAD_SIZE_BYTES = 8 * 1024 * 1024  # 8 MB is generous for a text-based resume PDF
MAX_JOB_DESCRIPTION_CHARS = 20_000
# Shared by both LLM endpoints, so each user gets one LLM call per window in total.
LLM_RATE_LIMIT = "1/5minute"

llm_analyzer = LLMAnalyzer()


def user_rate_limit_key(request: Request) -> str:
    """Key the LLM endpoints' rate limit by the authenticated user instead of remote address.

    The Streamlit frontend calls this API server-side, so every browser session
    reaches FastAPI as the same loopback address — an IP-based key would put all
    users in one shared bucket. Falls back to the IP if no valid token is present
    (such requests are then rejected by get_current_user).
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        try:
            sub = decode_internal_token(auth_header.split(" ", 1)[1]).get("sub")
            if sub:
                return f"user:{sub}"
        except jwt.PyJWTError:
            pass
    return get_remote_address(request)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "AI Resume Analyzer API"}


async def _run_pipeline(
    file: UploadFile, job_description: Optional[str], llm_task: Callable, label: str
) -> AnalysisResponse:
    """Shared by /analyze and /generate-resume: bounded upload read -> PDF text -> LLM."""
    try:
        # Never buffer more than the size limit + 1 byte.
        file_bytes = await file.read(MAX_UPLOAD_SIZE_BYTES + 1)
        if len(file_bytes) > MAX_UPLOAD_SIZE_BYTES:
            raise ValueError(f"File is too large. Maximum upload size is {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB.")

        # PDF parsing and the LLM call are blocking; run them off the event loop
        # so one slow request doesn't stall every other request.
        start_time = time.time()
        extracted_text = await run_in_threadpool(parse_pdf, file_bytes)
        if not extracted_text.strip():
            raise ValueError("Could not extract any usable text from the provided PDF file.")

        report, metadata = await run_in_threadpool(llm_task, extracted_text, job_description)
        if not report:
            raise HTTPException(status_code=502, detail=f"{label} failed. Please try again.")

        metadata["total_time_s"] = round(time.time() - start_time, 2)
        print(f"[Pipeline] {label} complete in {metadata['total_time_s']}s ({len(file_bytes) / 1024:.1f} KB PDF)")
        return AnalysisResponse(report=report, metadata=metadata)

    except ValueError as e:
        return AnalysisResponse(success=False, report=f"Input Error: {e}", metadata={"error_type": "Input Error"})
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Pipeline] {label} ERROR: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error during {label.lower()}.")


@app.post("/analyze", response_model=AnalysisResponse)
@limiter.shared_limit(LLM_RATE_LIMIT, scope="llm", key_func=user_rate_limit_key)
async def analyze_document(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    job_description: Optional[str] = Form(None, max_length=MAX_JOB_DESCRIPTION_CHARS),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await _run_pipeline(file, job_description, llm_analyzer.analyze_resume_content, "Analysis")


@app.post("/generate-resume", response_model=AnalysisResponse)
@limiter.shared_limit(LLM_RATE_LIMIT, scope="llm", key_func=user_rate_limit_key)
async def generate_resume(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    job_description: str = Form(..., min_length=1, max_length=MAX_JOB_DESCRIPTION_CHARS),
    current_user: CurrentUser = Depends(get_current_user),
):
    # Rewrites the resume's content to target the job description, keeping its original template.
    return await _run_pipeline(file, job_description, llm_analyzer.generate_tailored_resume, "Resume generation")
