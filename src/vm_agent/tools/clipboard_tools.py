"""Clipboard: wl-clipboard (Wayland), xclip (X11), pyperclip (Windows)."""

import subprocess

from mcp.server.fastmcp import FastMCP

from vm_agent.platformcaps import clipboard_backend


def _get() -> str:
    backend = clipboard_backend()
    if backend == "wl-clipboard":
        res = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, text=True, timeout=10)
        return res.stdout if res.returncode == 0 else ""  # rc=1 when clipboard is empty
    if backend == "xclip":
        res = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, timeout=10
        )
        return res.stdout if res.returncode == 0 else ""
    if backend == "pyperclip":
        import pyperclip

        return pyperclip.paste()
    raise RuntimeError("No clipboard backend available (headless or missing wl-clipboard/xclip).")


def _set(text: str) -> None:
    backend = clipboard_backend()
    if backend == "wl-clipboard":
        subprocess.run(["wl-copy"], input=text, text=True, timeout=10, check=True)
    elif backend == "xclip":
        subprocess.run(
            ["xclip", "-selection", "clipboard"], input=text, text=True, timeout=10, check=True
        )
    elif backend == "pyperclip":
        import pyperclip

        pyperclip.copy(text)
    else:
        raise RuntimeError("No clipboard backend available (headless or missing wl-clipboard/xclip).")


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def clipboard_get() -> dict:
        """Read the machine's clipboard."""
        return {"text": _get()}

    @mcp.tool()
    def clipboard_set(text: str) -> dict:
        """Put text on the machine's clipboard."""
        _set(text)
        return {"ok": True, "chars": len(text)}
