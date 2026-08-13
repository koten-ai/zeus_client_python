"""TOON encoding for tool results."""
import importlib
import json
import sys

import pytest

import zeus_client.toon as toon_mod
from zeus_client.toon import to_toon


def test_toon_import_fallback_when_encoder_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "toon":
            raise ImportError("no toon")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    mod = importlib.reload(importlib.import_module("zeus_client.toon"))
    assert mod._toon_encode is None


def test_to_toon_without_encoder(monkeypatch):
    monkeypatch.setattr(toon_mod, "_toon_encode", None)
    assert to_toon('{"a": 1}') == '{"a": 1}'


def test_to_toon_non_json_passthrough(monkeypatch):
    monkeypatch.setattr(toon_mod, "_toon_encode", lambda o: "TOON")
    assert to_toon("plain error") == "plain error"


def test_to_toon_success(monkeypatch):
    monkeypatch.setattr(toon_mod, "_toon_encode", lambda o: "encoded:" + json.dumps(o))
    assert to_toon('{"k": "v"}') == 'encoded:{"k": "v"}'


def test_to_toon_encode_exception_falls_back(monkeypatch):
    def boom(_):
        raise ValueError("encode failed")

    monkeypatch.setattr(toon_mod, "_toon_encode", boom)
    raw = '{"x": 1}'
    assert to_toon(raw) == raw