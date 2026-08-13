"""Catalog discovery, loading, scope-brief helpers, and dead auth shims."""

import json

import httpx
import pytest
import respx
import zeus_client.zeus.catalog as catalog
from zeus_client.contract_hash import compute_contract_hash, extract_stamped_hash
from zeus_client.zeus.catalog import (
    _normalize_chat_request_shape,
    chat_request_path,
    extract_scope_brief,
    list_chat_requests,
    load_chat_request,
    load_live_chat_request,
    merge_scope_brief,
    tools_from_chat_request,
)

ZEUS_URL = "http://zeus.test:8080"
BUCKET = "beer-sample"
SCOPE = "_default"
BRIEF = "## SCOPE BRIEF\nscope: beer-sample/_default\nmode: auto\n"


def test_list_chat_requests_empty_when_missing(patch_paths, monkeypatch):
    d = patch_paths["chat_req_dir"]
    for p in list(d.rglob("*")):
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            import shutil

            shutil.rmtree(p, ignore_errors=True)
    d.rmdir()
    assert list_chat_requests() == []


def test_list_chat_requests_general_and_subdir(patch_paths):
    d = patch_paths["chat_req_dir"]
    (d / "demo").mkdir(exist_ok=True)
    (d / "demo" / "chat_request_foo_v2.json").write_text("{}", encoding="utf-8")
    (d / "chat_request_v2.json").write_text("{}", encoding="utf-8")
    (d / "chat_request.json").write_text("{}", encoding="utf-8")
    (d / "chat_request_custom_v2.json").write_text("{}", encoding="utf-8")
    (d / "other_mode_v2.json").write_text("{}", encoding="utf-8")
    (d / "chat_request_legacy.json").write_text("{}", encoding="utf-8")

    entries = {(e["file"], e["mode"], e["source"]) for e in list_chat_requests()}
    assert ("chat_request_v2.json", "default", "general") in entries
    assert ("chat_request.json", "default", "general") in entries
    assert ("chat_request_custom_v2.json", "custom", "general") in entries
    assert ("other_mode_v2.json", "other_mode_v2", "general") in entries
    assert ("chat_request_legacy.json", "legacy", "general") in entries
    assert ("demo/chat_request_foo_v2.json", "foo", "demo") in entries


def test_chat_request_path_default_falls_through_when_top_missing(patch_paths, monkeypatch):
    isolated = patch_paths["chat_req_dir"].parent / "only_nested"
    (isolated / "nested").mkdir(parents=True)
    nested = isolated / "nested" / "chat_request_v2.json"
    nested.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(catalog, "CHAT_REQ_DIR", isolated)
    monkeypatch.setattr("zeus_client.constants.CHAT_REQ_DIR", isolated)
    assert chat_request_path("v2", "default") == nested


def test_chat_request_path_default_and_mode(patch_paths):
    d = patch_paths["chat_req_dir"]
    assert chat_request_path("v2", "default").name == "chat_request_v2.json"
    assert chat_request_path("v2", "analytics").name == "chat_request_analytics_v2.json"
    assert chat_request_path("v2", None).name == "chat_request_v2.json"
    assert chat_request_path("v2", "") is not None

    sub = d / "nested"
    sub.mkdir(exist_ok=True)
    nested = sub / "chat_request_nested_v2.json"
    nested.write_text("{}", encoding="utf-8")
    assert chat_request_path("v2", "nested") == nested


def test_chat_request_path_none_when_catalog_empty(patch_paths, monkeypatch):
    empty_root = patch_paths["chat_req_dir"].parent / "empty_catalog"
    empty_root.mkdir(parents=True)
    monkeypatch.setattr(catalog, "CHAT_REQ_DIR", empty_root)
    monkeypatch.setattr("zeus_client.constants.CHAT_REQ_DIR", empty_root)
    empty_user = patch_paths["user_chat_req_dir"].parent / "empty_user_chat"
    empty_user.mkdir(parents=True)
    monkeypatch.setattr(catalog, "user_chat_requests_dir", lambda: empty_user)
    monkeypatch.setattr("zeus_client.constants.user_chat_requests_dir", lambda: empty_user)
    assert chat_request_path("v2", "analytics") is None


def test_list_chat_requests_subdir_default_stem(patch_paths):
    sub = patch_paths["chat_req_dir"] / "src_test"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "chat_request_v2.json").write_text("{}", encoding="utf-8")
    entries = [e for e in list_chat_requests() if e["source"] == "src_test"]
    assert ("src_test/chat_request_v2.json", "default", "src_test") in {
        (e["file"], e["mode"], e["source"]) for e in entries
    }


