"""Screenshots: mss (X11/Windows), grim/spectacle/gnome-screenshot (Wayland)."""

import io
import json
import os
import subprocess
import tempfile

from mcp.server.fastmcp import FastMCP, Image

from vm_agent.platformcaps import display_server, has_tool

# Wide enough for the model to read UI text; clicks always use native coords.
MAX_WIDTH_DEFAULT = 1568


def _grab_mss(monitor: int) -> tuple[bytes, int, int]:
    import mss
    import mss.tools

    with mss.mss() as sct:
        # monitors[0] is the union of all monitors; [1..] are individual ones.
        index = monitor if 0 <= monitor < len(sct.monitors) else 1
        shot = sct.grab(sct.monitors[index])
        return mss.tools.to_png(shot.rgb, shot.size), shot.size[0], shot.size[1]


def _grab_wayland() -> bytes:
    errors = []
    if has_tool("grim"):
        res = subprocess.run(["grim", "-t", "png", "-"], capture_output=True, timeout=20)
        if res.returncode == 0 and res.stdout:
            return res.stdout
        errors.append(f"grim: {res.stderr.decode(errors='replace').strip()}")

    # KDE / GNOME compositors that lack the wlr-screencopy protocol.
    for builder in (
        (lambda f: ["spectacle", "-b", "-n", "-o", f]) if has_tool("spectacle") else None,
        (lambda f: ["gnome-screenshot", "-f", f]) if has_tool("gnome-screenshot") else None,
    ):
        if builder is None:
            continue
        fd, fname = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            res = subprocess.run(builder(fname), capture_output=True, timeout=30)
            with open(fname, "rb") as f:
                data = f.read()
            if data:
                return data
            errors.append(f"{builder(fname)[0]}: {res.stderr.decode(errors='replace').strip()}")
        finally:
            if os.path.exists(fname):
                os.unlink(fname)
    raise RuntimeError(
        "No working Wayland screenshot tool (tried grim/spectacle/gnome-screenshot). "
        + "; ".join(errors)
    )


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def screenshot(monitor: int = 1, max_width: int = MAX_WIDTH_DEFAULT) -> list:
        """Capture the desktop. Returns resolution metadata plus a PNG image.

        Mouse coordinates are in NATIVE pixels even when the returned image is
        downscaled — scale clicks by native_width/scaled_width. monitor=0 means
        all monitors combined (ignored on Wayland, which captures everything).
        """
        from PIL import Image as PILImage

        ds = display_server()
        if ds == "headless":
            raise RuntimeError("This machine has no display (headless) — screenshot unavailable.")

        if ds == "wayland":
            png = _grab_wayland()
            img = PILImage.open(io.BytesIO(png))
            native_w, native_h = img.size
        else:
            png, native_w, native_h = _grab_mss(monitor)
            img = PILImage.open(io.BytesIO(png))

        scaled_w, scaled_h = native_w, native_h
        if max_width and native_w > max_width:
            img.thumbnail((max_width, 1_000_000))
            scaled_w, scaled_h = img.size
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png = buf.getvalue()

        meta = {
            "native_width": native_w,
            "native_height": native_h,
            "scaled_width": scaled_w,
            "scaled_height": scaled_h,
            "display_server": ds,
            "monitor": monitor,
        }
        return [json.dumps(meta), Image(data=png, format="png")]
