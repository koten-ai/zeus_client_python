"""Chat request catalog discovery and loading."""
import asyncio
import json
import re
from copy import deepcopy
from pathlib import Path

import httpx

from zeus_client.contract_hash import extract_stamped_hash
from zeus_client.constants import (
    AUTH_TIMEOUT,
    bundled_chat_requests_dir,
    chat_request_search_dirs,
    scope_key_from_subdir,
    user_chat_requests_dir,
)
from zeus_client.http_client import client
from zeus_client.logging_setup import logger

_MANIFEST_NAME = "manifest.json"


def _mode_from_filename(name: str) -> str:
    stem = Path(name).stem
    if stem in ("chat_request", "chat_request_v2"):
        return "default"
    if stem.startswith("chat_request_"):
        mode = stem[len("chat_request_"):]
        if mode.endswith("_v2"):
            mode = mode[:-3]
        return mode
    return stem


def _subdir_source_name(root: Path, sub: Path) -> str:
    if root == user_chat_requests_dir():
        scope_key = scope_key_from_subdir(sub.name)
        if scope_key:
            return scope_key
    return sub.name


def _catalog_entries_from_dir(d: Path, origin: str) -> list[dict]:
    out: list[dict] = []
    if not d.is_dir():
        return out

    for p in sorted(d.glob("*.json")):
        if p.name == _MANIFEST_NAME:
            continue
        out.append({
            "api_version": "v2",
            "mode": _mode_from_filename(p.name),
            "file": p.name,
            "source": "general",
            "origin": origin,
        })

    for sub in sorted(x for x in d.iterdir() if x.is_dir()):
        src = _subdir_source_name(d, sub)
        for p in sorted(sub.glob("*.json")):
            if p.name == _MANIFEST_NAME:
                continue
            rel = f"{sub.name}/{p.name}"
            out.append({
                "api_version": "v2",
                "mode": _mode_from_filename(p.name),
                "file": rel,
                "source": src,
                "origin": origin,
            })
    return out


