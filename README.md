# AnalyzeMyCV

AI-powered resume analysis engine built with a FastAPI backend, Streamlit frontend, and Azure OpenAI (GPT-5 Mini). Analyzes resumes against job descriptions to provide semantic scores and gap analysis, hosted on Azure App Service.

**Production URL:** [https://tinyurl.com/analyzemycv](https://tinyurl.com/analyzemycv)

---

## Tech Stack & Architecture

* **Frontend UI:** Streamlit (Python-driven reactive web interface)
* **Backend API:** FastAPI (High-performance API server for robust model orchestration)
* **AI Engine:** Azure OpenAI API Integration (GPT-5 Mini for contextual parsing and semantic processing using the Responses API)
* **Infrastructure / Hosting:** Azure App Services (Linux Environment)
* **CI/CD Pipeline:** GitHub Actions (`master_analyzemycv.yml` automated zip deployment via Oryx)

---

## Local Quickstart & Installation Steps

Follow these exact steps to set up and run the application on your local machine.

### Prerequisites
* **Python:** Ensure you have Python 3.9, 3.10, or 3.11 installed. You can check your version by running:
  ```bash
  python3 --version
  ```
* **Git:** Installed and configured on your local terminal.

**Step 1: Clone the Repository**
Clone the codebase to your local system and navigate straight into the project root directory:
```bash
git clone https://github.com/ToastCoder/AnalyzeMyCV.git
cd AnalyzeMyCV
```

**Step 2: Create an Isolated Virtual Environment**
Create a local virtual environment (.venv) to keep the project packages isolated from your global system installations:
```bash
python3 -m venv .venv
```

**Step 3: Activate the Virtual Environment**
Activate the environment before running installations. This ensures packages are bound strictly to this workspace.
* On macOS / Linux Distributions (Ubuntu, Debian, Fedora, Arch)
  ```bash
  source .venv/bin/activate
  ```
* On Windows (Command Prompt)
  ```cmd
  .venv\Scripts\activate.bat
  ```
* On Windows (PowerShell)
  ```powershell
  .venv\Scripts\Activate.ps1
  ```
(Once activated, you will see (.venv) prepended to your terminal prompt line.)

**Step 4: Install Project Dependencies**
Upgrade the base package installer tool and fetch all the core packages listed in the requirements manifest:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Step 5: Configure Environment Variables Locally**
Create a .env file in the root folder of your project to securely pass your Azure OpenAI endpoints and keys to the application:
```bash
AZURE_OPENAI_API_KEY=your_actual_api_key_here
AZURE_OPENAI_ENDPOINT=https://your-resource.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5-mini
```

**Step 6: Launch the Local Application Services**
The application architecture is decoupled into a backend service and a frontend client. Boot up both services concurrently using the provided shell script:
```bash
chmod +x ./entrypoint.sh
./entrypoint.sh
```

Alternatively, for hot-reloading during active development, you can run them in separate isolated terminal windows:
* **Terminal 1 (Backend):** `uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload`
* **Terminal 2 (Frontend):** `streamlit run client/streamlit_client.py --server.port 8000`

Once executed, open your browser to `http://localhost:8000` to view the application live.

---

## Production Deployment (Azure App Service)
The application is deployed securely as a custom Python web container behind an automated reverse proxy structure on Azure.

### Critical App Settings (Environment Variables)
To allow heavy binary payloads and clear persistent state processing, the following variables must be configured under Settings -> Environment Variables in the Azure Portal:
* `AZURE_OPENAI_API_KEY`: Secure token validation endpoint for processing workflows.
* `AZURE_OPENAI_ENDPOINT`: Full URI string for the Azure API Gateway routing.
* `AZURE_OPENAI_DEPLOYMENT_NAME`: Set to gpt-5-mini (the exact deployment identity configured in Azure).
* `STREAMLIT_SERVER_MAX_UPLOAD_SIZE`: Set to 200 to prevent mobile proxy timeouts on multi-page PDF documents.
* `SCM_DO_BUILD_DURING_DEPLOYMENT`: Set to true to invoke clean automation routines during continuous delivery runs.
  
### Production Startup Command
To ensure both the backend API and frontend client start concurrently and properly bind to the Azure Linux container environment, the startup configuration is managed through a bash script. This command must be defined symmetrically inside the Azure Portal Configuration settings and the GitHub Workflow YAML manifest:
```bash
chmod +x ./entrypoint.sh && ./entrypoint.sh
```

### CI/CD Pipeline
Continuous deployment is triggered on every manual or automated merge request to the master integration timeline.

```yaml
name: Deploy AnalyzeMyCV to Azure

on:
  push:
    branches:
      - master

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
```
