"""Tests for automatic names assigned to agent-created Base workspaces."""

import pytest

from app.services.agent_required_base_workspace import suggest_workspace_name_from_request


@pytest.mark.parametrize(
    ("request", "expected"),
    [
        (
            "Je veux créer un outil interne pour suivre les interventions terrain.",
            "Suivi des interventions terrain",
        ),
        (
            "Peux-tu construire une application de gestion des congés ?",
            "Gestion des congés",
        ),
        (
            "Créer un tableau de bord pour planifier les équipes.",
            "Planning des équipes",
        ),
    ],
)
def test_suggest_workspace_name_from_business_request(request, expected):
    assert suggest_workspace_name_from_request(request) == expected


def test_suggest_workspace_name_skips_structured_brief_headings():
    request = """AS-IS

TO-BE
Créer un outil pour suivre les interventions."""

    assert suggest_workspace_name_from_request(request) == "Suivi des interventions"


def test_suggest_workspace_name_returns_none_without_a_request():
    assert suggest_workspace_name_from_request("   ") is None


def test_suggest_workspace_name_uses_pasted_text_when_message_is_empty():
    attachments = [{"type": "pasted_text", "content": "Créer un outil pour gérer les congés."}]

    assert suggest_workspace_name_from_request("", attachments) == "Gestion des congés"
