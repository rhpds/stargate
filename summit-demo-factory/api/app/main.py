"""Summit Demo Factory API — FastAPI application."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.app.database import init_db, close_db
from api.app.api.runs import router as runs_router
from api.app.api.stages import router as stages_router
from api.app.api.rubrics import router as rubrics_router
from api.app.api.reports import router as reports_router
from api.app.api.proposals import router as proposals_router
from api.app.api.integration import router as integration_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:8080").split(",")

app = FastAPI(
    title="Summit Demo Factory",
    description="Control plane for provisioning, validating, and observing Summit demo environments",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
)

app.include_router(runs_router)
app.include_router(stages_router)
app.include_router(rubrics_router)
app.include_router(reports_router)
app.include_router(proposals_router)
app.include_router(integration_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "stargate"}
