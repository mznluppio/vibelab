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
        "source_type": "open",
        "is_forkable": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _user(user_id=None, *, is_superuser=False):
    return SimpleNamespace(id=user_id or uuid4(), is_superuser=is_superuser)


def test_standard_user_can_edit_an_official_agent_by_creating_a_fork() -> None:
    user = _user()
    agent = _agent(created_by_user_id=user.id)
    official_source = SimpleNamespace(trust_level="official")

    assert is_protected_agent(agent, official_source) is True
    assert can_edit_agent(agent, official_source, user) is True


def test_standard_user_can_edit_assist_to_build_by_creating_a_fork() -> None:
    user = _user()
    agent = _agent(created_by_user_id=user.id, slug="assist-to-build")
    official_source = SimpleNamespace(trust_level="official")

    assert can_edit_agent(agent, official_source, user) is True


def test_superuser_can_edit_an_official_agent_from_the_library() -> None:
    user = _user(is_superuser=True)
    agent = _agent(created_by_user_id=user.id)
    official_source = SimpleNamespace(trust_level="official")

    assert can_edit_agent(agent, official_source, user) is True


def test_superuser_can_fork_another_users_personal_open_source_agent() -> None:
    creator = _user()
    agent = _agent(created_by_user_id=creator.id)
    local_source = SimpleNamespace(trust_level="local")

    assert can_edit_agent(agent, local_source, _user(is_superuser=True)) is True


def test_standard_user_cannot_edit_a_non_forkable_catalog_agent() -> None:
    user = _user()
    agent = _agent(is_forkable=False)
    local_source = SimpleNamespace(trust_level="local")

    assert can_edit_agent(agent, local_source, user) is False


def test_creator_can_edit_a_personal_agent() -> None:
    user = _user()
    agent = _agent(created_by_user_id=user.id)
    local_source = SimpleNamespace(trust_level="local")

    assert can_edit_agent(agent, local_source, user) is True


def test_other_user_can_edit_a_forkable_personal_agent_by_creating_a_copy() -> None:
    creator = _user()
    agent = _agent(created_by_user_id=creator.id)
    local_source = SimpleNamespace(trust_level="local")

    assert can_edit_agent(agent, local_source, _user()) is True
