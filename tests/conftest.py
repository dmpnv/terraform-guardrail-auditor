import os
import tempfile

# Point the app at a throwaway database BEFORE anything imports app.config.
os.environ.setdefault("GUARDRAIL_DATA_DIR", tempfile.mkdtemp(prefix="guardrail-test-"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:  # context manager runs lifespan -> init_db()
        yield c
