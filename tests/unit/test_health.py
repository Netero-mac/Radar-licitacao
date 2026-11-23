from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db import get_session
from app.main import create_app


@pytest.fixture
def session() -> MagicMock:
    return MagicMock()


@pytest.fixture
def client(session: MagicMock) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client


def test_health_ok_quando_banco_responde(client: TestClient, session: MagicMock) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "ok"
    session.execute.assert_called_once()


def test_health_503_quando_banco_falha(client: TestClient, session: MagicMock) -> None:
    session.execute.side_effect = OperationalError("SELECT 1", {}, Exception("sem conexão"))

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "error", "version": "0.1.0"}
