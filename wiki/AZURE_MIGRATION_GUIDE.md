# AnalyzeMyCV - Azure Entra ID & Azure SQL Migration Guide

## Overview

This document outlines the migration from Supabase authentication to **Azure Entra ID (OAuth2)** with **Azure SQL Database** for user data storage.

---

## Architecture Changes

### Before (Supabase)
- ❌ Email/password authentication through Supabase
- ❌ User data stored entirely in Supabase
- ❌ No relational database for app-specific user data
- ❌ Magic links for email confirmation

### After (Azure Entra ID + Azure SQL)
- ✅ OAuth2 authentication via Azure Entra ID
- ✅ Relational database (Azure SQL) for user profiles and analytics
- ✅ Enterprise-grade identity management
- ✅ No password management burden
- ✅ Support for MFA and conditional access

---

## Environment Variables Setup

### 1. Azure Entra ID Configuration

You need to register your application in Azure Portal. Follow these steps:

**Register Application:**
1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **Azure Active Directory → App registrations → New registration**
3. Name: `AnalyzeMyCV`
4. Supported account types: `Accounts in this organizational directory only`
5. Click **Register**

**Configure Redirect URI:**
1. In the app registration page, go to **Authentication**
2. Click **Add a platform → Web**
3. Add redirect URIs:
   - Local: `http://localhost:8501/auth/callback`
   - Production: `https://your-app-name.azurewebsites.net/auth/callback`

**Generate Client Secret:**
1. Go to **Certificates & secrets**
2. Click **New client secret**
3. Copy the secret value (only visible once!)

**Get Tenant ID:**
1. Go to **Overview** in the app registration
2. Copy the **Directory (tenant) ID**

**Environment Variables to Set:**
```env
AZURE_TENANT_ID=<Your Tenant ID>
AZURE_CLIENT_ID=<Your Application (client) ID>
AZURE_CLIENT_SECRET=<Your client secret>
AZURE_AUTH_REDIRECT_URI=http://localhost:8501/auth/callback
```

---

### 2. Azure SQL Database Configuration

