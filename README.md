# AnalyzeMyCV

AI-powered resume analysis built with a FastAPI backend, a Streamlit frontend, and Azure OpenAI (GPT-5 Mini). It scores resumes, compares them against job descriptions, and generates tailored rewrites. It's hosted on Azure App Service.

## Tailored resumes and LaTeX

"Generate Tailored Resume" rewrites your resume for a job description and returns it as structured data. The app renders that into a Markdown preview and into ten self-contained LaTeX templates (Jake's Resume, four moderncv styles, and five built-in layouts). Pick one in the UI and download the `.tex`; compile it in Overleaf or with `pdflatex` / `xelatex` / `lualatex`.

* Nothing is compiled on the server. The model never writes LaTeX: our code fills the templates and escapes every character, so a resume containing `\input{...}` or `\write18{...}` comes out as plain text.
* Templates live in `api/services/latex_templates.py`. Jake's Resume is MIT-licensed (Jake Gutierrez, based on sb2nov/resume); the moderncv templates use the `moderncv` class (LPPL) from TeX Live.
* To test compilation locally, install [Tectonic](https://tectonic-typesetting.github.io) (`brew install tectonic`); `tests/test_latex_templates.py` then compiles every template. Without it that test is skipped.

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
git clone https://github.com/<your-username>/AnalyzeMyCV.git
cd AnalyzeMyCV
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in the values
./entrypoint.sh        # open http://localhost:8000
```

With `CLERK_PUBLISHABLE_KEY` empty, the app signs you in as `LOCAL_DEV_USER_EMAIL` (ignored on App Service). Set the key (and `JWT_SECRET`) to test real Clerk sign-in locally. Without Azure OpenAI credentials, the API returns mock results.

## Production setup (Azure App Service)

1. **Clerk:** create an application at [dashboard.clerk.com](https://dashboard.clerk.com). A *development* instance works on `*.azurewebsites.net` but shows a dev banner; a *production* instance requires a custom domain you own, with the DNS records Clerk lists; it cannot run on `*.azurewebsites.net`. The proxy warns at startup if the Frontend API host does not resolve. Once the production instance works, set `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` and `CLERK_AUTHORIZED_PARTIES` in App Service, and add the `name`/`email` session claims to it (`clerk config patch --instance prod`).
2. **Environment variables:** set the following in App Service. For local runs, `.env.local` overrides `.env` (both git-ignored).
   * `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME` (`gpt-5-mini`)
   * `JWT_SECRET`: at least 32 random characters (`python -c "import secrets; print(secrets.token_urlsafe(48))"`)
   * `CLERK_PUBLISHABLE_KEY`, and optionally `CLERK_SECRET_KEY` (email/name lookup) and `CLERK_AUTHORIZED_PARTIES`
   * `SCM_DO_BUILD_DURING_DEPLOYMENT=true`
3. Turn on **HTTPS Only** and **Web sockets** (Streamlit needs them). Do not enable App Service Authentication; Clerk replaces it.
4. **Startup command:** `chmod +x ./entrypoint.sh && ./entrypoint.sh`. The GitHub workflow also sets this.
5. **Verify:** the startup log should show `Proxy: Clerk authentication enabled: True`, and an anonymous request should redirect to `/auth/sign-in`.

Password reset and email verification are handled by Clerk. To disable a user, ban them in the Clerk dashboard; it applies within an hour (the proxy session lifetime, `SESSION_TTL_SECONDS`, default 3600).

## Security notes

* **Identity:** `X-Auth-*` headers are set only by the proxy after it verifies the Clerk session; client-sent copies are dropped. If Clerk is misconfigured the proxy returns 503 instead of serving the app. Session cookies are never forwarded to Streamlit.
* **Request hardening (`proxy.py`):** paths with dot segments, encoded slashes or double encoding are rejected (they could make the public-path rule and Streamlit disagree about the route); the original encoded path is forwarded untouched; WebSocket and state-changing requests whose `Origin` is another site are refused (set `ALLOWED_HOSTS` if your host rewrites the `Host` header); only `GET`/`HEAD` can use the public paths (`/static/`, health).
* **Recommended in production:** set `CLERK_AUTHORIZED_PARTIES` to your site's origin(s) so session tokens minted for any other origin are rejected. `SESSION_TTL_SECONDS` (default 3600) is how long a Clerk ban can take to apply.
* **Model output is untrusted:** the analysis report has images stripped and links flattened to `text (url)` (an image URL carrying resume text would otherwise be fetched by the browser with no click); tailored resumes are validated data, Markdown-escaped, and LaTeX-escaped (see above).
* FastAPI and Streamlit listen only on `127.0.0.1`. `proxy.py` is the only public listener, and every response it sends carries anti-framing, `nosniff`, referrer and HSTS headers.
* Uploads are capped at 8 MB, 15 pages and 50,000 characters. The LLM endpoints allow one request per user every 5 minutes, shared across both. Error responses never include exception details. Resume content is never logged.
* GitHub Actions are pinned to commit hashes; update them deliberately. Dependencies are not pinned, so run a dependency audit (for example `pip-audit -r requirements.txt`) regularly.
* Keep secrets in App Service settings or Key Vault, never in git. Rotate `JWT_SECRET`, the Clerk secret key and the Azure OpenAI key if they're exposed.
