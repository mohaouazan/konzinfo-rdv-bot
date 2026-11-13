"""Reservation semi-automatique : le script fait tout SAUF saisir le code recu par e-mail et
cliquer « Complete booking ». Ces deux actions restent a l'humain, dans le navigateur visible."""
from __future__ import annotations

import logging
import random
import re
import time

from konzinfo import dates
from konzinfo import selectors as S
from konzinfo.browser import open_browser
from konzinfo.config import AppConfig
from konzinfo.notify import Notifier
from konzinfo.site import BannedError, BookingSite, CaptchaRequired, SiteError
from konzinfo.slots import Slot, choose_first, day_allowed
from konzinfo.state import State

log = logging.getLogger("konzinfo.booker")

MAX_DAYS_PER_ATTEMPT = 5


class Outcome:
    NO_SLOTS = "no_slots"
    NO_MATCH = "no_match"
    CONFIRMED = "confirmed"
    LOST = "lost"
    CLOSED = "closed"
    DRY_RUN = "dry_run"
    ERROR = "error"


def _label(cfg: AppConfig) -> str:
    return f"{cfg.booking.consulate} / {', '.join(cfg.booking.applications)}"


def find_slot(site: BookingSite, cfg: AppConfig) -> Slot | None:
    """Parcourt les jours cliquables (les plus proches d'abord) jusqu'au premier creneau conforme."""
    days = [d for d in dates.available_days(site) if day_allowed(d, cfg.slots)]
    if not days:
        log.info("aucun jour cliquable compatible avec la configuration (slots.*)")
        return None
    for day in days[:MAX_DAYS_PER_ATTEMPT]:
        slots = dates.select_day(site, day)
        chosen = choose_first(slots, cfg.slots)
        if chosen:
            return chosen
    return None


def wait_for_human(site: BookingSite, cfg: AppConfig, notifier: Notifier, slot: Slot) -> str:
    """Attend que l'humain termine (code e-mail + « Complete booking »). Ne clique jamais lui-meme."""
    page = site.page
    started = time.monotonic()
    timeout_s = cfg.human.confirm_timeout_minutes * 60
    warned = captcha_warned = False
    while True:
        if page.is_closed():
            return Outcome.CLOSED
        try:
            if page.get_by_text(S.TXT_CONFIRMED).first.is_visible():
                return Outcome.CONFIRMED
            complete_visible = page.get_by_role("button", name=re.compile(S.BTN_COMPLETE)).first.is_visible()
            continue_visible = page.get_by_role("button", name=re.compile(S.BTN_CONTINUE)).first.is_visible()
            if not complete_visible and continue_visible:
                return Outcome.LOST
            if not captcha_warned and site.detect_captcha():
                notifier.send("🧩 Un captcha s'affiche dans le navigateur : merci de le resoudre a la main.")
                captcha_warned = True
        except Exception as exc:  # noqa: BLE001 - la page peut etre en transition
            log.debug("sondage de la page : %s", exc)
        if not warned and time.monotonic() - started > timeout_s:
            notifier.send(f"⏰ {cfg.human.confirm_timeout_minutes} min sans confirmation pour {slot}.\n"
                          "Le navigateur reste ouvert : termine la reservation a la main, ou ferme la fenetre.")
            warned = True
        time.sleep(2)


def attempt(site: BookingSite, cfg: AppConfig, notifier: Notifier, *, dry_run: bool) -> tuple[str, Slot | None]:
    person = cfg.booking.person
    assert person is not None  # garanti par le chargement de la config (require_person)
    site.open()
    site.select_consulate(cfg.booking.consulate)
    site.select_applications(cfg.booking.applications)
    site.fill_person(person, cfg.booking.applicants, cfg.booking.extra_fields)
    if dry_run:
        shot = site.screenshot("dry_run_step1")
        log.info("--dry-run : formulaire rempli, arret avant « Select date » (capture : %s)", shot)
        return Outcome.DRY_RUN, None
    if not site.go_to_dates():
        site.dismiss_no_slots()
        return Outcome.NO_SLOTS, None
    slot = find_slot(site, cfg)
    if slot is None:
        site.screenshot("step2_no_matching_slot")
        return Outcome.NO_MATCH, None
    dates.click_slot(site, slot)
    dates.continue_to_validation(site)
    shot = site.screenshot("step3_validation")
    notifier.send(
        f"✅ Creneau selectionne : {slot}\n{_label(cfg)}\n\n"
        f"1) Ouvre la boite {person.email} (spams compris) et recopie le code recu\n"
        f"2) Clique « Complete booking » dans le navigateur\n"
        f"Delai : {cfg.human.confirm_timeout_minutes} min.",
        photo=shot, beep=True)
    return wait_for_human(site, cfg, notifier, slot), slot


