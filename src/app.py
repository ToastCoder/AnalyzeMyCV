# pyrefly: ignore [missing-import]
import streamlit as st
import os
import sys
from pathlib import Path

# Add the project root to sys.path so it can find 'src'
root_path = Path(__file__).parent.parent.parent
sys.path.append(str(root_path))

# pyrefly: ignore [missing-import]
from src.engine.parsers import extract_text_from_pdf
from src.engine.analyzer import get_match_report
from dotenv import load_dotenv

load_dotenv()
# ... rest of your streamlit code

load_dotenv() # Loads your Azure keys from .env

st.title("📄 AnalyzeMyCV")
st.markdown("### GPT-5 Mini Powered Resume Scorer")

# Inputs
jd_text = st.text_area("Paste the Job Description here", height=200)
uploaded_file = st.file_uploader("Upload Candidate Resume (PDF)", type="pdf")

if st.button("Run Analysis"):
    if uploaded_file and jd_text:
        with st.spinner("GPT-5 is analyzing..."):
            with open("temp_cv.pdf", "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            resume_markdown = extract_text_from_pdf("temp_cv.pdf")
            result = get_match_report(resume_markdown, jd_text)
            
            st.success("Analysis Complete!")
            st.markdown(result)
            
            os.remove("temp_cv.pdf")
    else:
        st.warning("Please upload a PDF and provide a JD.")