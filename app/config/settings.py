import os
import json
from pathlib import Path

# Load config.json if present; allow environment variable override for USER_DATA_DIR
ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "app" / "config" / "config.json"

_config = {}
try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        _config = json.load(f)
except Exception:
    _config = {}


def get_user_data_dir() -> str:
    # Priority: env COPILOT_USER_DATA_DIR > config.json user_data_dir > Desktop fallback
    env = os.environ.get("COPILOT_USER_DATA_DIR")
    if env:
        return env
    cfg = _config.get("user_data_dir")
    if cfg:
        return cfg
    # fallback to Desktop/copilot_chrome_data
    home = Path.home()
    desktop = home / "Desktop"
    return str(desktop / "copilot_chrome_data")
