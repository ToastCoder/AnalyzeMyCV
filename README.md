# AnalyzeMyCV

AI-powered resume analysis built with a FastAPI backend, a Streamlit frontend, and Azure OpenAI (GPT-5 Mini). It scores resumes, compares them against job descriptions, and generates tailored rewrites. It's hosted on Azure App Service.

**Production URL:** [https://tinyurl.com/analyzemycv](https://tinyurl.com/analyzemycv)

## Architecture

```
Browser ──▶ App Service Authentication ──▶ proxy.py :8000 ──▶ Streamlit 127.0.0.1:8001 ──▶ FastAPI 127.0.0.1:8080 ──▶ Azure OpenAI
            (Entra External ID sign-in)     (public entry)
```

* **Authentication:** Azure App Service Authentication ("Easy Auth") with Microsoft Entra External ID. The app stores no users or passwords. Easy Auth passes the signed-in user to the app as `X-MS-CLIENT-PRINCIPAL*` headers. Streamlit forwards that identity to FastAPI as a 5-minute HS256 token signed with `JWT_SECRET`.
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

Easy Auth only exists on App Service, so locally the app signs you in as `LOCAL_DEV_USER_EMAIL`. That setting is ignored on App Service. Without Azure OpenAI credentials, the API returns mock results.

## Production setup (Azure App Service)

1. **Identity provider:** in the [Entra admin center](https://entra.microsoft.com), create an *external* tenant. Add a **Sign up and sign in** user flow (email with password, collecting Display Name).
2. **Authentication:** Web App → Settings → Authentication → Add identity provider → **Microsoft**, tenant type **External**. Link the user flow, then set **Require authentication** with a **302 redirect** for unauthenticated requests. Also turn on **HTTPS Only**.
3. **Environment variables:** set the following.
   * `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME` (`gpt-5-mini`)
   * `JWT_SECRET`: at least 32 random characters (`python -c "import secrets; print(secrets.token_urlsafe(48))"`)
   * `EASY_AUTH_LOGIN_PATH`: optional, defaults to `/.auth/login/aad`
   * `SCM_DO_BUILD_DURING_DEPLOYMENT=true`
4. **Startup command:** `chmod +x ./entrypoint.sh && ./entrypoint.sh`. The GitHub workflow also sets this.
5. **Verify:** in Kudu (`https://<app>.scm.azurewebsites.net` → Environment), confirm `WEBSITE_AUTH_ENABLED=True`. The startup log should show `Proxy: App Service Authentication enabled: True`.

Password reset and email verification are handled by External ID. To disable a user, block their sign-in in the Entra admin center.

## Security notes

* Identity headers are trusted only when App Service reports `WEBSITE_AUTH_ENABLED=True`. If authentication is turned off, the proxy drops the headers and the app refuses access.
* FastAPI and Streamlit listen only on `127.0.0.1`. `proxy.py` is the only public listener, and it adds anti-framing, `nosniff`, referrer and HSTS headers.
* Uploads are capped at 8 MB. The LLM endpoints allow one request per user every 5 minutes. Error responses never include exception details. Resume content is never logged.
* Keep secrets in App Service settings or Key Vault, never in git. Rotate `JWT_SECRET` and the Azure OpenAI key if they're exposed.
