from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, object]


class ErrorResponse(BaseModel):
    error: ErrorBody
