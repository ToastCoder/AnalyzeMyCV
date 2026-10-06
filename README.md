# AnalyzeMyCV

AI-powered resume analysis built with a FastAPI backend, a Streamlit frontend, and Azure OpenAI (GPT-5 Mini). It scores resumes, compares them against job descriptions, and generates tailored rewrites. It's hosted on Azure App Service.

**Production URL:** [https://tinyurl.com/analyzemycv](https://tinyurl.com/analyzemycv)

## Architecture

```
Browser ──▶ proxy.py :8000 ──▶ Streamlit 127.0.0.1:8001 ──▶ FastAPI 127.0.0.1:8080 ──▶ Azure OpenAI
            (public entry, verifies Clerk session)
```

* **Authentication:** [Clerk](https://clerk.com). The app stores no users or passwords. Anonymous visitors are sent to `/auth/sign-in` (clerk-js); `proxy.py` verifies Clerk's session JWT against its JWKS and passes the user to Streamlit as `X-Auth-*` headers. Streamlit forwards that identity to FastAPI as a 5-minute HS256 token signed with `JWT_SECRET`. See `clerk_auth.py`.
* **Frontend:** Streamlit. **Backend:** FastAPI (PDF parsing with PyMuPDF, per-user rate limiting).
* **Hosting / CI:** Azure App Service (Linux). GitHub Actions deploys on every push to `master`.

## Local development

Requires Python 3.9–3.11.

```bash
git clone https://github.com/ToastCoder/AnalyzeMyCV.git
cd AnalyzeMyCV
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in the values
./entrypoint.sh        # open http://localhost:8000
```

With `CLERK_PUBLISHABLE_KEY` empty, the app signs you in as `LOCAL_DEV_USER_EMAIL` (ignored on App Service). Set the key (and `JWT_SECRET`) to test real Clerk sign-in locally. Without Azure OpenAI credentials, the API returns mock results.

## Production setup (Azure App Service)

1. **Clerk:** create an application at [dashboard.clerk.com](https://dashboard.clerk.com). A *development* instance works on `*.azurewebsites.net` but shows a dev banner; a *production* instance requires a custom domain you own.
2. **Environment variables:** set the following in App Service.
   * `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME` (`gpt-5-mini`)
   * `JWT_SECRET`: at least 32 random characters (`python -c "import secrets; print(secrets.token_urlsafe(48))"`)
   * `CLERK_PUBLISHABLE_KEY`, and optionally `CLERK_SECRET_KEY` (email/name lookup) and `CLERK_AUTHORIZED_PARTIES`
   * `SCM_DO_BUILD_DURING_DEPLOYMENT=true`
3. Turn on **HTTPS Only** and **Web sockets** (Streamlit needs them). Do not enable App Service Authentication; Clerk replaces it.
4. **Startup command:** `chmod +x ./entrypoint.sh && ./entrypoint.sh`. The GitHub workflow also sets this.
5. **Verify:** the startup log should show `Proxy: Clerk authentication enabled: True`, and an anonymous request should redirect to `/auth/sign-in`.

Password reset and email verification are handled by Clerk. To disable a user, ban them in the Clerk dashboard; it applies within 15 minutes (the proxy session lifetime).

## Security notes

* `X-Auth-*` identity headers are set only by the proxy after it verifies the Clerk session; client-sent copies are dropped. If Clerk is misconfigured, the proxy returns 503 instead of serving the app.
* FastAPI and Streamlit listen only on `127.0.0.1`. `proxy.py` is the only public listener, and it adds anti-framing, `nosniff`, referrer and HSTS headers.
* Uploads are capped at 8 MB. The LLM endpoints allow one request per user every 5 minutes. Error responses never include exception details. Resume content is never logged.
* Keep secrets in App Service settings or Key Vault, never in git. Rotate `JWT_SECRET` and the Azure OpenAI key if they're exposed.
