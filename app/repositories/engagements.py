from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engagement import Engagement


class EngagementRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_by_buyer_org(
        self, buyer_org_id: str, limit: int = 20, offset: int = 0
    ) -> tuple[list[Engagement], int]:
        base_query = select(Engagement).where(Engagement.buyer_org_id == buyer_org_id)

        count_result = await self.db.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total: int = count_result.scalar_one()

        result = await self.db.execute(
            base_query.order_by(Engagement.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), total
