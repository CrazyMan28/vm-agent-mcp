"""Configuration for VM Agent (~/.vm-agent/config.yaml)."""

from pathlib import Path

import yaml

CONFIG_DIR = Path.home() / ".vm-agent"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

DEFAULT_CONFIG = {
    "bearer_token": "change-me",
    "mcp_host": "0.0.0.0",
    "mcp_port": 8800,
    # exec output beyond this is head+tail truncated.
    "max_output_chars": 100_000,
}


def load_config() -> dict:
    """Load config from YAML file or create it with defaults."""
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(DEFAULT_CONFIG, f)
        print(f"Created config file: {CONFIG_FILE}")
        return dict(DEFAULT_CONFIG)

    with open(CONFIG_FILE) as f:
        config = yaml.safe_load(f)
    return {**DEFAULT_CONFIG, **(config or {})}


def get_bearer_token() -> str:
    return str(load_config()["bearer_token"])


def get_server_config() -> tuple[str, int]:
    config = load_config()
    return config["mcp_host"], int(config["mcp_port"])


def get_max_output_chars() -> int:
    return int(load_config()["max_output_chars"])
