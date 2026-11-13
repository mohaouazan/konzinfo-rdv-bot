"""Page-object du wizard Konzinfo Booking - etape 1 (donnees de reservation) + utilitaires."""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from playwright.sync_api import Page, Response
from playwright.sync_api import TimeoutError as PWTimeout

from konzinfo import selectors as S
from konzinfo.config import AppConfig, Person

log = logging.getLogger("konzinfo.site")


class SiteError(RuntimeError):
    """Erreur de navigation ou structure du site inattendue."""


class BannedError(SiteError):
    """Le site refuse l'acces (IP bloquee, HTTP 403/429)."""


class CaptchaRequired(SiteError):
    """Un captcha visible (hCaptcha) attend une action humaine."""


class BookingSite:
    def __init__(self, page: Page, cfg: AppConfig):
        self.page = page
        self.cfg = cfg

    # ------------------------------------------------------------------ utilitaires
    def screenshot(self, name: str) -> Path | None:
        self.cfg.screenshots_dir.mkdir(parents=True, exist_ok=True)
        path = self.cfg.screenshots_dir / f"{datetime.now():%Y%m%d-%H%M%S}_{name}.png"
        try:
            self.page.screenshot(path=str(path), full_page=True)
            return path
        except Exception as exc:  # noqa: BLE001 - la capture ne doit jamais faire echouer le flux
            log.debug("capture impossible : %s", exc)
            return None

    def body_text(self) -> str:
        try:
            return re.sub(r"\s+", " ", self.page.locator("body").inner_text(timeout=5_000))
        except Exception:  # noqa: BLE001
            return ""

    def check_health(self) -> None:
        if self.page.locator(S.BLAZOR_ERROR).is_visible():
            raise SiteError("Erreur Blazor non geree ('An unhandled error has occurred') - rechargement necessaire")
        txt = self.body_text()
        if any(marker in txt for marker in S.TXT_IP_BANNED):
            raise BannedError("Le site indique que l'adresse IP est bloquee")

    def wait_idle(self, timeout_ms: int = 30_000) -> None:
        """Attend la disparition de l'overlay blockUI (appel asynchrone Blazor en cours)."""
        try:
            self.page.locator(S.BLOCK_UI).first.wait_for(state="hidden", timeout=timeout_ms)
        except PWTimeout as exc:
            raise SiteError("Le site reste bloque sur son overlay de chargement") from exc
        self.page.wait_for_timeout(300)
        self.check_health()

    def wait_api(self, name: str, action: Callable[[], None], timeout_ms: int = 30_000) -> Response | None:
        """Execute `action()` et attend la reponse de l'API dont l'URL contient `name`."""
        try:
            with self.page.expect_response(lambda r: name in r.url, timeout=timeout_ms) as info:
                action()
            resp = info.value
            log.debug("API %s -> HTTP %s", name, resp.status)
            if resp.status in (403, 429):
                raise BannedError(f"L'API {name} repond HTTP {resp.status} (blocage probable)")
            return resp
        except PWTimeout:
            log.warning("aucune reponse %s dans le delai (%d ms)", name, timeout_ms)
            return None

    def detect_captcha(self) -> bool:
        loc = self.page.locator(S.HCAPTCHA)
        return loc.count() > 0 and loc.first.is_visible()

    def visible_validation_messages(self) -> list[str]:
        out = []
        for el in self.page.locator(S.VALIDATION_MSGS).all():
            try:
                if el.is_visible():
                    txt = el.inner_text().strip()
                    if txt:
                        out.append(txt)
            except Exception:  # noqa: BLE001
                continue
        return out

    # ------------------------------------------------------------------ chargement
    def open(self) -> None:
        resp = self.page.goto(self.cfg.site_url, wait_until="domcontentloaded", timeout=60_000)
        if resp is not None and resp.status in (403, 429):
            raise BannedError(f"HTTP {resp.status} a l'ouverture du site")
        self._wait_blazor()
        self.wait_idle()
        log.info("site charge : %s", self.cfg.site_url)

    def _wait_blazor(self, timeout_s: int = 90) -> None:
        deadline = time.monotonic() + timeout_s
        welcome = self.page.get_by_text(re.compile(S.TXT_WELCOME, re.I))
        button = self.page.get_by_role("button", name=S.BTN_SELECT_LOCATION)
        while time.monotonic() < deadline:
            if welcome.count() > 0 and button.count() > 0:
                return
            if self.page.locator(S.BLAZOR_ERROR).is_visible():
                raise SiteError("Erreur Blazor au chargement du site")
            self.page.wait_for_timeout(500)
        self.check_health()
        raise SiteError(f"Le site ne s'est pas charge (WebAssembly) en {timeout_s}s")

    # ------------------------------------------------------------------ etape 1
    def select_consulate(self, wanted: str) -> str:
        page = self.page
        page.get_by_role("button", name=S.BTN_SELECT_LOCATION).click()
        modal = page.locator(S.MODAL_CONSULATE)
        modal.wait_for(state="visible", timeout=10_000)
        search = modal.locator(S.MODAL_SEARCH)
        if search.count():
            search.first.fill(wanted)
            page.wait_for_timeout(400)
        labels = modal.locator(S.LABEL_IN_MODAL).filter(has_text=re.compile(re.escape(wanted), re.I))
        if labels.count() == 0:
            if search.count():
                search.first.fill("")
                page.wait_for_timeout(300)
            sample = modal.locator(S.LABEL_IN_MODAL).all_inner_texts()[:12]
            raise SiteError(f"Consulat {wanted!r} introuvable dans la liste. Exemples : {sample}")
        if labels.count() > 1:
            log.warning("plusieurs consulats correspondent a %r : %s (le premier est choisi)",
                        wanted, labels.all_inner_texts())
        full = labels.first.inner_text().strip()
        labels.first.click()
        modal.wait_for(state="hidden", timeout=10_000)
        self.wait_idle()
        log.info("consulat selectionne : %s", full)
        return full

    def select_applications(self, wanted: list[str]) -> list[str]:
        page = self.page
        page.get_by_role("button", name=S.BTN_SELECT_APPLICATION).click()
        modal = page.locator(S.MODAL_CASES)
        modal.wait_for(state="visible", timeout=10_000)
        available = [t.strip() for t in modal.locator(S.LABEL_IN_MODAL).all_inner_texts()]
        chosen: list[str] = []
        for want in wanted:
            cand = modal.locator(S.LABEL_IN_MODAL).filter(has_text=re.compile(re.escape(want), re.I))
            if cand.count() == 0:
                raise SiteError(f"Type de demande {want!r} introuvable pour ce consulat. Disponibles : {available}")
            label = cand.first
            target_id = label.get_attribute("for")
            box = modal.locator(f"input[id='{target_id}']") if target_id else None
            if box is None or box.count() == 0 or not box.first.is_checked():
                label.click()
            chosen.append(label.inner_text().strip())
        modal.get_by_role("button", name=S.BTN_SAVE).click()
        modal.wait_for(state="hidden", timeout=10_000)
        self.wait_idle()
        log.info("types de demande selectionnes : %s", chosen)
        return chosen

    def fill_duet(self, component: str, value: date) -> None:
        """Saisit une date dans un <duet-date-picker> (format du site) puis verifie la valeur ISO."""
        field = self.page.locator(f"{component} {S.DUET_INPUT}")
        field.click()
        field.fill(value.strftime(S.DATE_FORMAT))
        self.page.keyboard.press("Tab")
        self.page.wait_for_timeout(500)
        got = self.page.locator(component).evaluate("e => e.value")
        if got != value.isoformat():
            raise SiteError(f"Date {value} non prise en compte par {component} (valeur lue : {got!r})")

    def fill_person(self, person: Person, applicants: int, extra_fields: dict[str, str]) -> None:
        page = self.page
        page.locator(S.INPUT_NAME).fill(person.name)
        self.fill_duet(S.DUET_BIRTH, person.birth_date)
        page.locator(S.INPUT_APPLICANTS).fill(str(applicants))
        page.locator(S.INPUT_PHONE).fill(person.phone)
        page.locator(S.INPUT_EMAIL).fill(person.email)
        page.get_by_label(S.LABEL_EMAIL2).fill(person.email)
        passport = page.locator(S.INPUT_PASSPORT)
        if passport.count() and passport.first.is_visible():
            if not person.passport_number:
                raise SiteError("Le formulaire demande un numero de passeport : renseigner booking.person.passport_number")
            passport.first.fill(person.passport_number)
        for label, value in extra_fields.items():
            page.get_by_label(label).fill(value)
        for sel in (S.CHK_ACK, S.CHK_CONSENT):
            box = page.locator(sel)
            if not box.is_checked():
                box.check()
        page.wait_for_timeout(300)
        log.info("formulaire rempli (%s, %d demandeur(s))", person.name, applicants)

    def go_to_dates(self) -> bool:
        """Clique « Select date » ». True = etape 2 affichee ; False = banniere « aucun creneau »."""
        page = self.page
        button = page.get_by_role("button", name=re.compile(S.BTN_SELECT_DATE))
        self.wait_api(S.API_CHECK, lambda: button.click(), timeout_ms=25_000)
        self.wait_idle()
        banner = page.get_by_text(S.TXT_NO_SLOTS)
        if banner.count() and banner.first.is_visible():
            log.info("banniere : aucun creneau disponible")
            return False
        if self.detect_captcha():
            raise CaptchaRequired("Un hCaptcha est affiche apres « Select date »")
        cont = page.get_by_role("button", name=re.compile(S.BTN_CONTINUE))
        period = page.locator(S.DUET_PERIOD)
        if (cont.count() and cont.first.is_visible()) or (period.count() and period.first.is_visible()):
            log.info("etape 2 (choix de la date) affichee")
            return True
        msgs = self.visible_validation_messages()
        self.screenshot("step1_unexpected")
        raise SiteError(f"Etape 2 non atteinte apres « Select date ». Messages visibles : {msgs[:6]}")

    def dismiss_no_slots(self) -> None:
        ok = self.page.get_by_role("button", name=re.compile(S.BTN_OK))
        if ok.count() and ok.first.is_visible():
            ok.first.click()
            self.wait_idle()