**Create Azure SQL Database:**
1. Go to [Azure Portal](https://portal.azure.com)
2. Click **Create a resource → SQL Database**
3. Fill in details:
   - Database name: `analyzemycv`
   - Server: Create new
   - Compute + storage: Select tier (Basic is fine for dev)
4. Click **Create**

**Get Connection String:**
1. After creation, go to the database
2. Click **Connection strings**
3. Copy the **ODBC** connection string
4. Replace `{your_username}` and `{your_password}` with your SQL admin credentials

**Environment Variable:**
```env
AZURE_SQL_DATABASE_URL=mssql+pyodbc://username:password@server.database.windows.net/analyzemycv?driver=ODBC+Driver+17+for+SQL+Server
```

**For Local Development (SQLite):**
```env
AZURE_SQL_DATABASE_URL=sqlite:///./analyzemycv.db
```

---

### 3. Azure OpenAI Configuration
(No changes from before - keep existing)

```env
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-key-here
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5-mini
```

---

## Installation & Setup

### Prerequisites
```bash
# Install Python dependencies
pip install -r requirements.txt

# Install ODBC driver (for Azure SQL)
# macOS:
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew install mssql-tools

# Windows: Download from https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server
```

### Setup Steps

1. **Clone repository and create virtual environment**
```bash
git clone https://github.com/ToastCoder/AnalyzeMyCV.git
cd AnalyzeMyCV
python3 -m venv .venv
source .venv/bin/activate
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Configure environment variables**
```bash
cp .env.example .env
# Edit .env with your actual credentials
nano .env
```

4. **Initialize database**
The database tables will be created automatically when the API starts.

5. **Run locally**
```bash
# Terminal 1: Start FastAPI backend
python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8080

# Terminal 2: Start Streamlit frontend
streamlit run client/streamlit_client.py --server.port 8501
```

---

## API Endpoints

### Authentication Endpoints

**POST /auth/login**
```json
{
  "code": "authorization_code_from_azure"
}
```
Response:
```json
{
  "success": true,
  "user_id": "uuid",
  "user_email": "user@company.com",
  "display_name": "User Name",
  "access_token": "jwt_token",
  "refresh_token": "refresh_token"
}
```

**POST /auth/refresh**
```json
{
  "refresh_token": "refresh_token_from_previous_login"
}
```

**POST /auth/verify**
```json
{
  "access_token": "access_token_to_verify"
}
```

**POST /auth/logout**
Simple endpoint for client-side cleanup.

---

## Database Schema

### Users Table
```sql
CREATE TABLE users (
    user_id UNIQUEIDENTIFIER PRIMARY KEY,
    entra_id VARCHAR(255) UNIQUE NOT NULL,  -- Azure Entra ID Object ID
    email VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(255),
    email_verified BIT DEFAULT 1,
    is_active BIT DEFAULT 1,
    created_at DATETIME DEFAULT GETUTCDATE(),
    updated_at DATETIME DEFAULT GETUTCDATE(),
    last_login DATETIME
);
```

### Analysis Logs Table
```sql
CREATE TABLE analysis_logs (
    log_id UNIQUEIDENTIFIER PRIMARY KEY,
    user_id UNIQUEIDENTIFIER NOT NULL,  -- Foreign key to users
    file_name VARCHAR(255),
    has_job_description BIT DEFAULT 0,
    result_summary VARCHAR(2000),
    created_at DATETIME DEFAULT GETUTCDATE()
);
```

---

## Security Best Practices

### ✅ What's Protected

1. **Environment Variables**: All sensitive data (API keys, secrets) stored in `.env`
   - `.env` is in `.gitignore` and never committed
   - Only `.env.example` is in version control (with placeholder values)

2. **No Hardcoded Secrets**: All config loaded from environment variables
   - See `api/azure_auth.py` for examples

3. **Token Validation**: All tokens verified with Azure's public keys (JWKS)
   - `TokenVerifier` class in `api/azure_auth.py`

4. **HTTPS Required in Production**:
   - Update `AZURE_AUTH_REDIRECT_URI` to `https://` for production

### 🔒 Best Practices

1. **Never commit .env**
   - Use `.env.example` for documentation
   - Add to `.gitignore` (already done)

2. **Rotate secrets regularly**
   - Change `AZURE_CLIENT_SECRET` quarterly
   - Regenerate in Azure Portal

3. **Use Azure Key Vault for production**
   ```bash
   # Instead of .env file:
   from azure.identity import DefaultAzureCredential
   from azure.keyvault.secrets import SecretClient
   ```

4. **Enable MFA in Azure Entra ID**
   - Require MFA for all users
   - Configure conditional access policies

5. **Database connection security**
   - Use Azure SQL firewall rules
   - Enable encryption (TDE)
   - Use connection pooling with timeouts

---

## Migration from Supabase

### Step 1: Export user data from Supabase
```bash
# Via Supabase dashboard:
1. Go to Database
2. Run query to export auth users
3. Save as CSV
```

### Step 2: Import to Azure SQL (Optional)
```sql
-- Create temporary table
CREATE TABLE supabase_users_import (
    email VARCHAR(255),
    created_at DATETIME
);

-- Import CSV data
-- Then migrate to users table
```

### Step 3: Update Frontend/Backend
- ✅ Streamlit client updated to OAuth2 flow
- ✅ FastAPI auth module migrated to `api/azure_auth.py`
- ✅ New database models created in `api/user_models.py`

---

## Troubleshooting

### "Invalid token" error
- Ensure `AZURE_CLIENT_ID` matches your app registration
- Check token isn't expired
- Verify JWKS endpoint is reachable

### "Database connection failed"
- Verify `AZURE_SQL_DATABASE_URL` format
- Check ODBC driver installed: `odbcinst -j`
- Test connection: `sqlcmd -S server.database.windows.net -U username -P password`

### Localhost redirect not working
- Ensure `AZURE_AUTH_REDIRECT_URI` includes `http://localhost:8501/auth/callback`
- Check Streamlit is running on port 8501
- Browser might cache old redirect URIs (clear cookies)

### "Failed to fetch JWKS"
- Check internet connectivity
- Verify `AZURE_TENANT_ID` is correct
- Confirm Azure Portal is accessible

---

## Production Deployment to Azure

### 1. Create Azure Web App
```bash
az group create --name analyzemycv-rg --location eastus2
az appservice plan create --name analyzemycv-plan --resource-group analyzemycv-rg --sku B2
az webapp create --resource-group analyzemycv-rg --plan analyzemycv-plan --name analyzemycv
```

### 2. Configure App Settings
In Azure Portal → App Service → Configuration:
```
AZURE_TENANT_ID = <value>
AZURE_CLIENT_ID = <value>
AZURE_CLIENT_SECRET = <value>
AZURE_AUTH_REDIRECT_URI = https://analyzemycv.azurewebsites.net/auth/callback
AZURE_SQL_DATABASE_URL = <value>
AZURE_OPENAI_ENDPOINT = <value>
AZURE_OPENAI_API_KEY = <value>
AZURE_OPENAI_DEPLOYMENT_NAME = gpt-5-mini
```

### 3. Deploy
```bash
git push azure main  # If using Git deployment
# or
az webapp up --resource-group analyzemycv-rg --name analyzemycv
```

---

## Support & Documentation

- [Azure Entra ID Docs](https://learn.microsoft.com/en-us/entra/identity/)
- [MSAL Python Docs](https://github.com/AzureAD/microsoft-authentication-library-for-python)
- [Azure SQL Docs](https://learn.microsoft.com/en-us/azure/azure-sql/)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Streamlit Docs](https://docs.streamlit.io/)
