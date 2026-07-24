# AI Risk Register

| Risk | Control (wired today) |
|---|---|
| Prompt injection | File and web content enter prompts as UNTRUSTED evidence blocks with explicit do-not-follow framing (`backend/app/api/chat.py`) |
| Excessive agency | Tool registry role gates + `approval_required` + audit log on every execution (`backend/app/tools/registry.py`); code sandbox double-gated (env opt-in + admin role) |
| Credential leakage | JWTs only in Authorization headers; WebSockets use single-use Redis tickets; every repository access is owner-scoped |
| Hallucination | Answers grounded in retrieval carry citations (`[filename#chunk]` for files, `[W#]` for web sources); no automated verification engine yet |
