"""Central configuration. Environment variables override defaults."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("GUARDRAIL_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get(
    "GUARDRAIL_DATABASE_URL",
    f"sqlite:///{(DATA_DIR / 'guardrail.db').as_posix()}",
)

MAX_FILES_PER_SCAN = int(os.environ.get("GUARDRAIL_MAX_FILES", "500"))
MAX_FILE_BYTES = int(os.environ.get("GUARDRAIL_MAX_FILE_BYTES", "1000000"))

API_TITLE = "Guardrail Auditor API"
API_VERSION = "0.1.0"
