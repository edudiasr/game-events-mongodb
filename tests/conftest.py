import os
import uuid
from pathlib import Path

import pytest

from events import db as dbmod

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def db():
    """Banco novo e vazio pra cada teste, apagado no fim."""
    client = dbmod.client()
    name = f"events_test_{uuid.uuid4().hex[:10]}"
    database = client[name]
    dbmod.setup(database)
    yield database
    client.drop_database(name)
    client.close()


@pytest.fixture
def example_log() -> Path:
    return EXAMPLES / "DayZServer_x64_exemplo.ADM"


os.environ.setdefault("EVENTS_TTL_DAYS", "3650")
