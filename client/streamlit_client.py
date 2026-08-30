# AnalyzeMyCV
# client/streamlit_client.py
# Azure Entra ID OAuth2 Authentication

import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests
import streamlit as st

# Configuration
API_URL = os.getenv("API_URL", "http://localhost:8080")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "").strip()
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "").strip()
AZURE_AUTH_REDIRECT_URI = os.getenv("AZURE_AUTH_REDIRECT_URI", "").strip()

# Azure Entra ID Endpoints
AUTHORITY = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}"
AUTHORIZE_ENDPOINT = f"{AUTHORITY}/oauth2/v2.0/authorize"


def load_file_to_bytes(uploaded_file) -> Optional[bytes]:
    # Converting Uploaded Streamlit File Object To Raw Bytes
    if uploaded_file is None:
        return None
    return uploaded_file.read()


def get_azure_login_url() -> str:
    """Generate Azure Entra ID login URL."""
    params = {
        "client_id": AZURE_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email offline_access",
        "redirect_uri": AZURE_AUTH_REDIRECT_URI,
        "response_mode": "query",
    }
    return f"{AUTHORIZE_ENDPOINT}?{urlencode(params)}"


def exchange_code_for_token(code: str) -> Optional[dict]:
    """Exchange authorization code for access token via backend."""
    try:
        resp = requests.post(
            f"{API_URL}/auth/login",
            json={"code": code},
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


def verify_token(access_token: str) -> Optional[dict]:
    """Verify access token with backend."""
    try:
        resp = requests.post(
            f"{API_URL}/auth/verify",
            json={"access_token": access_token},
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
    file_bytes: bytes, job_description: str = "", access_token: str = ""
) -> Optional[dict]:
    # Sending The PDF File Bytes To The FastAPI Backend For Analysis
    if file_bytes is None:
        return {"status": "error", "message": "No file provided."}

    try:
        # Preparing The File Payload For The API Call
        files = {"file": ("uploaded_document.pdf", file_bytes, "application/pdf")}
        data = {}
        if job_description:
            data["job_description"] = job_description

        # Adding Authorization Header
        headers = {}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        # Making The POST Request
        response = requests.post(
            f"{API_URL}/analyze",
            files=files,
            data=data,
            headers=headers,
        )

        response.raise_for_status()
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

# Initialize session state
if "auth_session" not in st.session_state:
    st.session_state.auth_session = None


# Handle OAuth2 callback from Azure Entra ID
query_params = st.query_params
if "code" in query_params:
    auth_code = query_params["code"]
    
    # Clear the code from query params
    try:
        del st.query_params["code"]
    except Exception:
        pass
    
    # Exchange code for token
    result = exchange_code_for_token(auth_code)
    
    if result and result.get("success"):
        st.session_state.auth_session = result
        st.success("Login successful!")
        st.rerun()
    else:
        st.error(f"Login failed: {result.get('message', 'Unknown error')}")


# Check if user is authenticated
if not st.session_state.auth_session:
    # Not authenticated - show login page
    st.title("AnalyzeMyCV")
    st.markdown("Sign in with your Azure account to analyze your resume.")
    
    st.info(
        "Click the button below to authenticate with your Azure Entra ID account. "
        "You'll be redirected to Microsoft's login page."
    )
    
    # Generate login URL
    login_url = get_azure_login_url()
    
    # Create a link to Azure login
    st.markdown(f"[🔐 Sign In with Azure](${{{login_url}}})".replace("${{", "[").replace("}}", "]"))
    
    # Alternative: Show direct link if above doesn't work
    with st.expander("Or click here if the button above doesn't work"):
        st.markdown(f"[Sign In with Azure]({login_url})")
        st.code(login_url)
    
    st.stop()


# User is authenticated - show main app
user_email = st.session_state.auth_session.get("user_email", "Unknown")
user_name = st.session_state.auth_session.get("display_name", user_email)
access_token = st.session_state.auth_session.get("access_token", "")

st.sidebar.markdown(f"**Signed in as**")
st.sidebar.markdown(f"`{user_name}`")
st.sidebar.markdown(f"`{user_email}`")

# Logout button
if st.sidebar.button("Sign Out"):
    st.session_state.auth_session = None
    st.query_params.clear()
    st.rerun()

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
                # Calling The Backend API with authorization
                analysis_result = analyze_document_content(
                    file_bytes, job_description, access_token
                )

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
    st.caption("Created by Vigneshwar K R | [LinkedIn](https://linkedin.com/in/toastcoder) • [GitHub](https://github.com/toastcoder)")
