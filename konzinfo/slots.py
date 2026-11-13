"""Modele de creneau + filtrage selon la configuration (dates, jours, heures)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time

from konzinfo.config import SlotsConfig

_TIME_RE = re.compile(r"(\d{1,2})[:.hH](\d{2})")


@dataclass(frozen=True, order=True)
class Slot:
    start: datetime
    label: str = ""

    @property
    def day(self) -> date:
        return self.start.date()

    def __str__(self) -> str:
        return f"{self.start:%a %d/%m/%Y %H:%M}"


def parse_time(label: str) -> time | None:
    """Extrait l'heure de debut d'un libelle de creneau : '08:30', '08:30 - 08:45', 'from 8:30'."""
    m = _TIME_RE.search(label or "")
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)


def slot_from_label(day: date, label: str) -> Slot | None:
    t = parse_time(label)
    if t is None:
        return None
    return Slot(start=datetime.combine(day, t), label=label.strip())


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def day_allowed(d: date, cfg: SlotsConfig, today: date | None = None) -> bool:
    today = today or date.today()
    if d < today:
        return False
    if cfg.earliest and d < cfg.earliest:
        return False
    if cfg.latest and d > cfg.latest:
        return False
    if cfg.weekdays is not None and d.weekday() not in cfg.weekdays:
        return False
    return True


def slot_allowed(slot: Slot, cfg: SlotsConfig, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if slot.start <= now:
        return False
    if not day_allowed(slot.day, cfg, today=now.date()):
        return False
    if cfg.hours:
        start, end = (_parse_hhmm(v) for v in cfg.hours)
        if not (start <= slot.start.time() <= end):
            return False
    return True


def filter_slots(slots: list[Slot], cfg: SlotsConfig, now: datetime | None = None) -> list[Slot]:
    """Creneaux conformes a la configuration, tries du plus tot au plus tard."""
    return sorted({s for s in slots if slot_allowed(s, cfg, now)})


def choose_first(slots: list[Slot], cfg: SlotsConfig, now: datetime | None = None) -> Slot | None:
    ok = filter_slots(slots, cfg, now)
    return ok[0] if ok else None


def summarize(slots: list[Slot], limit: int = 8) -> str:
    """Resume lisible pour Telegram : regroupe par jour."""
    if not slots:
        return "aucun"
    by_day: dict[date, list[Slot]] = {}
    for s in sorted(slots):
        by_day.setdefault(s.day, []).append(s)
    lines = []
    for d, items in list(by_day.items())[:limit]:
        times = ", ".join(f"{s.start:%H:%M}" for s in items[:6])
        more = f" (+{len(items) - 6})" if len(items) > 6 else ""
        lines.append(f"- {d:%a %d/%m/%Y} : {times}{more}")
    if len(by_day) > limit:
        lines.append(f"- ... et {len(by_day) - limit} autre(s) jour(s)")
    return "\n".join(lines)
