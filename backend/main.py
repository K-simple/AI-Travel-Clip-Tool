import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent
load_dotenv(BACKEND_ROOT / ".env")
os.chdir(BACKEND_ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from models.database import init_db
from utils.security import ApiKeyMiddleware

for sub in ("templates", "assets", "thumbnails", "exports", "temp"):
    os.makedirs(BACKEND_ROOT / "storage" / sub, exist_ok=True)

init_db()

app = FastAPI(title="AI Travel Cut Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ApiKeyMiddleware)

app.mount("/storage", StaticFiles(directory=str(BACKEND_ROOT / "storage")), name="storage")

from routers import (  # noqa: E402
    assets,
    auth,
    cloud,
    effects,
    export,
    marketplace,
    match,
    project,
    publish,
    subtitle,
    template,
    template_library,
    v11,
)

app.include_router(template.router, prefix="/api/template", tags=["template"])
app.include_router(template_library.router, prefix="/api/template-library", tags=["template-library"])
app.include_router(assets.router, prefix="/api/assets", tags=["assets"])
app.include_router(match.router, prefix="/api/match", tags=["match"])
app.include_router(subtitle.router, prefix="/api/subtitle", tags=["subtitle"])
app.include_router(export.router, prefix="/api/export", tags=["export"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(project.router, prefix="/api/projects", tags=["projects"])
app.include_router(v11.router, prefix="/api/v11", tags=["v11"])
app.include_router(effects.router, prefix="/api/effects", tags=["effects"])
app.include_router(cloud.router, prefix="/api/cloud", tags=["cloud"])
app.include_router(marketplace.router, prefix="/api/marketplace", tags=["marketplace"])
app.include_router(publish.router, prefix="/api/publish", tags=["publish"])


@app.get("/")
def root():
    return {"message": "AI Travel Cut backend is running"}
