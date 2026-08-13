"""Prompt inject is hash-excluded when spliced after SCOPE BRIEF."""

from zeus_client.agent.prompt_inject import apply_control_plane_inject
from zeus_client.agent.settings import prepare_settings
from zeus_client.contract_hash import compute_contract_hash


def _catalog_with_brief():
    return {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a helpful agent.\n\n"
                    "## SCOPE BRIEF\n"
                    "bucket=beer scope=_default\n\n"
                    "## MINI-SCHEMA\n"
                    "Beer: name, abv\n"
                ),
            }
        ],
        "verbs": [{"function": {"name": "find", "parameters": {}}}],
        "contract": {"hash": "md5:placeholder"},
    }


def test_inject_keeps_contract_hash_stable():
    chat = _catalog_with_brief()
    before = compute_contract_hash(chat)
    settings = prepare_settings(
        {
            "company_context": "We are a craft beer marketplace.",
            "rules": {"seasonal": "Prefer seasonal beers when asked."},
            "output_request": {
                "app": {
                    "fields": {
                        "offer_code": {"type": "string", "description": "Promo if any"},
                    }
                },
            },
            "locale": "en-US",
            "channel": "web",
        }
    )
    after_doc = apply_control_plane_inject(chat, settings)
    after = compute_contract_hash(after_doc)
    assert before == after
    content = after_doc["messages"][0]["content"]
    assert "## Company context" in content
    assert "## Rules" in content
    assert "seasonal" in content
    assert "## Output request" in content
    assert "offer_code" in content


def test_inject_noop_without_brief_marker():
    chat = {
        "messages": [{"role": "system", "content": "plain system only"}],
    }
    settings = prepare_settings({"company_context": "Brand X"})
    out = apply_control_plane_inject(chat, settings)
    assert out["messages"][0]["content"] == "plain system only"
