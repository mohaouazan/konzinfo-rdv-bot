import konzinfo.notify as notify_mod
from konzinfo.config import CallConfig
from konzinfo.notify import Notifier


class FakeResp:
    def __init__(self, status=200, text="ok"):
        self.status_code = status
        self.text = text


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
