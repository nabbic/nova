from pydantic import BaseModel


class VersionResponse(BaseModel):
    version: str

    model_config = {
        "json_schema_extra": {
            "examples": [{"version": "2.0.0"}]
        }
    }
