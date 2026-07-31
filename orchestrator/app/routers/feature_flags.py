"""
Feature flags API endpoint.

Public (no auth required) — serves only flags marked as public in
defaults.yaml for frontend consumption.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..permissions import get_platform_settings as get_platform_governance_settings
from ..services.feature_flags import get_feature_flags

router = APIRouter()

@router.get("/api/feature-flags")
async def get_flags() -> dict:
    """Return public feature flags for the current environment."""
    ff = get_feature_flags()
    return {"env": ff.env, "flags": ff.public_flags}


@router.get("/api/platform-settings")
async def get_platform_settings(db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    """Return the small public subset of admin-managed platform settings."""
    settings = await get_platform_governance_settings(db)
    return {"show_home_integration_cards": bool(settings.show_home_connection_cards)}