def list_chat_requests():
    """Discover user-synced and bundled chat_request catalogs."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for origin, d in (
        ("synced", user_chat_requests_dir()),
        ("bundled", bundled_chat_requests_dir()),
    ):
        for entry in _catalog_entries_from_dir(d, origin):
            key = (entry["file"], entry["mode"])
            if key in seen:
                continue
            seen.add(key)
            out.append(entry)
    return out


def chat_request_path(api_version, mode, bucket=None, scope=None):
    """Resolve chat_request path (api_version kept for callers)."""
    del api_version
    dirs = chat_request_search_dirs(bucket, scope)
    if not dirs:
        dirs = [bundled_chat_requests_dir()]

    if mode in (None, "", "default"):
        for d in dirs:
            p = d / "chat_request_v2.json"
            if p.exists():
                return p

    candidate = f"chat_request_{mode}_v2.json"
    for d in dirs:
        for p in d.rglob("*.json"):
            if p.name == _MANIFEST_NAME:
                continue
            if p.name == candidate or (mode == "default" and p.name == "chat_request_v2.json"):
                return p

    for d in dirs:
        p = d / "chat_request_v2.json"
        if p.exists():
            return p
    return None


# ── chat_request loading ──────────────────────────────────────────
def extract_scope_brief(chat_req):
    """Pull the live ## SCOPE BRIEF suffix out of a chat_request system prompt.

    For standardized v4 shape, also check instructions.system_prompt as a fallback
    (the assembler and some paths may store it there after normalization).
    """
    try:
        # Prefer messages[0] (common case)
        content = (chat_req.get("messages") or [{}])[0].get("content") or ""
        marker = "## SCOPE BRIEF"
        idx = content.find(marker)
        if idx >= 0:
            return content[idx:].strip()
        # Try instructions.system_prompt for v4 standardized shape
        instr = chat_req.get("instructions") or {}
        if isinstance(instr, dict):
            sp = instr.get("system_prompt") or ""
            idx = sp.find(marker)
            if idx >= 0:
                return sp[idx:].strip()
    except Exception:
        pass
    return ""


def merge_scope_brief(chat_req, brief):
    """Append a live scope brief to a bundled catalog's system message.

    For standardized 5TH/v4 shape (with top-level "instructions"), also keep
    instructions.system_prompt in sync so that MINI-SCHEMA / SCOPE BRIEF is
    visible no matter which copy the assembler or downstream code reads.

    Hash note: strip-for-hash truncates at ``## SCOPE BRIEF`` / ``## MINI-SCHEMA``
    and rstrips the remaining prefix. Catalog system prompts should therefore
    not carry trailing whitespace, or the no-brief stamp will disagree with the
    post-merge hash Zeus computes on session create (409 contract_mismatch).
    """
    if not brief:
        return chat_req
    out = deepcopy(chat_req)
    messages = out.get("messages") or []
    if messages:
        current = messages[0].get("content") or ""
        if "## SCOPE BRIEF" not in current and "## MINI-SCHEMA" not in current:
            # rstrip base so post-strip hash matches a no-brief stamp of the
            # same rules text (server strip also TrimsRight whitespace).
            messages[0]["content"] = current.rstrip(" \t\n\r") + "\n\n" + brief.strip()
    # Standardized v4 shape support: also inject into instructions.system_prompt
    instr = out.get("instructions") or {}
    if isinstance(instr, dict):
        sp = instr.get("system_prompt") or ""
        if sp and "## SCOPE BRIEF" not in sp and "## MINI-SCHEMA" not in sp:
            instr["system_prompt"] = sp.rstrip(" \t\n\r") + "\n\n" + brief.strip()
            out["instructions"] = instr
    return out


# ---------------------------------------------------------------------------
# Mini-schema introspection + structured middle-man injection
#
# The runtime ## SCOPE BRIEF carries a ## MINI-SCHEMA block (per entity_type
# fields, FK pointers, example values) generated by the Zeus server from the
# scope's EntityMap. A middle-man operator wants to SEE that vocabulary before
# authoring a business-rule injection so the rule references REAL entity_types
# and fields (e.g. "for Beer, don't process beers from California with abv>7%")
# instead of guessing field names.
#
# get_mini_schema() parses that block into a structured dict. The reserved
# injection slot is guidance.injections.business_logic (advisory; excluded
# from the contract hash). inject_business_logic() writes grounded rules there,
# validating their entity_type/field references against the mini-schema, and
# apply_injected_business_logic() renders them into the system prompt AFTER the
# scope brief so they reach the LLM without changing the contract hash (the
# server + client _strip_scope_brief truncate everything after the brief
# marker before hashing).
# ---------------------------------------------------------------------------

_MINI_HEADER_RE = re.compile(r"^###\s+(?P<ent>.+?)\s+\(fields:\s*(?P<n>\d+)\)\s*$")
_MINI_FIELD_RE = re.compile(
    r"^\s+-\s+(?P<path>\S+)\s+(?P<kind>\S+)\s+\[(?P<idx>[^\]]+)\]"
    r"(?:\s+(?P<trailer>.*\S))?\s*$"
)
_MINI_INVERSE_RE = re.compile(
    r"^\s+\u2190\s+(?P<token>\S+)\s+\((?P<kind>[^)]+)\)\s+--\s+(?P<recipe>.*\S)?\s*$"
)
_FK_TO_RE = re.compile(r"fk_to=(\S+)")
_VIA_RE = re.compile(r"via=(\S+)")
_EX_RE = re.compile(r"ex:\s*(.+)$")

# Kinds that cannot be used in a `where` equality predicate (display rows are
# result-only; text_fts rows need fts/hybrid search instead of equality).
_NON_FILTERABLE_KINDS = {"display", "text_fts"}

# Heading used for the injected business-rules section. Matches the default
# guidance.assembler_hints.merge_business_logic_into in the standardized
# chat_request*.json so server and client agree on the section name.
INJECTED_BUSINESS_RULES_HEADING = "Additional Business Rules (injected by middle-man)"


def _system_prompt_text(chat_req):
    """Return the system-prompt text that carries the SCOPE BRIEF / MINI-SCHEMA.

    Prefers messages[0].content (the live, brief-merged copy); falls back to
    the standardized instructions.system_prompt.
    """
    content = ""
    try:
        content = (chat_req.get("messages") or [{}])[0].get("content") or ""
    except Exception:
        content = ""
    if "## MINI-SCHEMA" not in content and "## SCOPE BRIEF" not in content:
        instr = chat_req.get("instructions") or {}
        if isinstance(instr, dict):
            sp = instr.get("system_prompt") or ""
            if "## MINI-SCHEMA" in sp or "## SCOPE BRIEF" in sp:
                content = sp
    return content


def get_mini_schema(chat_req, values=False):
    """Parse the runtime MINI-SCHEMA out of a chat_request's SCOPE BRIEF.

    Lets a middle-man operator see exactly which entity_types and fields the AI
    is working against before authoring an injection.

    Args:
        chat_req: a loaded chat_request dict OR a path to a chat_request*.json.
        values:   when True, include each field's `ex:` example values (the
                  stored surface forms, e.g. "United Kingdom"); when False,
                  return structure only.

    Note:
        The MINI-SCHEMA is per-scope and only present AFTER the live scope brief
        has been merged (see load_chat_request / merge_scope_brief). A bundled
        on-disk file with no brief yet returns empty `entity_types`.

    Returns:
        {
          "scope": "beer-sample/_default" | "",
          "mode":  "auto" | "",
          "entity_types": {
            "Beer": {
              "field_count": 8,
              "fields": {
                "abv": {"kind": "number", "indexed": "gsi", "filterable": True},
                "brewery_id": {"kind": "entity_fk", "indexed": "gsi",
                               "filterable": True, "fk_to": "Brewery",
                               "examples": ["coopers_brewery"]},  # if values=True
                ...
              },
              "inverse_fks": [
                {"from_entity": "Beer", "from_path": "brewery_id",
                 "kind": "entity_fk"}
              ],
            },
            ...
          },
        }
    """
    if isinstance(chat_req, (str, Path)):
        chat_req = json.loads(Path(chat_req).read_text())

    out = {"scope": "", "mode": "", "entity_types": {}}
    content = _system_prompt_text(chat_req)
    if not content:
        return out

    m = re.search(r"^scope:\s+(\S+)", content, re.MULTILINE)
    if m:
        out["scope"] = m.group(1)
    m = re.search(r"^mode:\s+(\S+)", content, re.MULTILINE)
    if m:
        out["mode"] = m.group(1)

    # Slice the MINI-SCHEMA block: from its header to the next "## " top-level
    # section (e.g. "## WALK_PATHS") or the end of the brief.
    start = content.find("## MINI-SCHEMA")
    if start < 0:
        return out
    rest = content[start:]
    nxt = re.search(r"\n##\s+(?!MINI-SCHEMA)", rest)
    block = rest[: nxt.start()] if nxt else rest

    cur = None
    in_inverse = False
    for line in block.splitlines():
        hm = _MINI_HEADER_RE.match(line)
        if hm:
            cur = hm.group("ent")
            out["entity_types"][cur] = {
                "field_count": int(hm.group("n")),
                "fields": {},
                "inverse_fks": [],
            }
            in_inverse = False
            continue
        if cur is None:
            continue
        if line.strip() == "inverse_fks:":
            in_inverse = True
            continue
        if in_inverse:
            im = _MINI_INVERSE_RE.match(line)
            if im:
                ent, _, path = im.group("token").partition(".")
                out["entity_types"][cur]["inverse_fks"].append({
                    "from_entity": ent,
                    "from_path": path,
                    "kind": im.group("kind"),
                })
            continue
        fm = _MINI_FIELD_RE.match(line)
        if fm:
            kind = fm.group("kind")
            idx = fm.group("idx")
            field = {
                "kind": kind,
                "indexed": idx,
                "filterable": kind not in _NON_FILTERABLE_KINDS and idx not in ("none", ""),
            }
            trailer = fm.group("trailer") or ""
            fk = _FK_TO_RE.search(trailer)
            if fk:
                field["fk_to"] = fk.group(1)
            via = _VIA_RE.search(trailer)
            if via:
                field["via"] = via.group(1)
            if trailer.lstrip().startswith("--"):
                field["note"] = trailer.lstrip()[2:].strip()
            if values:
                ex = _EX_RE.search(trailer)
                if ex:
                    field["examples"] = [
                        e.strip() for e in ex.group(1).split(",") if e.strip()
                    ]
            out["entity_types"][cur]["fields"][fm.group("path")] = field
    return out


# camelCase alias to match the requested call site: getMiniSchema(values=...).
getMiniSchema = get_mini_schema


def _validate_rule_against_schema(entry, schema):
    """Raise ValueError if a structured rule references an unknown entity_type
    or field. Free-form rules (no entity_type) are not checked. If no
    MINI-SCHEMA is present (brief not merged yet) validation is skipped so the
    call still works against a bundled on-disk file.
    """
    ets = (schema or {}).get("entity_types") or {}
    et = entry.get("entity_type")
    if et is None or not ets:
        return
    if et not in ets:
        raise ValueError(
            f"business rule references unknown entity_type {et!r}; "
            f"valid types: {sorted(ets)}"
        )
    known = ets[et].get("fields") or {}
    bad = [f for f in (entry.get("fields") or []) if f not in known]
    if bad:
        raise ValueError(
            f"business rule for {et!r} references unknown field(s) {bad}; "
            f"valid fields: {sorted(known)}"
        )


def inject_business_logic(chat_req, *rules, validate=True):
    """Add operator business rule(s) into the reserved injection slot
    (guidance.injections.business_logic).

    This slot is ADVISORY and excluded from the contract hash (see
    contract_hash._strip_for_hash / the v4 _hash_policy), so injecting here
    never breaks contract binding.

    Each rule may be:
      * a plain string -> stored as {"rule": "<text>"}
      * a dict         -> stored as-is. When it carries "entity_type" and/or
                          "fields" and validate=True, those references are
                          checked against the live MINI-SCHEMA so a typo'd
                          entity_type or non-existent field is caught early.

    Example:
        chat_req = inject_business_logic(chat_req, {
            "entity_type": "Beer",
            "fields": ["abv"],
            "rule": "Do not process beers from California with abv > 7%.",
        })

    Returns a deepcopy of chat_req with the rule(s) appended.
    """
    out = deepcopy(chat_req)
    bl = (
        out.setdefault("guidance", {})
        .setdefault("injections", {})
        .setdefault("business_logic", [])
    )
    schema = get_mini_schema(out, values=False) if validate else None
    for rule in rules:
        if isinstance(rule, str):
            entry = {"rule": rule}
        elif isinstance(rule, dict):
            entry = dict(rule)
            if validate:
                _validate_rule_against_schema(entry, schema)
        else:
            raise TypeError(
                f"business rule must be str or dict, got {type(rule).__name__}"
            )
        # Give every rule a stable id so both the AI's self-report and the
        # operator's deterministic audit can refer to the same rule.
        if not entry.get("id"):
            entry["id"] = f"r{len(bl) + 1}"
        bl.append(entry)
    return out


def compliance_report_enabled(chat_req):
    """Whether the AI should self-report rule compliance. Default OFF so the AI
    does less work on normal turns. Turn it on explicitly for debugging/audit:

        chat_req["guidance"]["injections"]["report_compliance"] = True

    Debug mode (guidance.debug=True) implies it on, since debug already asks the
    AI to explain itself.
    """
    guidance = chat_req.get("guidance") or {}
    flag = (guidance.get("injections") or {}).get("report_compliance")
    if flag is not None:
        return bool(flag)
    return bool(guidance.get("debug"))


def render_injected_business_logic(chat_req):
    """Render guidance.injections.business_logic into a markdown section the LLM
    can read. Returns "" when there are no injected rules. The heading matches
    guidance.assembler_hints.merge_business_logic_into when present.

    The per-rule self-report instruction is appended ONLY when
    compliance_report_enabled(chat_req) is true (default OFF).
    """
    guidance = chat_req.get("guidance") or {}
    rules = (guidance.get("injections") or {}).get("business_logic") or []
    if not rules:
        return ""
    heading = (guidance.get("assembler_hints") or {}).get(
        "merge_business_logic_into"
    ) or INJECTED_BUSINESS_RULES_HEADING
    lines = [f"## {heading}", ""]
    for i, r in enumerate(rules):
        if isinstance(r, str):
            rid = f"r{i + 1}"
            lines.append(f"- ({rid}) {r}")
        elif isinstance(r, dict):
            rid = r.get("id") or f"r{i + 1}"
            text = r.get("rule") or r.get("text") or json.dumps(r, sort_keys=True)
            et = r.get("entity_type")
            lines.append(f"- ({rid}) {f'[{et}] ' if et else ''}{text}")
    # OPTIONAL (default OFF): ask the AI to self-report what it did with each
    # rule. Off keeps the AI's output lean; on gives a human-readable
    # "I produced Z because of rule Y / I removed X" for debugging/audit.
    # (Layer 2, audit_rows_against_rules(), is unaffected by this flag — it runs
    # in operator code and costs the AI nothing, so use it any time for trust.)
    if compliance_report_enabled(chat_req):
        lines += [
            "",
            "When you produce your final answer, append a `rule_compliance` block. "
            "For EACH rule id above, state one of: `applied` (you enforced it and what "
            "you changed/removed, with counts), `not_triggered` (no matching data this "
            "turn), or `cannot_comply` (and why). Be specific, e.g. "
            "\"(r1) applied — removed 3 California beers with abv > 7%\".",
        ]
    return "\n".join(lines)


def apply_injected_business_logic(chat_req):
    """Splice the rendered business-rules section into the system prompt so the
    injected rules actually reach the LLM.

    Hash safety: the section is appended only when a ## SCOPE BRIEF / ##
    MINI-SCHEMA marker is already present, so it always lands AFTER that marker.
    Both the server and client _strip_scope_brief truncate content at the brief
    marker before hashing, so the appended rules are excluded from the contract
    hash on both sides — binding stays stable with no Go changes. (The rules
    also live in guidance.injections.business_logic, which is excluded outright.)

    Returns a deepcopy with the section spliced, or the original chat_req
    unchanged when there are no rules or no brief marker is present.
    """
    section = render_injected_business_logic(chat_req)
    if not section:
        return chat_req
    heading_line = section.splitlines()[0]
    block = "\n\n" + section
    out = deepcopy(chat_req)

    def _splice(text):
        # Only append after a brief marker so the strip-for-hash truncation
        # covers it; skip (return unchanged) otherwise to avoid hash drift.
        if not text or ("## SCOPE BRIEF" not in text and "## MINI-SCHEMA" not in text):
            return text
        if heading_line in text:
            return text
        return text.rstrip() + block

    messages = out.get("messages") or []
    if messages:
        messages[0]["content"] = _splice(messages[0].get("content") or "")
    instr = out.get("instructions")
    if isinstance(instr, dict) and instr.get("system_prompt"):
        instr["system_prompt"] = _splice(instr["system_prompt"])
    return out


# --- Deterministic compliance audit (the "trust" layer) --------------------
#
# The AI's `rule_compliance` self-report (rendered above) is the AI's WORD and
# can be wrong. To actually KNOW the output obeyed a rule, give the rule a
# machine-checkable `deny_when` predicate and run audit_rows_against_rules()
# over the rows Zeus returned (captured by the operator in a `zeus_result` /
# `final_answer` hook). This runs in YOUR code, so the AI cannot fake it.
#
# Predicate grammar for `deny_when` (a row is a VIOLATION when ALL clauses match):
#   {"state": "California"}              -> row["state"] == "California"
#   {"abv": {">": 7}}                    -> row["abv"] > 7   (also >=, <, <=, ==, !=, in)
#   {"state": "California", "abv": {">": 7}}  -> both must hold (AND)
# Use `require` for the inverse (every row MUST match; non-matching = violation).

_OPS = {
    ">": lambda a, b: a is not None and a > b,
    ">=": lambda a, b: a is not None and a >= b,
    "<": lambda a, b: a is not None and a < b,
    "<=": lambda a, b: a is not None and a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "in": lambda a, b: a in b,
}


def _clause_matches(row, field, cond):
    val = row.get(field)
    if isinstance(cond, dict):
        for op, target in cond.items():
            fn = _OPS.get(op)
            if fn is None:
                raise ValueError(f"unknown predicate op {op!r} in rule")
            try:
                if not fn(val, target):
                    return False
            except TypeError:
                return False  # type mismatch -> clause does not match
        return True
    return val == cond


def _row_matches(row, predicate):
    return all(_clause_matches(row, f, c) for f, c in predicate.items())


def audit_rows_against_rules(rows, rules):
    """Deterministically check returned rows against injected rules.

    Only rules carrying a machine-checkable `deny_when` (forbidden rows) or
    `require` (mandatory shape) predicate are audited; free-text rules are
    reported as `unverifiable` (you must check those by reading the answer or
    the AI's self-report).

    Returns a list of per-rule results:
      {"id","status": "ok"|"violation"|"unverifiable",
       "checked": N, "violations": [<row>...], "rule": "<text>"}
    """
    if isinstance(rules, dict):  # accept a whole chat_req
        rules = (rules.get("guidance", {}).get("injections", {}) or {}).get(
            "business_logic", []
        ) or []
    rows = rows or []
    out = []
    for i, r in enumerate(rules):
        if isinstance(r, str):
            r = {"rule": r}
        rid = r.get("id") or f"r{i + 1}"
        text = r.get("rule") or r.get("text") or ""
        deny = r.get("deny_when")
        req = r.get("require")
        if not deny and not req:
            out.append({"id": rid, "status": "unverifiable",
                        "checked": len(rows), "violations": [], "rule": text})
            continue
        bad = []
        for row in rows:
            if deny and _row_matches(row, deny):
                bad.append(row)
            elif req and not _row_matches(row, req):
                bad.append(row)
        out.append({
            "id": rid,
            "status": "violation" if bad else "ok",
            "checked": len(rows),
            "violations": bad,
            "rule": text,
        })
    return out


def tools_from_chat_request(chat_req: dict) -> list:
    """Return LLM tool definitions from a loaded chat_request.

    Standardized V2 catalogs carry ``verbs``; legacy shapes may use ``tools``.
    Resolve at LLM-call time only — do not copy verbs→tools during load, because
    adding ``tools`` changes the contract hash Zeus computes on /v1/session.
    """
    if not isinstance(chat_req, dict):
        return []
    return chat_req.get("tools") or chat_req.get("verbs") or []


def _normalize_chat_request_shape(doc: dict) -> dict:
    """Lightweight prep for standardized 5TH contract shape (verbs + instructions + messages).

    Preserves the stamped on-disk shape for contract hashing. Use
    ``tools_from_chat_request()`` when the agent needs tool definitions for the LLM.
    """
    if not isinstance(doc, dict):
        return doc
    if "verbs" in doc or doc.get("_format") == "zeus.chat_request.v2":
        doc = dict(doc)  # shallow copy; don't mutate the original on disk
        if "instructions" in doc and "_instructions" not in doc:
            doc["_instructions"] = doc["instructions"]
    return doc


async def load_live_chat_request(zeus_url, mode, bucket, scope, zeus_headers):
    """Fetch live scope brief from Zeus /v1/ai/chat_request.json."""
    params = {"mode": mode}
    if bucket and scope:
        params["scope"] = f"{bucket}/{scope}"
    r = await client().get(f"{zeus_url}/v1/ai/chat_request.json", params=params,
                           headers=zeus_headers, timeout=AUTH_TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.json()


def _path_origin_label(path: Path) -> str:
    user_root = user_chat_requests_dir()
    try:
        if path.is_relative_to(user_root):
            return f"synced ({path.relative_to(user_root)})"
    except ValueError:
        pass
    bundled_root = bundled_chat_requests_dir()
    try:
        if path.is_relative_to(bundled_root):
            return f"bundled ({path.relative_to(bundled_root)})"
    except ValueError:
        pass
    return f"catalog ({path.name})"


async def load_chat_request(zeus_url, api_version, mode, bucket, scope, zeus_headers):
    """Load catalog from synced user dir or bundled package; merge live brief when needed."""
    logger.debug(f"load_chat_request: api={api_version} mode={mode} sample={bucket}/{scope}")
    path = chat_request_path(api_version, mode, bucket=bucket, scope=scope)
    if not path:
        raise RuntimeError(f"no chat_request file for mode '{mode}'")

    doc = await asyncio.to_thread(lambda: json.loads(path.read_text()))
    doc = _normalize_chat_request_shape(doc)
    embedded_h = extract_stamped_hash(doc)
    has_contract = bool(embedded_h)
    logger.info(f"loaded catalog from {path.name} (has_embedded_contract={has_contract})")

    origin = _path_origin_label(path)
    if extract_scope_brief(doc):
        return doc, origin

    live_err = "not attempted"
    live_doc = None
    try:
        live_doc = await load_live_chat_request(zeus_url, mode, bucket, scope, zeus_headers)
        live_err = "borrowed live scope brief"
        logger.debug("borrowed live SCOPE BRIEF from Zeus")
    except (RuntimeError, httpx.HTTPError) as e:
        live_doc = None
        live_err = str(e)
        logger.debug(f"could not borrow live scope brief: {live_err}")

    if live_doc:
        brief = extract_scope_brief(live_doc)
        if brief:
            return merge_scope_brief(doc, brief), f"{origin} + live scope brief"
        live_err = "live response had no SCOPE BRIEF"
    return doc, f"{origin}; live: {live_err}"

def chat_request_filename(mode: str) -> str:
    """On-disk filename for a bootstrap-fetched chat_request mode."""
    m = (mode or "default").strip() or "default"
    if m == "default":
        return "chat_request_v2.json"
    return f"chat_request_{m}_v2.json"


def modes_to_bootstrap(cfg: dict, bucket: str, scope: str) -> list[str]:
    """Union of bundled general modes and scope_contracts keys for the target scope."""
    from zeus_client.config import resolve_zeus_config

    modes: set[str] = {"default"}
    scope_key = f"{bucket}/{scope}"
    entry = resolve_zeus_config(cfg)
    contracts = (entry.get("scope_contracts") or {}).get(scope_key) or {}
    for key in contracts:
        if key:
            modes.add(str(key))
    for item in list_chat_requests():
        if item.get("source") != "general":
            continue
        rel = item.get("file") or ""
        if "/" in rel:
            continue
        modes.add(item.get("mode") or "default")
    return sorted(modes, key=lambda m: (0 if m == "default" else 1, m))


async def fetch_scope_bootstrap(zeus_url: str, bucket: str, scope: str, zeus_headers: dict) -> dict:
    """GET /v1/ai/bootstrap/scope/{bucket}/{scope} — wizard primary bootstrap fetch."""
    url = f"{zeus_url.rstrip('/')}/v1/ai/bootstrap/scope/{bucket}/{scope}"
    logger.info(f"fetching scope bootstrap (url={url}) (zeus_headers={zeus_headers})")

    r = await client().get(url, headers=zeus_headers, timeout=AUTH_TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"bootstrap HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


async def fetch_scope_chat_request(
    zeus_url: str, bucket: str, scope: str, mode: str, zeus_headers: dict,
) -> dict:
    """GET /v1/ai/chat_request.json for a specific scope + mode."""
    params: dict[str, str] = {"scope": f"{bucket}/{scope}"}
    if mode and mode != "default":
        params["mode"] = mode
    logger.info(f"fetching scope chat request (url={zeus_url}, params={params})")
    r = await client().get(
        f"{zeus_url.rstrip('/')}/v1/ai/chat_request.json",
        params=params,
        headers=zeus_headers,
        timeout=AUTH_TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"chat_request HTTP {r.status_code}: {r.text[:300]}")
    return r.json()
