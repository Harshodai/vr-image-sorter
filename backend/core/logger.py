import logging
import os

# ---------------------------------------------------------------------------
# Log level — configurable via LOG_LEVEL env var (default INFO)
# ---------------------------------------------------------------------------
_level_name: str = os.environ.get("LOG_LEVEL", "INFO").upper()
_level: int = getattr(logging, _level_name, logging.INFO)

# Configure centralized logging with a structured format that includes the
# request context fields injected by the middleware (request_id, etc.).
logging.basicConfig(
    level=_level,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

logger = logging.getLogger("vr-saree-sorter")
