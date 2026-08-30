# Security & Secrets Management

## Overview

This document explains how AnalyzeMyCV handles sensitive information and prevents credential leaks.

---

## Secrets Management Strategy

### ✅ GOOD: Environment Variables

All sensitive data is stored in `.env` file (never committed):

```env
AZURE_CLIENT_SECRET=your-secret-here
AZURE_OPENAI_API_KEY=your-key-here
AZURE_SQL_PASSWORD=your-password-here
```

**Why it's safe:**
- `.env` is in `.gitignore` → never pushed to GitHub
- Only `.env.example` is in version control (with placeholders)
- Different per environment (local, staging, production)
- Loaded at runtime via `python-dotenv`

### ❌ NEVER: Hardcoded Secrets

Examples of what NOT to do:

```python
# ❌ BAD - Hardcoded secret
SUPABASE_KEY = "sb_publishable__Ya82edvyUkjKCOjacOMuA_XBvL-m5F"

# ✅ GOOD - From environment
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
```

---

## File-by-File Security Review

### ✅ Safe Files (No Secrets)

**`api/azure_auth.py`**
```python
TENANT_ID = os.getenv("AZURE_TENANT_ID", "").strip()      # ✅ From env
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "").strip() # ✅ From env
logger.info(f"CLIENT_ID set = {bool(CLIENT_ID)}")          # ✅ Logs bool only
```

**`api/database.py`**
```python
SQLALCHEMY_DATABASE_URL = os.getenv("AZURE_SQL_DATABASE_URL", "").strip()
# ✅ Connection string from env, never hardcoded
```

**`client/streamlit_client.py`**
```python
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "").strip()
# ✅ Never exposes secrets, only config values
```

**`api/main.py`**
```python
# ✅ No secrets
# ✅ All config from environment
```

### ⚠️ Files to Watch

**`.env` (DO NOT COMMIT)**
- Contains all secrets
- Protected by `.gitignore`
- Never push this file

**`.env.example` (Safe to commit)**
```env
AZURE_CLIENT_SECRET=your-client-secret-here  # ✅ Placeholder only
AZURE_OPENAI_API_KEY=your-key-here           # ✅ Placeholder only
```

---

## Security Checklist

### Pre-Deployment Verification

- [ ] `.env` is in `.gitignore`
- [ ] `.env` file doesn't appear in git history
  ```bash
  git ls-files | grep -E '\.env$'  # Should be empty
  ```
- [ ] No secrets in `.py` files
  ```bash
  grep -r "sk_" . --include="*.py"        # Check for API keys
  grep -r "password=" . --include="*.py"  # Check for passwords
  ```
- [ ] `.env.example` only has placeholders
- [ ] All credentials use environment variables
- [ ] No debug logs expose secrets
  ```python
  print(f"Secret: {SECRET}")  # ❌ BAD
  logger.info(f"Configured: {bool(SECRET)}")  # ✅ GOOD
  ```

---

## How Each Component Loads Secrets

### 1. Azure OpenAI (Already Implemented)
```python
# api/services/llm_analyzer.py
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
```

### 2. Azure Entra ID Authentication (New)
```python
# api/azure_auth.py
TENANT_ID = os.getenv("AZURE_TENANT_ID", "").strip()
CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "").strip()
```

### 3. Azure SQL Database (New)
```python
# api/database.py
SQLALCHEMY_DATABASE_URL = os.getenv("AZURE_SQL_DATABASE_URL", "").strip()
```

### 4. Streamlit Frontend
```python
# client/streamlit_client.py
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "").strip()
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "").strip()
AZURE_AUTH_REDIRECT_URI = os.getenv("AZURE_AUTH_REDIRECT_URI", "").strip()
```

---

## What Gets Logged?

### ✅ Safe Logging (No Secrets)

```python
logger.info(f"Auth: AZURE_CLIENT_ID set = {bool(AZURE_CLIENT_ID)}")
# Output: "Auth: AZURE_CLIENT_ID set = True"

logger.info(f"Database connected: {bool(SQLALCHEMY_DATABASE_URL)}")
# Output: "Database connected: True"

logger.info(f"Auth login attempt for: {email}")
# Output: "Auth login attempt for: user@company.com"
# ✅ Safe - no secrets exposed
```

### ❌ NEVER Log This

