"""Tests for ``/api/v1/emails`` path validation: hex mail ids vs ``int`` path params."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from backend.app.exception_handlers import emails_request_validation_handler


def _minimal_app_with_int_path_param() -> FastAPI:
    """Simulates a route that wrongly types the segment as ``int`` (legacy / mistake)."""
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, emails_request_validation_handler)

    @app.get("/api/v1/emails/{fetched_email_id}")
    def _get_by_int(fetched_email_id: int) -> dict:
        return {"id": fetched_email_id}

    return app


def test_hex_mail_id_returns_404_when_handler_registered_and_path_is_int() -> None:
    """Gmail-style id is not a valid integer → without the handler this would be 422."""
    client = TestClient(_minimal_app_with_int_path_param())
    r = client.get("/api/v1/emails/19d3a38a3d325061")
    assert r.status_code == 404
    assert r.json() == {"detail": "Email not found"}


def test_hex_mail_id_returns_422_without_custom_handler() -> None:
    """Baseline: default FastAPI behaviour for non-integer path segment."""
    app = FastAPI()

    @app.get("/api/v1/emails/{fetched_email_id}")
    def _get_by_int(fetched_email_id: int) -> dict:
        return {"id": fetched_email_id}

    client = TestClient(app)
    r = client.get("/api/v1/emails/19d3a38a3d325061")
    assert r.status_code == 422
    body = r.json()
    assert "detail" in body
    assert any(e.get("type") == "int_parsing" for e in body["detail"])


def test_int_path_parsing_elsewhere_still_422_with_handler() -> None:
    """Handler only special-cases ``/api/v1/emails/``."""
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, emails_request_validation_handler)

    @app.get("/api/v1/other/{n}")
    def _other(n: int) -> dict:
        return {"n": n}

    client = TestClient(app)
    r = client.get("/api/v1/other/not-an-int")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_handler_unit_int_parsing_returns_404() -> None:
    from starlette.requests import Request

    scope: dict = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/emails/19d3a38a3d325061",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
        "scheme": "http",
    }
    request = Request(scope)
    exc = RequestValidationError(
        [
            {
                "type": "int_parsing",
                "loc": ("path", "fetched_email_id"),
                "msg": "invalid",
                "input": "19d3a38a3d325061",
            }
        ]
    )
    response = await emails_request_validation_handler(request, exc)
    assert response.status_code == 404
    assert json.loads(response.body) == {"detail": "Email not found"}


@pytest.mark.asyncio
async def test_handler_unit_delegates_for_wrong_path() -> None:
    from starlette.requests import Request

    scope: dict = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/other/abc",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
        "scheme": "http",
    }
    request = Request(scope)
    exc = RequestValidationError(
        [
            {
                "type": "int_parsing",
                "loc": ("path", "n"),
                "msg": "invalid",
                "input": "abc",
            }
        ]
    )
    response = await emails_request_validation_handler(request, exc)
    assert response.status_code == 422
