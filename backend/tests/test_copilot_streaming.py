from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from backend.copilot import generate_code_stream
from backend.schemas import ChatRequest


def _make_streaming_llm(result_code: str, explanation: str, events: list[dict] | None = None):
    def _impl(*_args, **_kwargs):
        for event in events or []:
            yield event
        return (
            SimpleNamespace(code=result_code, explanation=explanation),
            {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        )

    return _impl


def test_generate_code_stream_emits_reasoning_and_final_response():
    request = ChatRequest(message="make a beat", current_code="", conversation_history=[])

    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False):
        with patch("backend.copilot.window_conversation_history", return_value=[]):
            with patch("backend.copilot._get_allowed_function_names", return_value={"s"}):
                with patch("backend.copilot.should_prefetch_kb", return_value=False):
                    with patch("backend.copilot.detect_sound_types", return_value=([], False)):
                        with patch("backend.copilot.should_enable_web_search", return_value=False):
                            with patch("backend.copilot.get_all_preset_names", return_value={"bd", "sd"}):
                                with patch("backend.copilot.get_function_signatures", return_value={}):
                                    with patch("backend.copilot._log_interaction"):
                                        with patch(
                                            "backend.copilot.generate_with_context_stream",
                                            _make_streaming_llm(
                                                's("bd sd")',
                                                "Built a drum loop.",
                                                events=[
                                                    {"type": "reasoning", "delta": "Planning the rhythm."},
                                                ],
                                            ),
                                        ):
                                            events = list(generate_code_stream(request))

    assert any(event["type"] == "status" for event in events)
    assert any(event["type"] == "reasoning" for event in events)
    final = next(event for event in events if event["type"] == "final")
    assert final["response"]["code"] == 's("bd sd")'
    assert final["response"]["explanation"] == "Built a drum loop."


def test_generate_code_stream_repairs_invalid_first_draft():
    request = ChatRequest(message="make a beat", current_code="", conversation_history=[])

    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False):
        with patch("backend.copilot.window_conversation_history", return_value=[]):
            with patch("backend.copilot._get_allowed_function_names", return_value={"s"}):
                with patch("backend.copilot.should_prefetch_kb", return_value=False):
                    with patch("backend.copilot.detect_sound_types", return_value=([], False)):
                        with patch("backend.copilot.should_enable_web_search", return_value=False):
                            with patch("backend.copilot.get_all_preset_names", return_value={"bd", "sd"}):
                                with patch("backend.copilot.get_function_signatures", return_value={}):
                                    with patch("backend.copilot.retrieve_context_for_functions", return_value=""):
                                        with patch("backend.copilot.retrieve_preset_context", return_value=""):
                                            with patch("backend.copilot._log_interaction"):
                                                with patch(
                                                    "backend.copilot.generate_with_context_stream",
                                                    _make_streaming_llm(
                                                        "madeUpBeat()",
                                                        "First draft.",
                                                    ),
                                                ):
                                                    with patch(
                                                        "backend.copilot.repair_with_context_stream",
                                                        _make_streaming_llm(
                                                            's("bd")',
                                                            "Fixed the invalid function.",
                                                            events=[
                                                                {"type": "reasoning", "delta": "Replacing the invalid API."},
                                                            ],
                                                        ),
                                                    ):
                                                        events = list(generate_code_stream(request))

    repair_statuses = [
        event for event in events if event["type"] == "status" and event.get("phase") == "repair"
    ]
    assert repair_statuses
    final = next(event for event in events if event["type"] == "final")
    assert final["response"]["code"] == 's("bd")'
    assert final["response"]["explanation"] == "Fixed the invalid function."
