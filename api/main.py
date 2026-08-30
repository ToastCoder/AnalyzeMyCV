# AnalyzeMyCV
# api/main.py

import os
import re
import time
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

# Importing Services And Models
from api.auth import get_current_user, router as auth_router
from api.user_models import User
from api.models import AnalysisResponse
from api.services.llm_analyzer import LLMAnalyzer
from api.services.pdf_parser import PDFParser
from api.database import init_db

# Initialization
app = FastAPI(title="AI Resume Analyzer API")

# Initialize database tables
try:
    init_db()
    print("[Database] Tables initialized successfully")
except Exception as e:
    print(f"[Database] Warning: Could not initialize database tables: {e}")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

# CORS is restricted by default. Set CORS_ORIGINS to a comma-separated list
# when a browser-based client is hosted on a different origin.
configured_origins = os.getenv("CORS_ORIGINS", "http://localhost:8000,http://localhost:8501")
cors_origins = [origin.strip() for origin in configured_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Dependencies
# Initializing Services To Handle Environment Variables For Keys
try:
    pdf_parser = PDFParser()
    llm_analyzer = LLMAnalyzer()
except Exception as e:
    print(f"Warning: Failed to initialize service dependencies: {e}")
    pdf_parser = None
    llm_analyzer = None


# Utilities

def sanitize_text(text: str) -> str:
    # Removing Common Binary Markers And Control Characters From Extracted Text
    text = re.sub(r"<?xpacket[\s\S]*?>", "", text)
    text = re.sub(
        r"\r\n[\-\w\d]{10,}", "", text
    )  # Removing Common Signature Markers
    return text.strip()


# Endpoints

app.include_router(auth_router)

@app.get("/health")
async def health_check():
    # Basic Health Check Endpoint
    return {"status": "ok", "service": "AI Resume Analyzer API"}


@app.post("/analyze", response_model=AnalysisResponse)
@limiter.limit("1/5minute")
async def analyze_document(
    request: Request,
    file: UploadFile = File(...), 
    job_description: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
):
    # Handling The Full Pipeline: PDF Parsing -> Content Extraction -> LLM Analysis
    if pdf_parser is None or llm_analyzer is None:
        raise HTTPException(
            status_code=503, detail="Backend services failed to initialize."
        )

    try:
        # Processing File And Extracting Content
        file_bytes = await file.read()
        file_size_kb = len(file_bytes) / 1024
        print(f"[Pipeline] File received: {file.filename} ({file_size_kb:.1f} KB)")

        start_time = time.time()
        extracted_text = pdf_parser.parse_pdf(file_bytes)
        parse_time = time.time() - start_time
        print(f"[Pipeline] PDF parsed in {parse_time:.2f}s — extracted {len(extracted_text)} chars")

        # Sanitizing Extracted Text Before Passing It Downstream
        sanitized_text = sanitize_text(extracted_text)

        if not sanitized_text:
            raise ValueError(
                "Could not extract any usable text from the provided PDF file."
            )

        print(f"[Pipeline] Text sanitized — {len(sanitized_text)} chars ready for LLM")
        if job_description:
            print(f"[Pipeline] Job Description provided — {len(job_description)} chars")

        # Analyzing Content With LLM
        llm_start = time.time()
        report, metadata = llm_analyzer.analyze_resume_content(sanitized_text, job_description)
        llm_time = time.time() - llm_start

        total_time = time.time() - start_time
        print(f"[Pipeline] Analysis complete in {total_time:.2f}s (PDF: {parse_time:.2f}s, LLM: {llm_time:.2f}s)")
        print(f"[Pipeline] Report generated: {len(report)} chars")

        # Constructing Response
        return AnalysisResponse(
            report=report,
            metadata={"parser_status": "success", "llm_status": "success", "total_time_s": round(total_time, 2)},
        )

    except ValueError as e:
        # Handling Specific Business Logic Errors
        return AnalysisResponse(
            success=False,
            report=f"Input Error: {e}",
            metadata={"error_type": "Input Error"},
        )
    except Exception as e:
        # Handling General Unexpected Errors
        print(f"[Pipeline] ERROR: {type(e).__name__}: {e}")
        
        # Converting Exception Object To Safe String Representation For JSON
        raise HTTPException(
            status_code=500,
            detail="Internal Server Error during analysis.",
        )


# Custom Error Handlers
@app.exception_handler(400)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=400,
        content={"detail": f"Validation Error: {exc.detail}"},
    )
