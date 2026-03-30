"""FastAPI exception handlers."""

from __future__ import annotations

from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


async def emails_request_validation_handler(
    request: Request, exc: RequestValidationError
) -> Response:
    """If path validation fails because a segment was declared ``int`` but looks like a Gmail id
    (hex), return 404 instead of 422 so clients treat it as “not cached”.
    """
    if request.url.path.startswith("/api/v1/emails/"):
        for err in exc.errors():
            if err.get("type") == "int_parsing" and err.get("loc", ())[:1] == ("path",):
                return JSONResponse(
                    status_code=404,
                    content={"detail": "Email not found"},
                )
    return await request_validation_exception_handler(request, exc)
