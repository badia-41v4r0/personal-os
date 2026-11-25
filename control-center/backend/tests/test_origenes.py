import pytest

from app import security


@pytest.fixture
def origenes(monkeypatch):
    class S:
        allowed_origins = ("http://127.0.0.1:8770", "https://pc.ts.net:*", "https://*.trycloudflare.com")
    monkeypatch.setattr(security, "get_settings", lambda: S)


@pytest.mark.parametrize("origin", [
    "http://127.0.0.1:8770", "https://pc.ts.net", "https://pc.ts.net:8444",
    "https://abc-def-123.trycloudflare.com", "https://abc.trycloudflare.com/",
])
def test_origenes_admitidos(origenes, origin):
    assert security.origin_ok(origin)


@pytest.mark.parametrize("origin", [
    None, "", "http://127.0.0.1:3000", "https://pc.ts.net.evil.com", "https://pc.ts.net:x",
    "https://trycloudflare.com", "https://.trycloudflare.com", "http://abc.trycloudflare.com",
    "https://a.b.trycloudflare.com", "https://abc.trycloudflare.com.evil.com", "https://eviltrycloudflare.com",
    "https://abc.trycloudflare.com:8443",
])
def test_origenes_rechazados(origenes, origin):
    assert not security.origin_ok(origin)
