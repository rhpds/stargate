"""Summit Demo Factory API — FastAPI application."""

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


app = FastAPI(
    title="Summit Demo Factory",
    description="Control plane for provisioning, validating, and observing Summit demo environments",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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
