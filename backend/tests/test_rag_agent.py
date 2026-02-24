"""Tests for RAG agent (LangGraph KB tool and graph)."""

import unittest
from unittest.mock import patch

from backend.rag_agent import (
    build_rag_graph,
    get_rag_graph,
    search_strudel_knowledge_base,
    _search_strudel_kb_impl,
)


class TestSearchStrudelKB(unittest.TestCase):
    def test_tool_returns_string(self):
        with patch("backend.rag_agent.retrieve_relevant_context", return_value="Function: s\nDescription: pattern."):
            with patch("backend.rag_agent.extract_function_names_from_query", return_value=[]):
                result = search_strudel_knowledge_base.invoke({"query": "drum pattern"})
        self.assertIsInstance(result, str)
        self.assertIn("Function: s", result)

    def test_impl_calls_retrieve_with_extra_function_names(self):
        with patch("backend.rag_agent.retrieve_relevant_context", return_value="") as mock_retrieve:
            with patch("backend.rag_agent.extract_function_names_from_query", return_value=["stack", "s"]):
                _search_strudel_kb_impl("stack drums")
        mock_retrieve.assert_called_once()
        call_kw = mock_retrieve.call_args[1]
        self.assertEqual(call_kw.get("extra_function_names"), ["stack", "s"])


class TestRAGGraph(unittest.TestCase):
    def test_build_rag_graph_compiles(self):
        graph = build_rag_graph()
        self.assertIsNotNone(graph)

    def test_get_rag_graph_caches(self):
        g1 = get_rag_graph()
        g2 = get_rag_graph()
        self.assertIs(g1, g2)
