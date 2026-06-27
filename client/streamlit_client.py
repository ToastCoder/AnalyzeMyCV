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


def auth_request(endpoint: str, email: str, password: str) -> Optional[dict]:
    try:
        resp = requests.post(
            f"{API_URL}/auth/{endpoint}",
            json={"email": email, "password": password},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        detail = None
        try:
            detail = e.response.json().get("detail")
        except Exception:
            pass
        return {"success": False, "message": detail or str(e)}


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

# Injecting Custom CSS To Force JetBrains Mono Font, Reduce Size, And Align Widget Heights
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap');
    html, body, p, li, h1, h2, h3, h4, h5, h6, label, button, input, textarea, select {
        font-family: 'JetBrains Mono', 'SF Mono', ui-monospace, Menlo, Monaco, Consolas, "Courier New", monospace !important;
    }
    html, body {
        font-size: 14px !important;
    }
    /* Aligning the height of the text area to match the file uploader dropzone */
    [data-testid="stTextArea"] textarea {
        height: 95px !important;
        min-height: 95px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Authentication
if "auth_session" not in st.session_state:
    st.session_state.auth_session = None

if not st.session_state.auth_session:
    st.title("AnalyzeMyCV")
    st.markdown("Sign in or create an account to analyze your resume.")

    tab_login, tab_signup = st.tabs(["Sign In", "Sign Up"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In")

            if submitted:
                result = auth_request("login", email, password)
                if result and result.get("success"):
                    st.session_state.auth_session = result
                    st.rerun()
                else:
                    st.error(result.get("message", "Login failed."))

    with tab_signup:
        with st.form("signup_form"):
            new_email = st.text_input("Email")
            new_password = st.text_input("Password", type="password")
            new_confirm = st.text_input("Confirm Password", type="password")
            submitted = st.form_submit_button("Sign Up")

            if submitted:
                if new_password != new_confirm:
                    st.error("Passwords do not match.")
                elif len(new_password) < 6:
                    st.error("Password must be at least 6 characters.")
                else:
                    result = auth_request("signup", new_email, new_password)
                    if result and result.get("success"):
                        if result.get("access_token"):
                            st.session_state.auth_session = result
                            st.rerun()
                        else:
                            st.success(result.get("message", "Account created! Check your email to confirm."))
                    else:
                        st.error(result.get("message", "Signup failed."))

    st.stop()

user_email = st.session_state.auth_session.get("user_email", "")
st.sidebar.markdown(f"Signed in as **{user_email}**")

# Main App Layout
st.title("AnalyzeMyCV")
st.markdown(
    "Upload a PDF resume to analyze its content structure, skills, and experience using AI."
)

uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
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
