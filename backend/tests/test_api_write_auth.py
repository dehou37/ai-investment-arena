import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.api import dependencies


def test_write_route_requires_bearer_header(monkeypatch):
    monkeypatch.setattr(dependencies.settings, "API_WRITE_KEY", "expected")
    test_app = FastAPI()

    @test_app.post(
        "/write",
        dependencies=[Depends(dependencies.require_api_write_key)],
    )
    def write_route():
        return {"written": True}

    client = TestClient(test_app)

    assert client.post("/write").status_code == 401
    assert client.post(
        "/write",
        headers={"Authorization": "Bearer incorrect"},
    ).status_code == 401
    response = client.post(
        "/write",
        headers={"Authorization": "Bearer expected"},
    )
    assert response.status_code == 200
    assert response.json() == {"written": True}


def test_write_key_rejects_requests_when_not_configured(monkeypatch):
    monkeypatch.setattr(dependencies.settings, "API_WRITE_KEY", None)

    with pytest.raises(HTTPException) as exc:
        dependencies.require_api_write_key(None)

    assert exc.value.status_code == 503


def test_write_key_requires_matching_bearer_token(monkeypatch):
    monkeypatch.setattr(dependencies.settings, "API_WRITE_KEY", "expected")

    with pytest.raises(HTTPException) as missing:
        dependencies.require_api_write_key(None)
    assert missing.value.status_code == 401

    wrong_credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="incorrect",
    )
    with pytest.raises(HTTPException) as wrong:
        dependencies.require_api_write_key(wrong_credentials)
    assert wrong.value.status_code == 401

    correct_credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="expected",
    )
    assert dependencies.require_api_write_key(correct_credentials) is None
