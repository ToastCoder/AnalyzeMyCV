# AnalyzeMyCV
# api/services/pdf_parser.py

import io
import logging
import re

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

    @staticmethod
    def _clean_extracted_text(text: str) -> str:
        """Strip binary/metadata artifacts (XMP packets, signature blocks) PyMuPDF
        sometimes surfaces as literal text alongside the readable content."""
        text = re.sub(r"<?xpacket[\s\S]*?>", "", text)
        text = re.sub(r"\r\n[\-\w\d]{10,}", "", text)  # Common signature markers
        return text.strip()

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
                text_pages = [page.get_text() or "" for page in doc]
                full_text = "\n".join(text_pages)
                return self._clean_extracted_text(full_text)
        except Exception as e:
            self.logger.error(f"Error reading PDF: {e}")
            return ""
