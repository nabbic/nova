from fastapi import APIRouter

router = APIRouter()


@router.get(
    "/health-info",
    summary="Get factory health info",
    response_description="Factory generation and cutover date",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"factory_generation": "v2", "cutover_at": "2026-05-04"}
                }
            }
        }
    },
)
async def get_health_info() -> dict:
    return {"factory_generation": "v2", "cutover_at": "2026-05-04"}
