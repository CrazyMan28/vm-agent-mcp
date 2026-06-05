"""OS + display capability detection — single source of truth for every tool."""

import os
import platform
import shutil
from functools import lru_cache

IS_WINDOWS = platform.system() == "Windows"
OS_NAME = "windows" if IS_WINDOWS else "linux"


@lru_cache(maxsize=None)
def has_tool(name: str) -> bool:
    return shutil.which(name) is not None


@lru_cache(maxsize=1)
def display_server() -> str:
    """One of: windows | x11 | wayland | headless."""
    if IS_WINDOWS:
        return "windows"
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "headless"


def screenshot_backend() -> str:
    ds = display_server()
    if ds in ("windows", "x11"):
        return "mss"
    if ds == "wayland":
        for tool in ("grim", "spectacle", "gnome-screenshot"):
            if has_tool(tool):
                return tool
    return "none"


def input_backend() -> str:
    ds = display_server()
    if ds in ("windows", "x11"):
        return "pyautogui"
    if ds == "wayland" and has_tool("ydotool"):
        return "ydotool"
    return "none"


def clipboard_backend() -> str:
    ds = display_server()
    if ds == "windows":
        return "pyperclip"
    if ds == "wayland" and has_tool("wl-paste"):
        return "wl-clipboard"
    if ds == "x11" and has_tool("xclip"):
        return "xclip"
    return "none"


def capabilities() -> dict:
    """What works on this machine — exposed via system_info so agents know up front."""
    ds = display_server()
    return {
        "os": OS_NAME,
        "shell": "powershell" if IS_WINDOWS else "bash",
        "display_server": ds,
        "has_display": ds != "headless",
        "screenshot_backend": screenshot_backend(),
        "input_backend": input_backend(),
        "clipboard_backend": clipboard_backend(),
    }
