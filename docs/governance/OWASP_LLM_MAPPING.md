# OWASP LLM Mapping

| OWASP LLM risk | Zorali control (wired today) |
|---|---|
| LLM01 Prompt injection | UNTRUSTED evidence blocks for file/web content in the chat prompt (`backend/app/api/chat.py`) |
| LLM02 Insecure output handling | The frontend never renders raw HTML from the model (react-markdown without `rehype-raw`, no `dangerouslySetInnerHTML`) |
| LLM06 Excessive agency | Registry role gates, `approval_required`, audit log; sandbox behind env opt-in + admin role |
| LLM10 Unbounded consumption | HTTP rate limiting and an upload size ceiling (`MAX_UPLOAD_MB`); per-task cost budgets are **not** yet enforced (`QueuedTask.max_cost_usd` is unused — capability map U7) |
