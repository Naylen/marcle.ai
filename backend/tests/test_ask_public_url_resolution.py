from starlette.requests import Request

import app.routers.ask as ask_module


def _request(headers: dict[str, str] | None = None, scheme: str = "http") -> Request:
    raw_headers = []
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode("latin-1"), value.encode("latin-1")))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": scheme,
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": raw_headers,
        "client": ("127.0.0.1", 12345),
        "server": ("backend", 8000),
    }
    return Request(scope)


def test_normalize_base_url_removes_path_and_trailing_slash():
    assert ask_module._normalize_base_url("https://ask.example.com/base/") == "https://ask.example.com"


def test_get_public_base_url_prefers_base_public_url(monkeypatch):
    monkeypatch.setattr(ask_module, "BASE_PUBLIC_URL", "https://ask.example.com/path/")
    request = _request(headers={"host": "ignored.example.com"})

    assert ask_module._get_public_base_url(request) == "https://ask.example.com"


def test_get_public_base_url_accepts_domain_without_scheme(monkeypatch):
    monkeypatch.setattr(ask_module, "BASE_PUBLIC_URL", "ask.example.com")
    request = _request(headers={"host": "ignored.example.com"})

    assert ask_module._get_public_base_url(request) == "https://ask.example.com"


def test_get_public_base_url_uses_forwarded_headers_when_unset(monkeypatch):
    monkeypatch.setattr(ask_module, "BASE_PUBLIC_URL", "")
    request = _request(headers={"host": "internal:8000", "x-forwarded-host": "ask.example.com", "x-forwarded-proto": "https"})

    assert ask_module._get_public_base_url(request) == "https://ask.example.com"


def test_get_oauth_redirect_uri_prefers_google_redirect_url(monkeypatch):
    monkeypatch.setattr(ask_module, "GOOGLE_REDIRECT_URL", "https://auth.example.com/callback")
    monkeypatch.setattr(ask_module, "BASE_PUBLIC_URL", "https://ask.example.com")
    request = _request(headers={"host": "ask.example.com"})

    assert ask_module._get_oauth_redirect_uri(request) == "https://auth.example.com/callback"


def test_get_oauth_redirect_uri_falls_back_to_public_base_url(monkeypatch):
    monkeypatch.setattr(ask_module, "GOOGLE_REDIRECT_URL", "")
    monkeypatch.setattr(ask_module, "BASE_PUBLIC_URL", "https://ask.example.com")
    request = _request(headers={"host": "ask.example.com"})

    assert ask_module._get_oauth_redirect_uri(request) == "https://ask.example.com/api/ask/auth/callback"
