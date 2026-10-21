"""One error shape for every failure: {"error": {"code", "message", "details"?}}."""
from __future__ import annotations

import logging
import sqlite3

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("fraud.errors")


class AppError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str, details: list | None = None, code: str | None = None):
        super().__init__(message)
        self.message, self.details = message, details
        if code:
            self.code = code


class NotFound(AppError):
    status, code = 404, "not_found"


class Conflict(AppError):
    status, code = 409, "conflict"


class Unauthorized(AppError):
    status, code = 401, "unauthorized"


class Forbidden(AppError):
    status, code = 403, "forbidden"


class Invalid(AppError):
    status, code = 422, "validation_error"


class TooManyAttempts(AppError):
    status, code = 429, "too_many_attempts"


def _body(status: int, code: str, message: str, details: list | None = None, headers: dict | None = None):
    err = {"code": code, "message": message}
    if details:
        err["details"] = details
    return JSONResponse({"error": err}, status_code=status, headers=headers)


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
        return _body(exc.status, exc.code, exc.message, exc.details, headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]), "message": e["msg"]} for e in exc.errors()]
        return _body(422, "validation_error", "Request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return _body(exc.status_code, "http_error" if exc.status_code != 404 else "not_found", str(exc.detail))

    @app.exception_handler(sqlite3.Error)
    async def _db(request: Request, exc: sqlite3.Error):
        log.error("database error on %s %s: %s", request.method, request.url.path, type(exc).__name__)
        return _body(503, "database_error", "The database is unavailable or the operation failed. Try again.")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return _body(500, "internal_error", "Unexpected server error.")
