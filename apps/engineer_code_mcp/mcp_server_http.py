#!/usr/bin/env python3

import contextlib
import logging
import os
from typing import AsyncIterator

import uvicorn
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from server import EngineerCodeService, setup_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

HTTP_BIND = os.getenv("ENGINEER_CODE_MCP_BIND", "0.0.0.0")
HTTP_PORT = int(os.getenv("ENGINEER_CODE_MCP_PORT", "9010"))
HTTP_PATH = os.getenv("ENGINEER_CODE_MCP_PATH", "/mcp")


def _normalize_path(path: str) -> str:
    candidate = path.strip() or "/mcp"
    if not candidate.startswith("/"):
        candidate = f"/{candidate}"
    return candidate.rstrip("/") or "/"


def _health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "healthy"})


def create_app() -> Starlette:
    service = EngineerCodeService.from_env()
    server = Server("engineer-code-mcp")
    server.instructions = (
        "Safe code-repository assistant tools with strict allowlist and path-boundary enforcement"
    )
    setup_server(server, service)

    session_manager = StreamableHTTPSessionManager(app=server)
    streamable_http_app = StreamableHTTPASGIApp(session_manager)
    mcp_path = _normalize_path(HTTP_PATH)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        logger.info("Loaded %d allowlisted project(s)", len(service.projects))
        async with session_manager.run():
            yield

    return Starlette(
        routes=[
            Route(mcp_path, endpoint=streamable_http_app, methods=["GET", "POST", "DELETE", "OPTIONS"]),
            Route("/health", endpoint=_health, methods=["GET"]),
        ],
        lifespan=lifespan,
    )


def main() -> None:
    app = create_app()
    logger.info("Starting engineer-code-mcp on %s:%s", HTTP_BIND, HTTP_PORT)
    uvicorn.run(app, host=HTTP_BIND, port=HTTP_PORT, log_level="info")


if __name__ == "__main__":
    main()
