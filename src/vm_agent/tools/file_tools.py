"""File operations. Relative paths resolve against the default exec session cwd."""

import base64
import shutil
import stat
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from vm_agent.util import resolve_path


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def read_file(path: str, max_bytes: int = 200_000, as_base64: bool = False) -> dict:
        """Read a file. Set as_base64=true for binary files."""
        p = resolve_path(path)
        size = p.stat().st_size
        with open(p, "rb") as f:
            data = f.read(max_bytes)
        result = {"path": str(p), "size": size, "truncated": size > max_bytes}
        if as_base64:
            result["base64"] = base64.b64encode(data).decode()
        else:
            result["content"] = data.decode("utf-8", errors="replace")
        return result

    @mcp.tool()
    def write_file(
        path: str,
        content: str,
        append: bool = False,
        from_base64: bool = False,
        create_dirs: bool = True,
    ) -> dict:
        """Write (or append to) a file. Pass base64 content with from_base64=true for binary."""
        p = resolve_path(path)
        if create_dirs:
            p.parent.mkdir(parents=True, exist_ok=True)
        data = base64.b64decode(content) if from_base64 else content.encode()
        with open(p, "ab" if append else "wb") as f:
            f.write(data)
        return {"path": str(p), "bytes_written": len(data), "appended": append}

    @mcp.tool()
    def list_dir(path: str = ".") -> dict:
        """List a directory: name, type, size, mtime per entry (dirs first)."""
        p = resolve_path(path)
        entries = []
        for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
            try:
                st = child.lstat()
                kind = (
                    "symlink" if stat.S_ISLNK(st.st_mode)
                    else "dir" if child.is_dir()
                    else "file"
                )
                entries.append({
                    "name": child.name,
                    "type": kind,
                    "size": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                })
            except OSError as exc:
                entries.append({"name": child.name, "type": "error", "error": str(exc)})
        return {"path": str(p), "count": len(entries), "entries": entries}

    @mcp.tool()
    def delete_path(path: str, recursive: bool = False) -> dict:
        """Delete a file or directory. Non-empty directories need recursive=true."""
        p = resolve_path(path)
        if p.is_dir() and not p.is_symlink():
            if recursive:
                shutil.rmtree(p)
            else:
                p.rmdir()  # refuses non-empty dirs without the flag
        else:
            p.unlink()
        return {"deleted": str(p)}
