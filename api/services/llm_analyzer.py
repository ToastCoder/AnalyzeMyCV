# AnalyzeMyCV
# api/services/llm_analyzer.py

import json
import logging
import os
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

# Loading Environment Variables From Dotenv If Present
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()


class LLMAnalyzer:
    # Handling Interaction With The Large Language Model
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.client = self._initialize_llm_client()

    def _initialize_llm_client(self):
        # Initializing The Appropriate LLM Client Based On Environment
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")

        if api_key and endpoint:
            self.logger.info("Initializing Azure OpenAI client...")
            try:
                # Parsing The Endpoint To Extract Api Version If Present
                parsed_url = urlparse(endpoint)
                query_params = parse_qs(parsed_url.query)
                api_version = query_params.get("api-version", ["2025-03-01-preview"])[0]

                # We must use the full endpoint verbatim so custom routing (like /openai/responses) is preserved
                return AzureOpenAI(
                    api_key=api_key,
                    api_version=api_version,
                    azure_endpoint=endpoint,
                )
            except Exception as e:
                self.logger.error(f"Failed to initialize Azure OpenAI client: {e}")
                return "AZURE_CLIENT_MOCK"

        elif os.getenv("OLLAMA_BASE_URL"):
            self.logger.warning("Ollama environment variable found. Using Ollama mock.")
            return "OLLAMA_CLIENT_MOCK"

        else:
            self.logger.warning(
                "No LLM API key found (Azure or Ollama). Using mock client."
            )
            return "MOCK_CLIENT"

    def analyze_resume_content(
        self, extracted_text: str, job_description: Optional[str] = None
    ) -> Tuple[Optional[str], dict]:
        # Sending The Extracted Resume Content To The LLM For Comprehensive Analysis
        self.logger.info("Starting LLM analysis pipeline.")

        try:
            # Loading Prompts From Settings JSON File
            try:
                # Resolving Path To Config Settings Relative To The Project Root
                settings_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config", "settings.json")
                with open(settings_path, "r") as f:
                    settings = json.load(f)
                prompts = settings.get("analysis_prompts", {})
            except Exception as e:
                self.logger.error(f"Failed to load settings.json: {e}")
                prompts = {}
                
            base_system_prompt = prompts.get("system_role", "You are an expert AI Recruiter and Resume Analyzer.")
            match_template = prompts.get("match_report_template", "")

            if isinstance(self.client, AzureOpenAI):
                self.logger.info("Executing Azure OpenAI analysis call...")
                deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4")

                system_prompt = base_system_prompt
                if job_description and match_template:
                    user_message = match_template.format(job_description=job_description, resume_text=extracted_text)
                else:
                    user_message = f"Here is the resume text to analyze:\n\n{extracted_text}"

                if deployment_name == "gpt-5-mini":
                    self.logger.info("Using Azure OpenAI Responses API for gpt-5-mini model...")
                    response = self.client.responses.create(
                        model=deployment_name,
                        input=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ]
                    )
                    report = response.output_text
                else:
                    response = self.client.chat.completions.create(
                        model=deployment_name,
                        messages=[
                            {"role": "developer", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ]
                    )
                    report = response.choices[0].message.content

                metadata = {
                    "llm_provider": "AzureOpenAI",
                    "model_used": deployment_name,
                    "prompt_size": len(extracted_text)
                    + (len(job_description) if job_description else 0),
                    "has_job_description": bool(job_description),
                }
                return report, metadata

            elif self.client == "AZURE_CLIENT_MOCK":
                self.logger.info("Executing Azure OpenAI analysis mock call...")
                mock_report = (
                    "### AI Analysis Report (Azure OpenAI Mock) ###\n"
                    "The analysis ran successfully using the Azure OpenAI fallback mock service. "
                    "The document was successfully parsed and the key skills and experiences were extracted."
                )
                if job_description:
                    mock_report += (
                        "\n\n**Job Match:** The resume aligns well with the target role."
                    )
                return mock_report, {
                    "llm_provider": "AzureOpenAI-Mock",
                    "model_used": "gpt-4-mock",
                    "prompt_size": len(extracted_text),
                    "has_job_description": bool(job_description),
                }

            elif self.client == "OLLAMA_CLIENT_MOCK":
                self.logger.info("Executing Ollama analysis call...")
                mock_report = (
                    "### AI Analysis Report (Ollama Mock) ###\n"
                    "The analysis ran successfully using the local Ollama service mock."
                )
                if job_description:
                    mock_report += "\n\n**Job Match:** Insights generated based on the provided job description."
                return mock_report, {
                    "llm_provider": "Ollama",
                    "model_used": "llama3",
                    "prompt_size": len(extracted_text),
                    "has_job_description": bool(job_description),
                }

            else:
                if job_description:
                    mock_report = (
                        "### AI Analysis Report (MOCKED) ###\n"
                        "The analysis ran successfully using a mock client.\n\n"
                        "**Job Description Match:** Based on the provided job description, the resume shows strong foundational overlap.\n"
                        "**Identified Gaps:** Some specific technologies mentioned in the JD are missing from the resume.\n"
                        "**Actionable Advice:** Consider highlighting relevant projects that align better with the JD's requirements."
                    )
                else:
                    mock_report = (
                        "### AI Analysis Report (MOCKED) ###\n"
                        "The analysis ran successfully using a mock client. "
                        "The content was sufficiently rich for analysis. "
                        "The document structure suggests a strong academic background with measurable project experience."
                    )
                return mock_report, {
                    "llm_provider": "Mock",
                    "model_used": "gpt-4o-mock",
                    "prompt_size": len(extracted_text),
                    "has_job_description": bool(job_description),
                }

        except Exception as e:
            self.logger.error(f"Error during LLM analysis: {e}")
            return (
                f"Analysis failed due to a service error: {str(e)}. Please check service credentials and availability.",
                {"llm_provider": "Failed", "error_message": str(e)},
            )
