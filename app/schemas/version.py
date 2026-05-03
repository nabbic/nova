from pydantic import BaseModel


class VersionV2Response(BaseModel):
    version: str

    model_config = {
        "json_schema_extra": {
            "examples": [{"version": "2.0.0"}]
        }
    }
