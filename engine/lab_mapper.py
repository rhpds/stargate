"""Lab mapper — builds canonical mapping table resolving lab identity across all data sources.

Called from MV refresh loop. Populates lab_mappings table with:
- ci_name (Labagator catalog item name)
- ci_base (catalog type: zt-ansiblebu, openshift-cnv, etc.)
- namespace_pattern (how sandbox namespaces are named)
- pool_pattern (which Poolboy pools serve this lab type)
- agnosticv_path (directory in AgnosticV repo)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("stargate.lab_mapper")

CLOUD_TO_CATALOG = {
    "CNV": "openshift-cnv",
    "AWS": "clusterplatform",
}

SLUG_SUFFIX_TO_CATALOG = {
    "-cnv": "openshift-cnv",
    "-aws": "clusterplatform",
    "-tenant": None,
}


def refresh_lab_mappings(db: Session) -> Dict:
    """Build canonical lab mapping from live Labagator + Babylon data."""
    from db.models import LabMapping

    try:
        from api.routers._shared import _fetch_labagator_labs, _load_latest_babylon
    except ImportError:
        return {"updated": 0, "error": "imports failed"}

    labs = []
    try:
        labs = _fetch_labagator_labs()
    except Exception:
        pass

    if not labs:
        return {"updated": 0, "reason": "no labagator data"}

    babylon = {}
    try:
        babylon = _load_latest_babylon()
    except Exception:
        pass

    summit_mapping = babylon.get("summit_mapping", {})
    updated = 0

    for lab in labs:
        code = lab.get("lab_code", "")
        if not code:
            continue

        ci = lab.get("ci_name", "")
        cloud = lab.get("cloud", "")

        event = ci.split(".")[0] if "." in ci else ""
        slug = ci.split(".", 1)[1] if "." in ci else ""

        ci_base = _resolve_catalog_base(slug, cloud, summit_mapping.get(code, []))

        ns_pattern = f"sandbox-*-{ci_base}" if ci_base else ""
        pool_pat = f"{ci_base}.*" if ci_base else ""
        agv_path = f"{event}/{slug}" if event and slug else ""

        clusters = list(set(
            i.get("cluster", "") for i in summit_mapping.get(code, []) if i.get("cluster")
        ))

        mapping = db.query(LabMapping).filter_by(lab_code=code).first()
        if not mapping:
            mapping = LabMapping(lab_code=code)
            db.add(mapping)

        mapping.ci_name = ci
        mapping.ci_base = ci_base
        mapping.ci_slug = slug
        mapping.namespace_pattern = ns_pattern
        mapping.pool_pattern = pool_pat
        mapping.agnosticv_path = agv_path
        mapping.cloud = cloud
        mapping.clusters = clusters
        mapping.updated_at = datetime.now(timezone.utc)
        updated += 1

    try:
        db.commit()
    except Exception as e:
        logger.warning(f"Lab mapping commit failed: {e}")
        db.rollback()
        return {"updated": 0, "error": str(e)}

    logger.info(f"Lab mappings refreshed: {updated} labs")
    return {"updated": updated}


def _resolve_catalog_base(slug: str, cloud: str, instances: List[Dict]) -> str:
    """Determine the catalog base (e.g., zt-ansiblebu) from available data."""
    for inst in instances:
        governor = inst.get("governor", "")
        if governor:
            return governor.split(".")[0] if "." in governor else governor

    for suffix, catalog in SLUG_SUFFIX_TO_CATALOG.items():
        if slug.endswith(suffix):
            if catalog:
                return catalog
            return slug

    if cloud in CLOUD_TO_CATALOG:
        return CLOUD_TO_CATALOG[cloud]

    if cloud == "Tenant Namespace" and slug:
        return slug

    return ""
