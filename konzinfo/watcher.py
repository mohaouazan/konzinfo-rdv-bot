"""Surveillance : verifie la disponibilite et alerte sur Telegram. Ne selectionne JAMAIS de creneau."""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone

from konzinfo import dates
from konzinfo.browser import open_browser
from konzinfo.config import AppConfig
from konzinfo.notify import Notifier
from konzinfo.site import BannedError, BookingSite, CaptchaRequired, SiteError
from konzinfo.slots import Slot, summarize
from konzinfo.state import State, now_iso

log = logging.getLogger("konzinfo.watcher")


def check_once(cfg: AppConfig, *, headless: bool = True, deep: bool = True, max_days: int = 3) -> dict:
    """Un cycle : ouvre le site, remplit le formulaire, clique « Select date », lit les creneaux."""
    result: dict = {"ts": now_iso(), "available": False, "days": [], "slots": [], "error": None,
                    "screenshot": None}
    if cfg.booking.person is None:
        raise SiteError("La verification exige les donnees personnelles : le site valide le formulaire "
                        "avant d'interroger les creneaux (config.yaml ou variables KONZINFO_PERSON_*)")
    with open_browser(headless=headless) as page:
        site = BookingSite(page, cfg)
        site.open()
        site.select_consulate(cfg.booking.consulate)
        site.select_applications(cfg.booking.applications)
        site.fill_person(cfg.booking.person, cfg.booking.applicants, cfg.booking.extra_fields)
        if not site.go_to_dates():
            site.dismiss_no_slots()
            return result
        result["available"] = True
        days = dates.available_days(site)
        result["days"] = [d.isoformat() for d in days]
        if deep:
            slots: list[Slot] = []
            for day in days[:max_days]:
                try:
                    slots.extend(dates.select_day(site, day))
                except SiteError as exc:
                    log.warning("lecture des creneaux du %s impossible : %s", day, exc)
            result["slots"] = [s.start.isoformat() for s in sorted(set(slots))]
        shot = site.screenshot("watch_available")
        result["screenshot"] = str(shot) if shot else None
    return result


def _elapsed_minutes(iso: str | None) -> float:
    if not iso:
        return float("inf")
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return float("inf")
    return (datetime.now(timezone.utc) - then).total_seconds() / 60


def _slots_from_iso(values: list[str]) -> list[Slot]:
    out = []
    for v in values:
        try:
            out.append(Slot(start=datetime.fromisoformat(v)))
        except ValueError:
            continue
    return out


CALL_AVAILABLE = ("Konzinfo : des créneaux de rendez-vous sont disponibles au consulat. "
                  "Lance la réservation maintenant.")
CALL_ERROR = "Konzinfo : la surveillance du site est en erreur. Regarde Telegram."


def process_result(cfg: AppConfig, result: dict, prev: dict, notifier: Notifier, *,
                   notify_always: bool = False) -> dict:
    """Decide des alertes a partir du resultat courant et de l'etat precedent ; renvoie l'etat a sauver."""
    state = {**prev, **{k: result.get(k) for k in ("ts", "available", "days", "slots", "error")}}
    label = f"{cfg.booking.consulate} / {', '.join(cfg.booking.applications)}"
    if result.get("error"):
        state["consecutive_errors"] = int(prev.get("consecutive_errors", 0)) + 1
        if _elapsed_minutes(prev.get("last_error_alert_ts")) >= cfg.polling.error_alert_minutes:
            if notifier.send(f"⚠️ Surveillance Konzinfo ({label}) en erreur :\n{result['error']}", call=CALL_ERROR):
                state["last_error_alert_ts"] = now_iso()
        return state
    state["consecutive_errors"] = 0
    sent_any = False
    if result["available"]:
        first_time = not prev.get("available")
        if first_time or _elapsed_minutes(prev.get("last_alert_ts")) >= cfg.polling.realert_minutes:
            slots = _slots_from_iso(result.get("slots") or [])
            detail = summarize(slots) if slots else ("jours : " + ", ".join(result.get("days") or []) or "voir le site")
            msg = (f"🎯 Creneaux DISPONIBLES - {label}\n{detail}\n\n"
                   f"→ Lance maintenant sur le PC : python -m konzinfo book")
            photo = result.get("screenshot")
            if notifier.send(msg, photo=photo, beep=True, call=CALL_AVAILABLE):
                state["last_alert_ts"] = now_iso()
                sent_any = True
    elif prev.get("available"):
        sent_any = notifier.send(f"ℹ️ Plus aucun creneau disponible pour {label}.") or sent_any
    if notify_always and not result["available"]:
        sent_any = notifier.send(f"🔍 Verification {label} : aucun creneau ({result['ts']}).") or sent_any
    _heartbeat(cfg, result, prev, state, notifier, label, sent_any)
    return state


def _heartbeat(cfg: AppConfig, result: dict, prev: dict, state: dict, notifier: Notifier,
               label: str, sent_any: bool) -> None:
    """Message « surveillance active » au plus une fois par `polling.heartbeat_hours`, seulement si rien d'autre
    n'a ete envoye : un silence de plus d'un jour signale alors un surveillant arrete (cron desactive, quota, panne)."""
    checks = int(prev.get("checks_since_heartbeat", 0)) + 1
    state["checks_since_heartbeat"] = checks
    hours = cfg.polling.heartbeat_hours
    if not hours or sent_any or result["available"]:
        return
    if _elapsed_minutes(prev.get("last_heartbeat_ts")) < hours * 60:
        return
    msg = (f"💓 Surveillance active - {label}\n{checks} verification(s) depuis le dernier point, aucun creneau.\n"
           f"Derniere verification : {result['ts']}")
    if notifier.send(msg):
        state["last_heartbeat_ts"] = now_iso()
        state["checks_since_heartbeat"] = 0


def run(cfg: AppConfig, *, once: bool, headless: bool = True, deep: bool = True,
        notify_always: bool = False, notifier: Notifier | None = None, state: State | None = None) -> dict:
    notifier = notifier or Notifier(cfg.telegram.token, cfg.telegram.chat_id, beep=cfg.human.beep, call=cfg.call)
    state = state or State(cfg.state_dir)
    while True:
        prev = state.load()
        try:
            result = check_once(cfg, headless=headless, deep=deep)
        except BannedError as exc:
            result = {"ts": now_iso(), "available": False, "days": [], "slots": [], "error": f"BLOCAGE : {exc}"}
        except CaptchaRequired as exc:
            result = {"ts": now_iso(), "available": False, "days": [], "slots": [], "error": f"CAPTCHA : {exc}"}
        except Exception as exc:  # noqa: BLE001 - la boucle doit survivre a tout
            log.exception("cycle de surveillance en echec")
            result = {"ts": now_iso(), "available": False, "days": [], "slots": [],
                      "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        new_state = process_result(cfg, result, prev, notifier, notify_always=notify_always)
        state.save(new_state)
        log.info("resultat : disponible=%s jours=%s erreur=%s", result["available"], result["days"][:5],
                 result.get("error"))
        if once:
            return result
        errors = int(new_state.get("consecutive_errors", 0))
        base = cfg.polling.interval_minutes * 60 * (2 ** min(errors, 5))
        delay = min(base, cfg.polling.max_backoff_minutes * 60) + random.uniform(0, cfg.polling.jitter_seconds)
        log.info("prochaine verification dans %.0f s", delay)
        time.sleep(delay)
