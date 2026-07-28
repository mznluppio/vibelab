"""Unit coverage for team-controlled Marketplace and Automations access."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import permissions
from app.models_team import Team


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _Db:
    def __init__(self, team: Team | None):
        self.team = team

    async def execute(self, _statement):
        return _ScalarResult(self.team)


def _user(*, team_id, superuser: bool = False):
    return SimpleNamespace(id=uuid4(), default_team_id=team_id, is_superuser=superuser)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setting_name", "feature_name"),
    [
        ("marketplace_access_for_non_admins", "Marketplace"),
        ("automations_access_for_non_admins", "Automations"),
    ],
)
async def test_non_admin_is_denied_when_team_feature_is_disabled(
    monkeypatch, setting_name, feature_name
):
    team = Team(id=uuid4(), name="Test", slug="test")
    setattr(team, setting_name, False)
    user = _user(team_id=team.id)

    async def _membership(*_args):
        return SimpleNamespace(role="editor")

    monkeypatch.setattr(permissions, "get_team_membership", _membership)

    with pytest.raises(HTTPException) as exc:
        await permissions.require_team_feature_access(
            _Db(team), user, setting_name=setting_name, feature_name=feature_name
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_team_feature_access_allows_admins_and_opted_in_members(monkeypatch):
    team = Team(
        id=uuid4(),
        name="Test",
        slug="test",
        marketplace_access_for_non_admins=True,
        automations_access_for_non_admins=False,
    )

    async def _editor_membership(*_args):
        return SimpleNamespace(role="editor")

    monkeypatch.setattr(permissions, "get_team_membership", _editor_membership)
    await permissions.require_team_feature_access(
        _Db(team),
        _user(team_id=team.id),
        setting_name="marketplace_access_for_non_admins",
        feature_name="Marketplace",
    )

    async def _admin_membership(*_args):
        return SimpleNamespace(role="admin")

    monkeypatch.setattr(permissions, "get_team_membership", _admin_membership)
    await permissions.require_team_feature_access(
        _Db(team),
        _user(team_id=team.id),
        setting_name="automations_access_for_non_admins",
        feature_name="Automations",
    )


@pytest.mark.asyncio
async def test_technical_configuration_remains_admin_only(monkeypatch):
    team_id = uuid4()

    async def _viewer_membership(*_args):
        return SimpleNamespace(role="viewer")

    monkeypatch.setattr(permissions, "get_team_membership", _viewer_membership)
    with pytest.raises(HTTPException) as exc:
        await permissions.require_active_team_administrator(
            _Db(None), _user(team_id=team_id)
        )
    assert exc.value.status_code == 403

    async def _admin_membership(*_args):
        return SimpleNamespace(role="admin")

    monkeypatch.setattr(permissions, "get_team_membership", _admin_membership)
    await permissions.require_active_team_administrator(_Db(None), _user(team_id=team_id))


@pytest.mark.asyncio
async def test_router_guards_use_the_active_team_setting(monkeypatch):
    """The dependencies mounted on both endpoint groups reject editors."""
    from app.routers.automations import require_automations_feature_access
    from app.routers.marketplace import require_marketplace_feature_access

    team = Team(id=uuid4(), name="Test", slug="test")
    user = _user(team_id=team.id)

    async def _membership(*_args):
        return SimpleNamespace(role="viewer")

    monkeypatch.setattr(permissions, "get_team_membership", _membership)

    with pytest.raises(HTTPException) as marketplace_error:
        await require_marketplace_feature_access(_Db(team), user)
    with pytest.raises(HTTPException) as automations_error:
        await require_automations_feature_access(_Db(team), user)

    assert marketplace_error.value.status_code == 403
    assert automations_error.value.status_code == 403
