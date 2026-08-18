"""Cross-runtime preview readiness contract."""

import pytest

from app.services.orchestration.base import is_preview_http_response_ready


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (None, False),
        (200, True),
        (302, True),
        (401, True),
        (403, True),
        (404, False),
        (502, False),
    ],
)
def test_preview_ready_requires_a_routable_application_response(
    status_code: int | None, expected: bool
) -> None:
    """Do not advertise a preview while its route is still missing or broken."""
    assert is_preview_http_response_ready(status_code) is expected
