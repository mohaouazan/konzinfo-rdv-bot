"""Alertes Telegram (+ bip Windows, + appel vocal CallMeBot optionnel, + rafale de rappels jusqu'a reponse).
Jamais bloquant : une erreur reseau est loguee, pas levee."""
from __future__ import annotations

import logging
import re
import sys
import threading
import time
from pathlib import Path

import requests

from konzinfo.config import CallConfig

log = logging.getLogger("konzinfo.notify")

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
MAX_TEXT = 4000  # limite Telegram : 4096
CALLMEBOT_URL = "https://api.callmebot.com/start.php"  # appel vocal Telegram (service tiers, non officiel)
MAX_SPEECH = 256  # CallMeBot coupe le texte lu au-dela
# CallMeBot repond en HTTP 200 meme en cas de refus : le verdict est dans le texte de la page, ex.
# « Authorization for user @x is not received. Warning! User not authorized. »
_CALL_FAILURE = re.compile(r"error|not authorized|not received|warning|disabled|invalid", re.I)
# Echecs transitoires du service partage : saturation (« FLOOD »), ligne occupee, 65 s minimum entre deux appels.
_CALL_RETRYABLE = re.compile(r"flood|busy|too many|within 65 seconds", re.I)
CALL_ATTEMPTS = 3          # tentatives max pour un meme appel
CALL_RETRY_DELAY_S = 70    # CallMeBot refuse deux appels au meme utilisateur en moins de 65 s


def _wait(stop: threading.Event, seconds: float) -> bool:
    """Attend `seconds` ou le lever de `stop` ; True si `stop` a ete leve (isole pour les tests)."""
    return stop.wait(seconds)


def _visible_text(html: str) -> str:
    """Texte lisible d'une page HTML CallMeBot (scripts, styles et balises retires)."""
    txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "", flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


