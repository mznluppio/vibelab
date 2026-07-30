"""
Feature flags API endpoint.

Public (no auth required) — serves only flags marked as public in
defaults.yaml for frontend consumption.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import PlatformSetting
from ..services.feature_flags import get_feature_flags

router = APIRouter()

HOME_INTEGRATION_CARDS_KEY = "home.integration_cards"


@router.get("/api/feature-flags")
async def get_flags() -> dict:
    """Return public feature flags for the current environment."""
    ff = get_feature_flags()
    return {"env": ff.env, "flags": ff.public_flags}


@router.get("/api/platform-settings")
async def get_platform_settings(db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    """Return the small public subset of admin-managed platform settings."""
    setting = await db.get(PlatformSetting, HOME_INTEGRATION_CARDS_KEY)
    return {"show_home_integration_cards": bool(setting and setting.value is True)}
