"""Durable session handle (server-minted id; client never invents session_id)."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["SessionHandle"]


@dataclass(frozen=True, slots=True)
class SessionHandle:
    """Frozen handle for Zeus durable session state across turns."""

    session_id: str
    round: int
    chat_id: str = ""
    contract_id: str = ""
    contract_hash: str = ""
    contract_status: str = "none"
    created: bool = False
    rehydrated: bool = False
    recovered_from: str = ""
    enabled: bool = True
    create_req_id: str | None = None
    error: str | None = None

    def with_updates(self, **kwargs: object) -> SessionHandle:
        """Return a copy with selected fields replaced."""
        data = {
            "session_id": self.session_id,
            "round": self.round,
            "chat_id": self.chat_id,
            "contract_id": self.contract_id,
            "contract_hash": self.contract_hash,
            "contract_status": self.contract_status,
            "created": self.created,
            "rehydrated": self.rehydrated,
            "recovered_from": self.recovered_from,
            "enabled": self.enabled,
            "create_req_id": self.create_req_id,
            "error": self.error,
        }
        data.update(kwargs)
        return SessionHandle(**data)  # type: ignore[arg-type]
