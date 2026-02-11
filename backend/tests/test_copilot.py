"""Tests for copilot validation and helpers."""

import unittest

from backend.copilot import _query_hash, _validate_generated_code


class TestValidateGeneratedCode(unittest.TestCase):
    def test_rejects_require(self):
        self.assertIsNotNone(_validate_generated_code('const x = require("fs")'))

    def test_rejects_import(self):
        self.assertIsNotNone(
            _validate_generated_code("import { s } from 'strudel'")
        )

    def test_rejects_process(self):
        self.assertIsNotNone(_validate_generated_code("process.env.NODE_ENV"))

    def test_rejects_module_exports(self):
        self.assertIsNotNone(_validate_generated_code("module.exports = {}"))

    def test_rejects_dirname(self):
        self.assertIsNotNone(_validate_generated_code("const p = __dirname"))

    def test_accepts_strudel(self):
        self.assertIsNone(_validate_generated_code('s("bd sd")'))
        self.assertIsNone(_validate_generated_code("stack(s('bd'), s('hh'))"))
        self.assertIsNone(_validate_generated_code('$: note("c eb g")'))

    def test_kb_rejects_unknown_function(self):
        allowed = {"s", "stack", "note"}
        err = _validate_generated_code("madeUpFunc(1)", allowed_function_names=allowed)
        self.assertIsNotNone(err)
        self.assertIn("madeUpFunc", err)
        self.assertIn("knowledge base", err)

    def test_kb_accepts_only_allowed_functions(self):
        allowed = {"s", "stack", "note", "fast"}
        self.assertIsNone(
            _validate_generated_code('stack(s("bd"), s("hh"))', allowed_function_names=allowed)
        )
        self.assertIsNone(
            _validate_generated_code("note('c3').fast(2)", allowed_function_names=allowed)
        )

    def test_kb_allows_methods_when_in_kb(self):
        allowed = {"s", "note", "fast", "gain"}
        err = _validate_generated_code("s('bd').fast(2).gain(0.8)", allowed_function_names=allowed)
        self.assertIsNone(err)


class TestQueryHash(unittest.TestCase):
    def test_deterministic(self):
        a = _query_hash("hello", "code1")
        b = _query_hash("hello", "code1")
        self.assertEqual(a, b)

    def test_different_inputs_different_hashes(self):
        self.assertNotEqual(_query_hash("a", ""), _query_hash("b", ""))
        self.assertNotEqual(_query_hash("a", "x"), _query_hash("a", "y"))
