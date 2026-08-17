"""Post-write integrity checks shared by project file mutation tools."""

from __future__ import annotations

import hashlib
from typing import Any


def content_integrity(content: str) -> dict[str, Any]:
    """Return a small, serialisable identity for source that was written."""
    encoded = content.encode("utf-8")
    return {
        "size_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "line_count": len(content.split("\n")),
    }


async def verify_file_content(
    orchestrator: Any,
    *,
    user_id: Any,
    project_id: str | None,
    container_name: str | None,
    file_path: str,
    expected_content: str,
    project_slug: str | None,
    subdir: str | None,
    volume_id: str | None = None,
    cache_node: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Read back a file and verify the exact bytes acknowledged by a write."""
    expected = content_integrity(expected_content)
    actual = await orchestrator.read_file(
        user_id=user_id,
        project_id=project_id,
        container_name=container_name,
        file_path=file_path,
        project_slug=project_slug,
        subdir=subdir,
        volume_id=volume_id,
        cache_node=cache_node,
    )
    if actual is None:
        return False, {**expected, "verified": False, "actual_sha256": None}
    actual_hash = content_integrity(actual)["sha256"]
    return actual == expected_content, {
        **expected,
        "verified": actual == expected_content,
        "actual_sha256": actual_hash,
    }
