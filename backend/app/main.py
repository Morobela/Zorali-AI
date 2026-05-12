from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.project import router as project_router
from app.api.auth import router as auth_router
from app.api.tools import router as tools_router
from app.api.files import router as files_router
from app.api.mcp import router as mcp_router
from app.a2a.endpoint import router as a2a_router
from app.core.config import settings

app = FastAPI(title="Charlie AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(project_router)
app.include_router(tools_router)
app.include_router(files_router)
app.include_router(mcp_router)
app.include_router(a2a_router)

@app.get("/")
async def root():
    return {"name": settings.app_name, "status": "online", "message": "Charlie AI backend is running"}
