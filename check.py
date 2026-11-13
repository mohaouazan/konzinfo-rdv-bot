"""Surveille les creneaux de rendez-vous du consulat de Hongrie (Konzinfo Booking) et previent sur Telegram.

Lance toutes les 5 min par GitHub Actions (.github/workflows/watch.yml), ou a la main : python check.py
Le site n'affiche les disponibilites qu'apres un formulaire rempli : le script y met des valeurs factices fixes
(aucune donnee personnelle), clique « Select date » et lit la reponse : banniere « aucun creneau » ou calendrier.
Il ne reserve rien.
"""
from __future__ import annotations

import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

try:  # fichier .env facultatif en local (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID) ; sur GitHub ce sont des secrets
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

URL = "https://konzinfobooking.mfa.gov.hu/?lng=en"
CONSULATE = os.environ.get("KONZINFO_CONSULATE", "Morocco - Rabat")  # sous-chaine du libelle « Select location »
APPLICATION = os.environ.get("KONZINFO_APPLICATION", "Schengen")  # sous-chaine de la case « Applications »
# Valeurs factices : le site exige un formulaire valide avant d'interroger les disponibilites (rien n'est reserve).
FORM = {"name": "TEST TEST", "birth": "01/01/1990", "phone": "+212600000000",
        "email": "konzinfo.watch@example.com", "passport": "AA000000"}
REALERT_MIN = 60  # re-prevenir toutes les 60 min tant que des creneaux restent disponibles
ERROR_ALERT_MIN = 180  # au plus une alerte d'erreur toutes les 3 h
HEARTBEAT_H = 24  # « surveillance active » une fois par jour : plus de message pendant > 1 jour = surveillance arretee
STATE = Path("state/status.json")  # conserve entre deux runs (cache GitHub Actions)
SHOT = Path("state/last.png")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
NO_SLOTS = "there are currently no appointments available"
BANNED = ("letiltásra került", "IP address has been blocked", "Access Denied")


def log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {msg}", flush=True)


def telegram(text: str, photo: Path | None = None) -> bool:
    """Envoie un message (avec capture si fournie). Ne leve jamais."""
    if not TOKEN or not CHAT:
        log(f"[Telegram non configure] {text}")
        return False
    api = f"https://api.telegram.org/bot{TOKEN}"
    try:
        if photo and photo.exists():
            with photo.open("rb") as fh:
                r = requests.post(f"{api}/sendPhoto", data={"chat_id": CHAT, "caption": text[:1000]},
                                  files={"photo": fh}, timeout=30)
            if r.ok:
                return True
        r = requests.post(f"{api}/sendMessage", data={"chat_id": CHAT, "text": text[:4000]}, timeout=20)
        if not r.ok:
            log(f"Telegram refuse : {r.status_code} {r.text[:200]}")
        return r.ok
    except requests.RequestException as exc:
        log(f"Telegram injoignable : {exc}")
        return False


def wait_idle(page) -> None:
    """Attend la fin de l'overlay de chargement (appel Blazor en cours) et verifie l'absence d'erreur Blazor."""
    page.locator(".blockUI.blockOverlay, .blockUI.blockMsg").first.wait_for(state="hidden", timeout=30_000)
    page.wait_for_timeout(300)
    if page.locator("#blazor-error-ui").is_visible():
        raise RuntimeError("erreur Blazor non geree (An unhandled error has occurred)")


def pick(modal, wanted: str, what: str) -> None:
    """Coche, dans une modal du site, la case dont le libelle contient `wanted`."""
    labels = modal.locator("label.form-check-label")
    match = labels.filter(has_text=re.compile(re.escape(wanted), re.I))
    if match.count() == 0:
        raise RuntimeError(f"{what} {wanted!r} introuvable ; libelles : {labels.all_inner_texts()[:12]}")
    match.first.click()


