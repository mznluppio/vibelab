"""Unit coverage for the marketplace agent mutation policy."""

from types import SimpleNamespace
from uuid import uuid4

from app.services.agent_edit_permissions import can_edit_agent, is_protected_agent


def _agent(**overrides):
    values = {
        "id": uuid4(),
        "created_by_user_id": None,
        "forked_by_user_id": None,
        "is_system": False,
        "is_builtin": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _user(user_id=None):
    return SimpleNamespace(id=user_id or uuid4(), is_superuser=False)


def test_standard_user_cannot_edit_an_official_agent() -> None:
    user = _user()
    agent = _agent(created_by_user_id=user.id)
    official_source = SimpleNamespace(trust_level="official")

    assert is_protected_agent(agent, official_source) is True
    assert can_edit_agent(agent, official_source, user) is False


def test_assist_to_build_is_read_only_for_a_standard_user() -> None:
    user = _user()
    agent = _agent(created_by_user_id=user.id, slug="assist-to-build")
    official_source = SimpleNamespace(trust_level="official")

    assert can_edit_agent(agent, official_source, user) is False


def test_creator_can_edit_a_personal_agent() -> None:
    user = _user()
    agent = _agent(created_by_user_id=user.id)
    local_source = SimpleNamespace(trust_level="local")

    assert can_edit_agent(agent, local_source, user) is True


def test_other_user_cannot_edit_a_personal_agent() -> None:
    creator = _user()
    agent = _agent(created_by_user_id=creator.id)
    local_source = SimpleNamespace(trust_level="local")

    assert can_edit_agent(agent, local_source, _user()) is False
