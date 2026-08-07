from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import config
from .api.routes import router
from .db import init_db

DASHBOARD_FILE = Path(__file__).resolve().parent / "dashboard" / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=config.API_TITLE,
    version=config.API_VERSION,
    description=(
        "API-first enterprise security guardrail auditor for Terraform. "
        "Scans IaC against a built-in guardrail rule pack, persists results, "
        "and tracks security posture over time. The dashboard at `/` is just "
        "another consumer of this API."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(DASHBOARD_FILE, media_type="text/html")
