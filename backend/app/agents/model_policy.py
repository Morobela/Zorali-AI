"""Model selection per step kind (capability map U7, optional half).

A plan is not homogeneous work. Deciding which of three categories a sentence
falls into does not need the model that writes the final report, and paying
frontier prices for it is how a budget disappears without buying anything.
The planner labels each step with a *kind*; this module turns that label into
a model, from one configuration string:

    STEP_MODEL_POLICY="classification=llama3.2:1b,extraction=llama3.2:1b,synthesis=gpt-4o"

Precedence is deliberate and explicit, strongest first:

1. a model passed into the run (an operator or caller overriding everything),
2. the model the goal was started with — a user who picked a model in the UI
   meant it, and a policy must not silently override that choice,
3. the policy entry for the step's kind,
4. nothing, which leaves the provider router's own default in place.

Unset policy means step 3 never fires, so behaviour is exactly as before.
"""
from __future__ import annotations

from app.core.config import settings

# The vocabulary the planner may use. Anything else a model invents is mapped
# to GENERAL rather than trusted, so an unknown label can never route work to
# an unintended model.
CLASSIFICATION = "classification"
EXTRACTION = "extraction"
RESEARCH = "research"
SYNTHESIS = "synthesis"
CODE = "code"
GENERAL = "general"

STEP_KINDS = (CLASSIFICATION, EXTRACTION, RESEARCH, SYNTHESIS, CODE, GENERAL)

# Common near-misses, so a slightly-off label still routes sensibly instead of
# falling back to the default model.
_ALIASES = {
    "classify": CLASSIFICATION,
    "categorization": CLASSIFICATION,
    "categorisation": CLASSIFICATION,
    "extract": EXTRACTION,
    "parsing": EXTRACTION,
    "lookup": RESEARCH,
    "search": RESEARCH,
    "browse": RESEARCH,
    "summarize": SYNTHESIS,
    "summarise": SYNTHESIS,
    "summary": SYNTHESIS,
    "writing": SYNTHESIS,
    "write": SYNTHESIS,
    "report": SYNTHESIS,
    "coding": CODE,
    "implementation": CODE,
}


def normalize_kind(raw: object) -> str:
    """Map whatever the planner said onto the known vocabulary."""
    text = str(raw or "").strip().lower()
    if text in STEP_KINDS:
        return text
    return _ALIASES.get(text, GENERAL)


def parse_policy(raw: str | None = None) -> dict[str, str]:
    """``"classification=a,synthesis=b"`` → ``{"classification": "a", ...}``.

    Malformed entries are skipped rather than raising: a typo in one entry
    must not take the goal engine down, and the unmatched kinds simply fall
    through to the default model.
    """
    source = settings.step_model_policy if raw is None else raw
    policy: dict[str, str] = {}
    for chunk in (source or "").split(","):
        if "=" not in chunk:
            continue
        raw_kind, _, model = chunk.partition("=")
        model = model.strip()
        # An empty kind ("=model") is a typo, not an instruction. Normalising
        # it would quietly turn a mistake into the default for every
        # unlabelled step, which is exactly the wrong way to fail.
        if not raw_kind.strip() or not model:
            continue
        policy[normalize_kind(raw_kind)] = model
    return policy


def model_for_step(
    kind: object,
    *,
    explicit_model: str | None = None,
    goal_model: str | None = None,
    policy: dict[str, str] | None = None,
) -> str | None:
    """The model a step should run on, by the precedence documented above."""
    if explicit_model:
        return explicit_model
    if goal_model:
        return goal_model
    policy = parse_policy() if policy is None else policy
    return policy.get(normalize_kind(kind)) or None


def describe_policy() -> dict:
    """Current policy, for the API and for explaining a goal's spend."""
    policy = parse_policy()
    return {"enabled": bool(policy), "by_kind": policy, "kinds": list(STEP_KINDS)}
