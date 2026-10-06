"""Load config.json and expose project paths."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ARCHIVE_DIR = ROOT / "archive"
SEEDS_DIR = ROOT / "seeds"
STATE_DIR = DATA_DIR / "_state"


def load_config() -> dict:
    with open(ROOT / "config.json", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.pop("_comment", None)
    return cfg


def current_interval_days(cfg: dict, today: dt.date | None = None) -> int:
    """Weekly until `switch_to_monthly_on`, monthly afterwards."""
    today = today or dt.date.today()
    switch = cfg.get("switch_to_monthly_on")
    if switch and today >= dt.date.fromisoformat(switch):
        return int(cfg.get("monthly_interval_days", 30))
    return int(cfg.get("sync_interval_days", 7))
