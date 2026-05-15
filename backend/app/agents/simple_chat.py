async def run_simple_chat(message: str, context: dict) -> dict:
    return {"agent": "simple_chat", "plan": [f"Respond directly to: {message}"]}
