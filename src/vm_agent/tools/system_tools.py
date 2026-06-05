"""Processes, services, and the system_info capability report."""

import getpass
import os
import platform
import socket
import subprocess
import time
from typing import Optional

import psutil
from mcp.server.fastmcp import FastMCP

from vm_agent import __version__
from vm_agent.platformcaps import IS_WINDOWS, capabilities, display_server, has_tool

SERVICE_ACTIONS = ("status", "start", "stop", "restart", "enable", "disable")


def _run(argv: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def _tailscale_ip() -> Optional[str]:
    if not has_tool("tailscale"):
        return None
    try:
        res = _run(["tailscale", "ip", "-4"], timeout=10)
        lines = res.stdout.strip().splitlines()
        return lines[0] if res.returncode == 0 and lines else None
    except Exception:
        return None


def _os_pretty() -> str:
    if not IS_WINDOWS:
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
    return platform.platform()


def _gpus() -> list[str]:
    try:
        if IS_WINDOWS:
            res = _run([
                "powershell", "-NoProfile", "-Command",
                "(Get-CimInstance win32_VideoController).Name",
            ])
            return [l.strip() for l in res.stdout.splitlines() if l.strip()]
        if has_tool("lspci"):
            res = _run(["lspci"])
            return [
                line.split(": ", 1)[-1]
                for line in res.stdout.splitlines()
                if any(k in line.lower() for k in ("vga", "3d controller", "display controller"))
            ]
    except Exception:
        pass
    return []


def _resolution() -> Optional[dict]:
    # Wayland has no cheap query path; screenshot metadata reports native size there.
    if display_server() not in ("windows", "x11"):
        return None
    try:
        import mss

        with mss.mss() as sct:
            mons = sct.monitors
            return {
                "combined": {"width": mons[0]["width"], "height": mons[0]["height"]},
                "monitors": [{"width": m["width"], "height": m["height"]} for m in mons[1:]],
            }
    except Exception:
        return None


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def system_info() -> dict:
        """Who/what this machine is, plus which vm-agent tools work here.

        Check capabilities first: screenshot/input/clipboard backends are 'none'
        on headless machines.
        """
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\" if IS_WINDOWS else "/")
        return {
            "hostname": socket.gethostname(),
            "os": _os_pretty(),
            "user": getpass.getuser(),
            "is_admin": (
                bool(__import__("ctypes").windll.shell32.IsUserAnAdmin()) if IS_WINDOWS
                else os.geteuid() == 0 or _run(["sudo", "-n", "true"], timeout=5).returncode == 0
            ),
            "tailscale_ip": _tailscale_ip(),
            "cpu_count": psutil.cpu_count(),
            "cpu_percent": psutil.cpu_percent(interval=0.2),
            "memory_gb": {"total": round(mem.total / 1e9, 1), "available": round(mem.available / 1e9, 1)},
            "disk_gb": {"total": round(disk.total / 1e9, 1), "free": round(disk.free / 1e9, 1)},
            "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 1),
            "resolution": _resolution(),
            "gpus": _gpus(),
            "capabilities": capabilities(),
            "vm_agent_version": __version__,
        }

    @mcp.tool()
    def list_processes(filter: Optional[str] = None, limit: int = 100) -> dict:
        """List running processes (sorted by memory), optionally filtered by substring."""
        rows = []
        needle = (filter or "").lower()
        for proc in psutil.process_iter(["pid", "name", "username", "memory_info", "cmdline"]):
            try:
                info = proc.info
                cmdline = " ".join(info.get("cmdline") or [])
                if needle and needle not in (info["name"] or "").lower() and needle not in cmdline.lower():
                    continue
                rows.append({
                    "pid": info["pid"],
                    "name": info["name"],
                    "user": info["username"],
                    "rss_mb": round((info["memory_info"].rss if info["memory_info"] else 0) / 1e6, 1),
                    "cmdline": cmdline[:200],
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        rows.sort(key=lambda r: r["rss_mb"], reverse=True)
        return {"count": len(rows), "processes": rows[:limit]}

    @mcp.tool()
    def kill_process(pid: int, force: bool = False) -> dict:
        """Terminate a process by PID (force=true sends SIGKILL / hard-kills)."""
        proc = psutil.Process(pid)
        name = proc.name()
        if force:
            proc.kill()
        else:
            proc.terminate()
        return {"ok": True, "pid": pid, "name": name, "forced": force}

    @mcp.tool()
    def service_control(name: str, action: str = "status") -> dict:
        """Control a system service: status|start|stop|restart|enable|disable.

        Linux uses systemctl (sudo when needed); Windows uses PowerShell *-Service.
        """
        if action not in SERVICE_ACTIONS:
            raise RuntimeError(f"action must be one of {SERVICE_ACTIONS}")

        if IS_WINDOWS:
            safe = name.replace("'", "''")
            script = {
                "status": f"Get-Service -Name '{safe}' | Format-List Name,Status,StartType",
                "start": f"Start-Service -Name '{safe}'; Get-Service -Name '{safe}' | Format-List Name,Status",
                "stop": f"Stop-Service -Name '{safe}' -Force; Get-Service -Name '{safe}' | Format-List Name,Status",
                "restart": f"Restart-Service -Name '{safe}' -Force; Get-Service -Name '{safe}' | Format-List Name,Status",
                "enable": f"Set-Service -Name '{safe}' -StartupType Automatic",
                "disable": f"Set-Service -Name '{safe}' -StartupType Disabled",
            }[action]
            res = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=60)
        else:
            argv = ["systemctl", action, name]
            if action == "status":
                argv.append("--no-pager")
            elif os.geteuid() != 0:
                argv = ["sudo", "-n", *argv]
            res = _run(argv, timeout=60)

        return {
            "exit_code": res.returncode,
            "output": (res.stdout + res.stderr).strip()[:10_000],
        }
