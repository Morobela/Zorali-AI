async def run_code_assistant(message: str, context: dict) -> dict:
    return {"agent": "code_assistant", "steps": ["Inspect files", "Explain issue", "Propose patch"], "request": message}
