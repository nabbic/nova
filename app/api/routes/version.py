from fastapi import APIRouter

router = APIRouter()


@router.get(
    "/version",
    summary="Get API version",
    response_description="Current API version",
    responses={200: {"content": {"application/json": {"example": {"version": "1.0"}}}}},
)
async def get_version() -> dict:
    return {"version": "1.0"}


@router.get(
    "/version-v2",
    summary="Get API version v2",
    response_description="v2 API version identifier",
    responses={200: {"content": {"application/json": {"example": {"version": "2.0"}}}}},
)
async def get_version_v2() -> dict:
    return {"version": "2.0"}
