"""Family ErrorCode taxonomy + typed ZeusClientError hierarchy (ZCM-008).

Codes follow design ``guides/api/API_ERROR_CODES.md`` (six-digit zero-padded
strings). LLM classification ``050010``–``050018`` maps rate vs quota vs context
per ``docs/ai_api/FAMILY_LLM_ERRORS.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

__all__ = [
    "ErrorCode",
    "ZeusClientError",
    "ConfigError",
    "AuthError",
    "ContractError",
    "CatalogError",
    "SessionError",
    "ZeusTransportError",
    "ZeusToolError",
    "LlmError",
    "PolicyError",
    "ValidationError",
    "InternalError",
    "JobError",
    "default_retryable",
    "public_message_for",
]


class ErrorCode(str, Enum):
    """Stable family client error codes (string values, never dotted)."""

    # --- 00 generic ---
    UNKNOWN = "000001"
    NOT_IMPLEMENTED = "000002"
    INVALID_ARGUMENT = "000003"
    PRECONDITION_FAILED = "000004"
    TIMEOUT = "000005"
    CANCELLED = "000006"
    INTERNAL_INVARIANT = "000007"
    FEATURE_DISABLED = "000008"
    CLIENT_RATE_LIMITED = "000009"
    CONTEXT_DEADLINE = "000010"

    # --- 01 config ---
    CONFIG_PATH_NOT_FOUND = "010001"
    CONFIG_NOT_READABLE = "010002"
    CONFIG_PARSE_FAILED = "010003"
    CONFIG_NORMALIZE_FAILED = "010004"
    CONFIG_INVALID = "010006"
    ZEUS_URL_MISSING = "010007"
    ZEUS_AUTH_MODE_INVALID = "010008"
    ZEUS_AUTH_INCOMPLETE = "010009"
    LLM_BASE_URL_MISSING = "010010"
    LLM_MODEL_MISSING = "010011"
    LLM_API_KEY_MISSING = "010012"

    # --- 03 catalog ---
    CATALOG_NOT_FOUND = "030001"
    CATALOG_PARSE_FAILED = "030002"
    CATALOG_LINEAGE_UNKNOWN = "030003"
    CONTRACT_HASH_MISSING = "030004"
    CONTRACT_HASH_INVENT_FORBIDDEN = "030005"
    CONTRACT_BIND_MISMATCH = "030006"
    CATALOG_SYNC_FAILED = "030007"

    # --- 04 session ---
    SESSION_CREATE_FAILED = "040001"
    SESSION_CONTINUE_FAILED = "040002"
    SESSION_REHYDRATE_FAILED = "040003"
    SESSION_ID_MISSING = "040004"
    SESSION_DURABLE_DISABLED = "040005"
    SESSION_COMMIT_FAILED = "040006"
    AGENT_MEMORY_RECALL_FAILED = "040008"
    AGENT_MEMORY_WRITE_FAILED = "040009"
    AGENT_MEMORY_UNAVAILABLE = "040010"

    # --- 05 agent / LLM ---
    AGENT_TURN_FAILED = "050001"
    AGENT_MESSAGE_EMPTY = "050002"
    AGENT_MAX_ROUNDS = "050003"
    AGENT_LLM_REQUEST_FAILED = "050004"
    AGENT_LLM_TIMEOUT = "050005"
    AGENT_TOOL_PLAN_INVALID = "050006"
    AGENT_TERMINATE_MISSING = "050007"
    AGENT_HOOKS_ABORTED = "050008"
    # Family LLM classification (prefer over generic 050004 when known)
    LLM_RATE_LIMIT = "050010"
    LLM_QUOTA_EXHAUSTED = "050011"
    LLM_AUTH = "050012"
    LLM_CONTEXT_LENGTH = "050013"
    LLM_CONTENT_FILTER = "050014"
    LLM_PROVIDER_OVERLOAD = "050015"
    LLM_PROVIDER_UNAVAILABLE = "050016"
    LLM_INVALID_REQUEST = "050017"
    LLM_TOOL_SCHEMA = "050018"

    # --- 06 zeus direct ---
    ZEUS_TRANSPORT = "060001"
    ZEUS_HTTP_4XX = "060002"
    ZEUS_HTTP_5XX = "060003"
    ZEUS_CONTRACT_REQUIRED = "060004"
    ZEUS_AUTH_FAILED = "060005"
    ZEUS_VERB_NOT_ALLOWED = "060006"
    ZEUS_SEARCH_INVALID = "060007"
    ZEUS_RESPONSE_PARSE = "060008"
    ZEUS_REQ_ID_MISSING = "060009"
    ZEUS_PIPELINE_NOT_ON_DIRECT = "060010"

    # --- 09 layer A ---
    LAYER_A_VALIDATE_FAILED = "090001"
    POLICY_REFUSE = "070002"

    # --- 10 auth cross-cutting ---
    AUTH_FAILED = "100001"
    AUTH_SESSION_UNAVAILABLE = "100002"

    # --- 13 multi-agent jobs / units ---
    JOBS_UNAVAILABLE = "130001"
    JOBS_INVALID_UNIT_MAP = "130002"
    JOBS_BUDGET_INVALID = "130003"
    JOBS_NOT_FOUND = "130004"
    JOBS_WATCH_FAILED = "130005"
    JOBS_UNIT_FAILED = "130010"
    UNITS_CATALOG_MISSING = "130011"
    UNITS_INJECT_MISSING = "130012"
    UNITS_ISOLATION = "130013"

    # --- 99 internal ---
    INTERNAL_BUG = "990001"


# Default retryability per family law (LLM: rate/overload/unavailable yes; quota/context no).
_RETRYABLE: frozenset[ErrorCode] = frozenset(
    {
        ErrorCode.TIMEOUT,
        ErrorCode.CLIENT_RATE_LIMITED,
        ErrorCode.CONTEXT_DEADLINE,
        ErrorCode.AGENT_LLM_TIMEOUT,
        ErrorCode.LLM_RATE_LIMIT,
        ErrorCode.LLM_PROVIDER_OVERLOAD,
        ErrorCode.LLM_PROVIDER_UNAVAILABLE,
        ErrorCode.ZEUS_TRANSPORT,
        ErrorCode.ZEUS_HTTP_5XX,
        ErrorCode.AUTH_SESSION_UNAVAILABLE,
        ErrorCode.AGENT_MEMORY_RECALL_FAILED,
    }
)

_PUBLIC_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.UNKNOWN: "unknown client error",
    ErrorCode.NOT_IMPLEMENTED: "not implemented in this language SDK",
    ErrorCode.INVALID_ARGUMENT: "invalid argument",
    ErrorCode.PRECONDITION_FAILED: "precondition failed",
    ErrorCode.TIMEOUT: "timeout (client-side deadline)",
    ErrorCode.CANCELLED: "cancelled",
    ErrorCode.INTERNAL_INVARIANT: "internal invariant violated",
    ErrorCode.FEATURE_DISABLED: "feature disabled by config/flag",
    ErrorCode.CLIENT_RATE_LIMITED: "rate limited (client)",
    ErrorCode.CONTEXT_DEADLINE: "context deadline exceeded",
    ErrorCode.CONFIG_PATH_NOT_FOUND: "config path not found",
    ErrorCode.CONFIG_NOT_READABLE: "config path not readable",
    ErrorCode.CONFIG_PARSE_FAILED: "config file parse failed",
    ErrorCode.CONFIG_NORMALIZE_FAILED: "config normalize failed",
    ErrorCode.CONFIG_INVALID: "config mapping invalid",
    ErrorCode.ZEUS_URL_MISSING: "zeus.url missing or empty",
    ErrorCode.ZEUS_AUTH_MODE_INVALID: "zeus.auth_mode invalid",
    ErrorCode.ZEUS_AUTH_INCOMPLETE: "zeus auth fields incomplete for auth_mode",
    ErrorCode.LLM_BASE_URL_MISSING: "llm.base_url missing (agent required)",
    ErrorCode.LLM_MODEL_MISSING: "llm.model missing (agent required)",
    ErrorCode.LLM_API_KEY_MISSING: "llm.api_key missing",
    ErrorCode.CATALOG_NOT_FOUND: "catalog not found for mode/base_id",
    ErrorCode.CATALOG_PARSE_FAILED: "catalog parse failed",
    ErrorCode.CATALOG_LINEAGE_UNKNOWN: "catalog lineage unknown",
    ErrorCode.CONTRACT_HASH_MISSING: "contract hash missing on stamped catalog",
    ErrorCode.CONTRACT_HASH_INVENT_FORBIDDEN: "contract hash invent forbidden",
    ErrorCode.CONTRACT_BIND_MISMATCH: "contract bind mismatch for scope",
    ErrorCode.CATALOG_SYNC_FAILED: "catalog sync failed",
    ErrorCode.SESSION_CREATE_FAILED: "session create failed",
    ErrorCode.SESSION_CONTINUE_FAILED: "session continue failed",
    ErrorCode.SESSION_REHYDRATE_FAILED: "session rehydrate failed",
    ErrorCode.SESSION_ID_MISSING: "session id missing",
    ErrorCode.SESSION_DURABLE_DISABLED: "durable sessions disabled",
    ErrorCode.SESSION_COMMIT_FAILED: "session commit/trace failed",
    ErrorCode.AGENT_MEMORY_RECALL_FAILED: "agent memory recall failed",
    ErrorCode.AGENT_MEMORY_WRITE_FAILED: "agent memory write failed",
    ErrorCode.AGENT_MEMORY_UNAVAILABLE: "agent memory API unavailable",
    ErrorCode.AGENT_TURN_FAILED: "agent turn failed",
    ErrorCode.AGENT_MESSAGE_EMPTY: "agent message empty",
    ErrorCode.AGENT_MAX_ROUNDS: "agent max_rounds exceeded",
    ErrorCode.AGENT_LLM_REQUEST_FAILED: "agent LLM request failed",
    ErrorCode.AGENT_LLM_TIMEOUT: "agent LLM timeout",
    ErrorCode.AGENT_TOOL_PLAN_INVALID: "agent tool plan invalid",
    ErrorCode.AGENT_TERMINATE_MISSING: "agent terminate missing",
    ErrorCode.AGENT_HOOKS_ABORTED: "agent hooks aborted turn",
    ErrorCode.LLM_RATE_LIMIT: "llm rate limited (throttle)",
    ErrorCode.LLM_QUOTA_EXHAUSTED: "llm quota exhausted (billing/spend)",
    ErrorCode.LLM_AUTH: "llm auth failed",
    ErrorCode.LLM_CONTEXT_LENGTH: "llm context length exceeded",
    ErrorCode.LLM_CONTENT_FILTER: "llm content filter",
    ErrorCode.LLM_PROVIDER_OVERLOAD: "llm provider overload",
    ErrorCode.LLM_PROVIDER_UNAVAILABLE: "llm provider unavailable",
    ErrorCode.LLM_INVALID_REQUEST: "llm invalid request",
    ErrorCode.LLM_TOOL_SCHEMA: "llm tool schema rejected",
    ErrorCode.ZEUS_TRANSPORT: "zeus HTTP transport error",
    ErrorCode.ZEUS_HTTP_4XX: "zeus HTTP 4xx",
    ErrorCode.ZEUS_HTTP_5XX: "zeus HTTP 5xx",
    ErrorCode.ZEUS_CONTRACT_REQUIRED: "zeus contract_required (409 class)",
    ErrorCode.ZEUS_AUTH_FAILED: "zeus auth failed",
    ErrorCode.ZEUS_VERB_NOT_ALLOWED: "zeus verb not allow-listed",
    ErrorCode.ZEUS_SEARCH_INVALID: "zeus search invalid args",
    ErrorCode.ZEUS_RESPONSE_PARSE: "zeus response parse failed",
    ErrorCode.ZEUS_REQ_ID_MISSING: "zeus req_id missing on response",
    ErrorCode.ZEUS_PIPELINE_NOT_ON_DIRECT: "zeus pipeline not on direct surface",
    ErrorCode.LAYER_A_VALIDATE_FAILED: "layer A validation failed",
    ErrorCode.POLICY_REFUSE: "policy forced refuse",
    ErrorCode.AUTH_FAILED: "auth failed",
    ErrorCode.AUTH_SESSION_UNAVAILABLE: "auth session unavailable",
    ErrorCode.JOBS_UNAVAILABLE: "multi-agent capability unavailable",
    ErrorCode.JOBS_INVALID_UNIT_MAP: "invalid unit map / missing scope",
    ErrorCode.JOBS_BUDGET_INVALID: "job budget invalid",
    ErrorCode.JOBS_NOT_FOUND: "job not found",
    ErrorCode.JOBS_WATCH_FAILED: "job watch transport failed",
    ErrorCode.JOBS_UNIT_FAILED: "job failed (unit error)",
    ErrorCode.UNITS_CATALOG_MISSING: "agent unit missing catalog pin",
    ErrorCode.UNITS_INJECT_MISSING: "agent unit missing required inject",
    ErrorCode.UNITS_ISOLATION: "unit isolation violation",
    ErrorCode.INTERNAL_BUG: "internal client bug",
}


def default_retryable(code: ErrorCode) -> bool:
    """Family default retry hint for ``code`` (apps may still apply budgets)."""
    return code in _RETRYABLE


def public_message_for(code: ErrorCode) -> str:
    """Stable short English message for ``code`` (no secrets)."""
    return _PUBLIC_MESSAGES.get(code, "unknown client error")


class ZeusClientError(Exception):
    """Base typed client error — safe fields for journals and public APIs."""

    def __init__(
        self,
        *,
        code: ErrorCode,
        component: str,
        public_message: str | None = None,
        retryable: bool | None = None,
        cause_event_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.component = component
        self.public_message = (
            public_message if public_message is not None else public_message_for(code)
        )
        self.retryable = default_retryable(code) if retryable is None else bool(retryable)
        self.cause_event_id = cause_event_id
        self.details: dict[str, Any] = dict(details or {})
        super().__init__(f"[{self.code.value}] {self.public_message}")

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable error envelope (family wire shape)."""
        return {
            "error.code": self.code.value,
            "error.message": self.public_message,
            "error.retryable": self.retryable,
            "error.component": self.component,
            "error.cause_event_id": self.cause_event_id,
            "error.details": dict(self.details),
        }


class ConfigError(ZeusClientError):
    """Invalid settings, missing sample, bad paths."""


class AuthError(ZeusClientError):
    """401/403/lockout/session_unavailable."""


class ContractError(ZeusClientError):
    """Drift, mismatch 409, stamp issues."""


class CatalogError(ZeusClientError):
    """Load / sync / path resolution failures."""


class SessionError(ZeusClientError):
    """Create / rehydrate / turn CAS failures."""


class ZeusTransportError(ZeusClientError):
    """Network / timeouts reaching Zeus."""


class ZeusToolError(ZeusClientError):
    """Hop 4xx/5xx with body classification."""


class LlmError(ZeusClientError):
    """Provider failures (prefer 050010–050018 when classified)."""


class PolicyError(ZeusClientError):
    """Forced refuse paths (may still complete a turn with ui_text)."""


class ValidationError(ZeusClientError):
    """Input schema / argument validation."""


class InternalError(ZeusClientError):
    """Bug; include journal ref in details when available."""


class JobError(ZeusClientError):
    """Mode 3 jobs/units failures (130000–139999). Not SDK-auto-retryable."""