def test_extract_scope_brief_from_messages_and_instructions():
    from_messages = {"messages": [{"content": f"intro\n\n{BRIEF}"}]}
    assert extract_scope_brief(from_messages).startswith("## SCOPE BRIEF")

    from_instr = {
        "messages": [{"content": ""}],
        "instructions": {"system_prompt": f"rules\n{BRIEF}"},
    }
    assert "beer-sample/_default" in extract_scope_brief(from_instr)

    no_instr_dict = {"messages": [{"content": "x"}], "instructions": "bad"}
    assert extract_scope_brief(no_instr_dict) == ""

    assert extract_scope_brief({"messages": [{"content": "plain"}]}) == ""
    assert extract_scope_brief(None) == ""
    assert extract_scope_brief({"messages": "bad"}) == ""


def test_merge_scope_brief_messages_and_instructions():
    base = {
        "messages": [{"content": "BASE"}],
        "instructions": {"system_prompt": "INSTR"},
    }
    assert merge_scope_brief(base, "") is base

    merged = merge_scope_brief(base, BRIEF)
    assert BRIEF.strip() in merged["messages"][0]["content"]
    assert BRIEF.strip() in merged["instructions"]["system_prompt"]

    already = {"messages": [{"content": f"BASE\n{BRIEF}"}]}
    out = merge_scope_brief(already, "extra brief")
    assert out["messages"][0]["content"].count("## SCOPE BRIEF") == 1

    mini = {"messages": [{"content": "BASE\n## MINI-SCHEMA\nx"}]}
    assert "## MINI-SCHEMA" in merge_scope_brief(mini, BRIEF)["messages"][0]["content"]
    assert "extra" not in merge_scope_brief(mini, "extra brief")["messages"][0]["content"]

    instr_only = {"instructions": {"system_prompt": "SYS"}}
    merged_instr = merge_scope_brief(instr_only, BRIEF)
    assert BRIEF.strip() in merged_instr["instructions"]["system_prompt"]
    assert merged_instr["instructions"]["system_prompt"].startswith("SYS")

    skip_instr = {"instructions": {"system_prompt": f"SYS\n{BRIEF}"}}
    assert (
        merge_scope_brief(skip_instr, "more")["instructions"]["system_prompt"].count(
            "## SCOPE BRIEF",
        )
        == 1
    )

    empty_sp = {"messages": [{"content": "BASE"}], "instructions": {"system_prompt": ""}}
    assert merge_scope_brief(empty_sp, BRIEF)["instructions"]["system_prompt"] == ""

    non_dict_instr = {"messages": [{"content": "BASE"}], "instructions": "legacy"}
    merged_nd = merge_scope_brief(non_dict_instr, BRIEF)
    assert BRIEF.strip() in merged_nd["messages"][0]["content"]


def test_tools_from_chat_request():
    assert tools_from_chat_request({}) == []
    assert tools_from_chat_request("bad") == []
    assert tools_from_chat_request({"tools": [{"name": "a"}]}) == [{"name": "a"}]
    verbs = [{"name": "find"}]
    assert tools_from_chat_request({"verbs": verbs}) == verbs
    assert tools_from_chat_request({"tools": [{"name": "t"}], "verbs": verbs}) == [{"name": "t"}]


def test_normalize_chat_request_shape_branches():
    assert _normalize_chat_request_shape("not-a-dict") == "not-a-dict"
    plain = {"messages": [], "tools": []}
    assert _normalize_chat_request_shape(plain) is plain

    doc = {
        "verbs": [{"name": "find"}],
        "instructions": {"system_prompt": "x"},
        "messages": [],
    }
    out = _normalize_chat_request_shape(doc)
    assert "tools" not in out
    assert out["_instructions"] == doc["instructions"]
    assert tools_from_chat_request(out) == doc["verbs"]

    already = dict(doc)
    already["_instructions"] = {"keep": True}
    out2 = _normalize_chat_request_shape(already)
    assert out2["_instructions"] == {"keep": True}


# ── async catalog loading ──────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_load_live_chat_request_without_scope(patch_paths, http_client):
    route = respx.get(f"{ZEUS_URL}/v1/ai/chat_request.json")
    route.mock(return_value=httpx.Response(200, json={"messages": []}))
    await load_live_chat_request(ZEUS_URL, "auto", None, None, {})
    assert "scope" not in route.calls.last.request.url.params


@pytest.mark.asyncio
@respx.mock
async def test_load_live_chat_request(patch_paths, http_client):
    route = respx.get(f"{ZEUS_URL}/v1/ai/chat_request.json")
    route.mock(return_value=httpx.Response(200, json={"messages": []}))
    doc = await load_live_chat_request(ZEUS_URL, "analytics", BUCKET, SCOPE, {})
    assert doc == {"messages": []}
    assert route.calls.last.request.url.params["scope"] == f"{BUCKET}/{SCOPE}"

    route.mock(return_value=httpx.Response(500, text="fail"))
    with pytest.raises(RuntimeError, match="HTTP 500"):
        await load_live_chat_request(ZEUS_URL, "analytics", BUCKET, SCOPE, {})


