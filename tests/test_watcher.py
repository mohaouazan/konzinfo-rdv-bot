from datetime import datetime, timedelta, timezone

from konzinfo.config import load_config
from konzinfo.notify import Notifier
from konzinfo.watcher import process_result


class RecordingNotifier(Notifier):
    def __init__(self):
        super().__init__("t", "c")
        self.messages = []

    def send(self, text, **kwargs):  # noqa: D401
        self.messages.append(text)
        return True


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
