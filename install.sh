#!/usr/bin/env bash
# VM Agent MCP — Linux installer.
#   curl -fsSL https://raw.githubusercontent.com/CrazyMan28/vm-agent-mcp/main/install.sh | bash
#
# Installs uv + desktop deps + Tailscale (if missing), writes ~/.vm-agent/config.yaml,
# for desktop users, optionally grants passwordless sudo; root installs directly
# (including headless servers) without requiring sudo. Runs a systemd service
# and prints the client registration command.
#
# Env knobs (all optional):
#   VM_AGENT_TOKEN=...     use this bearer token instead of generating one
#   TS_AUTHKEY=...         bring Tailscale up unattended with this auth key
#   VM_AGENT_PORT=8800     listen port (default 8800)
#   VM_AGENT_REF=main      git ref / branch to install
#   NO_SUDOERS=1           skip the passwordless-sudo drop-in
set -euo pipefail

REPO="https://github.com/CrazyMan28/vm-agent-mcp"
REF="${VM_AGENT_REF:-main}"
PORT="${VM_AGENT_PORT:-8800}"
APP_DIR="$HOME/.vm-agent/app"
CFG_DIR="$HOME/.vm-agent"
CFG="$CFG_DIR/config.yaml"

say()  { printf '\033[1;36m[vm-agent]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[vm-agent]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[vm-agent]\033[0m %s\n' "$*" >&2; exit 1; }

TARGET_USER="$(id -un)"
USER_UID="$(id -u)"
# Privileged operations run directly as root, or via sudo for desktop users.
if [ "$USER_UID" -eq 0 ]; then
  SUDO=()
  say "Root install: the agent will run with full root privileges."
else
  command -v sudo >/dev/null || die "sudo is required for non-root installs."
  SUDO=(sudo)
fi

# ---- 1. package manager + deps -------------------------------------------------
if   command -v dnf >/dev/null; then PM="dnf"; INSTALL=(dnf install -y)
elif command -v apt-get >/dev/null; then PM="apt"; INSTALL=(apt-get install -y); "${SUDO[@]}" apt-get update -y
elif command -v pacman >/dev/null; then PM="pacman"; INSTALL=(pacman -S --noconfirm)
else die "Unsupported distro (need dnf, apt, or pacman)."; fi
say "Package manager: $PM"

