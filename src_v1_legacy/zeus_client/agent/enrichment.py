"""Amplify tool results so the LLM sees loud recall/ID guidance."""
import json

from zeus_client.logging_setup import logger


def amplify_tool_content(name: str, tstatus: int, ttext: str, ai_content: str) -> str:
    """Prepend problem/hint notes to tool content for search/find/get."""
    if name == "search":
        try:
            pr = json.loads(ttext) if ttext else {}
        except Exception:
            pr = {}
        is_problem = (tstatus != 200) or bool(pr.get("error")) or \
                     (isinstance(pr.get("result"), dict) and int(pr["result"].get("returned_count", 1)) == 0)
        hints = pr.get("input_hints") or []
        sugs = []
        for h in hints:
            if isinstance(h, dict):
                for k in ("suggested", "message", "code"):
                    if h.get(k):
                        sugs.append(str(h[k]))
        if is_problem or sugs:
            note = "[ZEUS RECALL NOTE: search status={} {} . hints: {} . ACTION (per verb priority + recovery rules): STOP further search calls for this question; use find (entity list) + get (hydrate body/desc) immediately instead. Copy a suggested fts only as absolute last resort.]".format(
                tstatus, "error/timeout/zero" if is_problem else "low-recall", " | ".join(sugs) if sugs else "none"
            )
            ai_content = note + "\n" + ai_content
            logger.debug(f"run_agent: amplified search problem/hint note for next LLM decision (name={name} status={tstatus} sugs={len(sugs)})")

    if name == "find":
        try:
            pr = json.loads(ttext) if ttext else {}
        except Exception:
            pr = {}
        items = (pr.get("result") or {}).get("items") or []
        good_ids = [it.get("id") for it in items if isinstance(it, dict) and it.get("id")]
        if good_ids:
            ids_list = json.dumps(good_ids)
            id_note = f"USE THESE IDS FOR ALL FOLLOW-UP get / project / traverse CALLS (copy exactly): {ids_list}\n(These are the 'id' fields from the find items below. NEVER use doc_key, source, or top-level node_ids for get — they will fail with missing_node_ids.)\n"
            ai_content = id_note + ai_content
            logger.debug(f"run_agent: amplified find ID guidance with USE THESE IDS list: {ids_list}")
    elif name == "get":
        try:
            pr = json.loads(ttext) if ttext else {}
        except Exception:
            pr = {}
        if (pr.get("status") == "partial" or (pr.get("result") or {}).get("returned_count", 1) == 0 or (pr.get("result") or {}).get("missing_node_ids")):
            missing = (pr.get("result") or {}).get("missing_node_ids") or []
            get_note = f"[ZEUS GET ID CORRECTION: You passed wrong IDs (got missing/partial for {missing or 'the ids'}). Go back to the prior find result and use the exact 'id' fields (the n_... ones) from its items — the amplification on that find result listed them as 'USE THESE IDS'. Retry get with those correct node ids only.]"
            ai_content = get_note + "\n" + ai_content
            logger.debug(f"run_agent: amplified get ID correction note (missing={missing})")

    return ai_content