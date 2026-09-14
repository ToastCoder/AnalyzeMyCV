# AnalyzeMyCV
# client/streamlit_client.py
# Email/password authentication

import os
from typing import Optional

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Configuration
API_URL = os.getenv("API_URL", "http://localhost:8080")


def load_file_to_bytes(uploaded_file) -> Optional[bytes]:
    # Converting Uploaded Streamlit File Object To Raw Bytes
    if uploaded_file is None:
        return None
    return uploaded_file.read()


def _auth_request(method: str, path: str, payload: dict, access_token: str = "") -> dict:
    """Call an auth endpoint, normalizing errors to the same {success, message} shape."""
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    try:
        resp = requests.request(method, f"{API_URL}/auth/{path}", json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        detail = None
        try:
            detail = e.response.json().get("detail")
        except Exception:
            pass
        return {"success": False, "message": detail or str(e)}


def authenticate(endpoint: str, email: str, password: str) -> dict:
    """Sign up or log in through the FastAPI auth endpoint."""
    return _auth_request("post", endpoint, {"email": email, "password": password})


def request_password_reset(email: str) -> dict:
    return _auth_request("post", "forgot-password", {"email": email})


def reset_password(token: str, new_password: str) -> dict:
    return _auth_request("post", "reset-password", {"token": token, "new_password": new_password})


def update_display_name(display_name: str, access_token: str) -> dict:
    return _auth_request("patch", "me", {"display_name": display_name}, access_token)


def change_account_password(current_password: str, new_password: str, access_token: str) -> dict:
    return _auth_request(
        "post", "change-password",
        {"current_password": current_password, "new_password": new_password},
        access_token,
    )


def _rate_limit_message(response) -> str:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            secs = max(0, int(float(retry_after)))
            if secs >= 60:
                return f"You've hit the rate limit. Try again in {secs // 60}m {secs % 60}s."
            return f"You've hit the rate limit. Try again in {secs}s."
        except ValueError:
            pass
    return "You've hit the rate limit. Please wait a bit and try again."


def _call_resume_endpoint(
    path: str, file_bytes: bytes, job_description: str, access_token: str
) -> Optional[dict]:
    """Shared POST logic for /analyze and /generate-resume: same file+form+auth shape."""
    if file_bytes is None:
        return {"status": "error", "message": "No file provided."}

    try:
        files = {"file": ("uploaded_document.pdf", file_bytes, "application/pdf")}
        data = {}
        if job_description:
            data["job_description"] = job_description
        headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}

        response = requests.post(f"{API_URL}/{path}", files=files, data=data, headers=headers)

        if response.status_code == 429:
            return {"status": "error", "message": _rate_limit_message(response)}

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


def analyze_document_content(
    file_bytes: bytes, job_description: str = "", access_token: str = ""
) -> Optional[dict]:
    # Sending The PDF File Bytes To The FastAPI Backend For Analysis
    return _call_resume_endpoint("analyze", file_bytes, job_description, access_token)


def generate_resume_content(
    file_bytes: bytes, job_description: str, access_token: str = ""
) -> Optional[dict]:
    # Sending The PDF File Bytes + Job Description For A Tailored Resume Rewrite
    if not job_description or not job_description.strip():
        return {"status": "error", "message": "A job description is required to generate a tailored resume."}
    return _call_resume_endpoint("generate-resume", file_bytes, job_description, access_token)


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


# Check if user is authenticated
if not st.session_state.auth_session:
    reset_token = st.query_params.get("reset_token")
    if reset_token:
        st.title("Reset your password")
        new_password = st.text_input("New password", type="password")
        confirm_password = st.text_input("Confirm new password", type="password")
        if st.button("Reset password"):
            if new_password != confirm_password:
                st.error("Passwords do not match.")
            elif len(new_password) < 8:
                st.error("Password must be at least 8 characters.")
            else:
                result = reset_password(reset_token, new_password)
                if result.get("success"):
                    st.query_params.clear()
                    st.success("Password reset successfully. You can now log in.")
                else:
                    st.error(result.get("message", "Password reset failed."))
        st.stop()

    st.title("AnalyzeMyCV")
    st.markdown("Sign in with your email and password.")
    mode = st.radio("Account", ["Log in", "Create account"], horizontal=True)
    email = st.text_input("Email", autocomplete="email")
    password = st.text_input("Password", type="password", autocomplete="current-password")
    if st.button(mode):
        endpoint = "login" if mode == "Log in" else "signup"
        result = authenticate(endpoint, email, password)
        if result.get("success"):
            st.session_state.auth_session = result
            st.rerun()
        st.error(result.get("message", "Authentication failed."))
    if mode == "Log in" and st.button("Forgot password?"):
        st.session_state.show_forgot_password = True
        st.rerun()
    if st.session_state.get("show_forgot_password"):
        st.divider()
        st.subheader("Reset your password")
        reset_email = st.text_input("Account email", key="reset_email")
        if st.button("Send reset link"):
            result = request_password_reset(reset_email)
            if result.get("success"):
                st.success(result.get("message"))
            else:
                st.error(result.get("message", "Could not request a reset link."))
        if st.button("Back to login"):
            st.session_state.show_forgot_password = False
            st.rerun()
    st.stop()


