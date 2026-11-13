"""Etape 2 du wizard : calendrier « Time period » (Duet) + creneaux horaires (div.box.free).

Cette etape n'a pu etre observee qu'a vide (aucun creneau au moment du developpement) :
le code journalise tout et capture l'ecran au moindre doute.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from konzinfo import selectors as S
from konzinfo.site import BookingSite, SiteError
from konzinfo.slots import Slot, slot_from_label

log = logging.getLogger("konzinfo.dates")

MAX_MONTHS_AHEAD = 6
MAX_PAGES = 10


def _open_calendar(site: BookingSite) -> None:
    comp = site.page.locator(S.DUET_PERIOD)
    if comp.locator(S.DUET_DIALOG_ACTIVE).count() == 0:
        toggle = comp.locator(S.DUET_TOGGLE)
        if toggle.count():
            toggle.first.click()
            site.page.wait_for_timeout(400)


def _month_year(site: BookingSite) -> tuple[int, int]:
    comp = site.page.locator(S.DUET_PERIOD)
    month = int(comp.locator(S.DUET_MONTH).first.input_value()) + 1
    year = int(comp.locator(S.DUET_YEAR).first.input_value())
    return month, year


def _day_number(text: str) -> int | None:
    m = re.match(r"\s*(\d{1,2})", text or "")
    return int(m.group(1)) if m else None


def available_days(site: BookingSite, max_months: int = MAX_MONTHS_AHEAD) -> list[date]:
    """Jours cliquables du calendrier de l'etape 2 (= jours avec disponibilite), tries."""
    _open_calendar(site)
    comp = site.page.locator(S.DUET_PERIOD)
    days: set[date] = set()
    for _ in range(max_months):
        month, year = _month_year(site)
        for btn in comp.locator(S.DUET_DAY_ENABLED).all():
            num = _day_number(btn.get_attribute("data-day") or btn.inner_text())
            if num:
                try:
                    days.add(date(year, month, num))
                except ValueError:
                    continue
        nxt = comp.locator(S.DUET_NEXT)
        if nxt.count() == 0 or nxt.first.is_disabled():
            break
        nxt.first.click()
        site.page.wait_for_timeout(300)
    result = sorted(days)
    log.info("jours cliquables dans le calendrier : %s", [d.isoformat() for d in result[:15]])
    return result


def select_day(site: BookingSite, day: date) -> list[Slot]:
    """Choisit un jour (saisie clavier dans le Duet) et renvoie les creneaux libres affiches."""
    site.wait_api(S.API_TIMES, lambda: site.fill_duet(S.DUET_PERIOD, day), timeout_ms=25_000)
    site.wait_idle()
    return read_slots(site, day)


def read_slots(site: BookingSite, day: date) -> list[Slot]:
    page = site.page
    slots: list[Slot] = []
    for _ in range(MAX_PAGES):
        for box in page.locator(S.SLOT_FREE).all():
            if not box.is_visible():
                continue
            slot = slot_from_label(day, box.inner_text())
            if slot:
                slots.append(slot)
        nxt = page.locator(S.PAGINATION_NEXT)
        if nxt.count() == 0 or not nxt.first.is_visible():
            break
        nxt.first.click()
        site.wait_idle()
    log.info("%s : %d creneau(x) libre(s)", day.isoformat(), len(slots))
    if not slots and page.locator(S.SLOT_BOX).count() == 0:
        site.screenshot(f"step2_noboxes_{day.isoformat()}")
    return sorted(set(slots))


def click_slot(site: BookingSite, slot: Slot) -> None:
    """Selectionne un creneau affiche (sans aller plus loin)."""
    page = site.page
    hhmm = f"{slot.start:%H:%M}"
    boxes = page.locator(S.SLOT_FREE).filter(has_text=re.compile(re.escape(hhmm)))
    if boxes.count() == 0:
        alt = hhmm.lstrip("0")
        boxes = page.locator(S.SLOT_FREE).filter(has_text=re.compile(rf"(^|\D){re.escape(alt)}(\D|$)"))
    if boxes.count() == 0:
        raise SiteError(f"Creneau {slot} disparu de la liste avant selection")
    boxes.first.click()
    site.wait_idle()
    if page.locator(S.SLOT_SELECTED).count() == 0:
        log.warning("aucune classe 'selected' detectee apres le clic sur %s (on continue)", slot)
    log.info("creneau selectionne : %s", slot)


def continue_to_validation(site: BookingSite) -> None:
    page = site.page
    button = page.get_by_role("button", name=re.compile(S.BTN_CONTINUE))
    if button.count() == 0:
        raise SiteError("Bouton « Continue to validation » introuvable")
    button.first.click()
    site.wait_idle(timeout_ms=45_000)
    complete = page.get_by_role("button", name=re.compile(S.BTN_COMPLETE))
    if complete.count() == 0 or not complete.first.is_visible():
        site.screenshot("step3_unexpected")
        msgs = site.visible_validation_messages()
        raise SiteError(f"Etape 3 (validation) non atteinte. Messages : {msgs[:6]}")
    log.info("etape 3 (validation) affichee - la suite appartient a l'humain")
