# AnalyzeMyCV
# api/services/pdf_parser.py

import logging
import re

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# A resume is a few pages; these bound parse time, memory and the LLM token bill.
MAX_PDF_PAGES = 15
MAX_TEXT_CHARS = 50_000


class PdfTooLargeError(ValueError):
    """The PDF is valid but exceeds the page or text limits."""


def _clean_extracted_text(text: str) -> str:
    """Strip binary/metadata artifacts (XMP packets, signature blocks) PyMuPDF
    sometimes surfaces as literal text alongside the readable content."""
    text = re.sub(r"<?xpacket[\s\S]*?>", "", text)
    text = re.sub(r"\r\n[\-\w\d]{10,}", "", text)  # Common signature markers
    return text.strip()


def parse_pdf(file_bytes: bytes) -> str:
    """Extract all text from a PDF. Returns "" if the file can't be read;
    raises PdfTooLargeError if it is too long to process."""
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            if doc.page_count > MAX_PDF_PAGES:
                raise PdfTooLargeError(f"The PDF has too many pages. Maximum is {MAX_PDF_PAGES}.")
            parts, total = [], 0
            for page in doc:
                text = page.get_text() or ""
                total += len(text)
                if total > MAX_TEXT_CHARS:
                    raise PdfTooLargeError("The PDF contains too much text to analyze.")
                parts.append(text)
            return _clean_extracted_text("\n".join(parts))
    except PdfTooLargeError:
        raise
    except Exception as e:
        logger.error(f"Error reading PDF: {type(e).__name__}: {e}")
        return ""
