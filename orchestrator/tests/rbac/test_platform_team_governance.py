"""Unit coverage for enterprise Team governance policy resolution."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import permissions


def _user(*, superuser: bool = False, override: bool | None = None):
    return SimpleNamespace(
        id=uuid4(),
        is_superuser=superuser,
        can_create_teams_override=override,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user", "platform_allowed", "expected"),
    [
        (_user(superuser=True), False, True),
        (_user(override=True), False, True),
        (_user(override=False), True, False),
        (_user(), True, True),
        (_user(), False, False),
    ],
)
async def test_effective_team_creation_capability(monkeypatch, user, platform_allowed, expected):
    async def _settings(_db):
        return SimpleNamespace(allow_user_team_creation=platform_allowed)

    monkeypatch.setattr(permissions, "get_platform_settings", _settings)
    assert await permissions.can_create_team(object(), user) is expected


def test_platform_settings_is_singleton_model():
    from app.models_team import PlatformSettings

    assert PlatformSettings.__tablename__ == "platform_settings"
    assert any(constraint.name == "ck_platform_settings_singleton" for constraint in PlatformSettings.__table__.constraints)


def test_project_default_visibility_is_private():
    from app.models import Project

    assert Project.__table__.c.visibility.default.arg == "private"
    assert Project.__table__.c.visibility.server_default.arg == "private"
