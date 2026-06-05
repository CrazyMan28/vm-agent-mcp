"""Mouse + keyboard: pyautogui (X11/Windows), ydotool (Wayland).

pyautogui is imported lazily inside functions — a top-level import crashes the
whole server on headless or Wayland-only machines.
"""

import os
import subprocess
import time

from mcp.server.fastmcp import FastMCP

from vm_agent.platformcaps import input_backend

# Linux input-event codes (input-event-codes.h) for the ydotool backend.
_YDOTOOL_KEYS = {
    "esc": 1, "escape": 1,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    "minus": 12, "-": 12, "equal": 13, "=": 13,
    "backspace": 14, "tab": 15,
    "q": 16, "w": 17, "e": 18, "r": 19, "t": 20, "y": 21, "u": 22, "i": 23, "o": 24, "p": 25,
    "[": 26, "]": 27,
    "enter": 28, "return": 28,
    "ctrl": 29, "control": 29,
    "a": 30, "s": 31, "d": 32, "f": 33, "g": 34, "h": 35, "j": 36, "k": 37, "l": 38,
    ";": 39, "'": 40, "`": 41,
    "shift": 42,
    "\\": 43,
    "z": 44, "x": 45, "c": 46, "v": 47, "b": 48, "n": 49, "m": 50,
    ",": 51, ".": 52, "/": 53,
    "rightshift": 54, "alt": 56, "space": 57, "capslock": 58,
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64, "f7": 65, "f8": 66,
    "f9": 67, "f10": 68, "f11": 87, "f12": 88,
    "printscreen": 99,
    "home": 102, "up": 103, "pageup": 104, "left": 105, "right": 106,
    "end": 107, "down": 108, "pagedown": 109, "insert": 110, "delete": 111, "del": 111,
    "super": 125, "meta": 125, "win": 125, "cmd": 125,
}

_BUTTONS = {"left": 0x00, "right": 0x01, "middle": 0x02}


def _pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = False
    return pyautogui


def _ydotool(*args: str) -> None:
    env = os.environ.copy()
    if "YDOTOOL_SOCKET" not in env:
        for candidate in (f"/run/user/{os.getuid()}/.ydotool_socket", "/tmp/.ydotool_socket"):
            if os.path.exists(candidate):
                env["YDOTOOL_SOCKET"] = candidate
                break
    res = subprocess.run(["ydotool", *args], capture_output=True, text=True, timeout=15, env=env)
    if res.returncode != 0:
        raise RuntimeError(
            f"ydotool {' '.join(args)} failed: {res.stderr.strip() or res.stdout.strip()} "
            "(is ydotoold running?)"
        )


def _backend() -> str:
    backend = input_backend()
    if backend == "none":
        raise RuntimeError("No input backend on this machine (headless, or Wayland without ydotool).")
    return backend


def _pyautogui_key(key: str) -> str:
    key = key.strip().lower()
    return {"super": "win", "meta": "win", "cmd": "win", "control": "ctrl", "return": "enter"}.get(key, key)


def _ydotool_code(key: str) -> int:
    code = _YDOTOOL_KEYS.get(key.strip().lower())
    if code is None:
        raise RuntimeError(f"Unknown key for ydotool backend: {key!r}")
    return code


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def mouse_move(x: int, y: int) -> dict:
        """Move the mouse to (x, y) in native screen pixels (see screenshot metadata)."""
        if _backend() == "pyautogui":
            _pyautogui().moveTo(x, y)
        else:
            _ydotool("mousemove", "-a", "-x", str(x), "-y", str(y))
        return {"ok": True, "x": x, "y": y}

    @mcp.tool()
    def mouse_click(x: int, y: int, button: str = "left", double: bool = False) -> dict:
        """Click at (x, y) in native screen pixels. button: left|right|middle."""
        if button not in _BUTTONS:
            raise RuntimeError(f"button must be one of {sorted(_BUTTONS)}")
        if _backend() == "pyautogui":
            pag = _pyautogui()
            pag.click(x, y, clicks=2 if double else 1, button=button)
        else:
            _ydotool("mousemove", "-a", "-x", str(x), "-y", str(y))
            code = format(0xC0 | _BUTTONS[button], "#x")
            _ydotool("click", code)
            if double:
                _ydotool("click", code)
        return {"ok": True, "x": x, "y": y, "button": button, "double": double}

    @mcp.tool()
    def mouse_drag(from_x: int, from_y: int, to_x: int, to_y: int, button: str = "left") -> dict:
        """Drag from one point to another (native pixels)."""
        if button not in _BUTTONS:
            raise RuntimeError(f"button must be one of {sorted(_BUTTONS)}")
        if _backend() == "pyautogui":
            pag = _pyautogui()
            pag.moveTo(from_x, from_y)
            pag.dragTo(to_x, to_y, duration=0.5, button=button)
        else:
            _ydotool("mousemove", "-a", "-x", str(from_x), "-y", str(from_y))
            _ydotool("click", format(0x40 | _BUTTONS[button], "#x"))  # press
            time.sleep(0.1)
            _ydotool("mousemove", "-a", "-x", str(to_x), "-y", str(to_y))
            time.sleep(0.1)
            _ydotool("click", format(0x80 | _BUTTONS[button], "#x"))  # release
        return {"ok": True, "from": [from_x, from_y], "to": [to_x, to_y], "button": button}

    @mcp.tool()
    def scroll(amount: int, x: int | None = None, y: int | None = None) -> dict:
        """Scroll the mouse wheel. Positive = up, negative = down. Optionally move to (x, y) first."""
        if _backend() == "pyautogui":
            pag = _pyautogui()
            if x is not None and y is not None:
                pag.moveTo(x, y)
            pag.scroll(amount)
        else:
            if x is not None and y is not None:
                _ydotool("mousemove", "-a", "-x", str(x), "-y", str(y))
            _ydotool("mousemove", "-w", "-x", "0", "-y", str(amount))
        return {"ok": True, "amount": amount}

    @mcp.tool()
    def type_text(text: str) -> dict:
        """Type text on the keyboard (into whatever has focus)."""
        if _backend() == "pyautogui":
            _pyautogui().write(text, interval=0.01)
        else:
            _ydotool("type", "--", text)
        return {"ok": True, "chars": len(text)}

    @mcp.tool()
    def press_key(combo: str) -> dict:
        """Press a key or combo, e.g. 'enter', 'ctrl+c', 'ctrl+shift+t', 'alt+F4'."""
        keys = [k for k in combo.split("+") if k.strip()]
        if not keys:
            raise RuntimeError("Empty key combo")
        if _backend() == "pyautogui":
            mapped = [_pyautogui_key(k) for k in keys]
            pag = _pyautogui()
            if len(mapped) == 1:
                pag.press(mapped[0])
            else:
                pag.hotkey(*mapped)
        else:
            codes = [_ydotool_code(k) for k in keys]
            args = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
            _ydotool("key", *args)
        return {"ok": True, "combo": combo}