def _delay_seconds(cfg: AppConfig, errors: int) -> float:
    base = cfg.polling.interval_minutes * 60 * (2 ** min(errors, 5))
    return min(base, cfg.polling.max_backoff_minutes * 60) + random.uniform(0, cfg.polling.jitter_seconds)


def run(cfg: AppConfig, *, loop: bool, headless: bool = False, dry_run: bool = False, force: bool = False,
        notifier: Notifier | None = None, state: State | None = None) -> int:
    notifier = notifier or Notifier(cfg.telegram.token, cfg.telegram.chat_id, beep=cfg.human.beep)
    state = state or State(cfg.state_dir)
    if state.is_booked() and not force:
        info = state.booked_info()
        log.warning("Une reservation est deja enregistree (%s, le %s). Relance avec --force pour recommencer.",
                    info.get("slot"), info.get("booked_at"))
        return 0
    person = cfg.booking.person
    assert person is not None
    user_data = None if headless else cfg.user_data_dir
    with open_browser(headless=headless, user_data_dir=user_data) as page:
        site = BookingSite(page, cfg)
        errors = 0
        while True:
            if page.is_closed():
                log.warning("navigateur ferme par l'utilisateur : arret")
                return 1
            slot: Slot | None = None
            try:
                outcome, slot = attempt(site, cfg, notifier, dry_run=dry_run)
                errors = 0
            except BannedError as exc:
                errors += 3
                outcome = Outcome.ERROR
                notifier.send(f"⛔ Le site bloque l'acces : {exc}\nPause longue avant nouvel essai.",
                              key="banned", min_interval_s=3600)
            except CaptchaRequired as exc:
                errors += 1
                outcome = Outcome.ERROR
                site.screenshot("captcha")
                notifier.send(f"🧩 Captcha demande par le site : {exc}\nResous-le dans le navigateur ; "
                              "nouvel essai ensuite.", key="captcha", min_interval_s=1800)
            except SiteError as exc:
                errors += 1
                outcome = Outcome.ERROR
                log.error("tentative en echec : %s", exc)
                site.screenshot("error")
                notifier.send(f"⚠️ Erreur pendant la reservation : {exc}", key="error", min_interval_s=3600)
            except Exception as exc:  # noqa: BLE001 - la boucle doit survivre
                errors += 1
                outcome = Outcome.ERROR
                log.exception("erreur inattendue")
                if page.is_closed():
                    return 1
                notifier.send(f"⚠️ Erreur inattendue : {type(exc).__name__}: {str(exc)[:200]}",
                              key="error", min_interval_s=3600)

            if outcome == Outcome.CONFIRMED:
                shot = site.screenshot("confirmation")
                state.mark_booked({"slot": str(slot), "consulate": cfg.booking.consulate,
                                   "applications": cfg.booking.applications, "email": person.email})
                notifier.send(f"🎉 RENDEZ-VOUS RESERVE : {slot}\n{_label(cfg)}\n"
                              f"Un e-mail de confirmation arrive sur {person.email}. "
                              "Pense a VALIDER la reservation via l'e-mail de rappel avant le RDV.",
                              photo=shot, beep=True)
                return 0
            if outcome == Outcome.DRY_RUN:
                return 0
            if outcome == Outcome.CLOSED:
                log.warning("navigateur ferme sans confirmation")
                return 1
            if outcome == Outcome.LOST:
                notifier.send("↩️ Le creneau a ete perdu avant la confirmation : nouvelle recherche immediate.")
                continue
            if not loop:
                log.info("resultat : %s (sans --loop, arret)", outcome)
                return 0 if outcome in (Outcome.NO_SLOTS, Outcome.NO_MATCH) else 1
            delay = _delay_seconds(cfg, errors)
            log.info("resultat : %s - prochaine tentative dans %.0f s", outcome, delay)
            time.sleep(delay)
