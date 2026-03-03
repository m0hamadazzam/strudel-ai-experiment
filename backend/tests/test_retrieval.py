"""Tests for retrieval helpers."""

import unittest
from unittest.mock import MagicMock

from backend.rag.retrieval import _group_ids_by_type


class TestGroupIdsByType(unittest.TestCase):
    def test_deduplicates_and_preserves_order(self):
        doc = MagicMock()
        doc.metadata = {"type": "function", "function_id": 1}
        doc2 = MagicMock()
        doc2.metadata = {"type": "function", "function_id": 1}
        doc3 = MagicMock()
        doc3.metadata = {"type": "function", "function_id": 2}
        docs = [(doc, 0.1), (doc2, 0.2), (doc3, 0.3)]
        fids, rids, pids = _group_ids_by_type(docs)
        self.assertEqual(fids, [1, 2])
        self.assertEqual(rids, [])
        self.assertEqual(pids, [])

    def test_recipe_and_preset(self):
        doc_r = MagicMock()
        doc_r.metadata = {"type": "recipe", "recipe_id": 10}
        doc_p = MagicMock()
        doc_p.metadata = {"type": "preset", "preset_id": 20}
        fids, rids, pids = _group_ids_by_type(
            [(doc_r, 0.1), (doc_p, 0.2)]
        )
        self.assertEqual(fids, [])
        self.assertEqual(rids, [10])
        self.assertEqual(pids, [20])

    def test_ignores_invalid_metadata(self):
        doc = MagicMock()
        doc.metadata = {"type": "function"}
        fids, rids, pids = _group_ids_by_type([(doc, 0.1)])
        self.assertEqual(fids, [])
        self.assertEqual(rids, [])
        self.assertEqual(pids, [])
