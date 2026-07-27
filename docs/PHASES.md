# Phases

1. Make Zorali talk. — shipped
2. Add safe tools. — shipped
3. Add smart memory. — shipped
4. Add J.A.R.V.I.S. runtime. — shipped
5. Make it act on its own, within bounds. — shipped (capability map U1–U9)

Phase 5 is the one that changed what Zorali *is*: work that survives a restart,
a scan that runs whether or not anyone is watching, and a notification channel
Zorali opens first. `docs/ULTRON_CAPABILITY_MAP.md` is the plan it was built
from; `docs/ARCHITECTURE.md` describes the result.

The phase after this one is deliberately **not** "let it change its own code".
Self-improvement stops at proposing; merge authority stays human by
construction, not by a flag. See `docs/SECURITY.md`.
