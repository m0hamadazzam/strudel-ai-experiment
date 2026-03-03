"""Tests for copilot validation and helpers."""

import unittest

from backend.copilot import validate_generated_code


class TestValidateGeneratedCode(unittest.TestCase):
    def test_rejects_require(self):
        r = validate_generated_code('const x = require("fs")')
        self.assertFalse(r.ok)
        self.assertTrue(len(r.errors) > 0)

    def test_rejects_import(self):
        r = validate_generated_code("import { s } from 'strudel'")
        self.assertFalse(r.ok)
        self.assertTrue(len(r.errors) > 0)

    def test_rejects_process(self):
        r = validate_generated_code("process.env.NODE_ENV")
        self.assertFalse(r.ok)
        self.assertTrue(len(r.errors) > 0)

    def test_rejects_module_exports(self):
        r = validate_generated_code("module.exports = {}")
        self.assertFalse(r.ok)
        self.assertTrue(len(r.errors) > 0)

    def test_rejects_dirname(self):
        r = validate_generated_code("const p = __dirname")
        self.assertFalse(r.ok)
        self.assertTrue(len(r.errors) > 0)

    def test_accepts_strudel(self):
        r = validate_generated_code('s("bd sd")')
        self.assertTrue(r.ok, r.errors)
        r = validate_generated_code("stack(s('bd'), s('hh'))")
        self.assertTrue(r.ok, r.errors)
        r = validate_generated_code('$: note("c eb g")')
        self.assertTrue(r.ok, r.errors)

    def test_kb_rejects_unknown_function(self):
        allowed = {"s", "stack", "note"}
        r = validate_generated_code("madeUpFunc(1)", allowed_names=allowed)
        self.assertFalse(r.ok)
        self.assertIn("madeUpFunc", r.errors[0] if r.errors else "")

    def test_kb_accepts_only_allowed_functions(self):
        allowed = {"s", "stack", "note", "fast"}
        r = validate_generated_code(
            'stack(s("bd"), s("hh"))', allowed_names=allowed
        )
        self.assertTrue(r.ok, r.errors)
        r = validate_generated_code(
            "note('c3').fast(2)", allowed_names=allowed
        )
        self.assertTrue(r.ok, r.errors)

    def test_kb_allows_methods_when_in_kb(self):
        allowed = {"s", "note", "fast", "gain"}
        r = validate_generated_code(
            "s('bd').fast(2).gain(0.8)", allowed_names=allowed
        )
        self.assertTrue(r.ok, r.errors)
