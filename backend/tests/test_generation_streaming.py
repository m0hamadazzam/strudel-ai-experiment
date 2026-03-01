from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from backend.generation import generate_with_context_stream


class _FailingStream:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, exc_tb):
        return False

    def __iter__(self):
        raise RuntimeError("stream failed")

    def get_final_response(self):
        raise RuntimeError("stream failed")


class _FakeResponses:
    def __init__(self, parsed_response):
        self._parsed_response = parsed_response

    def stream(self, **_kwargs):
        return _FailingStream()

    def parse(self, **_kwargs):
        return self._parsed_response


class _FakeClient:
    def __init__(self, parsed_response):
        self.responses = _FakeResponses(parsed_response)


def _drain_generator(gen):
    events = []
    while True:
        try:
            events.append(next(gen))
        except StopIteration as stop:
            return events, stop.value


def test_generate_with_context_stream_recovers_with_non_stream_parse():
    parsed_response = SimpleNamespace(
        output_parsed=SimpleNamespace(code='s("bd")', explanation="Recovered result."),
        usage=SimpleNamespace(input_tokens=10, output_tokens=20, total_tokens=30),
        status="completed",
    )

    with patch("backend.generation.build_prompt_messages", return_value=[]):
        with patch("backend.generation._get_openai_client", return_value=_FakeClient(parsed_response)):
            gen = generate_with_context_stream(
                user_content="make a beat",
                kb_context="",
                conversation_history=[],
                enable_web_search=False,
            )
            events, result = _drain_generator(gen)

    assert any(event["type"] == "status" and event["phase"] == "recovery" for event in events)
    parsed, usage = result
    assert parsed.code == 's("bd")'
    assert parsed.explanation == "Recovered result."
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 20
