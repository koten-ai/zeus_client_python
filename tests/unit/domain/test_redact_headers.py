"""Unit tests for V2 security redactor (ZCP-5 / Task 1.2 · ZCM-009)."""

from __future__ import annotations

from zeus_client_v2.security.redact import REDACTED, DefaultRedactor, default_redactor


def test_redact_headers_authorization_and_api_key() -> None:
    r = default_redactor()
    out = r.headers(
        {
            "Authorization": "Bearer sk-secret-token",
            "X-Api-Key": "abc123",
            "Content-Type": "application/json",
            "Cookie": "session=xyz",
            "X-Zeus-Mode": "analytics",
        }
    )
    assert out["Authorization"] == REDACTED
    assert out["X-Api-Key"] == REDACTED
    assert out["Cookie"] == REDACTED
    assert out["Content-Type"] == "application/json"
    assert out["X-Zeus-Mode"] == "analytics"


def test_redact_headers_case_insensitive() -> None:
    r = default_redactor()
    out = r.headers({"authorization": "Basic dXNlcjpwYXNz", "X-API-KEY": "k"})
    assert out["authorization"] == REDACTED
    assert out["X-API-KEY"] == REDACTED


def test_redact_json_nested_keys() -> None:
    r = default_redactor()
    payload = {
        "user": "alice",
        "password": "s3cret",
        "nested": {
            "api_key": "key-1",
            "token": "tok",
            "ok": True,
            "deeper": {"authorization": "Bearer x", "count": 1},
        },
        "items": [{"secret": "nope", "id": 7}],
    }
    out = r.json_value(payload)
    assert out["user"] == "alice"
    assert out["password"] == REDACTED
    assert out["nested"]["api_key"] == REDACTED
    assert out["nested"]["token"] == REDACTED
    assert out["nested"]["ok"] is True
    assert out["nested"]["deeper"]["authorization"] == REDACTED
    assert out["nested"]["deeper"]["count"] == 1
    assert out["items"][0]["secret"] == REDACTED
    assert out["items"][0]["id"] == 7


def test_redact_text_masks_bearer_and_truncates() -> None:
    r = default_redactor()
    text = "call with Authorization: Bearer sk-live-abc and more padding " * 5
    out = r.text(text, max_chars=80)
    assert "sk-live-abc" not in out
    assert "Bearer" not in out or REDACTED in out
    assert len(out) <= 80 + len("…")  # allow ellipsis


def test_redact_text_short_unchanged_if_clean() -> None:
    r = default_redactor()
    assert r.text("hello world", max_chars=100) == "hello world"


def test_default_redactor_is_default_redactor_instance() -> None:
    assert isinstance(default_redactor(), DefaultRedactor)