# User is authenticated - show main app
user_email = st.session_state.auth_session.get("user_email", "Unknown")
user_name = st.session_state.auth_session.get("display_name") or user_email
access_token = st.session_state.auth_session.get("access_token", "")

st.sidebar.markdown(f"**Signed in as**")
st.sidebar.markdown(f"`{user_name}`")
st.sidebar.markdown(f"`{user_email}`")

with st.sidebar.expander("Account Settings"):
    settings_display_name = st.text_input("Display name", value=user_name, key="settings_display_name")
    if st.button("Save name", key="save_name_btn"):
        new_name = settings_display_name.strip()
        if not new_name:
            st.error("Display name cannot be empty.")
        else:
            result = update_display_name(new_name, access_token)
            if result.get("success"):
                st.session_state.auth_session["display_name"] = result.get("display_name", new_name)
                st.success("Name updated.")
                st.rerun()
            else:
                st.error(result.get("message", "Could not update name."))

    st.divider()
    st.markdown("**Change password**")
    current_pw = st.text_input("Current password", type="password", key="settings_current_pw")
    new_pw = st.text_input("New password", type="password", key="settings_new_pw")
    confirm_pw = st.text_input("Confirm new password", type="password", key="settings_confirm_pw")
    if st.button("Change password", key="change_pw_btn"):
        if new_pw != confirm_pw:
            st.error("New passwords do not match.")
        elif len(new_pw) < 8:
            st.error("Password must be at least 8 characters.")
        else:
            result = change_account_password(current_pw, new_pw, access_token)
            if result.get("success"):
                st.success("Password changed successfully.")
            else:
                st.error(result.get("message", "Could not change password."))

# Logout button
if st.sidebar.button("Sign Out"):
    st.session_state.auth_session = None
    st.query_params.clear()
    st.rerun()

# Main App Layout
st.title("AnalyzeMyCV")
st.markdown(
    "Upload a PDF resume to analyze its content, or generate a version tailored to a job description."
)

uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
job_description = st.text_area(
    "Job description (optional for analysis matching; required to generate a tailored resume)"
)

if uploaded_file:
    # Converting Uploaded File To Bytes For The API Call
    file_bytes = load_file_to_bytes(uploaded_file)

    st.info("File loaded. Choose an action below.")
    action_col1, action_col2 = st.columns(2)
    analyze_clicked = action_col1.button("Analyze Document", use_container_width=True)
    generate_clicked = action_col2.button(
        "Generate Tailored Resume",
        use_container_width=True,
        help="Requires a job description above.",
    )

    if analyze_clicked and file_bytes:
        with st.spinner("Analyzing resume content... This may take a minute."):
            # Calling The Backend API with authorization
            analysis_result = analyze_document_content(file_bytes, job_description, access_token)

        if analysis_result.get("success") is True:
            st.success("Analysis Complete!")
            report = analysis_result.get("report")

            st.subheader("Full Analysis Report")
            score_col1, score_col2, score_col3 = st.columns(3)
            resume_score = analysis_result.get("metadata", {}).get("resume_score")
            ats_score = analysis_result.get("metadata", {}).get("ats_friendliness_score")
            match_score = analysis_result.get("metadata", {}).get("match_score")
            if resume_score is not None:
                score_col1.metric("Resume Score", f"{resume_score}/100")
            if ats_score is not None:
                score_col2.metric("ATS Friendliness", f"{ats_score}/100")
            if match_score is not None:
                score_col3.metric("Job Match", f"{match_score}/100")
            st.markdown(report)
        else:
            # Handling Errors From The API Or Connection Issues
            error_message = (
                analysis_result.get("report")
                or analysis_result.get("detail")
                or analysis_result.get("message")
            )
            st.error(f"Analysis Failed: {error_message}")

    if generate_clicked and file_bytes:
        if not job_description or not job_description.strip():
            st.error("Please paste a job description above before generating a tailored resume.")
        else:
            with st.spinner("Generating a tailored resume... This may take a minute."):
                generation_result = generate_resume_content(file_bytes, job_description, access_token)

            if generation_result.get("success") is True:
                st.success("Tailored resume generated!")
                generated_report = generation_result.get("report", "")
                st.subheader("Tailored Resume")
                st.markdown(generated_report)
                st.download_button(
                    "Download tailored resume (Markdown)",
                    data=generated_report,
                    file_name="tailored_resume.md",
                    mime="text/markdown",
                )
            else:
                error_message = (
                    generation_result.get("report")
                    or generation_result.get("detail")
                    or generation_result.get("message")
                )
                st.error(f"Resume Generation Failed: {error_message}")

else:
    st.markdown("""
    ## How It Works
    1. Upload a PDF file containing a resume.
    2. Click 'Analyze Document' for a scored report, or paste a job description and click
       'Generate Tailored Resume' for a rewritten version aimed at that role.
    3. The frontend sends the file to the FastAPI backend.
    4. The backend extracts text and sends it to the LLM for analysis or generation.
    """)
    st.caption("Powered by Streamlit, FastAPI, Azure OpenAI, PyMuPDF, and Docker on Azure Web App Service.")
    st.caption("Created by Vigneshwar K R | [LinkedIn](https://linkedin.com/in/toastcoder) • [GitHub](https://github.com/toastcoder)")
