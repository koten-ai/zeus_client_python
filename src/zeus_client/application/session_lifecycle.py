"""Session lifecycle use-case — create / rehydrate / dead-sid recovery / commit turn.

Server mints session ids. Dead/expired sid → recreate same turn (no 404 on commit).
Multi-hop session-trace aggregate is ZCP-15; this module posts continue_turn and
optional single-req trace helpers only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from zeus_client.adapters.zeus_http.headers import (
    TRACE_CLASS_SESSION,
    correlation_headers,
    merge_headers,
)
from zeus_client.adapters.zeus_http.session import HttpxSessionClient
from zeus_client.config.models import DataTarget
from zeus_client.domain.contract import (
    compute_contract_hash,
    extract_stamped_hash,
    resolve_session_contract_hash,
)
from zeus_client.domain.session import SessionHandle
from zeus_client.observability.logging import get_family_logger

__all__ = [
    "SessionLifecycle",
    "CommitResult",
    "contract_status_from_rehydrate",
]


def contract_status_from_rehydrate(
    contract_id: str,
    session_hash: str,
    reh: Mapping[str, Any] | None,
) -> str:
    """Derive contract_status after successful GET /v2/session rehydrate.

    SessionDoc omits contract_status; compare frozen head hash to bind hash.
    """
    reh = reh if isinstance(reh, Mapping) else {}
    reh_hash = str(reh.get("hash") or "").strip()
    reh_cid = str(reh.get("contract_id") or "").strip()
    cid = str(contract_id or "").strip()
    want_h = str(session_hash or "").strip()

    if not cid and not reh_cid:
        return "none"
    if want_h and reh_hash:
        return "match" if want_h == reh_hash else "drift"
    # Binding present but incomplete hash material — prefer match (V1 oracle).
    if cid or reh_cid:
        return "match"
    return "none"


@dataclass(frozen=True, slots=True)
class CommitResult:
    ok: bool
    handle: SessionHandle
    turn_req_id: str | None = None
    error: str | None = None


def _session_hop_headers(
    *,
    chat_id: str = "",
    turn_id: str = "",
    force_trace: bool = False,
    extra: Mapping[str, str] | None = None,
    chat_session_id: str = "",
    brief_sha12: str = "",
    mini_sha12: str = "",
) -> dict[str, str]:
    """Correlation for /v2/session* hops. Caller keys win. No Call-Id / Req-Id."""
    base = correlation_headers(
        chat_id=chat_id,
        turn_id=turn_id,
        force_trace=force_trace,
        trace_class=TRACE_CLASS_SESSION,
        chat_session_id=chat_session_id,
        brief_sha12=brief_sha12,
        mini_sha12=mini_sha12,
    )
    return merge_headers(base, extra)


@dataclass
class SessionLifecycle:
    """Setup + commit durable sessions over :class:`HttpxSessionClient`."""

    client: HttpxSessionClient
    target: DataTarget | None = None

    async def setup(
        self,
        *,
        chat_request: Mapping[str, Any],
        user_message: str,
        prior: SessionHandle | None = None,
        contract_id: str = "",
        bound_contract_hash: str = "",
        mode: str = "analytics",
        chat_id: str = "",
        enable_sessions: bool = True,
        headers: Mapping[str, str] | None = None,
        turn_id: str = "",
        force_trace: bool = False,
        rewind: bool = False,
        brief_sha12: str = "",
        mini_sha12: str = "",
    ) -> SessionHandle:
        """Create or rehydrate a session; dead sid → recreate same turn."""
        chat_req = dict(chat_request or {})
        cid = (contract_id or "").strip()
        stamped = extract_stamped_hash(chat_req)
        try:
            payload_h = compute_contract_hash(chat_req) if chat_req else ""
        except Exception:
            payload_h = ""
        choice = resolve_session_contract_hash(bound_contract_hash, stamped, payload_h)
        session_hash = choice.hash
        prior_sid = ((prior.session_id if prior else "") or "").strip()
        hop_headers = _session_hop_headers(
            chat_id=chat_id,
            turn_id=turn_id,
            force_trace=force_trace,
            extra=headers,
            chat_session_id=prior_sid,
            brief_sha12=brief_sha12,
            mini_sha12=mini_sha12,
        )

        if not enable_sessions:
            return SessionHandle(
                session_id="",
                round=1,
                chat_id=chat_id,
                contract_id=cid,
                contract_hash=session_hash,
                contract_status="none" if not cid else "match",
                enabled=False,
                mode=mode,
            )

        prior_mode = ((prior.mode if prior else "") or "").strip()
        if prior_sid and prior_mode and prior_mode != (mode or "").strip():
            # Mode switch = new session (CHECKLIST B).
            return await self._create(
                chat_req=chat_req,
                user_message=user_message,
                contract_id=cid,
                contract_hash=session_hash,
                mode=mode,
                chat_id=chat_id or (prior.chat_id if prior else ""),
                headers=hop_headers,
                recovered_from="",
                rewind=rewind,
            )

        if prior_sid:
            reh = await self.client.rehydrate(
                prior_sid,
                rounds=6,
                headers=hop_headers,
                mode=mode,
                target=self.target,
            )
            if reh and isinstance(reh, dict):
                reh_round = int(reh.get("round") or (prior.round if prior else 0) or 0)
                this_round = reh_round + 1 if reh_round > 0 else 1
                cst = contract_status_from_rehydrate(cid, session_hash, reh)
                get_family_logger().info(
                    "zeus_client.session.rehydrated",
                    **{
                        "session.id": prior_sid,
                        "req_id": reh.get("_req_id") or getattr(self.client, "last_req_id", None),
                        "zeus.round": this_round,
                        "contract_status": cst,
                        "result": "ok",
                    },
                )
                return SessionHandle(
                    session_id=prior_sid,
                    round=this_round,
                    chat_id=chat_id or (prior.chat_id if prior else ""),
                    contract_id=cid,
                    contract_hash=session_hash,
                    contract_status=cst,
                    created=False,
                    rehydrated=True,
                    enabled=True,
                    mode=mode,
                )
            # Dead/expired sid → same-turn recreate
            return await self._create(
                chat_req=chat_req,
                user_message=user_message,
                contract_id=cid,
                contract_hash=session_hash,
                mode=mode,
                chat_id=chat_id or (prior.chat_id if prior else ""),
                headers=hop_headers,
                recovered_from=prior_sid,
                rewind=rewind,
            )

        return await self._create(
            chat_req=chat_req,
            user_message=user_message,
            contract_id=cid,
            contract_hash=session_hash,
            mode=mode,
            chat_id=chat_id,
            headers=hop_headers,
            rewind=rewind,
        )

    async def _create(
        self,
        *,
        chat_req: dict[str, Any],
        user_message: str,
        contract_id: str,
        contract_hash: str,
        mode: str,
        chat_id: str,
        headers: Mapping[str, str] | None,
        recovered_from: str = "",
        rewind: bool = False,
    ) -> SessionHandle:
        init_conv = [{"role": "user", "content": user_message}] if user_message else []
        result = await self.client.create(
            contract_id=contract_id,
            contract_hash=contract_hash,
            chat_request=chat_req,
            conversation=init_conv,
            headers=headers,
            mode=mode,
            target=self.target,
            rewind=rewind,
        )
        if result.ok and isinstance(result.body, Mapping):
            body = result.body
            sid = str(body.get("session_id") or "")
            rnd = int(body.get("round") or 1)
            # Wire may say "ok"; normalize to match/none vocabulary for handle.
            raw_cst = str(body.get("contract_status") or "none")
            cst = "match" if raw_cst in ("ok", "match") else raw_cst
            log = get_family_logger()
            log.info(
                "zeus_client.session.created",
                **{
                    "session.id": sid,
                    "req_id": result.req_id,
                    "scope": f"{self.target.bucket}/{self.target.scope}" if self.target else "",
                    "zeus.url": (self.client.endpoint.url or "").rstrip("/"),
                    "contract_status": cst,
                    "result": "ok",
                },
            )
            return SessionHandle(
                session_id=sid,
                round=rnd,
                chat_id=chat_id,
                contract_id=contract_id,
                contract_hash=contract_hash,
                contract_status=cst,
                created=True,
                rehydrated=False,
                recovered_from=recovered_from,
                enabled=True,
                create_req_id=result.req_id,
                mode=mode,
            )
        err = result.error or (
            str(result.body)[:300] if result.body else f"HTTP {result.status_code}"
        )
        get_family_logger().error(
            "zeus_client.session.failed",
            **{
                "req_id": result.req_id,
                "http.status_code": result.status_code,
                "error.message": err,
                "result": "error",
            },
        )
        return SessionHandle(
            session_id="",
            round=1,
            chat_id=chat_id,
            contract_id=contract_id,
            contract_hash=contract_hash,
            contract_status="none",
            created=False,
            recovered_from=recovered_from,
            enabled=True,
            create_req_id=result.req_id,
            error=err,
            mode=mode,
        )

    async def commit(
        self,
        handle: SessionHandle,
        *,
        chat_request: Mapping[str, Any],
        produced_delta: Sequence[Mapping[str, Any]],
        mode: str = "analytics",
        headers: Mapping[str, str] | None = None,
        turn_id: str = "",
        force_trace: bool = False,
        rewind: bool = False,
        brief_sha12: str = "",
        mini_sha12: str = "",
    ) -> CommitResult:
        """POST ``/v2/session/{id}/turn`` for this user question's delta.

        Just-created sessions: round = create_round+1 and user message is
        stripped from new_turns (already on the create head).
        """
        if not handle.enabled or not handle.session_id:
            return CommitResult(ok=True, handle=handle)

        just_created = bool(handle.created)
        if just_created:
            turn_round = int(handle.round) + 1
            turn_turns = [m for m in produced_delta if (m.get("role") or "") != "user"]
        else:
            turn_round = int(handle.round)
            turn_turns = list(produced_delta)

        if not turn_turns:
            return CommitResult(
                ok=True,
                handle=handle.with_updates(round=turn_round, created=False),
            )

        result = await self.client.continue_turn(
            session_id=handle.session_id,
            client_round=turn_round,
            chat_request=chat_request,
            new_turns=turn_turns,
            headers=_session_hop_headers(
                chat_id=handle.chat_id,
                turn_id=turn_id,
                force_trace=force_trace,
                extra=headers,
                chat_session_id=handle.session_id or "",
                brief_sha12=brief_sha12,
                mini_sha12=mini_sha12,
            ),
            mode=mode,
            target=self.target,
            rewind=rewind,
        )
        if result.ok:
            get_family_logger().info(
                "zeus_client.session.committed",
                **{
                    "session.id": handle.session_id,
                    "round": turn_round,
                    "req_id": result.req_id,
                    "result": "ok",
                },
            )
            return CommitResult(
                ok=True,
                handle=handle.with_updates(
                    round=turn_round,
                    created=False,
                    rehydrated=False,
                    error=None,
                ),
                turn_req_id=result.req_id,
            )
        err = result.error or str(result.body)[:300]
        get_family_logger().error(
            "zeus_client.session.failed",
            **{
                "session.id": handle.session_id,
                "req_id": result.req_id,
                "error.message": err,
                "result": "error",
            },
        )
        return CommitResult(
            ok=False,
            handle=handle.with_updates(error=err),
            turn_req_id=result.req_id,
            error=err,
        )
