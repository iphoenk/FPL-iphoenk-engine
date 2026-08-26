from live_service import app
from src.engine import ENGINE_VERSION as ENGINE_RUNTIME_VERSION
from src.engine import SCHEMA_VERSION as ENGINE_RUNTIME_SCHEMA
from src.version import ENGINE_VERSION, SCHEMA_VERSION, SERVICE_TITLE


def test_release_metadata_single_source_of_truth():
    assert ENGINE_VERSION == "3.10.0"
    assert SCHEMA_VERSION == 39
    assert ENGINE_RUNTIME_VERSION == ENGINE_VERSION
    assert ENGINE_RUNTIME_SCHEMA == SCHEMA_VERSION
    assert app.version == ENGINE_VERSION
    assert app.title == SERVICE_TITLE
