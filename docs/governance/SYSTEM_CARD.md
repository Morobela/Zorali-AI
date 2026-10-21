# Zorali System Card

Zorali is intended for software development assistance, project diagnostics,
research, and safe automation under human oversight. It is not intended for
unsupervised medical, legal, financial, or destructive operations.

## What runs without a request

Zorali is no longer purely request→response. With the shipped `.env.example`,
these run on their own — an operator should know about them before deploying:

| Behaviour | Trigger | What it can do | What it cannot do |
|---|---|---|---|
| Reality scan | every 60s | Probe services, read git state and log tails; write `reality_events`; post notifications | Change anything it observes |
| Durable goals | a user starts one; resumed on boot | Run planned steps through the normal tool loop, spending against a cap | Exceed `GOAL_MAX_COST_USD`, or resume itself once paused |
| Nightly self-check | 03:00 UTC | Run the test suite and ruff, audit the documentation against the code, open a GitHub issue, notify | Change code, open a pull request, or merge — that code does not exist |
| Nightly backup | 02:00 UTC | `pg_dump` to local disk with rotation; notify on failure | Serve a dump over HTTP |
| GitHub event inbox | an inbound webhook | Record an event, open a diagnosis goal, notify | Write to any repository; run at all without a configured HMAC secret |
| User routines | a schedule its owner set | Run that owner's prompt through the normal tool loop and notify them | Run more often than `ROUTINE_MIN_INTERVAL_SECONDS`, exceed its per-run ceiling, use a tool its owner could not, or keep running after it starts failing |
| Recovery action | a service seen down | Restart one allowlisted compose service | Restart `postgres` or `backend`; act at all without a docker socket the stock stack does not mount |

Sandboxed code execution is off in code **and** in the shipped template. It runs
arbitrary Python in a `python -I` subprocess — not a container — so it belongs
only on a trusted single-admin deployment.

## Human authority

Merge authority over Zorali's own source is human by construction. The
self-check proposes; a person disposes. This is not a configuration option that
could be flipped — the code to push a branch or open a pull request is not in
the repository, and a test asserts the only write call targets the issues
endpoint.

Details: `docs/SECURITY.md`, `docs/governance/AI_RISK_REGISTER.md`.
