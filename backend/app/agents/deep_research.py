async def run_deep_research(message: str, context: dict) -> dict:
    subq = [f"Background for: {message}", f"Current evidence for: {message}", f"Risks/tradeoffs for: {message}"]
    return {"agent": "deep_research", "steps": subq, "citations": []}
