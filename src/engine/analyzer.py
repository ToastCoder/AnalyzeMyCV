from openai import AzureOpenAI
import os

# Debug
print(os.getenv("AZURE_OPENAI_ENDPOINT"))

def get_match_report(resume_text, jd_text):
    
    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version="2025-03-01-preview" 
    )

    prompt_content = f"""
    Compare this Resume to the JD. Provide a Match Score.
    
    ## JOB DESCRIPTION:
    {jd_text}
    
    ## RESUME:
    {resume_text}
    """

    response = client.responses.create(
        model="gpt-5-mini",
        input=[
            {"role": "system", "content": "You are a professional AI CV Analyzer."},
            {"role": "user", "content": prompt_content}
        ]
    )
    
    # ...
    # The correct attribute for the 2026 Responses API is output_text
    return response.output_text