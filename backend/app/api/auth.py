from fastapi import APIRouter
from app.core.auth import create_access_token

router = APIRouter(prefix="/api/auth")

@router.post("/demo-login")
async def demo_login():
    return {"access_token": create_access_token("demo-owner", "owner"), "token_type": "bearer"}
