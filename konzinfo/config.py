"""Chargement et validation de la configuration (config.yaml + .env).

Les donnees personnelles ne vivent que dans config.yaml / .env (gitignores).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

DEFAULT_SITE_URL = "https://konzinfobooking.mfa.gov.hu/?lng=en"
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


class ConfigError(ValueError):
    """Configuration invalide ou incomplete."""


@dataclass
class Person:
    name: str
    birth_date: date
    phone: str
    email: str
    passport_number: str | None = None


@dataclass
class BookingConfig:
    consulate: str
    applications: list[str]
    applicants: int = 1
    person: Person | None = None
    extra_fields: dict[str, str] = field(default_factory=dict)


@dataclass
class SlotsConfig:
    earliest: date | None = None
    latest: date | None = None
    weekdays: list[int] | None = None        # 0 = lundi ... 6 = dimanche
    hours: tuple[str, str] | None = None     # ("08:00", "12:00")


@dataclass
class PollingConfig:
    interval_minutes: float = 5
    jitter_seconds: int = 60
    realert_minutes: int = 30
    max_backoff_minutes: int = 120
    error_alert_minutes: int = 60
    heartbeat_hours: int = 24          # 0 = pas de message « surveillance active »


@dataclass
class HumanConfig:
    confirm_timeout_minutes: int = 15
    beep: bool = True


@dataclass
class TelegramConfig:
    token: str | None = None
    chat_id: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)


@dataclass
class AppConfig:
    site_url: str
    booking: BookingConfig
    slots: SlotsConfig
    polling: PollingConfig
    human: HumanConfig
    telegram: TelegramConfig
    root: Path

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def screenshots_dir(self) -> Path:
        return self.root / "screenshots"

    @property
    def discovery_dir(self) -> Path:
        return self.root / "discovery"

    @property
    def user_data_dir(self) -> Path:
        return self.root / "user_data"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"


# --------------------------------------------------------------------------- helpers

def _parse_date(value: Any, what: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ConfigError(f"{what} : date invalide {value!r} (format attendu AAAA-MM-JJ)") from exc


def _parse_hours(value: Any) -> tuple[str, str] | None:
    if value in (None, "", []):
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ConfigError('slots.hours doit etre une liste de 2 heures, ex. ["08:00", "12:00"]')
    start, end = (str(v).strip() for v in value)
    for v in (start, end):
        if not _TIME_RE.match(v):
            raise ConfigError(f"slots.hours : heure invalide {v!r} (format HH:MM)")
    return start, end


def _parse_weekdays(value: Any) -> list[int] | None:
    if value in (None, "", []):
        return None
    if not isinstance(value, (list, tuple)):
        raise ConfigError("slots.weekdays doit etre une liste d'entiers 0..6 (0 = lundi)")
    days = []
    for v in value:
        try:
            d = int(v)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"slots.weekdays : valeur invalide {v!r}") from exc
        if not 0 <= d <= 6:
            raise ConfigError("slots.weekdays : valeurs attendues entre 0 (lundi) et 6 (dimanche)")
        days.append(d)
    return sorted(set(days))


def _parse_person(raw: Any) -> Person | None:
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("booking.person doit etre un bloc de champs")
    name = str(raw.get("name") or "").strip()
    phone = str(raw.get("phone") or "").strip()
    email = str(raw.get("email") or "").strip()
    birth = _parse_date(raw.get("birth_date"), "booking.person.birth_date")
    if not name or name.upper() == "PRENOM NOM":
        raise ConfigError("booking.person.name manquant (remplir config.yaml)")
    if birth is None:
        raise ConfigError("booking.person.birth_date manquant")
    if not phone.startswith("+") or not phone[1:].replace(" ", "").isdigit():
        raise ConfigError("booking.person.phone doit etre au format international, ex. +212600000000")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ConfigError("booking.person.email invalide")
    passport = raw.get("passport_number")
    passport = str(passport).strip() if passport not in (None, "") else None
    if passport and passport.upper() == "XX0000000":
        passport = None
    return Person(name=name, birth_date=birth, phone=phone, email=email, passport_number=passport)


def _split_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


# --------------------------------------------------------------------------- public API

def load_config(path: Path | str | None = None, *, root: Path | str | None = None,
                require_person: bool = False) -> AppConfig:
    """Charge config.yaml (+ .env) et renvoie un AppConfig valide.

    - path : chemin du YAML (defaut : <root>/config.yaml, sinon <root>/config.watch.yaml).
    - require_person : True pour `book` (donnees personnelles obligatoires).
    - Overrides par variables d'environnement : KONZINFO_SITE_URL, KONZINFO_CONSULATE,
      KONZINFO_APPLICATIONS (separees par des virgules), KONZINFO_INTERVAL_MINUTES,
      KONZINFO_PERSON_NAME / _BIRTH_DATE / _PHONE / _EMAIL / _PASSPORT (secrets GitHub Actions).
    """
    root_path = Path(root) if root else Path.cwd()
    load_dotenv(root_path / ".env", override=False)

    if path is None:
        for candidate in ("config.yaml", "config.watch.yaml"):
            if (root_path / candidate).exists():
                path = root_path / candidate
                break
        else:
            raise ConfigError("Aucun config.yaml trouve : copier config.example.yaml en config.yaml")
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Fichier de configuration introuvable : {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config.yaml : structure invalide")

    site = raw.get("site") or {}
    booking_raw = raw.get("booking") or {}
    slots_raw = raw.get("slots") or {}
    polling_raw = raw.get("polling") or {}
    human_raw = raw.get("human") or {}

    site_url = os.environ.get("KONZINFO_SITE_URL") or site.get("url") or DEFAULT_SITE_URL

    consulate = (os.environ.get("KONZINFO_CONSULATE") or booking_raw.get("consulate") or "").strip()
    if not consulate:
        raise ConfigError("booking.consulate manquant")

    apps_env = os.environ.get("KONZINFO_APPLICATIONS")
    applications = _split_list(apps_env) if apps_env else [
        str(a).strip() for a in (booking_raw.get("applications") or []) if str(a).strip()
    ]
    if not applications:
        raise ConfigError("booking.applications doit contenir au moins un type de demande")

    try:
        applicants = int(booking_raw.get("applicants", 1))
    except (TypeError, ValueError) as exc:
        raise ConfigError("booking.applicants doit etre un entier") from exc
    if applicants < 1:
        raise ConfigError("booking.applicants doit etre >= 1")

    person_raw = dict(booking_raw.get("person") or {})
    for key, env in (("name", "KONZINFO_PERSON_NAME"), ("birth_date", "KONZINFO_PERSON_BIRTH_DATE"),
                     ("phone", "KONZINFO_PERSON_PHONE"), ("email", "KONZINFO_PERSON_EMAIL"),
                     ("passport_number", "KONZINFO_PERSON_PASSPORT")):
        if os.environ.get(env):
            person_raw[key] = os.environ[env]
    try:
        person = _parse_person(person_raw)
    except ConfigError:
        if require_person:
            raise
        person = None  # donnees perso absentes ou placeholders : tolere quand elles ne sont pas requises
    if require_person and person is None:
        raise ConfigError("booking.person est obligatoire pour cette commande (voir config.example.yaml)")

    extra_fields = booking_raw.get("extra_fields") or {}
    if not isinstance(extra_fields, dict):
        raise ConfigError("booking.extra_fields doit etre un dictionnaire { libelle: valeur }")
    extra_fields = {str(k): str(v) for k, v in extra_fields.items()}

    slots = SlotsConfig(
        earliest=_parse_date(slots_raw.get("earliest"), "slots.earliest"),
        latest=_parse_date(slots_raw.get("latest"), "slots.latest"),
        weekdays=_parse_weekdays(slots_raw.get("weekdays")),
        hours=_parse_hours(slots_raw.get("hours")),
    )
    if slots.earliest and slots.latest and slots.earliest > slots.latest:
        raise ConfigError("slots.earliest doit etre <= slots.latest")

    interval_env = os.environ.get("KONZINFO_INTERVAL_MINUTES")
    polling = PollingConfig(
        interval_minutes=float(interval_env or polling_raw.get("interval_minutes", 5)),
        jitter_seconds=int(polling_raw.get("jitter_seconds", 60)),
        realert_minutes=int(polling_raw.get("realert_minutes", 30)),
        max_backoff_minutes=int(polling_raw.get("max_backoff_minutes", 120)),
        error_alert_minutes=int(polling_raw.get("error_alert_minutes", 60)),
        heartbeat_hours=int(polling_raw.get("heartbeat_hours", 24)),
    )
    if polling.interval_minutes < 1:
        raise ConfigError("polling.interval_minutes doit etre >= 1 (respect du site)")
    if polling.heartbeat_hours < 0:
        raise ConfigError("polling.heartbeat_hours doit etre >= 0 (0 = desactive)")

    human = HumanConfig(
        confirm_timeout_minutes=int(human_raw.get("confirm_timeout_minutes", 15)),
        beep=bool(human_raw.get("beep", True)),
    )

    telegram = TelegramConfig(
        token=(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip() or None,
        chat_id=(os.environ.get("TELEGRAM_CHAT_ID") or "").strip() or None,
    )

    return AppConfig(
        site_url=site_url,
        booking=BookingConfig(consulate=consulate, applications=applications, applicants=applicants,
                              person=person, extra_fields=extra_fields),
        slots=slots,
        polling=polling,
        human=human,
        telegram=telegram,
        root=root_path,
    )
