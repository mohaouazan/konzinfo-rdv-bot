"""Alertes Telegram (+ bip Windows). Jamais bloquant : une erreur reseau est loguee, pas levee."""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import requests

log = logging.getLogger("konzinfo.notify")

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
MAX_TEXT = 4000  # limite Telegram : 4096


class Notifier:
    def __init__(self, token: str | None, chat_id: str | None, *, beep: bool = False):
        self.token = token
        self.chat_id = chat_id
        self.beep_enabled = beep
        self._last_sent: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    # ------------------------------------------------------------------ public
    def send(self, text: str, *, photo: Path | None = None, key: str | None = None,
             min_interval_s: int = 0, beep: bool = False) -> bool:
        """Envoie `text` (et eventuellement une capture). Dedoublonne par `key` sur `min_interval_s`."""
        if key and min_interval_s:
            last = self._last_sent.get(key, 0.0)
            if time.monotonic() - last < min_interval_s:
                log.debug("notification %r ignoree (dedoublonnage)", key)
                return False

        if beep and self.beep_enabled:
            self.beep()

        if not self.enabled:
            log.info("[TELEGRAM desactive] %s", text)
            return False

        ok = self._send_photo(text, photo) if photo and Path(photo).exists() else self._send_message(text)
        if ok and key:
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
