#!/usr/bin/env bash
# Register a vm-agent server into Claude Code, Codex, and Copilot CLI on this dev box.
# Idempotent: re-running updates the entry in place.
#
#   client-setup.sh --name vm-myhost --url http://100.x.y.z:8800/mcp --token <tok>
set -euo pipefail

NAME="" URL="" TOKEN=""
while [ $# -gt 0 ]; do
  case "$1" in
    --name)  NAME="$2"; shift 2 ;;
    --url)   URL="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done
[ -n "$NAME" ] && [ -n "$URL" ] && [ -n "$TOKEN" ] || { echo "usage: --name N --url URL --token TOK" >&2; exit 1; }

say() { printf '\033[1;36m[client-setup]\033[0m %s\n' "$*"; }
PY="$(command -v python3 || command -v python)"
ENVVAR="VM_$(echo "$NAME" | tr '[:lower:]-' '[:upper:]_')_TOKEN"

# ---- Claude Code ---------------------------------------------------------------
if command -v claude >/dev/null; then
  claude mcp remove --scope user "$NAME" >/dev/null 2>&1 || true
  if claude mcp add --transport http --scope user "$NAME" "$URL" \
       --header "Authorization: Bearer $TOKEN" >/dev/null 2>&1; then
    say "Claude Code: registered '$NAME' (user scope)."
  else
    say "Claude Code CLI add failed — patching ~/.claude.json directly."
    "$PY" - "$NAME" "$URL" "$TOKEN" <<'PYEOF'
import json, os, sys
name, url, token = sys.argv[1:4]
path = os.path.expanduser("~/.claude.json")
data = json.load(open(path)) if os.path.exists(path) else {}
data.setdefault("mcpServers", {})[name] = {
    "type": "http", "url": url, "headers": {"Authorization": f"Bearer {token}"}}
json.dump(data, open(path, "w"), indent=2)
PYEOF
    say "Claude Code: patched ~/.claude.json."
  fi
else
  say "Claude Code CLI not found — skipping."
fi

# ---- Codex ---------------------------------------------------------------------
RC="${ZDOTDIR:-$HOME}/.zshrc"; [ -f "$RC" ] || RC="$HOME/.bashrc"
LINE="export $ENVVAR='$TOKEN'"
grep -qsF "$LINE" "$RC" 2>/dev/null || echo "$LINE" >> "$RC"
export "$ENVVAR=$TOKEN"
if command -v codex >/dev/null; then
  codex mcp remove "$NAME" >/dev/null 2>&1 || true
  if codex mcp add "$NAME" --url "$URL" --bearer-token-env-var "$ENVVAR" >/dev/null 2>&1; then
    say "Codex: registered '$NAME' (token via \$$ENVVAR)."
  else
    say "Codex CLI add failed — appending to ~/.codex/config.toml."
    mkdir -p "$HOME/.codex"; TOML="$HOME/.codex/config.toml"
    if ! grep -qsF "[mcp_servers.$NAME]" "$TOML" 2>/dev/null; then
      printf '\n[mcp_servers.%s]\nurl = "%s"\nbearer_token_env_var = "%s"\n' "$NAME" "$URL" "$ENVVAR" >> "$TOML"
    fi
    say "Codex: wrote ~/.codex/config.toml."
  fi
else
  say "Codex CLI not found — skipping (env var still exported to $RC)."
fi

# ---- Copilot CLI ---------------------------------------------------------------
COP="$HOME/.copilot/mcp-config.json"
if [ -d "$HOME/.copilot" ] || command -v copilot >/dev/null; then
  mkdir -p "$HOME/.copilot"
  "$PY" - "$NAME" "$URL" "$TOKEN" "$COP" <<'PYEOF'
import json, os, sys
name, url, token, path = sys.argv[1:5]
data = json.load(open(path)) if os.path.exists(path) else {}
if os.path.exists(path):
    json.dump(data, open(path + ".bak", "w"), indent=2)
data.setdefault("mcpServers", {})[name] = {
    "type": "http", "url": url,
    "headers": {"Authorization": f"Bearer {token}"}, "tools": ["*"]}
json.dump(data, open(path, "w"), indent=2)
PYEOF
  say "Copilot CLI: registered '$NAME' in ~/.copilot/mcp-config.json."
else
  say "Copilot CLI not detected — skipping."
fi

echo
say "Done. '$NAME' is registered. Smoke test in Claude Code:"
say "   \"Using $NAME, call system_info then take a screenshot.\""
say "(Restart your shell or 'source $RC' so Codex sees \$$ENVVAR.)"
