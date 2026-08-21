"""Admin router package — sub-routers composed into a single router."""

from fastapi import APIRouter

from api.routers.admin.scheduler import router as scheduler_router
from api.routers.admin.llm import router as llm_router
from api.routers.admin.approval import router as approval_router
from api.routers.admin.proof import router as proof_router
from api.routers.admin.monitoring import router as monitoring_router
from api.routers.admin.analytics import router as analytics_router

router = APIRouter()
router.include_router(scheduler_router)
router.include_router(llm_router)
router.include_router(approval_router)
router.include_router(proof_router)
router.include_router(monitoring_router)
router.include_router(analytics_router)

# Re-exports for external consumers
from api.routers.admin.approval import VALID_EXECUTION_MODES  # noqa: E402, F401
