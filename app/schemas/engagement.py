import uuid
from datetime import datetime

from pydantic import BaseModel


class EngagementResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedEngagements(BaseModel):
    items: list[EngagementResponse]
    total: int
    limit: int
    offset: int
