import pytest
from fastapi.testclient import TestClient

from snip.app import create_app
from snip.config import Settings

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "snip.db")


@pytest.fixture
def make_client(db_path):
    clients = []

    def _make(token=TOKEN, base_url=None):
        app = create_app(Settings(api_token=token, db_path=db_path, base_url=base_url))
        client = TestClient(app, follow_redirects=False)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()
