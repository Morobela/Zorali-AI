"""
Pre-built sequential chains for Zorali's reasoning pipelines.
Pattern: LangChain chain architecture for sequential reasoning.
Each chain is a Runnable built by composing smaller Runnables with |.
"""
from __future__ import annotations
from typing import Any
from app.chains.base import Runnable, RunnableLambda, RunnableConfig


async def _rag_retrieve(inputs: dict) -> dict:
    from app.memory.retrieval import hybrid_retriever
    project_id = inputs.get("project_id", "default")
    message = inputs.get("message", "")
    # Chain inputs must state who the chain runs for (user id or SYSTEM).
    hits = await hybrid_retriever.retrieve(
        message, top_k=3, project_id=project_id, owner_id=inputs["owner_id"]
    ) or []
    return {**inputs, "retrieved_chunks": hits}


async def _build_context(inputs: dict) -> dict:
    chunks = inputs.get("retrieved_chunks", [])
    rag_block = "\n\n".join(
        [f"[{c['filename']}#{c['chunk_id']}] {c['text']}" for c in chunks]
    )
    return {**inputs, "rag_context": rag_block}


async def _route_agent(inputs: dict) -> dict:
    from app.agents.orchestrator import route_agent
    plan = await route_agent(
        inputs.get("mode", "chat"),
        inputs.get("message", ""),
        {"project_id": inputs.get("project_id", "default"),
         "attachments": inputs.get("attachments", []),
         "owner_id": inputs["owner_id"],
         "role": inputs.get("role", "user")},
    )
    return {**inputs, "agent_plan": plan}


async def _assemble_prompt(inputs: dict) -> dict:
    system = inputs.get("system_prompt", "You are Zorali, a local-first assistant.")
    plan = inputs.get("agent_plan", "")
    rag = inputs.get("rag_context", "")
    history = inputs.get("history", [])
    messages = [{"role": "system", "content": system}]
    if plan:
        messages.append({"role": "system", "content": f"Agent plan: {plan}"})
    if rag:
        messages.append({"role": "system", "content": f"Project context:\n{rag}"})
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    return {**inputs, "prompt_messages": messages}


# Pre-built chain: RAG → context build → agent route → prompt assembly
rag_chain: Runnable = (
    RunnableLambda(_rag_retrieve)
    | RunnableLambda(_build_context)
    | RunnableLambda(_route_agent)
    | RunnableLambda(_assemble_prompt)
)
