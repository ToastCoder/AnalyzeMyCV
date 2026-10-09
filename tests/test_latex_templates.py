# AnalyzeMyCV
# tests/test_latex_templates.py
"""Structured resume validation, LaTeX escaping, and every template. No network, no model."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

# A developer's .env.local may hold production Clerk keys; tests must never pick them up.
for _name in ("CLERK_SECRET_KEY", "CLERK_PUBLISHABLE_KEY", "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "CLERK_AUTHORIZED_PARTIES"):
    os.environ[_name] = ""
os.environ["AZURE_OPENAI_API_KEY"] = ""
os.environ["AZURE_OPENAI_ENDPOINT"] = ""

from api.services.latex_templates import TEMPLATES, esc, render_all, url_arg
from api.services.llm_analyzer import LLMAnalyzer, _count_source_bullets
from api.services.resume_data import Link, Resume, parse_resume_json, to_markdown

NASTY = {
    "name": "José O'Brien & Sons",
    "headline": "Backend Engineer — Python & \\input{/etc/passwd} 100%",
    "email": "jose_ob@example.com", "phone": "+91 98765-43210", "location": "Chennai, IN",
    "links": [
        {"label": "linkedin.com/in/jose_o", "url": "linkedin.com/in/jose_o"},
        {"label": "site", "url": "https://example.com/a%20b?x=1&y=2#frag"},
        {"label": "bad", "url": "javascript:alert(1)"},
    ],
    "summary": "Cut costs by 30% ~ $10k/mo. Uses {braces}, #hash, ^caret, \\write18{rm -rf /}, "
               "\\immediate\\openin and emoji \U0001F680 plus \u201cquotes\u201d \u2013 dashes.",
    "sections": [
        {"title": "Skills", "skills": [{"label": "Languages", "items": "Python, C#, SQL_Server"}]},
        {"title": "Experience", "entries": [
            {"title": "Backend Engineer", "organization": "Acme Corp.", "location": "Remote", "dates": "2022 \u2013 Present",
             "bullets": ["Reduced latency by 30% on <10ms paths", "\u2022 Wrote tests: 100% coverage_of core"]},
            {"title": "", "organization": "Freelance", "dates": "2020"}]},
        {"title": "Education", "entries": [{"title": "BSc Computer Science", "organization": "Anna University", "dates": "2017 - 2021"}]},
        {"title": "Certifications", "text": "AWS Certified Developer \u2013 Associate (2023)"},
    ],
}


class EscapeTest(unittest.TestCase):
    def test_special_characters(self):
        self.assertEqual(esc(r"a & b % c $ d # e _ f { g } h ~ i ^ j \ k"),
                         r"a \& b \% c \$ d \# e \_ f \{ g \} h \textasciitilde{} i \textasciicircum{} j \textbackslash{} k")

    def test_injection_strings_become_literal_text(self):
        for attack in (r"\input{/etc/passwd}", r"\write18{rm -rf /}", r"\immediate\write18{x}", r"\openin1=secret"):
            with self.subTest(attack):
                out = esc(attack)
                self.assertNotRegex(out, r"(?<!textbackslash\{\})\\(input|write|immediate|openin)")
                self.assertTrue(out.startswith(r"\textbackslash{}"))

    def test_typography_and_emoji(self):
        self.assertEqual(esc("\u201cHi\u201d \u2013 it\u2019s"), "``Hi'' -- it's")
        self.assertEqual(esc("ship it \U0001F680\u2728"), "ship it ")
        self.assertEqual(esc("Jos\u00e9"), "Jos\u00e9")

    def test_url_whitelist(self):
        self.assertEqual(url_arg("https://x.com/a%20b#c"), r"https://x.com/a\%20b\#c")
        self.assertEqual(url_arg("https://x.com/{\\input}$"), "https://x.com/input")


class ResumeDataTest(unittest.TestCase):
    def test_link_validator(self):
        self.assertEqual(Link(label="x", url="linkedin.com/in/a").url, "https://linkedin.com/in/a")
        for bad in ("javascript:alert(1)", "data:text/html,x", "ftp://example.com/x", "https://localhost/x", "not a url", "mailto:a@b.co", "https://google.com@evil.com/x"):
            with self.subTest(bad):
                self.assertEqual(Link(label="x", url=bad).url, "")

    def test_invalid_links_and_empty_sections_are_removed(self):
        r = Resume.model_validate(NASTY | {"sections": NASTY["sections"] + [{"title": "Empty"}, {"title": "", "text": "x"}]})
        self.assertEqual(len(r.links), 2)
        self.assertEqual([s.title for s in r.sections], ["Skills", "Experience", "Education", "Certifications"])

    def test_text_is_cleaned_and_capped(self):
        with self.assertRaises(ValueError):  # over-long values are rejected, not silently stored
            Resume.model_validate({"name": "A", "summary": "x" * 5000})
        r = Resume.model_validate({"name": "A\x00B\u200bC\nD", "sections": [
            {"title": "Experience", "entries": [{"title": "T", "bullets": ["\u2022 one", "- two", ""] + ["b"] * 30}]}]})
        self.assertEqual(r.name, "ABC D")
        bullets = r.sections[0].entries[0].bullets
        self.assertEqual(bullets[:2], ["one", "two"])
        self.assertLessEqual(len(bullets), 12)

    def test_parse_accepts_code_fence_and_ignores_extra_keys(self):
        raw = "```json\n" + json.dumps({"name": "A", "summary": "s", "surprise": {"x": 1}}) + "\n```"
        self.assertEqual(parse_resume_json(raw).name, "A")

    def test_parse_rejects_unusable_replies(self):
        for raw in ("", "not json", "[]", json.dumps({"name": ""}), json.dumps({"name": "A"}), json.dumps({"sections": []})):
            with self.subTest(raw):
                with self.assertRaises(ValueError):
                    parse_resume_json(raw)

    def test_markdown_cannot_carry_images_or_links(self):
        attack = "![x](https://a.io/?q=1) [c](https://e.io) <img src=x>"
        r = Resume.model_validate({"name": attack, "headline": attack, "summary": attack, "sections": [
            {"title": attack, "text": attack, "skills": [{"label": attack, "items": attack}],
             "entries": [{"title": attack, "organization": attack, "dates": attack, "bullets": [attack]}]}]})
        md = to_markdown(r)
        try:
            from markdown_it import MarkdownIt
        except ImportError:  # markdown-it-py ships with Streamlit's dependencies; skip if absent
            self.skipTest("markdown-it-py not installed")
        html = MarkdownIt("commonmark", {"html": False}).render(md)
        for tag in ("<img", "<a ", "<script"):
            self.assertNotIn(tag, html)

    def test_markdown(self):
        md = to_markdown(Resume.model_validate(NASTY))
        self.assertTrue(md.startswith("# José O'Brien & Sons"))
        self.assertIn("## Experience", md)
        self.assertIn("**Backend Engineer, Acme Corp., Remote (2022 – Present)**", md)
        self.assertIn("- **Languages:** Python, C#, SQL_Server", md)


class TemplateTest(unittest.TestCase):
    def setUp(self):
        self.resume = Resume.model_validate(NASTY)

    def test_there_are_ten_unique_templates(self):
        ids = [t.id for t in TEMPLATES]
        self.assertEqual(len(ids), 10)
        self.assertEqual(len(set(ids)), 10)

    def test_every_template_renders_a_complete_document(self):
        for item in render_all(self.resume):
            with self.subTest(item["id"]):
                tex = item["tex"]
                self.assertIn("\\documentclass", tex)
                self.assertIn("\\begin{document}", tex)
                self.assertTrue(tex.rstrip().endswith("\\end{document}"))
                self.assertIn("Jos\u00e9", tex)

    def test_no_model_text_reaches_latex_as_a_command(self):
        for item in render_all(self.resume):
            with self.subTest(item["id"]):
                tex = item["tex"]
                # The only \input is the engine block's glyphtounicode; nothing dangerous at all.
                self.assertLessEqual(set(re.findall(r"\\input\{([^}]*)\}", tex)), {"glyphtounicode"})
                for forbidden in ("\\write", "\\immediate", "\\openin", "\\openout", "\\read", "\\catcode", "\\def\\"):
                    self.assertNotIn(forbidden, tex.replace("\\textbackslash{}", ""))
                self.assertNotIn("javascript:", tex)
                self.assertNotIn("\U0001F680", tex)

    def test_minimal_resume_renders(self):
        minimal = Resume.model_validate({"name": "Solo", "summary": "Just a summary."})
        for item in render_all(minimal):
            with self.subTest(item["id"]):
                self.assertIn("Just a summary.", item["tex"])

    @unittest.skipUnless(shutil.which("tectonic"), "tectonic is not installed")
    def test_every_template_compiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            for item in render_all(self.resume):
                with self.subTest(item["id"]):
                    path = os.path.join(tmp, f"{item['id']}.tex")
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(item["tex"])
                    proc = subprocess.run(["tectonic", path], capture_output=True, text=True, timeout=300, cwd=tmp)
                    self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
                    self.assertTrue(os.path.exists(path[:-4] + ".pdf"))


class NeutralizeMarkdownTest(unittest.TestCase):
    def test_images_are_removed_and_links_show_their_destination(self):
        from api.services.llm_analyzer import _neutralize_markdown as n
        out = n("### A\n![x](https://evil.example/?q=1)\n![y][ref]\n[Verify](https://evil.example/login \"t\")\n<img src=x>\n[ref]: http://evil.example\n- ok")
        self.assertNotIn("![", out)
        self.assertNotIn("<img", out)
        self.assertNotIn("](", out)
        self.assertNotIn("[ref]:", out)
        self.assertIn("Verify (https://evil.example/login)", out)
        self.assertIn("- ok", out)


class GenerateFlowTest(unittest.TestCase):
    """generate_tailored_resume with a fake model: validation, the single retry, and the bullet guard."""

    SOURCE = "Experience\n- built apis\n- led migration\nIntern\n- wrote pipelines\n"

    def analyzer(self, replies):
        a = LLMAnalyzer()
        a.client = object()  # truthy: take the real (non-mock) path
        a._call_llm = lambda *args, **kwargs: replies.pop(0)
        self.calls_left = replies
        return a

    @staticmethod
    def reply(n_bullets):
        return json.dumps({"name": "A", "sections": [{"title": "Experience", "entries": [
            {"title": "Dev", "organization": "X", "dates": "2020", "bullets": [f"b{i}" for i in range(n_bullets)]}]}]})

    def test_counts_source_bullets(self):
        self.assertEqual(_count_source_bullets(self.SOURCE), 3)

    def test_good_reply_is_used_without_retry(self):
        a = self.analyzer([self.reply(3), self.reply(3)])
        md, meta = a.generate_tailored_resume(self.SOURCE, "job")
        self.assertIn("# A", md)
        self.assertEqual(len(meta["latex"]), 10)
        self.assertEqual(len(self.calls_left), 1)  # second reply never requested

    def test_malformed_reply_is_retried_once(self):
        md, meta = self.analyzer(["not json", self.reply(3)]).generate_tailored_resume(self.SOURCE, "job")
        self.assertIsNotNone(md)

    def test_two_malformed_replies_fail_cleanly(self):
        md, meta = self.analyzer(["nope", "still nope"]).generate_tailored_resume(self.SOURCE, "job")
        self.assertIsNone(md)
        self.assertEqual(meta["llm_provider"], "Failed")

    def test_dropped_bullets_trigger_one_retry_and_the_better_attempt_wins(self):
        md, _ = self.analyzer([self.reply(1), self.reply(3)]).generate_tailored_resume(self.SOURCE, "job")
        self.assertEqual(md.count("\n- "), 3)
        md, _ = self.analyzer([self.reply(2), self.reply(1)]).generate_tailored_resume(self.SOURCE, "job")
        self.assertEqual(md.count("\n- "), 2)  # a worse retry never replaces a better first answer

    def test_notes_reach_the_ui_escaped_and_stay_out_of_the_resume(self):
        reply = json.loads(self.reply(3))
        reply["notes"] = ["Moved the bot first", "Gap: ![x](https://a.io/?q=1) Kubernetes"]
        md, meta = self.analyzer([json.dumps(reply)]).generate_tailored_resume(self.SOURCE, "job")
        self.assertEqual(meta["tailoring_notes"][0], "Moved the bot first")
        self.assertNotIn("![", meta["tailoring_notes"][1])
        self.assertNotIn("Moved the bot first", md)
        self.assertTrue(all("Moved the bot first" not in item["tex"] for item in meta["latex"]))

    def test_mock_mode_returns_sample_templates(self):
        md, meta = LLMAnalyzer().generate_tailored_resume(self.SOURCE, "job")
        self.assertEqual(meta["llm_provider"], "Mock")
        self.assertEqual(len(meta["latex"]), 10)


if __name__ == "__main__":
    unittest.main()
