from backend.generation import _prompt_cache_key


def test_prompt_cache_key_is_within_api_limit():
    key = _prompt_cache_key("generate_with_context_stream:recovery")
    assert len(key) <= 64


def test_prompt_cache_key_changes_by_kind():
    assert _prompt_cache_key("generate") != _prompt_cache_key("repair")
