import konzinfo.notify as notify_mod
from konzinfo.config import CallConfig
from konzinfo.notify import Notifier


class FakeResp:
    def __init__(self, status=200, text="ok", payload=None):
        self.status_code = status
        self.text = text
        self._payload = payload if payload is not None else {"ok": True, "result": []}

    def json(self):
        return self._payload


def _no_wait(monkeypatch):
    """Les rafales n'attendent pas : l'attente renvoie immediatement l'etat du drapeau d'arret."""
    monkeypatch.setattr(notify_mod, "_wait", lambda stop, seconds: stop.is_set())


def test_disabled_without_token():
    n = Notifier(None, None)
    assert not n.enabled
    assert n.send("hello") is False


def test_send_message_and_dedup(monkeypatch):
    calls = []

    def fake_post(url, timeout, **kwargs):
        calls.append((url, kwargs))
        return FakeResp()

    monkeypatch.setattr(notify_mod.requests, "post", fake_post)
    n = Notifier("123:abc", "42")
    assert n.send("premier", key="k", min_interval_s=600) is True
    assert n.send("doublon", key="k", min_interval_s=600) is False
    assert n.send("autre") is True
    assert len(calls) == 2
    assert calls[0][0].endswith("/bot123:abc/sendMessage")
    assert calls[0][1]["data"]["chat_id"] == "42"
    assert calls[0][1]["data"]["text"] == "premier"


def test_photo_fallback_to_text(monkeypatch, tmp_path):
    seen = []

    def fake_post(url, timeout, **kwargs):
        seen.append(url.rsplit("/", 1)[-1])
        return FakeResp(200) if url.endswith("sendMessage") else FakeResp(400, "bad photo")

    monkeypatch.setattr(notify_mod.requests, "post", fake_post)
    photo = tmp_path / "shot.png"
    photo.write_bytes(b"\x89PNG")
    n = Notifier("123:abc", "42")
    assert n.send("avec photo", photo=photo) is True
    assert seen == ["sendPhoto", "sendMessage"]


def test_network_error_is_swallowed(monkeypatch):
    def boom(url, timeout, **kwargs):
        raise notify_mod.requests.RequestException("offline")

    monkeypatch.setattr(notify_mod.requests, "post", boom)
    assert Notifier("123:abc", "42").send("x") is False


def test_call_placed_with_message(monkeypatch):
    posts, gets = [], []

    def fake_post(url, timeout, **kwargs):
        posts.append(url)
        return FakeResp()

    def fake_get(url, params, timeout):
        gets.append((url, params))
        return FakeResp(200, "<p>Call queued</p>")

    monkeypatch.setattr(notify_mod.requests, "post", fake_post)
    monkeypatch.setattr(notify_mod.requests, "get", fake_get)
    n = Notifier("123:abc", "42", call=CallConfig(user="@moi", lang="fr-FR-Standard-F", repeat=3))
    assert n.send("texte", call="Konzinfo : test. " * 30) is True
    assert len(posts) == 1 and len(gets) == 1
    url, params = gets[0]
    assert url == notify_mod.CALLMEBOT_URL
    assert params["user"] == "@moi" and params["lang"] == "fr-FR-Standard-F"
    assert params["rpt"] == "3" and params["cc"] == "no"
    assert len(params["text"]) == 256  # coupe a la limite CallMeBot


def test_no_call_when_not_configured_or_not_requested(monkeypatch):
    gets = []
    monkeypatch.setattr(notify_mod.requests, "post", lambda url, timeout, **kw: FakeResp())
    monkeypatch.setattr(notify_mod.requests, "get", lambda url, params, timeout: gets.append(url) or FakeResp())
    Notifier("123:abc", "42").send("sans appel", call="Konzinfo : appel")          # CallMeBot non configure
    Notifier("123:abc", "42", call=CallConfig(user="@moi")).send("sans appel")      # appel non demande
    assert gets == []


def test_call_is_best_effort(monkeypatch):
    gets = []

    def boom(url, timeout, **kwargs):
        raise notify_mod.requests.RequestException("offline")

    monkeypatch.setattr(notify_mod.requests, "post", boom)
    monkeypatch.setattr(notify_mod.requests, "get", lambda url, params, timeout: gets.append(params) or FakeResp())
    n = Notifier("123:abc", "42", call=CallConfig(user="@moi"))
    assert n.send("x", call="Konzinfo : appel") is False      # Telegram en panne : resultat inchange...
    assert len(gets) == 1                                      # ...mais l'appel est tout de meme tente
    assert Notifier(None, None, call=CallConfig(user="@moi")).send("x", call="Konzinfo : appel") is False
    assert len(gets) == 2                                      # appel meme sans Telegram configure
    monkeypatch.setattr(notify_mod.requests, "get",
                        lambda url, params, timeout: FakeResp(200, "<b>ERROR:</b> user not authorized"))
    assert n._call("Konzinfo : appel") is False                # refus CallMeBot = echec logue, pas d'exception
    real = ('<script>window.dataLayer = window.dataLayer || [];</script>Checking Authorization for @moi...<br>'
            'Using bot: @CallMeBot_API Authorization for user @moi is not received. <b>Warning!</b> User not authorized.')
    monkeypatch.setattr(notify_mod.requests, "get", lambda url, params, timeout: FakeResp(200, real))
    assert n._call("Konzinfo : appel") is False                # vraie reponse CallMeBot sans le mot « error »
    ok_page = '<script>var error = 0;</script><p>Checking Authorization for @moi...</p><p>Call queued</p>'
    monkeypatch.setattr(notify_mod.requests, "get", lambda url, params, timeout: FakeResp(200, ok_page))
    assert n._call("Konzinfo : appel") is True                 # un mot suspect dans un <script> ne compte pas