def check() -> bool:
    """True si des creneaux existent pour CONSULATE / APPLICATION, False sinon. Leve en cas de probleme."""
    SHOT.unlink(missing_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(locale="en-GB").new_page()
        page.set_default_timeout(30_000)
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
            page.get_by_role("button", name="Select location").wait_for(timeout=90_000)  # appli Blazor chargee
            wait_idle(page)

            # 1) consulat
            page.get_by_role("button", name="Select location").click()
            modal = page.locator("#modal2")
            modal.wait_for(state="visible")
            modal.locator("input[placeholder='Search']").fill(CONSULATE)
            page.wait_for_timeout(400)
            pick(modal, CONSULATE, "consulat")
            modal.wait_for(state="hidden")
            wait_idle(page)

            # 2) type de demande
            page.get_by_role("button", name="Select type of application").click()
            cases = page.locator("#modalCases")
            cases.wait_for(state="visible")
            pick(cases, APPLICATION, "type de demande")
            cases.get_by_role("button", name="Save").click()
            cases.wait_for(state="hidden")
            wait_idle(page)

            # 3) formulaire factice (obligatoire pour que le site interroge les disponibilites)
            page.locator("#label4").fill(FORM["name"])
            birth = page.locator("#birthDateComponent input.duet-date__input")
            birth.click()
            birth.fill(FORM["birth"])
            page.keyboard.press("Tab")
            page.locator("#label6").fill("1")
            page.locator("#label9").fill(FORM["phone"])
            page.locator("#label10").fill(FORM["email"])
            page.get_by_label("Re-enter the email address").fill(FORM["email"])
            passport = page.locator("#label1000")
            if passport.count() and passport.first.is_visible():
                passport.first.fill(FORM["passport"])
            for box in ("#slabel13", "#label13"):
                page.locator(box).check()

            # 4) « Select date » : le site appelle CheckAvailableBookingTimes puis affiche la banniere ou le calendrier
            try:
                with page.expect_response(lambda r: "CheckAvailableBookingTimes" in r.url, timeout=25_000):
                    page.get_by_role("button", name=re.compile("Select date")).click()
            except PWTimeout:
                log("pas de reponse CheckAvailableBookingTimes dans le delai : lecture de la page quand meme")
            wait_idle(page)
            body = re.sub(r"\s+", " ", page.locator("body").inner_text())
            if any(marker in body for marker in BANNED):
                raise RuntimeError("le site indique que l'adresse IP est bloquee")
            page.screenshot(path=str(SHOT), full_page=True)
            if NO_SLOTS in body:
                return False
            if (page.get_by_role("button", name=re.compile("Continue to validation")).count()
                    or page.locator("#idoszakComponent").is_visible()):
                return True
            msgs = [t.strip() for t in page.locator(".validation-message, .invalid-feedback, .text-danger")
                    .all_inner_texts() if t.strip()]
            raise RuntimeError(f"etape des dates non atteinte ; messages du site : {msgs[:6]}")
        finally:
            browser.close()


def minutes_since(iso: str | None) -> float:
    if not iso:
        return float("inf")
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60
    except ValueError:
        return float("inf")


def main() -> int:
    STATE.parent.mkdir(exist_ok=True)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    label = f"{CONSULATE} / {APPLICATION}"

    try:
        available, error = check(), None
    except Exception as exc:  # noqa: BLE001 - tout probleme devient une alerte (limitee) plutot qu'un crash
        available, error = False, f"{type(exc).__name__}: {str(exc)[:300]}"
        traceback.print_exc()
    log(f"resultat : creneaux={'OUI' if available else 'non'} erreur={error}")

    sent = False
    if error:
        state["errors"] = state.get("errors", 0) + 1
        if minutes_since(state.get("last_error_alert")) >= ERROR_ALERT_MIN:
            sent = telegram(f"⚠️ Surveillance Konzinfo ({label}) en erreur ({state['errors']} fois de suite) :\n{error}",
                            photo=SHOT)
            if sent:
                state["last_error_alert"] = now
    else:
        state["errors"] = 0
        if available and (not state.get("available") or minutes_since(state.get("last_alert")) >= REALERT_MIN):
            sent = telegram(f"🎯 CRENEAUX DISPONIBLES - {label} !\nReserve vite : {URL}", photo=SHOT)
            if sent:
                state["last_alert"] = now
        elif not available and state.get("available"):
            sent = telegram(f"ℹ️ Plus aucun creneau disponible ({label}).")
        state["available"] = available

    state["checks"] = state.get("checks", 0) + 1
    if not sent and not available and not error and minutes_since(state.get("last_heartbeat")) >= HEARTBEAT_H * 60:
        if telegram(f"💓 Surveillance active ({label}) : {state['checks']} verification(s) depuis le dernier point, "
                    "aucun creneau."):
            state["last_heartbeat"] = now
            state["checks"] = 0
    state["ts"] = now
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return 0  # toujours 0 : les erreurs partent sur Telegram, pas en e-mails d'echec GitHub toutes les 5 min


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main())
