# AnalyzeMyCV
# src/engine/parsers.py

# Import required libraries
import pymupdf4llm
import os

# Define extract_text_from_pdf function
def extract_text_from_pdf(pdf_path):
    """
    Converts PDF to Markdown. GPT-5 performs significantly better 
    on Markdown than on raw, unstructured text.
    """
    try:

        # Markdown conversion of PDF
        md_text = pymupdf4llm.to_markdown(pdf_path)
        return md_text
    except Exception as e:
        return f"Error parsing PDF: {str(e)}"