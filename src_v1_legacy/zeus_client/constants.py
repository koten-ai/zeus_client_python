"""Paths, timeouts, and V2 verb ordering."""
import os
from functools import lru_cache
from importlib import resources
from pathlib import Path

__version__ = "0.3.1"

MAX_ROUNDS = 12
MAX_TOOLCALLS_PER_ROUND = 32
UPSTREAM_TIMEOUT = 90  # seconds — LLM round can be slow
TOOL_TIMEOUT = 60      # seconds — Zeus tool dispatch
AUTH_TIMEOUT = 20      # seconds — Zeus login / catalog load
PING_TIMEOUT = 5       # seconds — health probes


def user_config_dir() -> Path:
    override = (os.environ.get("ZEUS_CLIENT_CONFIG_DIR") or "").strip()
    if override:
        return Path(override)
    return Path.home() / ".config" / "zeus_client"


USER_CONFIG_DIR = user_config_dir()
CONFIG_PATH = USER_CONFIG_DIR / "config.json"
EXAMPLE_CONFIG_PATH = USER_CONFIG_DIR / "config.example.json"
CHAT_LOG_PATH = Path(os.environ.get("CHAT_LOG_PATH") or (USER_CONFIG_DIR / "chats.jsonl"))

# Legacy alias kept for tests and callers that referenced repo-root BASE_DIR.
BASE_DIR = USER_CONFIG_DIR


@lru_cache(maxsize=1)
def package_data_dir() -> Path:
    """Return the installed package data directory (chat_requests, templates)."""
    return Path(resources.files("zeus_client")) / "data"


@lru_cache(maxsize=1)
def _default_bundled_chat_requests_dir() -> Path:
    return package_data_dir() / "chat_requests"


CHAT_REQ_DIR = _default_bundled_chat_requests_dir()


def bundled_chat_requests_dir() -> Path:
    """Bundled package catalogs (CHAT_REQ_DIR; patchable in tests)."""
    return CHAT_REQ_DIR


def chat_requests_dir() -> Path:
    """Alias for the bundled (package) chat_requests directory."""
    return bundled_chat_requests_dir()


def user_chat_requests_dir() -> Path:
    override = (os.environ.get("ZEUS_CHAT_REQUESTS_DIR") or "").strip()
    if override:
        return Path(override)
    return USER_CONFIG_DIR / "chat_requests"


def scope_chat_requests_subdir(bucket: str, scope: str) -> str:
    """Filesystem-safe dir for a bucket/scope (e.g. beer-sample/_default → beer-sample__default)."""
    tail = scope[1:] if scope.startswith("_") else scope
    return f"{bucket}__{tail}"


def scope_key_from_subdir(name: str) -> str | None:
    if "__" not in name:
        return None
    bucket, tail = name.split("__", 1)
    scope = f"_{tail}" if tail else tail
    return f"{bucket}/{scope}"


def chat_request_search_dirs(bucket: str | None = None, scope: str | None = None) -> list[Path]:
    """Ordered catalog roots: scope-specific sync, user general, bundled."""
    user = user_chat_requests_dir()
    bundled = bundled_chat_requests_dir()
    dirs: list[Path] = []
    if bucket and scope:
        dirs.append(user / scope_chat_requests_subdir(bucket, scope))
    dirs.extend([user, bundled])
    return [d for d in dirs if d.is_dir()]


@lru_cache(maxsize=1)
def bundled_example_config_path() -> Path:
    return package_data_dir() / "config.example.json"


def normalize_api_version(v):
    return "v2" if str(v or "").lower() == "v2" else "v1"


# V2 verb x-axis for the trace frequency chart.
V2_DOCS_VERB_ORDER = (
    "describe", "explain", "get", "find",
    "set", "order", "enrich", "project",
    "traverse", "pipeline", "search", "analyze", "return",
)
V2_DOCS_VERBS = frozenset(V2_DOCS_VERB_ORDER)
ZEUS_V2_DOCS_DIR = Path(
    os.environ.get("ZEUS_V2_DOCS") or (Path.home() / "Zeus" / "docs" / "API" / "V2"))


def v2_verbs_from_docs_dir(docs_dir):
    """Return canonical V2 order when every docs/API/V2 verb page is present."""
    if not docs_dir.is_dir():
        return None
    md_verbs = set()
    for path in docs_dir.glob("*.md"):
        if path.name == "WORK_DOCS.md":
            continue
        if path.name == "transforms.md":
            md_verbs.update(("set", "order", "enrich", "project"))
            continue
        md_verbs.add(path.stem)
    if not V2_DOCS_VERBS.issubset(md_verbs):
        return None
    return list(V2_DOCS_VERB_ORDER)


def v2_tool_order():
    loaded = v2_verbs_from_docs_dir(ZEUS_V2_DOCS_DIR)
    return loaded if loaded else list(V2_DOCS_VERB_ORDER)