```python
logger.error(f"Token: {access_token}")              # ❌ Never!
logger.info(f"Client secret: {CLIENT_SECRET}")     # ❌ Never!
print(f"Database URL: {SQLALCHEMY_DATABASE_URL}")  # ❌ Never!
```

---

## Git Security

### Verify .env is Protected

```bash
# Check .gitignore contains .env
cat .gitignore | grep -E '^\.env'

# Verify .env is not in git
git status | grep .env
# Should output: nothing (not in staging)

# Verify .env not in history
git log --all --source --full-history -- .env
# Should output: nothing (no history)
```

### If Accidentally Committed

```bash
# Remove from history (DANGEROUS - rewrites git history)
git filter-branch --tree-filter 'rm -f .env' HEAD

# Force push (ONLY if no one else is working on the repo)
git push --force-with-lease
```

---

## Production Security

### Azure Key Vault (Recommended for Production)

Instead of `.env`, use Azure Key Vault:

```python
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

credential = DefaultAzureCredential()
vault_url = "https://your-vault-name.vault.azure.net/"
client = SecretClient(vault_url=vault_url, credential=credential)

# Load secrets
CLIENT_SECRET = client.get_secret("azure-client-secret").value
API_KEY = client.get_secret("azure-openai-api-key").value
```

**Benefits:**
- Centralized secret management
- Automatic rotation policies
- Audit logs
- No .env files in production
- Role-based access control

### Azure App Service Configuration

Set environment variables in Azure Portal:

```
Settings → Configuration → Application settings
```

Then in code:
```python
SECRET = os.getenv("AZURE_CLIENT_SECRET")
```

---

## Token Security

### Access Tokens (JWT)

**What they contain:**
```json
{
  "oid": "12345-user-object-id",
  "email": "user@company.com",
  "name": "User Name",
  "exp": 1234567890
}
```

**Security:**
- Signed with Azure's private key
- Verified using Azure's public keys (JWKS)
- Expires after 1 hour
- Should be in Authorization header only

**NEVER expose in:**
- Logs
- URLs
- Local storage (Streamlit)
- Browser console

### Refresh Tokens

**Security:**
- Rotated on each use
- Longer expiration (90 days)
- Should only be stored securely
- In production: use secure cookies (HttpOnly, Secure, SameSite)

---

## Data Privacy

### PII (Personally Identifiable Information)

What we store:
- User email (necessary for identification)
- Display name (user-provided)
- Azure Object ID (from Entra ID)
- Analysis timestamps (audit trail)

What we DON'T store:
- ❌ Password (Azure Entra ID handles this)
- ❌ Access tokens (generated on-demand)
- ❌ Resume content (in memory only, not persisted)
- ❌ Job descriptions (in memory only)

---

## Testing Security

### Local Development Checklist

```bash
# 1. Verify .env is loaded
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(bool(os.getenv('AZURE_CLIENT_SECRET')))"
# Should output: True

# 2. Search for hardcoded secrets
grep -r "sk_\|password\|secret" . --include="*.py" --exclude-dir=.git --exclude-dir=.venv
# Should have no results (except in .env which is ignored)

# 3. Verify environment variables required
python api/azure_auth.py  # Should not error about missing env vars

# 4. Check API doesn't expose secrets
curl http://localhost:8080/health
# Should only return: {"status": "ok", "service": "..."}
```

---

## Incident Response

### If a Secret Gets Leaked

1. **Immediate actions:**
   - Notify your team immediately
   - Go to Azure Portal
   - Regenerate compromised secrets

2. **For AZURE_CLIENT_SECRET:**
   - Azure AD → App registrations → Your app
   - Certificates & secrets → Delete old secret
   - Create new secret
   - Update `.env` and deployment

3. **For AZURE_OPENAI_API_KEY:**
   - Azure OpenAI resource → Keys and endpoints
   - Regenerate key
   - Update `.env` and deployment

4. **For Azure SQL password:**
   - Reset in Azure SQL Server settings
   - Update connection string in `.env`

5. **Post-incident:**
   - Review git history to find where it leaked
   - Update team on rotation schedule
   - Document lessons learned

---

## References

- [Azure Key Vault Documentation](https://learn.microsoft.com/en-us/azure/key-vault/)
- [OWASP: Secrets Management](https://owasp.org/www-community/Secrets_Management)
- [12 Factor App: Secrets](https://12factor.net/config)
- [Microsoft: Secure password storage](https://learn.microsoft.com/en-us/azure/)
