import konzinfo.notify as notify_mod
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
