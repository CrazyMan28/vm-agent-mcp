"""exec + background jobs: the 'be on the machine' shell."""

import os
import shlex
import signal
import subprocess
import time
from typing import Optional

from mcp.server.fastmcp import FastMCP

from vm_agent import sessions
from vm_agent.config import get_max_output_chars
from vm_agent.platformcaps import IS_WINDOWS
from vm_agent.util import truncate_middle

# Marks the rc + final cwd the wrapper appends so cd persists across calls.
SENTINEL = "__VM_AGENT_DONE__"


def _shell_argv(command: str, cwd: str, shell: Optional[str], with_sentinel: bool = True) -> list[str]:
    """Wrap command so it runs in the session cwd and reports rc + final cwd."""
    if IS_WINDOWS:
        cwd_ps = cwd.replace("'", "''")
        wrapped = f"Set-Location -LiteralPath '{cwd_ps}' -ErrorAction SilentlyContinue\n{command}"
        if with_sentinel:
            wrapped += (
                "\n$ec = if ($null -ne $LASTEXITCODE) { $LASTEXITCODE } elseif ($?) { 0 } else { 1 }"
                f"\nWrite-Output (\"`n{SENTINEL}\" + $ec + \"`t\" + (Get-Location).Path)"
            )
        return [shell or "powershell", "-NoProfile", "-NonInteractive", "-Command", wrapped]

    wrapped = f"cd {shlex.quote(cwd)} 2>/dev/null || cd ~\n{command}"
    if with_sentinel:
        wrapped += f"\n__rc=$?; printf '\\n{SENTINEL}%s\\t%s\\n' \"$__rc\" \"$PWD\""
    return [shell or "bash", "-c", wrapped]


def _parse_sentinel(stdout: str) -> tuple[str, Optional[int], Optional[str]]:
    """Split off the sentinel line; return (clean_stdout, exit_code, new_cwd)."""
    idx = stdout.rfind(SENTINEL)
    if idx == -1:
        return stdout, None, None
    tail = stdout[idx + len(SENTINEL):]
    line = tail.splitlines()[0] if tail else ""
    rc_str, _, new_cwd = line.partition("\t")
    try:
        rc = int(rc_str.strip())
    except ValueError:
        rc = None
    # Drop the newline the wrapper injected before the sentinel.
    clean = stdout[:idx]
    if clean.endswith("\n"):
        clean = clean[:-1]
    return clean, rc, new_cwd.strip() or None


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _popen(argv: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        start_new_session=not IS_WINDOWS,  # process group so timeouts kill the whole tree
    )


def register(mcp: FastMCP) -> None:
    @mcp.tool(name="exec")
    def exec_command(
        command: str,
        session: str = "default",
        timeout_seconds: int = 120,
        background: bool = False,
        shell: Optional[str] = None,
    ) -> dict:
        """Run a shell command on this machine (bash on Linux, PowerShell on Windows).

        The working directory persists across calls in the same session, so `cd`
        works like a real terminal. On Linux sudo needs no password; on Windows
        the process is already elevated. Use background=true for long-running
        commands (returns a job_id to poll with job_output).
        """
        sess = sessions.get_session(session)

        if background:
            proc = _popen(_shell_argv(command, sess.cwd, shell, with_sentinel=False))
            job = sessions.register_job(command, proc)
            return {"job_id": job.id, "status": "running", "cwd": sess.cwd}

        start = time.monotonic()
        proc = _popen(_shell_argv(command, sess.cwd, shell))
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            stdout, stderr = proc.communicate()
        duration_ms = int((time.monotonic() - start) * 1000)

        stdout, rc, new_cwd = _parse_sentinel(stdout or "")
        if new_cwd and os.path.isdir(new_cwd):
            sess.cwd = new_cwd

        max_chars = get_max_output_chars()
        stdout, trunc_out = truncate_middle(stdout, max_chars)
        stderr, trunc_err = truncate_middle(stderr or "", max_chars // 4)
        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": rc if rc is not None else proc.returncode,
            "cwd": sess.cwd,
            "duration_ms": duration_ms,
            "timed_out": timed_out,
            "truncated": trunc_out or trunc_err,
        }

    @mcp.tool()
    def job_output(job_id: str, tail_chars: int = 20_000) -> dict:
        """Get the output and status of a background job started with exec(background=true)."""
        job = sessions.get_job(job_id)
        if job is None:
            return {"error": f"Unknown job_id: {job_id}", "known_jobs": [j.id for j in sessions.list_jobs()]}
        with job.lock:
            out, err = job.stdout, job.stderr
        return {
            "job_id": job.id,
            "command": job.command,
            "status": job.status(),
            "stdout": out[-tail_chars:],
            "stderr": err[-tail_chars:],
        }

    @mcp.tool()
    def job_kill(job_id: str) -> dict:
        """Kill a background job (and its whole process tree)."""
        job = sessions.get_job(job_id)
        if job is None:
            return {"error": f"Unknown job_id: {job_id}"}
        _kill_tree(job.proc)
        job.proc.wait(timeout=10)
        return {"job_id": job.id, "status": job.status()}

    @mcp.tool()
    def job_list() -> dict:
        """List all background jobs from this server run."""
        return {
            "jobs": [
                {"job_id": j.id, "command": j.command, "status": j.status()}
                for j in sessions.list_jobs()
            ]
        }
