# AnalyzeMyCV
# api/services/pdf_parser.py

import logging
import re

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


def _clean_extracted_text(text: str) -> str:
    """Strip binary/metadata artifacts (XMP packets, signature blocks) PyMuPDF
    sometimes surfaces as literal text alongside the readable content."""
    text = re.sub(r"<?xpacket[\s\S]*?>", "", text)
    text = re.sub(r"\r\n[\-\w\d]{10,}", "", text)  # Common signature markers
    return text.strip()


def parse_pdf(file_bytes: bytes) -> str:
    """Extract all text from a PDF. Returns "" if the file can't be read."""
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            return _clean_extracted_text("\n".join(page.get_text() or "" for page in doc))
    except Exception as e:
        logger.error(f"Error reading PDF: {type(e).__name__}: {e}")
        return ""
