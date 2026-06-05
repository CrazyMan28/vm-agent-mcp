"""VM Agent MCP server: FastAPI + FastMCP streamable HTTP with Bearer auth."""

import hmac
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from vm_agent import __version__
from vm_agent.config import get_bearer_token, get_server_config
from vm_agent.tools import register_all

# Every request is Bearer-token protected and the server lives on a private
# tailnet, so DNS-rebinding protection (which would reject the Tailscale IP /
# MagicDNS Host headers) is disabled instead of enumerating every name the VM
# might be reached by. A rebinding attempt without the token still gets a 401.
mcp = FastMCP(
    "VM Agent",
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
register_all(mcp)
mcp_app = mcp.streamable_http_app()


def verify_token(authorization: Optional[str]) -> bool:
    """Verify the Authorization: Bearer header."""
    if not authorization:
        return False
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    return hmac.compare_digest(parts[1], get_bearer_token())


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="VM Agent MCP", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Verify bearer token on all requests except /health."""
    if request.url.path == "/health" or request.method == "OPTIONS":
        return await call_next(request)

    if not verify_token(request.headers.get("Authorization")):
        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized", "message": "Invalid or missing bearer token"},
        )

    return await call_next(request)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "vm-agent-mcp", "version": __version__}


# Mount the MCP streamable transport at /mcp.
app.mount("/", mcp_app)


def main() -> None:
    host, port = get_server_config()
    print(f"VM Agent MCP v{__version__} starting on {host}:{port}/mcp")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
