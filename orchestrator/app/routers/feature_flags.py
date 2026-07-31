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
async def get_platform_settings(db: AsyncSession = Depends(get_db)) -> dict[str, bool | str]:
    """Return the public authentication and onboarding presentation settings."""
    settings = await get_platform_governance_settings(db)
    return {
        "show_home_integration_cards": bool(settings.show_home_connection_cards),
        "show_google_sign_in": bool(settings.show_google_sign_in),
        "show_github_sign_in": bool(settings.show_github_sign_in),
        "auth_background_mode": settings.auth_background_mode,
        "auth_background_value": settings.auth_background_value,
    }
