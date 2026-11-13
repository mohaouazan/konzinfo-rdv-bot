from datetime import datetime, timedelta, timezone

from konzinfo.config import load_config
from konzinfo.notify import Notifier
from konzinfo.watcher import process_result


class RecordingNotifier(Notifier):
    def __init__(self):
        super().__init__("t", "c")
        self.messages = []
        self.calls = []  # texte d'appel vocal demande (None = pas d'appel)

    def send(self, text, **kwargs):  # noqa: D401
        self.messages.append(text)
        self.calls.append(kwargs.get("call"))
        return True


def test_calls_only_for_urgent_alerts(tmp_path):
    cfg = _cfg(tmp_path)
    n = RecordingNotifier()
    quiet = {"ts": "x", "available": False, "days": [], "slots": [], "error": None}
    process_result(cfg, quiet, {}, n)                        # battement de coeur : pas d'appel
    process_result(cfg, quiet, {"available": True}, n)       # « plus aucun creneau » : pas d'appel
    process_result(cfg, quiet, {}, n, notify_always=True)    # simple verification : pas d'appel
    assert len(n.calls) == 3 and all(c is None for c in n.calls)
    avail = {"ts": "x", "available": True, "days": ["2026-12-01"], "slots": [], "error": None, "screenshot": None}
    process_result(cfg, avail, {}, n)
    assert n.calls[-1] and "disponibles" in n.calls[-1]
    err = {"ts": "x", "available": False, "days": [], "slots": [], "error": "boom"}
    process_result(cfg, err, {}, n)
    assert n.calls[-1] and "erreur" in n.calls[-1]


def _cfg(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text("booking:\n  consulate: Morocco - Rabat\n  applications: [Schengen]\n"
                        "polling:\n  realert_minutes: 30\n  error_alert_minutes: 60\n", encoding="utf-8")
    return load_config(cfg_file, root=tmp_path)


def test_alert_on_first_availability_then_throttled(tmp_path):
    cfg = _cfg(tmp_path)
    n = RecordingNotifier()
    res = {"ts": "2026-11-13T10:00:00+00:00", "available": True, "days": ["2026-12-01"],
           "slots": ["2026-12-01T09:00:00"], "error": None, "screenshot": None}
    state = process_result(cfg, res, {}, n)
    assert len(n.messages) == 1 and "DISPONIBLES" in n.messages[0] and "09:00" in n.messages[0]
    assert state["last_alert_ts"]
    process_result(cfg, res, state, n)          # re-alerte trop tot : rien
    assert len(n.messages) == 1
    old = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    process_result(cfg, res, {**state, "last_alert_ts": old}, n)
    assert len(n.messages) == 2


def test_gone_and_error_throttling(tmp_path):
    cfg = _cfg(tmp_path)
    n = RecordingNotifier()
    gone = {"ts": "x", "available": False, "days": [], "slots": [], "error": None}
    process_result(cfg, gone, {"available": True}, n)
    assert "Plus aucun" in n.messages[-1]
    err = {"ts": "x", "available": False, "days": [], "slots": [], "error": "boom"}
    state = process_result(cfg, err, {}, n)
    assert state["consecutive_errors"] == 1 and "boom" in n.messages[-1]
    count = len(n.messages)
    state = process_result(cfg, err, state, n)  # deuxieme erreur dans l'heure : pas de spam
    assert len(n.messages) == count and state["consecutive_errors"] == 2


def test_heartbeat_once_a_day(tmp_path):
    cfg = _cfg(tmp_path)
    n = RecordingNotifier()
    quiet = {"ts": "2026-11-13T10:00:00+00:00", "available": False, "days": [], "slots": [], "error": None}
    state = process_result(cfg, quiet, {}, n)            # tout premier cycle : point de vie immediat
    assert len(n.messages) == 1 and "Surveillance active" in n.messages[0] and "1 verification" in n.messages[0]
    assert state["last_heartbeat_ts"] and state["checks_since_heartbeat"] == 0
    state = process_result(cfg, quiet, state, n)         # quelques minutes plus tard : silence
    state = process_result(cfg, quiet, state, n)
    assert len(n.messages) == 1 and state["checks_since_heartbeat"] == 2
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    state = process_result(cfg, quiet, {**state, "last_heartbeat_ts": old}, n)
    assert len(n.messages) == 2 and "3 verification" in n.messages[1]
    assert state["checks_since_heartbeat"] == 0


def test_heartbeat_disabled_and_not_doubled(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text("booking:\n  consulate: Morocco - Rabat\n  applications: [Schengen]\n"
                        "polling:\n  heartbeat_hours: 0\n", encoding="utf-8")
    cfg = load_config(cfg_file, root=tmp_path)
    n = RecordingNotifier()
    quiet = {"ts": "x", "available": False, "days": [], "slots": [], "error": None}
    process_result(cfg, quiet, {}, n)
    assert n.messages == []
    cfg2 = _cfg(tmp_path)                                # avec --notify-always : pas de battement en double
    n2 = RecordingNotifier()
    process_result(cfg2, quiet, {}, n2, notify_always=True)
    assert len(n2.messages) == 1 and "Verification" in n2.messages[0]
