from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class EOError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(EOError):
    status_code = 404
    code = "not_found"


class ValidationError(EOError):
    status_code = 422
    code = "validation_error"


class IngestionError(EOError):
    status_code = 400
    code = "ingestion_error"


class ModelLoadError(EOError):
    status_code = 503
    code = "model_unavailable"


class ForbiddenPathError(EOError):
    status_code = 403
    code = "forbidden_path"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(EOError)
    async def _handle(_: Request, exc: EOError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "message": exc.message, "details": exc.details},
        )
