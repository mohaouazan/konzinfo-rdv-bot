"""Persistance legere : dernier etat observe + marqueur de reservation effectuee."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    def __init__(self, state_dir: Path):
        self.dir = Path(state_dir)
        self.file = self.dir / "last_status.json"
        self.booked_marker = self.dir / "BOOKED"

    def load(self) -> dict[str, Any]:
        if not self.file.exists():
            return {}
        try:
            return json.loads(self.file.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self, data: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    def is_booked(self) -> bool:
        return self.booked_marker.exists()

    def mark_booked(self, info: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        payload = {"booked_at": now_iso(), **info}
        self.booked_marker.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                                      encoding="utf-8")

    def booked_info(self) -> dict[str, Any]:
        if not self.is_booked():
            return {}
        try:
            return json.loads(self.booked_marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
