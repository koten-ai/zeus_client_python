"""Nested JSON redaction covered alongside headers (ZCP-5)."""

from __future__ import annotations

from zeus_client_v2.security.redact import REDACTED, default_redactor


def test_redact_json_credit_card_and_ssn_keys() -> None:
    r = default_redactor()
    out = r.json_value({"credit_card": "4111", "ssn": "123-45-6789", "name": "bob"})
    assert out["credit_card"] == REDACTED
    assert out["ssn"] == REDACTED
    assert out["name"] == "bob"


def test_redact_json_list_of_scalars_passthrough() -> None:
    r = default_redactor()
    assert r.json_value([1, "a", None]) == [1, "a", None]
