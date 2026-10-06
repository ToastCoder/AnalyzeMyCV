# AnalyzeMyCV
# tests/test_llm_analyzer.py
"""Markdown normalization and score extraction. Pure functions: no network."""

import os
import unittest

os.environ["AZURE_OPENAI_API_KEY"] = ""
os.environ["AZURE_OPENAI_ENDPOINT"] = ""

from api.services.llm_analyzer import LLMAnalyzer, _tidy_markdown


class TidyMarkdownTest(unittest.TestCase):
    def test_unwraps_whole_answer_code_fence(self):
        self.assertEqual(_tidy_markdown("```markdown\n### A\n\n- x\n```"), "### A\n\n- x")

    def test_keeps_inner_code_fences(self):
        text = "### A\n\nUse `x`:\n\n```\ncode\n```"
        self.assertEqual(_tidy_markdown(text), text)

    def test_demotes_top_level_headings_only_when_asked(self):
        self.assertEqual(_tidy_markdown("# T\n\n## S\n\n#### K", demote_headings=True), "### T\n\n### S\n\n#### K")
        self.assertEqual(_tidy_markdown("# T\n\n## S"), "# T\n\n## S")

    def test_adds_blank_lines_around_headings_and_collapses_extras(self):
        self.assertEqual(_tidy_markdown("intro\n### A\ntext\n\n\n\nmore"), "intro\n\n### A\n\ntext\n\nmore")

    def test_hash_inside_text_is_not_a_heading(self):
        self.assertEqual(_tidy_markdown("C# and F# skills\n#hashtag"), "C# and F# skills\n#hashtag")


class EnsureScoresTest(unittest.TestCase):
    def scores(self, report, jd="job"):
        return LLMAnalyzer._ensure_scores(report, "resume text", jd)

    def test_reads_heading_style_scores_without_adding_duplicates(self):
        report = "### Resume Score: 78/100\n\n### ATS Friendliness Score: 86/100\n\n### Match Score: 70/100\n\nbody"
        out, s = self.scores(report)
        self.assertEqual((s["resume_score"], s["ats_friendliness_score"], s["match_score"]), (78, 86, 70))
        self.assertEqual(out, report)

    def test_reads_bold_scores(self):
        out, s = self.scores("**Resume Score**: 61\n**ATS Friendliness Score** - 55/100\n**Match Score:** 40")
        self.assertEqual((s["resume_score"], s["ats_friendliness_score"], s["match_score"]), (61, 55, 40))
        self.assertNotIn("### Resume Score", out)

    def test_clamps_and_falls_back_when_missing(self):
        out, s = self.scores("### Resume Score: 250\n\nnothing else")
        self.assertEqual(s["resume_score"], 100)
        self.assertIn("### ATS Friendliness Score:", out)
        self.assertIsNotNone(s["match_score"])

    def test_no_match_score_without_job_description(self):
        _, s = self.scores("### Resume Score: 70\n### ATS Friendliness Score: 70", jd="")
        self.assertIsNone(s["match_score"])


class PromptTemplateTest(unittest.TestCase):
    def test_templates_format_with_only_the_documented_fields(self):
        prompts = LLMAnalyzer().settings
        for group, key in (("analysis_prompts", "report_template"), ("analysis_prompts", "match_report_template"),
                           ("resume_generation_prompts", "generation_template")):
            with self.subTest(key):
                out = prompts[group][key].format(job_description="JD-X", resume_text="CV-X")
                self.assertIn("CV-X", out)


if __name__ == "__main__":
    unittest.main()
