"""Tool registration: each module contributes a register(mcp)."""

from mcp.server.fastmcp import FastMCP

from vm_agent.tools import (
    clipboard_tools,
    exec_tools,
    file_tools,
    input_tools,
    screen_tools,
    system_tools,
)


def register_all(mcp: FastMCP) -> None:
    for module in (
        exec_tools,
        file_tools,
        screen_tools,
        input_tools,
        clipboard_tools,
        system_tools,
    ):
        module.register(mcp)
