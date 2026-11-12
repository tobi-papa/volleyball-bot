import json

import pytest

from bot.telegram import TelegramError, send

TOKEN = "123456:SECRET-token"


class Resp:
    def __init__(self, status, body):
        self.status_code = status
        self.text = json.dumps(body)

    def json(self):
        return json.loads(self.text)


class FakeSession:
    def __init__(self, status=200, body=None):
        self.calls = []
        self.status = status
        self.body = body if body is not None else {"ok": True}

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        return Resp(self.status, self.body)


def test_send_posts_each_chunk():
    sess = FakeSession()
    text = "\n".join("y" * 100 for _ in range(100))   # ~10 kB -> 3 chunks
    send(text, TOKEN, "42", session=sess)
    assert len(sess.calls) == 3
    url, payload = sess.calls[0]
    assert url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert payload["chat_id"] == "42"
    assert payload["disable_web_page_preview"] is True


def test_send_error_hides_token():
    sess = FakeSession(status=401, body={"ok": False, "description": "Unauthorized"})
    with pytest.raises(TelegramError) as e:
        send("hi", TOKEN, "42", session=sess)
    assert TOKEN not in str(e.value)
    assert "401" in str(e.value)


def test_send_ok_false_is_error():
    with pytest.raises(TelegramError):
        send("hi", TOKEN, "42", session=FakeSession(status=200, body={"ok": False, "description": "chat not found"}))


def test_network_error_hides_token():
    class Boom:
        def post(self, url, **kw):
            raise ConnectionError(f"failed to reach {url}")

    with pytest.raises(TelegramError) as e:
        send("hi", TOKEN, "42", session=Boom())
    assert TOKEN not in str(e.value)
