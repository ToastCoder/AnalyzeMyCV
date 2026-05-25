# AnalyzeMyCV
# client/streamlit_client.py

import os
from typing import Optional

import requests
import streamlit as st

# Configuration
# Pointing to the internal FastAPI server which runs on port 8080 inside Docker
API_URL = os.getenv("API_URL", "http://localhost:8080")


def load_file_to_bytes(uploaded_file) -> Optional[bytes]:
    # Converting Uploaded Streamlit File Object To Raw Bytes
    if uploaded_file is None:
        return None
    return uploaded_file.read()


def analyze_document_content(
    file_bytes: bytes, job_description: str = ""
) -> Optional[dict]:
    # Sending The PDF File Bytes To The FastAPI Backend For Analysis
    if file_bytes is None:
        return {"status": "error", "message": "No file provided."}

    # Preparing The File Payload For The API Call
    files = {"file": (None, "uploaded_document.pdf", "application/pdf")}

    try:
        # Simulating The File Structure The Backend Expects
        files = {"file": ("uploaded_document.pdf", file_bytes, "application/pdf")}

        # Making The POST Request
        data = {}
        if job_description:
            data["job_description"] = job_description

        response = requests.post(
            f"{API_URL}/analyze",
            files=files,
            data=data,
            headers={"X-CSRFToken": "dummy"},  # Dummy Header For Stability
        )

        response.raise_for_status()  # Raising HTTPError For Bad Status Codes
        return response.json()

    except requests.exceptions.ConnectionError:
        return {
            "status": "error",
            "message": f"Connection Error: Could not connect to the API server at {API_URL}. Ensure uvicorn is running.",
        }
    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "message": f"An API request error occurred: {str(e)}",
        }
    except Exception as e:
        return {"status": "error", "message": f"An unexpected error occurred: {str(e)}"}


# Setting Page Config
st.set_page_config(
    page_title="AnalyzeMyCV", layout="wide", initial_sidebar_state="expanded"
)

# Injecting Custom CSS To Force SF Mono Font, Reduce Size, And Align Widget Heights
st.markdown(
    """
    <style>
    * {
        font-family: 'SF Mono', ui-monospace, Menlo, Monaco, Consolas, "Courier New", monospace !important;
    }
    html, body {
        font-size: 14px !important;
    }
    /* Aligning the heights of the file uploader and text area */
    [data-testid="stFileUploaderDropzone"] {
        height: 95px !important;
        min-height: 95px !important;
        padding-top: 10px !important;
        padding-bottom: 10px !important;
    }
    [data-testid="stTextArea"] textarea {
        height: 95px !important;
        min-height: 95px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Main App Layout
st.title("AnalyzeMyCV")
st.markdown(
    "Upload a PDF resume to analyze its content structure, skills, and experience using AI."
)

# Using Columns To Display Inputs Side-by-Side
col1, col2 = st.columns(2)

with col1:
    uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")

with col2:
    job_description = st.text_area("Optional: Paste a Job Description to match against")

if uploaded_file:
    # Converting Uploaded File To Bytes For The API Call
    file_bytes = load_file_to_bytes(uploaded_file)

    # Displaying A Status Placeholder And Triggering Analysis
    st.info("File loaded. Click 'Analyze Document' to start the process...")

    if st.button("Analyze Document"):
        if file_bytes:
            with st.spinner("Analyzing resume content... This may take a minute."):
                # Calling The Backend API
                analysis_result = analyze_document_content(file_bytes, job_description)

            st.success("Analysis Complete!")

            if analysis_result and analysis_result.get("success") is True:
                report = analysis_result.get("report")

                st.subheader("Full Analysis Report")
                st.markdown(report)
            else:
                # Handling Errors From The API Or Connection Issues
                error_message = (
                    analysis_result.get("report")
                    or analysis_result.get("detail")
                    or analysis_result.get("message")
                )
                st.error(f"Analysis Failed: {error_message}")

else:
    st.markdown("""
    ## How It Works
    1. Upload a PDF file containing a resume.
    2. Click 'Analyze Document'.
    3. The frontend sends the file to the FastAPI backend.
    4. The backend extracts text, sends it to the LLM, and returns the structured report.
    """)
    st.caption("Powered by Streamlit, FastAPI, Azure OpenAI, PyMuPDF, and Docker on Azure Web App Service.")
    st.caption("Created by ToastCoder | [LinkedIn](https://linkedin.com/in/toastcoder) • [GitHub](https://github.com/toastcoder)")
