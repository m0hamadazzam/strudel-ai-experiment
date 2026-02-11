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
            "retrieved context" in prompt or "Strudel facts" in prompt
        )

    def test_with_context_injects_and_restricts(self):
        context = "Function: stack\nDescription: stacks patterns."
        prompt = build_system_prompt(context)
        self.assertIn("Retrieved Knowledge Base Context", prompt)
        self.assertIn(context, prompt)
        self.assertTrue("use ONLY" in prompt or "ONLY functions" in prompt)

    def test_mentions_explanation_field(self):
        prompt = build_system_prompt()
        self.assertIn("explanation", prompt)
