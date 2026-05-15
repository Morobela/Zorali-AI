async def run_file_analysis(message: str, context: dict) -> dict:
    return {"agent": "file_analysis", "steps": ["Find relevant uploaded files", "Summarize key content"], "request": message}
