# VM Agent MCP

Install one MCP server on a VM and your AI coding agents (Claude Code, Codex,
GitHub Copilot CLI) can **act like they're on that machine** — run shell
commands with sudo/admin, read/write files, see the desktop, drive the mouse and
keyboard, manage processes and services — all over your private Tailscale network.

One command installs everything (Python via `uv`, desktop deps, Tailscale if
missing), asks for a bearer token, starts an auto-starting service, and prints a
second one-liner you run on your dev box to wire the VM into all three clients.

---

## Install on a VM

**Linux** (Fedora / Debian / Ubuntu / Arch):

```bash
curl -fsSL https://raw.githubusercontent.com/CrazyMan28/vm-agent-mcp/main/install.sh | bash
```

**Root / headless Linux hosts (including Proxmox):** the same command works
from a root SSH shell. No `sudo` binary or desktop session is required. It
installs a system-level `vm-agent` service running as root, with configuration
at `/root/.vm-agent/config.yaml`, and skips optional desktop packages. On
headless servers, shell/files/services work but screenshot and keyboard/mouse
tools are unavailable.

For root installs, the MCP listener binds to the Tailscale IPv4 address rather
than all network interfaces. If Tailscale isn't connected, it binds to
`127.0.0.1` instead. Complete `tailscale up` and rerun the installer to
expose the service on your tailnet. Check with
`systemctl status vm-agent` or `journalctl -u vm-agent -e`.

**Windows** (PowerShell — it self-elevates to Administrator):

```powershell
irm https://raw.githubusercontent.com/CrazyMan28/vm-agent-mcp/main/install.ps1 | iex
```

The installer prints something like:

```
curl -fsSL https://github.com/CrazyMan28/vm-agent-mcp/raw/main/client-setup.sh | bash -s -- \
  --name vm-buildbox --url http://100.92.1.7:8800/mcp --token 7f3c…
```

Run that on your **dev box** to register the VM in Claude Code, Codex, and
Copilot CLI. Then, in Claude Code:

> "Using vm-buildbox, call `system_info`, then take a screenshot."

### Unattended install

Set env vars before running to skip the prompts:

```bash
VM_AGENT_TOKEN=mytoken TS_AUTHKEY=tskey-auth-… \
  bash <(curl -fsSL https://raw.githubusercontent.com/CrazyMan28/vm-agent-mcp/main/install.sh)
```

---

## Tools

| Tool | What it does |
|---|---|
| `exec` | Run bash/PowerShell. Working dir persists across calls (`cd` works). sudo is passwordless (Linux) / elevated (Windows). `background=true` → job id. |
| `job_output` / `job_kill` / `job_list` | Poll, kill, or list background jobs. |
| `read_file` / `write_file` / `list_dir` / `delete_path` | File ops (binary via base64; write auto-creates dirs). |
| `screenshot` | Capture the desktop (multi-monitor). Returns native + scaled resolution; click coords are native pixels. |
| `mouse_move` / `mouse_click` / `mouse_drag` / `scroll` | Drive the pointer at screenshot coordinates. |
| `type_text` / `press_key` | Keyboard input, including combos like `ctrl+shift+t`. |
| `clipboard_get` / `clipboard_set` | Read/write the system clipboard. |
| `list_processes` / `kill_process` | Inspect and kill processes. |
| `service_control` | systemd / Windows services: status/start/stop/restart/enable/disable. |
| `system_info` | OS, hostname, Tailscale IP, CPU/RAM/disk/GPU, display server, **and a capability report** so the agent knows which tools work here (e.g. headless = no screenshot/input). |

---

## How it works

- **Transport:** HTTP streamable MCP at `/mcp`, `Authorization: Bearer <token>` on
  every request. `/health` is the only unauthenticated route. Reach it over
  Tailscale (default port **8800**).
- **Linux (regular user):** a systemd **system** service runs as your desktop
  user with `DISPLAY`/`XAUTHORITY`/`WAYLAND_DISPLAY` baked in, so screenshots
  and input hit your real session. A `/etc/sudoers.d/vm-agent` drop-in gives
  passwordless sudo unless `NO_SUDOERS=1`.
- **Linux (root):** the system service runs as root without `sudo` or a sudoers
  drop-in. Headless root installs don't inject a fake X11 display, and the
  listener binds to Tailscale (or localhost until Tailscale is connected).
- **Windows:** a Scheduled Task at logon, **Interactive + highest privileges**, so
  it has admin rights and can see the real desktop (not Session 0).
- **Desktop backends** are auto-detected: `mss` (X11/Windows) or `grim` (Wayland)
  for screenshots; `pyautogui` (X11/Windows) or `ydotool` (Wayland) for input;
  `wl-clipboard`/`xclip`/`pyperclip` for the clipboard. Headless VMs simply report
  those tools as unavailable instead of failing to start.

## Configuration

`~/.vm-agent/config.yaml` (`%USERPROFILE%\.vm-agent\config.yaml` on Windows):

```yaml
bearer_token: <secret>
mcp_host: 0.0.0.0
mcp_port: 8800
max_output_chars: 100000
```

Linux: `sudo systemctl restart vm-agent` after editing · logs:
`sudo journalctl -u vm-agent -e`.
Windows: restart the `vm-agent-mcp` task in Task Scheduler.

## ⚠️ Security

This grants full remote control of the machine to anyone holding the bearer token
— including passwordless sudo / local admin. Only install on machines you own,
keep the token secret, and rely on Tailscale (not a public IP) for reachability.
The passwordless-sudo drop-in can be skipped for non-root Linux installs with
`NO_SUDOERS=1`. Root installs already have unrestricted local privileges: a
stolen bearer token gives **full root access**. Avoid forwarding port 8800 to
the public internet; keep Tailscale access tightly controlled.

## Local development

The default Python on the dev box exports a `PYTHONPATH` that breaks plain venvs,
so run the server isolated:

```bash
env -u PYTHONPATH uv run vm-agent-mcp
env -u PYTHONPATH uv run python scripts/selftest.py "$(awk '/bearer_token/{print $2}' ~/.vm-agent/config.yaml)"
```