@pytest.mark.asyncio
@respx.mock
async def test_load_chat_request_merges_live_brief(patch_paths, http_client):
    d = patch_paths["chat_req_dir"]
    minimal = {
        "messages": [{"role": "system", "content": "BASE RULES"}],
        "tools": [],
    }
    (d / "chat_request_merge_v2.json").write_text(json.dumps(minimal), encoding="utf-8")

    live = {"messages": [{"content": f"live\n{BRIEF}"}]}
    respx.get(f"{ZEUS_URL}/v1/ai/chat_request.json").mock(
        return_value=httpx.Response(200, json=live),
    )
    cat, src = await load_chat_request(
        ZEUS_URL,
        "v2",
        "merge",
        BUCKET,
        SCOPE,
        {},
    )
    assert "## SCOPE BRIEF" in cat["messages"][0]["content"]
    assert "live scope brief" in src


@pytest.mark.asyncio
@respx.mock
async def test_load_chat_request_no_brief_and_missing_file(patch_paths, http_client, monkeypatch):
    respx.get(f"{ZEUS_URL}/v1/ai/chat_request.json").mock(
        return_value=httpx.Response(200, json={"messages": [{"content": "no brief"}]}),
    )
    cat, src = await load_chat_request(
        ZEUS_URL,
        "v2",
        "analytics",
        BUCKET,
        SCOPE,
        {},
    )
    assert "bundled" in src
    assert "live response had no SCOPE BRIEF" in src or "bundled" in src

    empty_root = patch_paths["chat_req_dir"].parent / "empty_for_load"
    empty_root.mkdir(parents=True)
    monkeypatch.setattr(catalog, "CHAT_REQ_DIR", empty_root)
    monkeypatch.setattr("zeus_client.constants.CHAT_REQ_DIR", empty_root)
    empty_user = patch_paths["user_chat_req_dir"].parent / "empty_user_for_load"
    empty_user.mkdir(parents=True)
    monkeypatch.setattr(catalog, "user_chat_requests_dir", lambda: empty_user)
    monkeypatch.setattr("zeus_client.constants.user_chat_requests_dir", lambda: empty_user)

    respx.get(f"{ZEUS_URL}/v1/ai/chat_request.json").mock(
        side_effect=httpx.ConnectError("down"),
    )
    with pytest.raises(RuntimeError, match="no chat_request"):
        await load_chat_request(ZEUS_URL, "v2", "analytics", BUCKET, SCOPE, {})


@pytest.mark.asyncio
@respx.mock
async def test_load_chat_request_normalizes_verbs_shape(patch_paths, http_client):
    d = patch_paths["chat_req_dir"]
    shaped = {
        "verbs": [{"name": "find"}],
        "instructions": {"system_prompt": "sys"},
        "messages": [{"role": "system", "content": "base"}],
    }
    path = d / "chat_request_shaped_v2.json"
    path.write_text(json.dumps(shaped), encoding="utf-8")

    respx.get(f"{ZEUS_URL}/v1/ai/chat_request.json").mock(
        side_effect=httpx.ConnectError("down"),
    )
    cat, _ = await load_chat_request(ZEUS_URL, "v2", "shaped", BUCKET, SCOPE, {})
    assert "tools" not in cat
    assert cat["verbs"] == shaped["verbs"]
    assert tools_from_chat_request(cat) == shaped["verbs"]


@pytest.mark.asyncio
@respx.mock
async def test_load_chat_request_preserves_stamped_hash(patch_paths, http_client):
    """Loaded catalog must not gain hash-affecting fields (e.g. tools duplicate of verbs)."""
    respx.get(f"{ZEUS_URL}/v1/ai/chat_request.json").mock(
        side_effect=httpx.ConnectError("down"),
    )
    cat, _ = await load_chat_request(ZEUS_URL, "v2", "analytics", BUCKET, SCOPE, {})
    embedded = extract_stamped_hash(cat)
    computed = compute_contract_hash(cat)
    assert embedded
    assert embedded == computed


@pytest.mark.asyncio
@respx.mock
async def test_load_chat_request_live_fetch_fails(patch_paths, http_client):
    respx.get(f"{ZEUS_URL}/v1/ai/chat_request.json").mock(
        side_effect=httpx.ConnectError("down"),
    )
    cat, src = await load_chat_request(
        ZEUS_URL,
        "v2",
        "analytics",
        BUCKET,
        SCOPE,
        {},
    )
    assert "bundled" in src
    assert "down" in src
