"""
Expose VibeLab as an MCP server via Streamable HTTP transport.

Uses FastMCP from the ``mcp`` Python SDK to register the core tools and serve
them over the MCP JSON-RPC protocol. The ASGI app is mounted in main.py under
``/api/mcp/server``.

Authorization: the mount is a raw ASGI sub-application, so FastAPI's
``Depends`` chain never runs for it. ``get_mcp_asgi_app()`` therefore wraps the
transport in :func:`_authenticated_mcp_app`, which authenticates the request
with the same external API key mechanism the ``/api/v1`` routers use and
publishes the caller in a context variable. Every tool then goes through
:func:`_resolve_project`, which checks the key's scopes and resolves the target
Workspace via ``permissions.get_project_with_access`` — without that pair, the
tools would list files, read files and execute shell commands in any project.
"""

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, HTTPException
from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from ..permissions import Permission

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _McpCaller:
    """Identity behind the current MCP request.

    Plain values rather than the ``User`` row: the auth helper commits, which
    expires the ORM attributes once its session closes.
    """

    user_id: UUID
    # ``None`` means the API key declares no scope restriction.
    scopes: list[str] | None


# Caller resolved by the ASGI auth wrapper, read by ``_resolve_project``.
# A context variable is the only channel available: FastMCP tool callables take
# just their declared JSON-RPC arguments.
_mcp_caller: ContextVar[_McpCaller | None] = ContextVar("_mcp_caller", default=None)

# ---------------------------------------------------------------------------
# FastMCP server instance
# ---------------------------------------------------------------------------

mcp_app = FastMCP(
    "OpenSail",
    stateless_http=True,
    json_response=True,
    instructions=(
        "Tools for managing and building web applications via OpenSail. "
        "Use these tools to list files, read code, and run commands in project containers."
    ),
)

# Mount at root of wherever Starlette mounts us (e.g. /api/mcp/server)
mcp_app.settings.streamable_http_path = "/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_project(project_id: str, permission: Permission):
    """Resolve project_id (slug or UUID) to (project, container, orchestrator).

    Authorization happens here rather than in each tool so no tool can forget
    it. Two gates, both keyed on ``permission``: the API key must declare the
    scope, and the caller must hold it on the target Workspace.

    Returns ``(None, None, None)`` when the caller is unauthenticated, the key
    lacks the scope, the Workspace does not exist, or the caller has no access
    to it — the tools surface all of these as "not found" so neither the
    existence of someone else's Workspace nor the reason for refusal leaks.
    """
    from ..config import get_settings
    from ..database import AsyncSessionLocal
    from ..models import Container
    from ..permissions import get_project_with_access

    settings = get_settings()

    caller = _mcp_caller.get()
    if caller is None:
        return None, None, None

    if caller.scopes is not None and permission.value not in caller.scopes:
        return None, None, None

    async with AsyncSessionLocal() as db:
        try:
            project, _role = await get_project_with_access(
                db, project_id, caller.user_id, permission
            )
        except HTTPException:
            return None, None, None

        # Get first container for the project
        container_result = await db.execute(
            select(Container)
            .where(Container.project_id == project.id)
            .order_by(Container.created_at)
            .limit(1)
        )
        container = container_result.scalar_one_or_none()
        container_name = container.name if container else "frontend"

        if settings.deployment_mode == "kubernetes":
            from ..services.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

            return project, container_name, KubernetesOrchestrator()
        else:
            from ..services.orchestration.docker import DockerComposeOrchestrator

            return project, container_name, DockerComposeOrchestrator()


# ---------------------------------------------------------------------------
# MCP tool registrations
# ---------------------------------------------------------------------------


@mcp_app.tool()
async def list_project_files(project_id: str, path: str = "/") -> dict:
    """List files in an OpenSail project directory.

    Args:
        project_id: The project UUID or slug.
        path: Directory path relative to project root. Defaults to "/".

    Returns:
        A listing of files and directories at the given path.
    """
    project, container_name, orchestrator = await _resolve_project(project_id, Permission.FILE_READ)
    if not project:
        return {"error": f"Project '{project_id}' not found"}

    try:
        files = await orchestrator.list_files(project.owner_id, project.id, container_name, path)
        return {"project_id": str(project.id), "path": path, "files": files}
    except Exception as e:
        logger.error("MCP list_project_files failed: %s", e)
        return {"error": str(e), "project_id": project_id, "path": path}


