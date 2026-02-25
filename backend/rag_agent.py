"""
RAG agent using LangGraph: the LLM decides when to query the KB and with what query;
a generate_code node then produces structured StrudelCodeOut.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Optional, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from openai import OpenAI

from .prompts import build_system_prompt
from .retrieval import extract_function_names_from_query, retrieve_relevant_context
from .schemas import StrudelCodeOut

backend_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(backend_dir, ".env"))

logger = logging.getLogger(__name__)

# Model for code generation (Responses API only, e.g. gpt-5.x)
DEFAULT_MODEL = "gpt-5.1-codex-mini"
# Model for the agent node (must support Chat Completions, e.g. gpt-4o-mini)
DEFAULT_AGENT_MODEL = "gpt-4o-mini"
# Must be large enough for full JSON: {"code": "...", "explanation": "..."} without truncation
MAX_OUTPUT_TOKENS = 8192

_openai_client: Optional[OpenAI] = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _openai_client


# --- KB tool ---

def _search_strudel_kb_impl(query: str) -> str:
    """Search the Strudel knowledge base; used by the LangChain tool."""
    extra = extract_function_names_from_query(query)
    return retrieve_relevant_context(
        query,
        k=4,
        extra_function_names=extra[:3] if extra else None,
    )


@tool
def search_strudel_knowledge_base(query: str) -> str:
    """Search the Strudel knowledge base for functions, recipes, and presets.
    Use this to find API details and example patterns when the user asks for code.
    Input: a search query string (e.g. 'stack pattern', 'drum beat', 'reverb')."""
    return _search_strudel_kb_impl(query)


# --- State: messages (with reducer) + optional parsed_output ---

class RAGAgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    parsed_output: Optional[StrudelCodeOut]


# --- Agent system message (instructs: call KB tool with search query, do not generate code here) ---

AGENT_SYSTEM_PROMPT = """You are a Strudel.cc live-coding assistant. When the user asks for code or patterns, you must first search the knowledge base for relevant functions and examples using the search_strudel_knowledge_base tool. Call the tool with a short search query (e.g. the main concept: "drum pattern", "stack", "reverb"). Do not generate code in this step; only decide the search query and call the tool once. If the request is very generic (e.g. "hello"), you may respond without calling the tool."""


# --- Nodes ---

def _get_chat_model() -> ChatOpenAI:
    """Chat model for the agent node; must support v1/chat/completions (e.g. gpt-4o-mini)."""
    return ChatOpenAI(
        model=os.getenv("OPENAI_AGENT_MODEL", DEFAULT_AGENT_MODEL),
        temperature=0,
        api_key=os.getenv("OPENAI_API_KEY"),
    )


def agent_node(state: RAGAgentState) -> dict:
    """Call the LLM to decide whether to retrieve from KB (tool call) or go straight to code gen."""
    model = _get_chat_model().bind_tools([search_strudel_knowledge_base])
    messages = state["messages"]
    full_messages = [SystemMessage(content=AGENT_SYSTEM_PROMPT)] + list(messages)
    response = model.invoke(full_messages)
    return {"messages": [response]}


def generate_code_node(state: RAGAgentState) -> dict:
    """Extract KB context from tool message (if any), build prompt, call LLM with structured output."""
    messages = state["messages"]
    kb_context = ""
    for m in reversed(messages):
        if hasattr(m, "type") and m.type == "tool":
            kb_context = getattr(m, "content", "") or ""
            if isinstance(kb_context, list):
                kb_context = str(kb_context)
            break

    user_content = ""
    for m in messages:
        if hasattr(m, "type") and m.type == "human":
            user_content = getattr(m, "content", "") or ""
            if isinstance(user_content, list):
                user_content = str(user_content)
            break

    system_prompt = build_system_prompt(kb_context=kb_context)
    client = _get_openai_client()
    try:
        resp = client.responses.parse(
            model=os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
            tools=[
                {
                    "type": "web_search",
                    "filters": {
                        "allowed_domains": [
                            "github.com",
                            "strudel.cc",
                            "strudel.learn.audio",
                            "youtube.com",
                        ]
                    },
                }
            ],
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            text_format=StrudelCodeOut,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
    except Exception as e:
        logger.warning("Structured parse failed: %s", e)
        return {"parsed_output": None}

    parsed = resp.output_parsed
    if parsed is None:
        return {"parsed_output": None}
    return {"parsed_output": parsed}


# --- Graph assembly ---

def build_rag_graph() -> StateGraph:
    workflow = StateGraph(RAGAgentState)

    workflow.add_node("agent", agent_node)
    workflow.add_node("retrieve", ToolNode([search_strudel_knowledge_base]))
    workflow.add_node("generate_code", generate_code_node)

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "retrieve", END: "generate_code"},
    )
    workflow.add_edge("retrieve", "generate_code")
    workflow.add_edge("generate_code", END)

    return workflow.compile()


# Compiled graph singleton for use from copilot
_compiled_graph = None


def get_rag_graph():
    """Return the compiled RAG agent graph (cached)."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_rag_graph()
    return _compiled_graph
