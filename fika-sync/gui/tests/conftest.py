import os
import sys
import tempfile
from pathlib import Path

import pytest

GUI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GUI_DIR))


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Each test runs against a temporary, disposable SQLite database,
    never against the real fika_sync.db."""
    db_path = tmp_path / "test_fika_sync.db"
    monkeypatch.setenv("FIKA_SYNC_DB_PATH", str(db_path))
    yield db_path


@pytest.fixture
def client():
    # Deferred import: this way it picks up FIKA_SYNC_DB_PATH already
    # set by temp_db before create_app() calls models.init_db().
    import app as app_module
    application = app_module.create_app()
    application.config.update(TESTING=True)
    with application.test_client() as test_client:
        yield test_client
