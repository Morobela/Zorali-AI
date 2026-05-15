from pathlib import Path


async def run_code_assistant(message: str, context: dict) -> dict:
    project_root = Path("/workspace/Charlie-AI")
    files = []
    for p in project_root.rglob("*"):
        if p.is_file() and p.suffix in {".py", ".js", ".jsx", ".ts", ".tsx", ".md"}:
            files.append(str(p.relative_to(project_root)))
        if len(files) >= 20:
            break
    patch_template = (
        "Suggested patch plan:\n"
        "1) Identify target files from file list\n"
        "2) Edit minimal scope\n"
        "3) Add/adjust tests\n"
    )
    return {"agent": "code_assistant", "request": message, "candidate_files": files, "patch_template": patch_template}