class Notifier:
    def __init__(self, token: str | None, chat_id: str | None, *, beep: bool = False,
                 call: CallConfig | None = None, insist_minutes: float = 0, insist_every_s: int = 30):
        self.token = token
        self.chat_id = chat_id
        self.beep_enabled = beep
        self.call = call or CallConfig()
        self.insist_minutes = max(0.0, float(insist_minutes))
        self.insist_every_s = max(10, int(insist_every_s))
        self._last_sent: dict[str, float] = {}
        self._insist_stop = threading.Event()
        self._threads: list[threading.Thread] = []

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    # ------------------------------------------------------------------ public
    def send(self, text: str, *, photo: Path | None = None, key: str | None = None,
             min_interval_s: int = 0, beep: bool = False, call: str | None = None,
             insist: bool = False, insist_async: bool = False) -> bool:
        """Envoie `text` (et eventuellement une capture). Dedoublonne par `key` sur `min_interval_s`.
        `call`  : texte lu lors d'un appel vocal CallMeBot (si configure) - complement « meilleur effort ».
        `insist`: rafale de rappels Telegram jusqu'a ce que l'utilisateur reponde (voir `insist()`) ; avec
                  `insist_async`, la rafale tourne dans un fil separe pour ne pas bloquer l'appelant.
        Toute nouvelle notification annule la rafale precedente. Renvoie le resultat de l'envoi Telegram."""
        if key and min_interval_s:
            last = self._last_sent.get(key, 0.0)
            if time.monotonic() - last < min_interval_s:
                log.debug("notification %r ignoree (dedoublonnage)", key)
                return False

        self.cancel_insist()
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

        if insist and ok and self.insist_minutes > 0:
            stop = threading.Event()
            self._insist_stop = stop
            if insist_async:
                worker = threading.Thread(target=self.insist, args=(text,), kwargs={"stop": stop},
                                          name="konzinfo-insist", daemon=False)
                worker.start()
                self._threads.append(worker)
            else:
                self.insist(text, stop=stop)
        return ok

    def insist(self, text: str, *, stop: threading.Event | None = None, since: float | None = None) -> int:
        """Rappels Telegram repetes toutes les `insist_every_s` s pendant `insist_minutes` min, jusqu'a ce que
        l'utilisateur reponde au bot (n'importe quel message), que `stop` soit leve ou que la duree soit ecoulee.
        Renvoie le nombre de rappels envoyes. Ne leve jamais."""
        if not self.enabled or self.insist_minutes <= 0:
            return 0
        stop = stop or threading.Event()
        start = time.time() if since is None else since
        total = max(1, int(self.insist_minutes * 60 // self.insist_every_s))
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "alerte")[:200]
        sent = 0
        for i in range(1, total + 1):
            if _wait(stop, self.insist_every_s):
                log.info("rappels arretes (nouvelle notification ou fin du flux)")
                break
            if self._replied_since(start - 5):
                log.info("rappels arretes : reponse recue sur Telegram")
                break
            if self._send_message(f"🔔 Rappel {i}/{total} : {first_line}\n"
                                  "Reponds n'importe quoi a ce bot pour arreter les rappels."):
                sent += 1
        return sent

    def cancel_insist(self) -> None:
        """Interrompt la rafale de rappels en cours (le flux a avance : confirmation, creneau perdu, nouvelle alerte)."""
        self._insist_stop.set()

    def shutdown(self, timeout_s: float = 5) -> None:
        """A appeler avant de quitter : stoppe les rappels et attend les fils en cours."""
        self.cancel_insist()
        for worker in self._threads:
            worker.join(timeout=timeout_s)
        self._threads.clear()

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

    def _replied_since(self, since_ts: float) -> bool:
        """True si l'utilisateur a ecrit au bot depuis `since_ts` (epoch). Offset negatif : on ne lit que la fin de
        la file, sans long polling, pour ne pas gener un autre processus qui l'interrogerait aussi."""
        url = TELEGRAM_API.format(token=self.token, method="getUpdates")
        try:
            resp = requests.get(url, params={"offset": -20, "timeout": 0}, timeout=15)
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.debug("getUpdates impossible : %s", exc)
            return False
        if not data.get("ok"):
            return False
        for upd in data.get("result", []):
            msg = upd.get("message") or upd.get("edited_message") or {}
            chat = msg.get("chat") or {}
            if str(chat.get("id")) == str(self.chat_id) and float(msg.get("date", 0)) >= since_ts:
                return True
        return False

    def _call(self, text: str) -> bool:
        """Appel vocal Telegram via CallMeBot : le service appelle `self.call.user` et lit `text` (synthese vocale).
        cc=no : pas de copie texte (notre message Telegram suffit). Service partage : en cas de saturation
        (« FLOOD », ligne occupee, 65 s entre deux appels), reessaie jusqu'a CALL_ATTEMPTS fois. Ne leve jamais."""
        params = {"user": self.call.user, "text": text[:MAX_SPEECH], "lang": self.call.lang,
                  "rpt": str(self.call.repeat), "cc": "no"}
        for attempt in range(1, CALL_ATTEMPTS + 1):
            try:
                # CallMeBot ne repond qu'une fois l'appel termine (synthese vocale + 30 s de sonnerie) : delai large.
                resp = requests.get(CALLMEBOT_URL, params=params, timeout=90)
            except requests.RequestException as exc:
                log.warning("CallMeBot injoignable : %s", exc)
                return False
            verdict = _visible_text(resp.text)
            if resp.status_code == 200 and not _CALL_FAILURE.search(verdict):
                log.info("CallMeBot : appel vers %s demande (%s)", self.call.user, verdict[:200] or "OK")
                return True
            if attempt < CALL_ATTEMPTS and _CALL_RETRYABLE.search(verdict):
                log.info("CallMeBot sature (%s) : nouvel essai %d/%d dans %d s", verdict[-120:],
                         attempt + 1, CALL_ATTEMPTS, CALL_RETRY_DELAY_S)
                time.sleep(CALL_RETRY_DELAY_S)
                continue
            log.warning("CallMeBot : appel non passe (HTTP %s) : %s", resp.status_code,
                        verdict[:300] or "(reponse vide)")
            return False
        return False

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
