"""Contract binding resolution from config."""
from zeus_client.logging_setup import logger

def resolve_contract_for_scope(zcfg, bucket, scope, mode=None):
    """Return (contract_id, contract_hash) for this scope (optionally mode-specific).
    Supports:
      zeus.scope_contracts["bucket/scope"] = {"contract_id":.., "contract_hash":..}   # default for scope
      zeus.scope_contracts["bucket/scope"] = {"analytics": {"contract_id":.., ...}, ...}  # per-mode
      or flat zeus.contract_id / contract_hash as last resort.
    Per-mode takes precedence over scope default. Empty strings mean 'no contract'.
    """
    if not zcfg:
        logger.debug("resolve_contract_for_scope: no zcfg -> empty")
        return "", ""
    key = f"{bucket}/{scope}"
    sc = (zcfg.get("scope_contracts") or {}).get(key) or {}
    if isinstance(sc, dict):
        # mode-specific override?
        if mode and mode in sc and isinstance(sc[mode], dict):
            m = sc[mode]
            cid = (m.get("contract_id") or "").strip()
            ch = (m.get("contract_hash") or "").strip()
            if cid or ch:
                logger.debug(f"resolve_contract_for_scope: per-mode hit {key}/{mode} cid={cid} hash={(ch or '')[:12]}…")
                return cid, ch
        # scope-level default
        cid = (sc.get("contract_id") or "").strip()
        ch = (sc.get("contract_hash") or "").strip()
        if cid or ch:
            logger.debug(f"resolve_contract_for_scope: scope default {key} cid={cid} hash={(ch or '')[:12]}…")
            return cid, ch
    # final flat fallback
    cid = (zcfg.get("contract_id") or "").strip()
    ch = (zcfg.get("contract_hash") or "").strip()
    if cid or ch:
        logger.debug(f"resolve_contract_for_scope: flat fallback cid={cid} hash={(ch or '')[:12]}…")
    return cid, ch
