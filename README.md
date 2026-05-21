# AnalyzeMyCV

AI-powered resume analysis engine built with Streamlit and Azure OpenAI (GPT-5 Mini). Analyzes resumes against job descriptions to provide semantic scores and gap analysis, hosted on Azure App Service.

**Production URL:** [https://tinyurl.com/analyzemycv](https://tinyurl.com/analyzemycv)

---

## Tech Stack & Architecture

* **Frontend UI:** Streamlit (Python-driven reactive web interface)
* **AI Engine:** Azure OpenAI API Integration (GPT-5 Mini for contextual parsing and semantic processing)
* **Infrastructure / Hosting:** Azure App Services (Linux Environment)
* **CI/CD Pipeline:** GitHub Actions (`master_analyzemycv.yml` automated zip deployment via Oryx)

---

## Local Quickstart & Installation Steps

Follow these exact steps to set up and run the application on your local machine.

### Prerequisites
* **Python:** Ensure you have Python 3.9, 3.10, or 3.11 installed. You can check your version by running:
  ```bash
  python3 --version
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
* On Windows (Command Prompt)
* On Windows (PowerShell)
(Once activated, you will see (.venv) prepended to your terminal prompt line.)

**Step 4: Install Project Dependencies**
Upgrade the base package installer tool and fetch all the core packages listed in the requirements manifest:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Step 5: Configure Environment Variables Locally**
Create a .env file in the root folder of your project to securely pass your API keys to the application:
```bash
OPENAI_API_KEY=your_actual_api_key_here
```

**Step 6: Launch the Local Streamlit Server**
Boot up the development instance of the web application:
```bash
python -m streamlit run src/app.py
```

Once executed, the terminal will provide a local loopback link (usually `http://localhost:8501`). Copy and paste it into your browser to view the application live.

### Production Deployment (Azure App Service)
The application is deployed securely as a custom Python web container behind an automated reverse proxy structure on Azure. Critical App Settings (Environment Variables)
To allow heavy binary payloads and clear persistent state processing, the following variables must be configured under Settings -> Environment Variables in the Azure Portal:
* `OPENAI_API_KEY`: Secure token validation endpoint for processing workflows.
* `STREAMLIT_SERVER_MAX_UPLOAD_SIZE`: Set to 200 to prevent mobile proxy timeouts on multi-page PDF documents.
* `SCM_DO_BUILD_DURING_DEPLOYMENT`: Set to true to invoke clean automation routines during continuous delivery runs.
  
### Production Startup Command
To prevent aggressive mobile browser drops (CORS/XSRF handshake timeouts during long native file-picker selection events), the production node must be run with security relaxed selectively on proxy loops. This command should be defined symmetrically inside the Azure Portal General Settings and the GitHub Workflow YAML manifest:
```bash
python -m streamlit run src/app.py --server.port 8000 --server.address 0.0.0.0 --server.enableCORS=false --server.enableXsrfProtection=false --server.maxUploadSize=200
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


