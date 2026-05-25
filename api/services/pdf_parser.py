# AnalyzeMyCV
# api/services/pdf_parser.py

import io
import logging
from typing import Union

# Using PyMuPDF For Robust PDF Handling
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None
    logging.warning("pymupdf not found. PDF parsing will fail until it is installed.")


class PDFParser:
    # Handling The Extraction Of Text Content From Uploaded PDF Files Using PyMuPDF
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        if fitz is None:
            self.logger.error(
                "PDFParser initialized without pymupdf. Parsing functionality disabled."
            )
        else:
            self.logger.info("PDFParser initialized successfully using pymupdf.")

    def parse_pdf(self, file_bytes: bytes) -> str:
        # Taking File Bytes And Extracting All Text Content
        if fitz is None:
            raise NotImplementedError(
                "PDF library (pymupdf) is not installed or initialized."
            )

        try:
            # Using BytesIO To Treat The Raw Bytes As A File-like Object
            pdf_file_io = io.BytesIO(file_bytes)

            # Using Fitz Open To Create A PDF Document Object
            with fitz.open(stream=pdf_file_io, filetype="pdf") as doc:
                text_pages = []
                for page in doc:
                    # PyMuPDF Text Extraction Is Highly Robust And Handles Encoding Internally
                    text = page.get_text()
                    if text:
                        text_pages.append(text)
                    else:
                        text_pages.append("")

                full_text = "\n".join(text_pages)
                return full_text
        except Exception as e:
            self.logger.error(f"Error reading PDF: {e}")
            # Fallback If PyMuPDF Fails For Any Reason To Try Reading Raw Bytes With Replacement
            try:
                return e.args[0].decode("utf-8", errors="replace")
            except Exception:
                return ""
