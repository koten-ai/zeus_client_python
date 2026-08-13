"""Constants and helper tests."""

from zeus_client.constants import (
    V2_DOCS_VERB_ORDER,
    normalize_api_version,
    v2_tool_order,
    v2_verbs_from_docs_dir,
)


def test_normalize_api_version():
    assert normalize_api_version("v2") == "v2"
    assert normalize_api_version("V2") == "v2"
    assert normalize_api_version(None) == "v1"
    assert normalize_api_version("v1") == "v1"


def test_v2_tool_order_fallback():
    order = v2_tool_order()
    assert order == list(V2_DOCS_VERB_ORDER)


def test_v2_verbs_from_docs_dir_missing(tmp_path):
    assert v2_verbs_from_docs_dir(tmp_path / "nope") is None


def test_v2_verbs_from_docs_dir_complete(tmp_path):
    for verb in (
        "describe",
        "explain",
        "get",
        "find",
        "traverse",
        "pipeline",
        "search",
        "analyze",
        "return",
    ):
        (tmp_path / f"{verb}.md").write_text("#", encoding="utf-8")
    (tmp_path / "transforms.md").write_text("#", encoding="utf-8")
    assert v2_verbs_from_docs_dir(tmp_path) == list(V2_DOCS_VERB_ORDER)


def test_v2_verbs_from_docs_dir_incomplete(tmp_path):
    (tmp_path / "describe.md").write_text("#", encoding="utf-8")
    assert v2_verbs_from_docs_dir(tmp_path) is None


def test_v2_verbs_from_docs_dir_skips_work_docs(tmp_path):
    (tmp_path / "WORK_DOCS.md").write_text("# meta", encoding="utf-8")
    for verb in (
        "describe",
        "explain",
        "get",
        "find",
        "traverse",
        "pipeline",
        "search",
        "analyze",
        "return",
    ):
        (tmp_path / f"{verb}.md").write_text("#", encoding="utf-8")
    (tmp_path / "transforms.md").write_text("#", encoding="utf-8")
    assert v2_verbs_from_docs_dir(tmp_path) == list(V2_DOCS_VERB_ORDER)