@mcp_app.tool()
async def read_project_file(project_id: str, path: str) -> dict:
    """Read a file from an OpenSail project.

    Args:
        project_id: The project UUID or slug.
        path: File path relative to project root.

    Returns:
        The contents of the requested file.
    """
    project, container_name, orchestrator = await _resolve_project(project_id, Permission.FILE_READ)
    if not project:
        return {"error": f"Project '{project_id}' not found"}

    try:
        content = await orchestrator.read_file(
            project.owner_id,
            project.id,
            container_name,
            path,
            project_slug=project.slug,
        )
        if content is None:
            return {"error": f"File '{path}' not found", "project_id": str(project.id)}
        return {"project_id": str(project.id), "path": path, "content": content}
    except Exception as e:
        logger.error("MCP read_project_file failed: %s", e)
        return {"error": str(e), "project_id": project_id, "path": path}


@mcp_app.tool()
async def run_project_command(project_id: str, command: str) -> dict:
    """Execute a shell command inside an OpenSail project container.

    Args:
        project_id: The project UUID or slug.
        command: The shell command to execute.

    Returns:
        The stdout/stderr output of the command.
    """
    project, container_name, orchestrator = await _resolve_project(
        project_id, Permission.TERMINAL_ACCESS
    )
    if not project:
        return {"error": f"Project '{project_id}' not found"}

    try:
        result = await orchestrator.execute_command(
            project.owner_id,
            project.id,
            container_name,
            command,
        )
        return {"project_id": str(project.id), "command": command, "output": result}
    except Exception as e:
        logger.error("MCP run_project_command failed: %s", e)
        return {"error": str(e), "project_id": project_id, "command": command}


# ---------------------------------------------------------------------------
# FastAPI router — info endpoint + ASGI mount helper
# ---------------------------------------------------------------------------

router = APIRouter(tags=["mcp-server"])


@router.get("/api/mcp/server")
async def mcp_server_info():
    """Return metadata about the OpenSail MCP server."""
    return {
        "name": "OpenSail",
        "description": "MCP server exposing OpenSail project tools (list files, read files, run commands)",
        "transport": "streamable-http",
        "endpoint": "/api/mcp/server/mcp",
        "tools": [
            {
                "name": "list_project_files",
                "description": "List files in an OpenSail project directory",
            },
            {
                "name": "read_project_file",
                "description": "Read a file from an OpenSail project",
            },
            {
                "name": "run_project_command",
                "description": "Execute a shell command in a project container",
            },
        ],
    }


def _authenticated_mcp_app(inner):
    """Wrap the MCP transport in external-API-key authentication.

    ``app.mount()`` hands the sub-application raw ASGI scopes, so none of the
    FastAPI dependency chain (auth, CSRF) applies to it. This wrapper is the
    only place authentication can happen for the MCP transport, so it runs
    before the transport sees the request and publishes the caller in
    :data:`_mcp_caller` for :func:`_resolve_project`.

    Accepts the same ``Authorization: Bearer tsk_...`` external API key the
    ``/api/v1`` routers accept.
    """

    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            # Must reach the transport: its session manager starts here.
            await inner(scope, receive, send)
            return

        if scope["type"] != "http":
            # The transport only serves HTTP; close anything else instead of
            # forwarding an unauthenticated scope.
            await send({"type": "websocket.close", "code": 1008})
            return

        from ..auth_external import get_external_api_user
        from ..database import AsyncSessionLocal

        header = None
        for raw_name, raw_value in scope.get("headers") or []:
            if raw_name == b"authorization":
                header = raw_value.decode("latin-1")
                break

        caller = None
        if header:
            try:
                async with AsyncSessionLocal() as db:
                    user = await get_external_api_user(api_key=header, db=db)
                    # Read everything needed while the session is open: the
                    # helper commits ``last_used_at``, which expires the ORM
                    # attributes, so they cannot be touched after it closes.
                    key_record = getattr(user, "_api_key_record", None)
                    caller = _McpCaller(
                        user_id=user.id,
                        scopes=getattr(key_record, "scopes", None),
                    )
            except HTTPException:
                caller = None
            except Exception:
                # Never let an auth-path failure fall through as "authorized".
                logger.exception("MCP authentication failed unexpectedly")
                caller = None

        if caller is None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"detail":"API key required"}',
                }
            )
            return

        token = _mcp_caller.set(caller)
        try:
            await inner(scope, receive, send)
        finally:
            _mcp_caller.reset(token)

    return app


def get_mcp_asgi_app():
    """Return the authenticated Streamable HTTP ASGI app for mounting.

    Usage in main.py::

        from .routers.mcp_server import get_mcp_asgi_app, router as mcp_server_router
        app.include_router(mcp_server_router)
        app.mount("/api/mcp/server", get_mcp_asgi_app())
    """
    return _authenticated_mcp_app(mcp_app.streamable_http_app())
