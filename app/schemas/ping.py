from pydantic import BaseModel


class PingResponse(BaseModel):
    pong: bool
    timestamp: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "pong": True,
                "timestamp": "2025-01-15T14:32:45.123456Z",
            }
        }
    }
