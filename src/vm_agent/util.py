"""Small shared helpers."""

import os
from pathlib import Path

from vm_agent import sessions


def truncate_middle(text: str, max_chars: int) -> tuple[str, bool]:
    """Keep head + tail of overlong text with a marker in the middle."""
    if len(text) <= max_chars:
        return text, False
    head = text[: max_chars // 2]
    tail = text[-(max_chars - max_chars // 2):]
    dropped = len(text) - len(head) - len(tail)
    return f"{head}\n...[truncated {dropped} chars]...\n{tail}", True


def resolve_path(path: str) -> Path:
    """Expand ~ and env vars; relative paths resolve against the default session cwd."""
    p = Path(os.path.expandvars(os.path.expanduser(path)))
    if not p.is_absolute():
        p = Path(sessions.get_session().cwd) / p
    return p
