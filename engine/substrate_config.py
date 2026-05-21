"""Substrate router configuration — loads thresholds and hardware types from YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class SubstrateThresholds(BaseModel):
    gaudi_saturated: float = 90
    xeon6_underutil: float = 20
    gaudi_busy: float = 70
    memory_pressure: float = 80


class HardwareTypes(BaseModel):
    inference: str = "gaudi"
    compute: str = "xeon6"


class SubstrateConfig(BaseModel):
    version: str = "1.0"
    thresholds: SubstrateThresholds = Field(default_factory=SubstrateThresholds)
    hardware_types: HardwareTypes = Field(default_factory=HardwareTypes)


_DEFAULT_PATH = Path(__file__).parent.parent / "policies" / "substrate.yaml"
_cache: Optional[SubstrateConfig] = None


def load_substrate_config(path: Optional[Path] = None) -> SubstrateConfig:
    """Load substrate router config from YAML. Caches on first load for default path."""
    global _cache
    use_path = path or _DEFAULT_PATH
    if path is None and _cache is not None:
        return _cache
    if not use_path.exists():
        config = SubstrateConfig()
    else:
        with open(use_path) as f:
            data = yaml.safe_load(f) or {}
        config = SubstrateConfig(**data)
    if path is None:
        _cache = config
    return config
