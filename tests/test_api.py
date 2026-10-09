# AnalyzeMyCV
# tests/test_api.py
"""API auth, shared rate limit and PDF limits. Runs in mock mode: no Azure OpenAI calls."""

import os
import time
import unittest

# Must be set before the api modules are imported. An empty (not missing) key stops
# load_dotenv from filling in real credentials from a developer's .env.
# A developer's .env.local may hold production Clerk keys; tests must never pick them up.
for _name in ("CLERK_SECRET_KEY", "CLERK_PUBLISHABLE_KEY", "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "CLERK_AUTHORIZED_PARTIES"):
    os.environ[_name] = ""
os.environ["AZURE_OPENAI_API_KEY"] = ""
os.environ["AZURE_OPENAI_ENDPOINT"] = ""
os.environ["JWT_SECRET"] = "t" * 40

import pymupdf as fitz
import jwt
from fastapi.testclient import TestClient

from api.main import app, limiter
from api.services import pdf_parser


def make_pdf(pages=1, text="Skills: Python. Experience: built and improved systems by 30%."):
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


def auth_header(user="user_1"):
    now = int(time.time())
    token = jwt.encode(
        {"sub": user, "iss": "analyzemycv-frontend", "aud": "analyzemycv-api", "iat": now, "exp": now + 60},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


class ApiTest(unittest.TestCase):
    def setUp(self):
        limiter.reset()
        self.client = TestClient(app)
        self.pdf = {"file": ("cv.pdf", make_pdf(), "application/pdf")}

    def test_requires_a_valid_token(self):
        self.assertEqual(self.client.post("/analyze", files=self.pdf).status_code, 401)
        bad = {"Authorization": "Bearer nonsense"}
        self.assertEqual(self.client.post("/analyze", files=self.pdf, headers=bad).status_code, 401)

    def test_token_signed_with_another_secret_is_rejected(self):
        now = int(time.time())
        token = jwt.encode(
            {"sub": "u", "iss": "analyzemycv-frontend", "aud": "analyzemycv-api", "iat": now, "exp": now + 60},
            "x" * 40, algorithm="HS256",
        )
        resp = self.client.post("/analyze", files=self.pdf, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 401)

    def test_analyze_returns_scores_in_mock_mode(self):
        resp = self.client.post("/analyze", files=self.pdf, headers=auth_header())
        self.assertEqual(resp.status_code, 200)
        meta = resp.json()["metadata"]
        self.assertEqual(meta["llm_provider"], "Mock")
        self.assertIsNotNone(meta["resume_score"])
        self.assertIsNone(meta["match_score"])

    def test_rate_limit_is_shared_across_llm_endpoints_and_per_user(self):
        self.assertEqual(self.client.post("/analyze", files=self.pdf, headers=auth_header("a")).status_code, 200)
        again = self.client.post(
            "/generate-resume", files={"file": ("cv.pdf", make_pdf(), "application/pdf")},
            data={"job_description": "python"}, headers=auth_header("a"),
        )
        self.assertEqual(again.status_code, 429)
        # A different user is unaffected.
        other = self.client.post("/analyze", files={"file": ("cv.pdf", make_pdf(), "application/pdf")}, headers=auth_header("b"))
        self.assertEqual(other.status_code, 200)

    def test_oversized_pdf_is_rejected_as_input_error(self):
        pdf = {"file": ("cv.pdf", make_pdf(pages=pdf_parser.MAX_PDF_PAGES + 1), "application/pdf")}
        body = self.client.post("/analyze", files=pdf, headers=auth_header()).json()
        self.assertFalse(body["success"])
        self.assertIn("too many pages", body["report"])

    def test_non_pdf_is_rejected_as_input_error(self):
        resp = self.client.post("/analyze", files={"file": ("cv.pdf", b"not a pdf", "application/pdf")}, headers=auth_header())
        self.assertFalse(resp.json()["success"])

    def test_generate_resume_returns_markdown_and_ten_latex_templates(self):
        resp = self.client.post("/generate-resume", files=self.pdf, data={"job_description": "python"}, headers=auth_header())
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["report"].startswith("# "))
        self.assertEqual(len(body["latex"]), 10)
        self.assertEqual({"id", "label", "description", "source", "tex"}, set(body["latex"][0]))
        self.assertNotIn("latex", body["metadata"])  # large payload lives in its own field
        self.assertTrue(body["metadata"]["tailoring_notes"])

    def test_analyze_has_no_latex(self):
        self.assertIsNone(self.client.post("/analyze", files=self.pdf, headers=auth_header()).json()["latex"])

    def test_generate_resume_requires_a_job_description(self):
        resp = self.client.post("/generate-resume", files=self.pdf, headers=auth_header())
        self.assertEqual(resp.status_code, 422)


class PdfParserTest(unittest.TestCase):
    def test_extracts_text(self):
        self.assertIn("Python", pdf_parser.parse_pdf(make_pdf()))

    def test_text_limit(self):
        dense = "\n".join(["x" * 100] * 55)  # ~5.5k chars per page, so 12 pages exceed the cap
        with self.assertRaises(pdf_parser.PdfTooLargeError):
            pdf_parser.parse_pdf(make_pdf(pages=12, text=dense))

    def test_garbage_returns_empty(self):
        self.assertEqual(pdf_parser.parse_pdf(b"garbage"), "")


if __name__ == "__main__":
    unittest.main()
