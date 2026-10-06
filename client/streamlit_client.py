# AnalyzeMyCV
# client/streamlit_client.py
# Sign-in is handled by Clerk, verified in proxy.py

import os
import time
from typing import Optional, Tuple
from urllib.parse import unquote

import jwt
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Configuration
API_URL = os.getenv("API_URL", "http://127.0.0.1:8080")
API_TIMEOUT_SECONDS = 180
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
# Must match api/auth.py.
TOKEN_ISSUER = "analyzemycv-frontend"
TOKEN_AUDIENCE = "analyzemycv-api"
API_TOKEN_TTL_SECONDS = 300
# proxy.py verifies the Clerk session and sets these headers (any client-sent copy is dropped
# there). Same rule as proxy.py: they are only trusted once Clerk is configured.
CLERK_ENABLED = bool(os.getenv("CLERK_PUBLISHABLE_KEY", "").strip())
SIGN_IN_PATH = "/auth/sign-in?redirect=/"
SIGN_OUT_PATH = "/auth/sign-out"


def _header(name: str) -> Optional[str]:
    value = unquote(st.context.headers.get(name) or "").strip()
    return value or None


def get_signed_in_user() -> Optional[dict]:
    """Return the user the proxy signed in through Clerk, or None."""
    if CLERK_ENABLED:
        user_id = _header("X-Auth-User-Id")
        if not user_id:
            return None
        email, name = _header("X-Auth-Email"), _header("X-Auth-Name")
        return {"user_id": user_id, "email": email, "display_name": name or email}

    # Never fall back to a dev identity on App Service: if Clerk isn't configured
    # there, the app must refuse access rather than let everyone in.
    if os.getenv("WEBSITE_SITE_NAME"):
        return None
    dev_email = os.getenv("LOCAL_DEV_USER_EMAIL", "").strip()
    if dev_email:
        return {"user_id": f"local-dev:{dev_email}", "email": dev_email, "display_name": dev_email}
    return None


def create_api_token(user: dict) -> str:
    """Short-lived token the internal FastAPI service verifies (see api/auth.py)."""
    now = int(time.time())
    return jwt.encode(
        {
            "sub": user["user_id"],
            "email": user.get("email"),
            "name": user.get("display_name"),
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "iat": now,
            "exp": now + API_TOKEN_TTL_SECONDS,
        },
        JWT_SECRET,
        algorithm="HS256",
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


def call_api(path: str, file_bytes: bytes, job_description: str, user: dict) -> Tuple[Optional[dict], str]:
    """POST the resume to /analyze or /generate-resume. Returns (result, error_message)."""
    try:
        response = requests.post(
            f"{API_URL}/{path}",
            files={"file": ("uploaded_document.pdf", file_bytes, "application/pdf")},
            data={"job_description": job_description} if job_description else {},
            headers={"Authorization": f"Bearer {create_api_token(user)}"},
            timeout=API_TIMEOUT_SECONDS,
        )
        if response.status_code == 429:
            return None, _rate_limit_message(response)
        if not response.ok:
            # Show FastAPI's `detail` only; never raw exception text or internal URLs.
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            return None, detail if isinstance(detail, str) and detail else f"The service returned an error (HTTP {response.status_code})."
        result = response.json()
        if not result.get("success"):
            return None, result.get("report") or "The request failed."
        return result, ""
    except requests.exceptions.Timeout:
        return None, "The request timed out. Please try again."
    except requests.exceptions.ConnectionError:
        return None, "Could not reach the analysis service. Please try again shortly."
    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"[Client] API request failed: {type(e).__name__}: {e}")
        return None, "An unexpected error occurred. Please try again."


# Setting Page Config
st.set_page_config(
    page_title="AnalyzeMyCV", layout="wide", initial_sidebar_state="expanded"
)

