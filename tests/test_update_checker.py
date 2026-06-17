import httpx
import pytest

from bot.update import checker as checker_mod
from bot.update.checker import UpdateChecker, _is_newer

_MANIFEST = {
    "version": "1.3.0",
    "url": "https://example.com/MT5Bot-1.3.0.exe",
    "sha256": "abc123",
    "notes": "Fixed things",
}


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        if self._exc is not None:
            raise self._exc
        return self._resp


def _patch(monkeypatch, resp=None, exc=None):
    monkeypatch.setattr(checker_mod.httpx, "AsyncClient", lambda *a, **k: _FakeClient(resp, exc))


@pytest.mark.parametrize(
    "latest,current,expected",
    [
        ("1.2.0", "1.2.0", False),
        ("1.1.9", "1.2.0", False),
        ("1.2.1", "1.2.0", True),
        ("1.3.0", "1.2.9", True),
        ("2.0", "1.9.9", True),
        ("1.2", "1.2.0", False),
        ("1.2.0.1", "1.2.0", True),
    ],
)
def test_is_newer(latest, current, expected):
    assert _is_newer(latest, current) is expected


def test_is_newer_malformed_is_false():
    assert _is_newer("oops", "1.2.0") is False


async def test_check_finds_newer(monkeypatch):
    _patch(monkeypatch, resp=_FakeResp(_MANIFEST))
    c = UpdateChecker("https://example.com/latest.json", current_version="1.2.0")
    await c.check()
    assert c.info.available is True
    assert c.info.version == "1.3.0"
    assert c.info.url == _MANIFEST["url"]
    assert c.info.sha256 == "abc123"
    assert c.info.notes == "Fixed things"


async def test_check_same_version_not_available(monkeypatch):
    _patch(monkeypatch, resp=_FakeResp(_MANIFEST))
    c = UpdateChecker("https://example.com/latest.json", current_version="1.3.0")
    await c.check()
    assert c.info.available is False


async def test_check_http_error_is_non_fatal(monkeypatch):
    _patch(monkeypatch, exc=httpx.ConnectError("down"))
    c = UpdateChecker("https://example.com/latest.json", current_version="1.2.0")
    await c.check()
    assert c.info.available is False


async def test_check_malformed_manifest_is_non_fatal(monkeypatch):
    _patch(monkeypatch, resp=_FakeResp({"notes": "no version key"}))
    c = UpdateChecker("https://example.com/latest.json", current_version="1.2.0")
    await c.check()
    assert c.info.available is False


async def test_check_empty_url_is_noop(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must not hit the network without a URL")

    monkeypatch.setattr(checker_mod.httpx, "AsyncClient", _boom)
    c = UpdateChecker("", current_version="1.2.0")
    await c.check()
    assert c.info.available is False
