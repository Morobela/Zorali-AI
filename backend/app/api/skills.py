"""Skills management API routes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.skills.registry import skill_registry
from app.skills.loader import discover_and_load
from app.core.rbac import user_or_above, owner_only

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillInvokeRequest(BaseModel):
    inputs: dict


@router.get("")
async def list_skills(_=user_or_above):
    return {"skills": skill_registry.list_skills()}


@router.get("/capabilities")
async def get_capabilities(_=user_or_above):
    return {"capabilities": list(skill_registry.compute_capability_union())}


@router.post("/{skill_name}/invoke")
async def invoke_skill(skill_name: str, body: SkillInvokeRequest, _=user_or_above):
    try:
        skill = skill_registry.get(skill_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill {skill_name!r} not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        result = await skill.ainvoke(body.inputs)
        return {"skill": skill_name, "result": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Skill execution failed: {exc}")


@router.post("/reload")
async def reload_skills(_=owner_only):
    """Re-scan the skills/installed directory and load new skills."""
    loaded = discover_and_load()
    return {"loaded": loaded, "total": len(skill_registry.list_skills())}
