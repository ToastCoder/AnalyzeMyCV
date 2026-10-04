# AnalyzeMyCV
# client/streamlit_client.py
# Sign-in is handled by Azure App Service Authentication (Easy Auth)

import base64
import json
import os
import time
from typing import Optional, Tuple

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
# App Service sets WEBSITE_AUTH_ENABLED=True when Authentication is turned on.
EASY_AUTH_ENABLED = os.getenv("WEBSITE_AUTH_ENABLED", "").strip().lower() == "true"
EASY_AUTH_LOGIN_PATH = os.getenv("EASY_AUTH_LOGIN_PATH", "/.auth/login/aad")
EASY_AUTH_LOGOUT_PATH = "/.auth/logout?post_logout_redirect_uri=/"

_EMAIL_CLAIMS = (
    "emails",
    "email",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    "preferred_username",
)
_NAME_CLAIMS = ("name", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name")


def _decode_principal_claims(encoded: Optional[str]) -> dict:
    """Decode Easy Auth's base64 X-MS-CLIENT-PRINCIPAL header into a {claim_type: value} map."""
    if not encoded:
        return {}
    try:
        principal = json.loads(base64.b64decode(encoded, validate=True))
        return {
            claim["typ"]: claim["val"]
            for claim in principal.get("claims", [])
            if isinstance(claim, dict) and isinstance(claim.get("typ"), str) and isinstance(claim.get("val"), str)
        }
    except (ValueError, TypeError, AttributeError):
        return {}


def get_signed_in_user() -> Optional[dict]:
    """Return the user App Service Authentication signed in, or None.

    Easy Auth authenticates every request before it reaches the container,
    strips any client-supplied X-MS-CLIENT-PRINCIPAL* headers, and injects its
    own. Those headers are therefore only trusted when App Service reports
    that authentication is enabled (WEBSITE_AUTH_ENABLED); otherwise they
    could be forged by the caller. proxy.py applies the same rule.
    """
    if EASY_AUTH_ENABLED:
        headers = st.context.headers
        user_id = (headers.get("X-MS-CLIENT-PRINCIPAL-ID") or "").strip()
        if not user_id:
            return None
        claims = _decode_principal_claims(headers.get("X-MS-CLIENT-PRINCIPAL"))
        email = next(
            (claims[c] for c in _EMAIL_CLAIMS if claims.get(c)),
            (headers.get("X-MS-CLIENT-PRINCIPAL-NAME") or "").strip() or None,
        )
        name = next((claims[c] for c in _NAME_CLAIMS if claims.get(c)), None) or email
        return {"user_id": user_id, "email": email, "display_name": name}

    # Never fall back to a dev identity on App Service: if auth is switched off
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

current_user = get_signed_in_user()
if not current_user:
    # With "Require authentication" on, Easy Auth redirects anonymous visitors to
    # sign in before they reach the app, so landing here means a configuration problem.
    st.title("AnalyzeMyCV")
    st.error("You are not signed in.")
    if EASY_AUTH_ENABLED:
        st.link_button("Sign in", f"{EASY_AUTH_LOGIN_PATH}?post_login_redirect_uri=/")
    elif os.getenv("WEBSITE_SITE_NAME"):
        st.caption("App Service Authentication is not enabled for this app.")
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

if EASY_AUTH_ENABLED:
    st.sidebar.link_button("Sign Out", EASY_AUTH_LOGOUT_PATH)

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
            st.markdown(result.get("report", ""))
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
