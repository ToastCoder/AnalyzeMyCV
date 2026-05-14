# AnalyzeMyCV
# src/app.py

# Importing Libraries
import streamlit as st
import os
import sys
from pathlib import Path
from src.engine.parsers import extract_text_from_pdf
from src.engine.analyzer import get_match_report
from dotenv import load_dotenv

root_path = Path(__file__).parent.parent.parent
sys.path.append(str(root_path))

# Load environment variables
load_dotenv()

# Streamlit UI
st.title("AnalyzeMyCV")
st.markdown("### AI Powered Resume Analyzer")

# Inputs section
jd_text = st.text_area("Paste the Job Description here", height=200)
uploaded_file = st.file_uploader("Upload Candidate Resume (PDF)", type="pdf")

# Run analysis button
if st.button("Run Analysis"):

    # Check if file and JD are provided
    if uploaded_file and jd_text:
        with st.spinner("GPT-5 is analyzing..."):

            # Save the uploaded PDF temporarily
            with open("temp_cv.pdf", "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            # Extract text from PDF
            resume_markdown = extract_text_from_pdf("temp_cv.pdf")

            # Get match report
            result = get_match_report(resume_markdown, jd_text)
            
            st.success("Analysis Complete!")
            st.markdown(result)
            
            # Cleanup
            os.remove("temp_cv.pdf")
    else:
        st.warning("Please upload a PDF and provide a Job Description.")