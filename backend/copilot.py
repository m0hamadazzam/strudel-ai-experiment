from .schemas import ChatRequest, ChatResponse


def generate_code(request: ChatRequest) -> ChatResponse:
    """
    Generate Strudel code based on user message and current code.

    TODO: Implement LLM integration
    """
    # Stub implementation
    return ChatResponse(code=request.current_code, explanation="Not implemented yet")
