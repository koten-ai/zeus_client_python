"""Logging configuration for the Zeus Python sample client."""
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] zeus_client: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("zeus_client")

# Suppress the low-level http state machine spam that drowns the signal.
# You can temporarily set these to DEBUG if you ever need to debug connection/TLS/headers.
for _name in ("httpx", "httpcore", "httpcore.http11", "httpcore.h2", "h2"):
    logging.getLogger(_name).setLevel(logging.WARNING)

# Pings (/api/ping and /api/ping_ai) are called frequently by the UI health badges.
# They produce repetitive uvicorn access lines and internal client chatter.
# Quiet the uvicorn access logger so the heart of agent/contract/debug logs stands out.
# Our own logger.debug calls inside the ping handlers will still be visible if you really want them.
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