say "Installing system dependencies…"
"${SUDO[@]}" "${INSTALL[@]}" git curl openssl pciutils || die "Could not install required packages."
# grim/ydotool/slurp = Wayland desktop; xclip = X11 clipboard.
# A headless root-hosted server does not need desktop dependencies, some of
# which may be unavailable in minimal Debian/Proxmox repositories.
if [ "$USER_UID" -eq 0 ] && [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  say "Headless root install: skipping optional desktop input/screenshot packages."
else
  "${SUDO[@]}" "${INSTALL[@]}" wl-clipboard xclip grim slurp ydotool || warn "Some optional desktop packages are unavailable."
fi

# ---- 2. uv ---------------------------------------------------------------------
if ! command -v uv >/dev/null && [ ! -x "$HOME/.local/bin/uv" ]; then
  say "Installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
UV="$HOME/.local/bin/uv"; [ -x "$UV" ] || UV="$(command -v uv)"
[ -x "$UV" ] || die "uv install failed."

# ---- 3. fetch / update app -----------------------------------------------------
if [ -d "$APP_DIR/.git" ]; then
  say "Updating existing checkout…"
  git -C "$APP_DIR" fetch --depth 1 origin "$REF" && git -C "$APP_DIR" reset --hard FETCH_HEAD
else
  say "Cloning $REPO…"
  rm -rf "$APP_DIR"; mkdir -p "$(dirname "$APP_DIR")"
  git clone --depth 1 --branch "$REF" "$REPO" "$APP_DIR"
fi
say "Resolving Python environment (uv sync)…"
( cd "$APP_DIR" && env -u PYTHONPATH "$UV" sync )

# ---- 4. Tailscale --------------------------------------------------------------
if ! command -v tailscale >/dev/null; then
  say "Installing Tailscale…"
  curl -fsSL https://tailscale.com/install.sh | "${SUDO[@]}" sh
fi
"${SUDO[@]}" systemctl enable --now tailscaled 2>/dev/null || true
if ! tailscale ip -4 >/dev/null 2>&1; then
  if [ -n "${TS_AUTHKEY:-}" ]; then
    say "Bringing Tailscale up with auth key…"; "${SUDO[@]}" tailscale up --authkey "$TS_AUTHKEY"
  else
    say "Bringing Tailscale up — open the URL below to authenticate:"
    "${SUDO[@]}" tailscale up &
    for _ in $(seq 1 150); do tailscale ip -4 >/dev/null 2>&1 && break; sleep 2; done
  fi
fi
TS_IP="$(tailscale ip -4 2>/dev/null | head -1 || true)"
[ -n "$TS_IP" ] || warn "Could not detect Tailscale IP — finish 'tailscale up' and rerun the installer."
# Root-running remote shell access must not listen on every LAN interface.
# Bind root installs only to Tailscale; if disconnected, stay on localhost.
BIND_HOST="0.0.0.0"
if [ "$USER_UID" -eq 0 ]; then
  BIND_HOST="${TS_IP:-127.0.0.1}"
  [ -n "$TS_IP" ] || warn "Root service will only listen locally until Tailscale is connected and the installer is rerun."
fi

# ---- 5. token + config ---------------------------------------------------------
TOKEN="${VM_AGENT_TOKEN:-}"
if [ -z "$TOKEN" ] && [ -f "$CFG" ]; then TOKEN="$(awk '/bearer_token:/{print $2}' "$CFG")"; fi
if [ -z "$TOKEN" ]; then
  if [ -t 0 ]; then read -r -p "Bearer token (blank = generate a secure one): " TOKEN; fi
  [ -z "$TOKEN" ] && TOKEN="$(openssl rand -hex 32)"
fi
mkdir -p "$CFG_DIR"
cat > "$CFG" <<EOF
bearer_token: $TOKEN
mcp_host: $BIND_HOST
mcp_port: $PORT
max_output_chars: 100000
EOF
chmod 600 "$CFG"
say "Wrote $CFG"

# ---- 6. passwordless sudo ------------------------------------------------------
if [ "$USER_UID" -eq 0 ]; then
  say "Root already has elevated privileges; no sudoers entry needed."
elif [ "${NO_SUDOERS:-0}" != "1" ]; then
  say "Granting $TARGET_USER passwordless sudo (so the agent's exec can use sudo)…"
  TMP="$(mktemp)"; echo "$TARGET_USER ALL=(ALL) NOPASSWD:ALL" > "$TMP"
  if "${SUDO[@]}" visudo -cf "$TMP" >/dev/null 2>&1; then
    "${SUDO[@]}" install -m 0440 "$TMP" /etc/sudoers.d/vm-agent
  else warn "sudoers validation failed — skipping (sudo will still prompt)."; fi
  rm -f "$TMP"
fi

# ---- 7. ydotoold (Wayland input) ----------------------------------------------
if [ "$USER_UID" -ne 0 ] && [ -n "${WAYLAND_DISPLAY:-}" ] && command -v ydotoold >/dev/null; then
  mkdir -p "$HOME/.config/systemd/user"
  cat > "$HOME/.config/systemd/user/ydotoold.service" <<EOF
[Unit]
Description=ydotool daemon (vm-agent input)
[Service]
ExecStart=$(command -v ydotoold) --socket-path=%t/.ydotool_socket --socket-own=$USER_UID:$USER_UID
Restart=always
[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload 2>/dev/null || true
  systemctl --user enable --now ydotoold 2>/dev/null || warn "couldn't start ydotoold (input may not work)."
fi

# ---- 8. systemd service (sees the desktop) ------------------------------------
say "Installing systemd service…"
UNIT=/etc/systemd/system/vm-agent.service
# An SSH root session on a headless host should not advertise a fake :0 display.
SERVICE_DISPLAY="${DISPLAY:-:0}"
if [ "$USER_UID" -eq 0 ] && [ -z "${DISPLAY:-}" ]; then SERVICE_DISPLAY=""; fi
"${SUDO[@]}" tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=VM Agent MCP
After=network-online.target graphical.target
Wants=network-online.target

[Service]
Type=simple
User=$TARGET_USER
Environment=DISPLAY=$SERVICE_DISPLAY
Environment=XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}
Environment=WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-}
Environment=XDG_RUNTIME_DIR=/run/user/$USER_UID
Environment=YDOTOOL_SOCKET=/run/user/$USER_UID/.ydotool_socket
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
WorkingDirectory=$APP_DIR
ExecStart=$UV run vm-agent-mcp
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
"${SUDO[@]}" systemctl daemon-reload
"${SUDO[@]}" systemctl enable vm-agent.service
# enable --now alone does not restart an already running service after an
# upgrade, which could leave it using a stale bind address/configuration.
"${SUDO[@]}" systemctl restart vm-agent.service

# ---- 9. firewall (best effort) -------------------------------------------------
if [ "$USER_UID" -eq 0 ]; then
  say "Root mode: not opening a public firewall port; use the Tailscale interface."
elif command -v firewall-cmd >/dev/null; then
  "${SUDO[@]}" firewall-cmd --add-port="${PORT}/tcp" --permanent >/dev/null 2>&1 && "${SUDO[@]}" firewall-cmd --reload >/dev/null 2>&1 || true
elif command -v ufw >/dev/null; then
  "${SUDO[@]}" ufw allow "${PORT}/tcp" >/dev/null 2>&1 || true
fi

# ---- 10. verify + print client one-liner --------------------------------------
sleep 3
if curl -fsS -H "Authorization: Bearer $TOKEN" "http://${BIND_HOST/0.0.0.0/127.0.0.1}:${PORT}/health" >/dev/null 2>&1; then
  say "Server is up and healthy."
else
  warn "Health check failed — see: journalctl -u vm-agent -e"
fi

NAME="vm-$(hostname -s 2>/dev/null || hostname)"
echo
say "=========================================================================="
say " VM Agent is installed. Run THIS on your dev box to connect to this VM:"
echo
echo "  curl -fsSL ${REPO}/raw/${REF}/client-setup.sh | bash -s -- \\"
echo "    --name ${NAME} --url http://${TS_IP:-<this-vm-tailscale-ip>}:${PORT}/mcp --token ${TOKEN}"
echo
say "=========================================================================="
