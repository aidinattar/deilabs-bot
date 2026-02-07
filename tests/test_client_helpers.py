from deilabs_bot.client import DeilabsClient
from deilabs_bot.config import DeilabsConfig


class FakePage:
    def __init__(self, url: str, html: str):
        self.url = url
        self._html = html

    def content(self) -> str:
        return self._html


def _client(user_id: str = "123") -> DeilabsClient:
    return DeilabsClient(DeilabsConfig(user_id=user_id, lab_name="LAB-X"))


def test_session_expired_message_contains_login_and_upload_steps():
    client = _client("174325172")
    msg = client._session_expired_message()
    assert "deilabs login --user-id 174325172" in msg
    assert "auth_174325172.json" in msg


def test_is_session_expired_detects_redirect_url():
    client = _client()
    page = FakePage("https://deilabs.dei.unipd.it/login", "<html></html>")
    assert client._is_session_expired(page) is True


def test_is_session_expired_detects_expired_banner_in_html():
    client = _client()
    page = FakePage(
        "https://deilabs.dei.unipd.it/laboratory_in_outs",
        "<div>Sorry, your session seems to have expired. Please login again.</div>",
    )
    assert client._is_session_expired(page) is True


def test_is_session_expired_false_for_normal_page():
    client = _client()
    page = FakePage(
        "https://deilabs.dei.unipd.it/laboratory_in_outs",
        "<div>You are not in any lab.</div>",
    )
    assert client._is_session_expired(page) is False
