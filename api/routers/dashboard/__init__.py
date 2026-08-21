"""Dashboard router package — sub-routers composed into a single router."""

from fastapi import APIRouter

from api.routers.dashboard.deployments import router as deployments_router
from api.routers.dashboard.views import router as views_router
from api.routers.dashboard.ops import router as ops_router
from api.routers.dashboard.infra import router as infra_router
from api.routers.dashboard.classification import router as classification_router
from api.routers.dashboard.llm import router as llm_router
from api.routers.dashboard.remediation import router as remediation_router

router = APIRouter()
router.include_router(deployments_router)
router.include_router(views_router)
router.include_router(ops_router)
router.include_router(infra_router)
router.include_router(classification_router)
router.include_router(llm_router)
router.include_router(remediation_router)

# Re-exports for external consumers
from api.routers.dashboard.deployments import (  # noqa: E402, F401
    dashboard_summit,
    _get_capacity_evidence_for_summary,
)
from api.routers.dashboard.ops import (  # noqa: E402, F401
    dashboard_executive_summary,
)
from api.routers.dashboard.remediation import (  # noqa: E402, F401
    _redact_sensitive,
    _save_investigation,
    _is_ecosystem_ns,
    dashboard_remediation,
)
from api.routers.dashboard.classification import (  # noqa: E402, F401
    propose_classification,
)