# Injecting Custom CSS To Use The Inter Font, Reduce Size, And Align Widget Heights.
# Inter (SIL OFL) is self-hosted by proxy.py at /auth/fonts/; the system UI fonts are the fallback.
# Code blocks stay monospace.
st.markdown(
    """
    <style>
    @font-face {
        font-family: "Inter";
        src: url("/auth/fonts/InterVariable.woff2") format("woff2");
        font-weight: 100 900;
        font-style: normal;
        font-display: swap;
    }
    html, body, p, li, span, a, small, th, td, summary, h1, h2, h3, h4, h5, h6, label, button, input, textarea, select,
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {
        font-family: Inter, -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui,
            "Segoe UI", Roboto, sans-serif !important;
    }
    code, pre, kbd {
        font-family: ui-monospace, "SF Mono", Menlo, Monaco, Consolas, monospace !important;
    }
    html, body {
        font-size: 15px !important;
    }
    /* Aligning the height of the text area to match the file uploader dropzone */
    [data-testid="stTextArea"] textarea {
        height: 95px !important;
        min-height: 95px !important;
    }
    /* Report typography: clear section breaks and readable lists */
    [data-testid="stMarkdownContainer"] h3 {
        margin-top: 1.4rem;
        padding-bottom: 0.3rem;
        border-bottom: 1px solid #27272a;
    }
    [data-testid="stMarkdownContainer"] h4 { margin-top: 1rem; }
    [data-testid="stMarkdownContainer"] li { margin-bottom: 0.35rem; }
    [data-testid="stMarkdownContainer"] hr { margin: 1rem 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

current_user = get_signed_in_user()
if not current_user:
    # The proxy redirects anonymous visitors to sign in before they reach the app,
    # so landing here means a configuration problem.
    st.title("AnalyzeMyCV")
    st.error("You are not signed in.")
    if CLERK_ENABLED:
        st.link_button("Sign in", SIGN_IN_PATH)
    elif os.getenv("WEBSITE_SITE_NAME"):
        st.caption("Clerk is not configured for this app.")
    else:
        st.caption("For local development, set LOCAL_DEV_USER_EMAIL in your .env file.")
    st.stop()

if len(JWT_SECRET) < 32:
    st.error("The app is misconfigured: JWT_SECRET must be set to at least 32 characters.")
    st.stop()


# User is authenticated - show main app
user_email = current_user.get("email") or ""
user_name = current_user.get("display_name") or user_email or "Signed in"

# st.text renders verbatim, so identity-provider-supplied values can't inject markdown.
st.sidebar.markdown("**Signed in as**")
st.sidebar.text(user_name)
if user_email and user_email != user_name:
    st.sidebar.text(user_email)

if CLERK_ENABLED:
    st.sidebar.link_button("Sign Out", SIGN_OUT_PATH)

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
    file_bytes = uploaded_file.getvalue()

    st.info("File loaded. Choose an action below.")
    action_col1, action_col2 = st.columns(2)
    analyze_clicked = action_col1.button("Analyze Document", use_container_width=True)
    generate_clicked = action_col2.button(
        "Generate Tailored Resume",
        use_container_width=True,
        help="Requires a job description above.",
    )

    if analyze_clicked:
        with st.spinner("Analyzing resume content... This may take a minute."):
            result, error = call_api("analyze", file_bytes, job_description, current_user)
        if result:
            st.success("Analysis Complete!")
            st.subheader("Full Analysis Report")
            metadata = result.get("metadata", {})
            for col, (key, label) in zip(
                st.columns(3),
                (("resume_score", "Resume Score"), ("ats_friendliness_score", "ATS Friendliness"), ("match_score", "Job Match")),
            ):
                if metadata.get(key) is not None:
                    col.metric(label, f"{metadata[key]}/100")
            report = result.get("report", "")
            with st.container(border=True):
                st.markdown(report)
            st.download_button(
                "Download report (Markdown)",
                data=report,
                file_name="resume_analysis.md",
                mime="text/markdown",
            )
        else:
            st.error(f"Analysis Failed: {error}")

    if generate_clicked:
        if not job_description.strip():
            st.error("Please paste a job description above before generating a tailored resume.")
        else:
            with st.spinner("Generating a tailored resume... This may take a minute."):
                result, error = call_api("generate-resume", file_bytes, job_description, current_user)
            if result:
                st.success("Tailored resume generated!")
                st.subheader("Tailored Resume")
                with st.container(border=True):
                    st.markdown(result.get("report", ""))
                st.download_button(
                    "Download tailored resume (Markdown)",
                    data=result.get("report", ""),
                    file_name="tailored_resume.md",
                    mime="text/markdown",
                )
            else:
                st.error(f"Resume Generation Failed: {error}")

else:
    st.markdown("""
    ## How It Works
    1. Upload a PDF file containing a resume.
    2. Click 'Analyze Document' for a scored report, or paste a job description and click
       'Generate Tailored Resume' for a rewritten version aimed at that role.
    3. The frontend sends the file to the FastAPI backend.
    4. The backend extracts text and sends it to the LLM for analysis or generation.
    """)
    st.caption("Powered by Streamlit, FastAPI, Azure OpenAI, and PyMuPDF on Azure App Service.")
    st.caption("Created by Vigneshwar K R | [LinkedIn](https://linkedin.com/in/toastcoder) • [GitHub](https://github.com/toastcoder)")