def test_call_retries_when_callmebot_is_flooded(monkeypatch):
    flood = ("Autorization OK Starting Telegram Audio Call. Script ended before Timeout. "
             "Error: FLOOD - Too many users making calls at this time. This call was skipped.")
    answers = iter([FakeResp(200, flood), FakeResp(200, flood), FakeResp(200, "Autorization OK. Call done.")])
    gets, sleeps = [], []
    monkeypatch.setattr(notify_mod.requests, "get", lambda url, params, timeout: gets.append(1) or next(answers))
    monkeypatch.setattr(notify_mod.time, "sleep", lambda s: sleeps.append(s))
    n = Notifier(None, None, call=CallConfig(user="@moi"))
    assert n._call("Konzinfo : appel") is True                 # 3e essai reussi
    assert len(gets) == 3 and sleeps == [notify_mod.CALL_RETRY_DELAY_S] * 2
    gets.clear()
    monkeypatch.setattr(notify_mod.requests, "get", lambda url, params, timeout: gets.append(1) or FakeResp(200, flood))
    assert n._call("Konzinfo : appel") is False                # sature jusqu'au bout : abandon
    assert len(gets) == notify_mod.CALL_ATTEMPTS
    gets.clear()
    monkeypatch.setattr(notify_mod.requests, "get",
                        lambda url, params, timeout: gets.append(1) or FakeResp(200, "Warning! User not authorized."))
    assert n._call("Konzinfo : appel") is False and len(gets) == 1   # refus definitif : pas de nouvel essai


def test_insist_sends_reminders_until_reply(monkeypatch):
    _no_wait(monkeypatch)
    posts, polls = [], []
    monkeypatch.setattr(notify_mod.requests, "post",
                        lambda url, timeout, **kw: posts.append(kw["data"]["text"]) or FakeResp())

    def fake_get(url, params, timeout):
        polls.append(params)
        replied = len(polls) >= 3  # l'utilisateur repond apres le 2e rappel
        msg = {"date": 10**10 if replied else 1, "chat": {"id": 42}, "text": "ok"}
        return FakeResp(200, "{}", {"ok": True, "result": [{"update_id": 1, "message": msg}]})

    monkeypatch.setattr(notify_mod.requests, "get", fake_get)
    n = Notifier("123:abc", "42", insist_minutes=3, insist_every_s=30)
    assert n.insist("🎯 Creneaux DISPONIBLES - Rabat\ndetails", since=100.0) == 2
    assert posts[0].startswith("🔔 Rappel 1/6 : 🎯 Creneaux DISPONIBLES - Rabat") and "Reponds" in posts[0]
    assert len(posts) == 2 and polls[0]["offset"] < 0 and polls[0]["timeout"] == 0


def test_insist_full_burst_disabled_and_cancelled(monkeypatch):
    _no_wait(monkeypatch)
    posts = []
    monkeypatch.setattr(notify_mod.requests, "post", lambda url, timeout, **kw: posts.append(1) or FakeResp())
    monkeypatch.setattr(notify_mod.requests, "get", lambda url, params, timeout: FakeResp())  # aucune reponse
    assert Notifier("123:abc", "42", insist_minutes=2, insist_every_s=30).insist("alerte") == 4
    assert Notifier("123:abc", "42", insist_minutes=0).insist("alerte") == 0
    assert Notifier(None, None, insist_minutes=3).insist("alerte") == 0
    stop = notify_mod.threading.Event()
    stop.set()
    assert Notifier("123:abc", "42", insist_minutes=3).insist("alerte", stop=stop) == 0  # annulee
    assert len(posts) == 4


def test_send_with_insist(monkeypatch):
    _no_wait(monkeypatch)
    posts = []
    monkeypatch.setattr(notify_mod.requests, "post",
                        lambda url, timeout, **kw: posts.append(kw["data"]["text"]) or FakeResp())
    monkeypatch.setattr(notify_mod.requests, "get", lambda url, params, timeout: FakeResp())
    n = Notifier("123:abc", "42", insist_minutes=1, insist_every_s=30)
    assert n.send("urgent", insist=True) is True
    assert posts[0] == "urgent" and len(posts) == 3  # message + 2 rappels
    assert all(p.startswith("🔔 Rappel") for p in posts[1:])
    n.send("info")                                   # sans insist : rien de plus
    assert len(posts) == 4
    assert n.send("asynchrone", insist=True, insist_async=True) is True
    n.shutdown()                                     # attend le fil de rappels
    assert len(posts) == 5 + 2
