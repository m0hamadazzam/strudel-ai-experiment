"""Tests for prompt builder."""

import unittest

from backend.prompts import build_system_prompt


class TestBuildSystemPrompt(unittest.TestCase):
    def test_contains_no_require_rule(self):
        prompt = build_system_prompt()
        self.assertIn("require()", prompt)
        self.assertTrue(
            "Do not use" in prompt or "No require()" in prompt
        )

    def test_contains_only_apis_from_context(self):
        prompt = build_system_prompt()
        self.assertTrue(
            "only APIs" in prompt or "ONLY functions" in prompt
        )
        self.assertTrue(
            "Knowledge Base" in prompt or "Strudel facts" in prompt
        )

    def test_with_kb_context_injects_and_restricts(self):
        kb_context = "Function: stack\nDescription: stacks patterns."
        prompt = build_system_prompt(kb_context=kb_context)
        self.assertIn("Knowledge Base", prompt)
        self.assertIn(kb_context, prompt)
        self.assertTrue("use ONLY" in prompt or "ONLY functions" in prompt)

    def test_mentions_explanation_field(self):
        prompt = build_system_prompt()
        self.assertIn("explanation", prompt)
