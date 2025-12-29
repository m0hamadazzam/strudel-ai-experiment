import os

from dotenv import load_dotenv
from openai import OpenAI

from .prompts import SYSTEM_PROMPT
from .schemas import ChatRequest, ChatResponse

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def generate_code(request: ChatRequest) -> ChatResponse:
    """
    Generate Strudel code based on user message and current code.
    """
    if not client.api_key:
        return ChatResponse(
            code=request.current_code,
            explanation="Error: OPENAI_API_KEY not set in environment",
        )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if request.current_code:
        user_content = (
            f"Current code:\n```javascript\n{request.current_code}\n```\n\n"
            f"User request: {request.message}\n\n"
            "Return ONLY the Strudel code, no explanations."
        )
        messages.append({"role": "user", "content": user_content})
    else:
        user_content = (
            f"{request.message}\n\nReturn ONLY the Strudel code, no explanations."
        )
        messages.append({"role": "user", "content": user_content})

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", messages=messages, temperature=0.7, max_tokens=1000
        )

        generated_code = response.choices[0].message.content.strip()

        # Remove markdown code blocks if present
        if generated_code.startswith("```"):
            lines = generated_code.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].strip() == "```":
                lines = lines[:-1]
            generated_code = "\n".join(lines).strip()

        return ChatResponse(
            code=generated_code, explanation="Code generated successfully"
        )
    except Exception as e:
        return ChatResponse(
            code=request.current_code, explanation=f"Error generating code: {str(e)}"
        )
