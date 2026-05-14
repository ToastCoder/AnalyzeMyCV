import pymupdf4llm
import os

def extract_text_from_pdf(pdf_path):
    """
    Converts PDF to Markdown. GPT-5 performs significantly better 
    on Markdown than on raw, unstructured text.
    """
    try:
        # 2026 Standard: to_markdown preserves tables and headers
        md_text = pymupdf4llm.to_markdown(pdf_path)
        return md_text
    except Exception as e:
        return f"Error parsing PDF: {str(e)}"