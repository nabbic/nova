from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_buyer_org_id
from app.core.database import get_db
from app.repositories.engagements import EngagementRepository
from app.schemas.engagement import EngagementResponse, PaginatedEngagements

router = APIRouter()


@router.get(
    "/engagements",
    response_model=PaginatedEngagements,
    summary="List engagements for the calling buyer org",
    response_description="Paginated list of engagements",
    responses={
        200: {
            "description": "Paginated engagement list",
            "content": {
                "application/json": {
                    "example": {
                        "items": [
                            {
                                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                                "name": "Acme Corp Diligence",
                                "status": "active",
                                "created_at": "2026-01-01T00:00:00Z",
                            }
                        ],
                        "total": 1,
                        "limit": 20,
                        "offset": 0,
                    }
                }
            },
        },
        401: {"description": "Not authenticated"},
    },
)
async def list_engagements(
    limit: int = Query(default=20, ge=1, le=100, description="Max number of results"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip"),
    buyer_org_id: str = Depends(get_current_buyer_org_id),
    db: AsyncSession = Depends(get_db),
) -> PaginatedEngagements:
    repo = EngagementRepository(db)
    orm_items, total = await repo.list_by_buyer_org(
        buyer_org_id, limit=limit, offset=offset
    )
    items = [EngagementResponse.model_validate(e) for e in orm_items]
    return PaginatedEngagements(items=items, total=total, limit=limit, offset=offset)
