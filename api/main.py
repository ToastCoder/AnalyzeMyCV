# AnalyzeMyCV
# api/main.py

import os
import re
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

# Importing Services And Models
from api.auth import router as auth_router
from api.models import AnalysisResponse
from api.services.llm_analyzer import LLMAnalyzer
from api.services.pdf_parser import PDFParser

# Initialization
app = FastAPI(title="AI Resume Analyzer API")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

# Configuring CORS For Both Local And Production Environments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allowing All Origins For Azure Web App Compatibility
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
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
    job_description: Optional[str] = Form(None)
):
    # Handling The Full Pipeline: PDF Parsing -> Content Extraction -> LLM Analysis
    if pdf_parser is None or llm_analyzer is None:
        raise HTTPException(
            status_code=503, detail="Backend services failed to initialize."
        )

    try:
        # Processing File And Extracting Content
        print(f"Starting PDF parsing for file: {file.filename}...")
        file_bytes = await file.read()
        extracted_text = pdf_parser.parse_pdf(file_bytes)

        # Sanitizing Extracted Text Before Passing It Downstream
        sanitized_text = sanitize_text(extracted_text)

        if not sanitized_text:
            raise ValueError(
                "Could not extract any usable text from the provided PDF file."
            )

        # Analyzing Content With LLM
        print("Starting LLM analysis...")
        report, metadata = llm_analyzer.analyze_resume_content(sanitized_text, job_description)

        # Constructing Response
        return AnalysisResponse(
            report=report,
            metadata={"parser_status": "success", "llm_status": "success"},
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
        print(f"An unexpected error occurred during analysis: {e}")
        
        # Converting Exception Object To Safe String Representation For JSON
        error_detail = str(e)
        raise HTTPException(
            status_code=500,
            detail=f"Internal Server Error during analysis: {error_detail}",
        )


# Custom Error Handlers
@app.exception_handler(400)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=400,
        content={"detail": f"Validation Error: {exc.detail}"},
    )
