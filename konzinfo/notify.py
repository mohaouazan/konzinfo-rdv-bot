"""Alertes Telegram (+ bip Windows, + appel vocal CallMeBot optionnel). Jamais bloquant : une erreur reseau est
loguee, pas levee."""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path

import requests

from konzinfo.config import CallConfig

log = logging.getLogger("konzinfo.notify")

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
MAX_TEXT = 4000  # limite Telegram : 4096
CALLMEBOT_URL = "https://api.callmebot.com/start.php"  # appel vocal Telegram (service tiers, non officiel)
MAX_SPEECH = 256  # CallMeBot coupe le texte lu au-dela


class Notifier:
    def __init__(self, token: str | None, chat_id: str | None, *, beep: bool = False,
                 call: CallConfig | None = None):
        self.token = token
        self.chat_id = chat_id
        self.beep_enabled = beep
        self.call = call or CallConfig()
        self._last_sent: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    # ------------------------------------------------------------------ public
    def send(self, text: str, *, photo: Path | None = None, key: str | None = None,
             min_interval_s: int = 0, beep: bool = False, call: str | None = None) -> bool:
        """Envoie `text` (et eventuellement une capture). Dedoublonne par `key` sur `min_interval_s`.
        Si `call` est fourni et que CallMeBot est configure, declenche en plus un appel vocal qui lit `call`.
        Renvoie le resultat de l'envoi Telegram (l'appel est un complement « meilleur effort »)."""
        if key and min_interval_s:
            last = self._last_sent.get(key, 0.0)
            if time.monotonic() - last < min_interval_s:
                log.debug("notification %r ignoree (dedoublonnage)", key)
                return False

        if beep and self.beep_enabled:
            self.beep()

        ok = False
        if not self.enabled:
            log.info("[TELEGRAM desactive] %s", text)
        else:
            ok = self._send_photo(text, photo) if photo and Path(photo).exists() else self._send_message(text)

        called = bool(call) and self.call.enabled and self._call(call)  # type: ignore[arg-type]
        if (ok or called) and key:
            self._last_sent[key] = time.monotonic()
        return ok

    def beep(self) -> None:
        try:
            if sys.platform == "win32":
                import winsound

                for _ in range(3):
                    winsound.Beep(1200, 350)
                    time.sleep(0.15)
            else:
                sys.stdout.write("\a")
                sys.stdout.flush()
        except Exception as exc:  # pragma: no cover - depend de la machine
            log.debug("bip impossible : %s", exc)

    # ------------------------------------------------------------------ internals
    def _send_message(self, text: str) -> bool:
        url = TELEGRAM_API.format(token=self.token, method="sendMessage")
        payload = {"chat_id": self.chat_id, "text": text[:MAX_TEXT], "disable_web_page_preview": True}
        return self._post(url, data=payload)

    def _send_photo(self, caption: str, photo: Path) -> bool:
        url = TELEGRAM_API.format(token=self.token, method="sendPhoto")
        try:
            with Path(photo).open("rb") as fh:
                ok = self._post(url, data={"chat_id": self.chat_id, "caption": caption[:1000]},
                                files={"photo": fh})
        except OSError as exc:
            log.warning("capture illisible (%s) : envoi du texte seul", exc)
            ok = False
        if not ok:
            ok = self._send_message(caption)
        return ok

    def _call(self, text: str) -> bool:
        """Appel vocal Telegram via CallMeBot : le service appelle `self.call.user` et lit `text` (synthese vocale).
        cc=no : pas de copie texte (notre message Telegram suffit). Ne leve jamais."""
        params = {"user": self.call.user, "text": text[:MAX_SPEECH], "lang": self.call.lang,
                  "rpt": str(self.call.repeat), "cc": "no"}
        try:
            resp = requests.get(CALLMEBOT_URL, params=params, timeout=20)
        except requests.RequestException as exc:
            log.warning("CallMeBot injoignable : %s", exc)
            return False
        snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", resp.text or ""))[:200].strip()
        if resp.status_code != 200 or "error" in snippet.lower():
            log.warning("CallMeBot : appel refuse (HTTP %s) : %s", resp.status_code, snippet)
            return False
        log.info("CallMeBot : appel vers %s demande (%s)", self.call.user, snippet or "OK")
        return True

    @staticmethod
    def _post(url: str, **kwargs) -> bool:
        try:
            resp = requests.post(url, timeout=20, **kwargs)
        except requests.RequestException as exc:
            log.warning("Telegram injoignable : %s", exc)
            return False
        if resp.status_code != 200:
            log.warning("Telegram a refuse l'envoi (%s) : %s", resp.status_code, resp.text[:200])
            return False
        return True
