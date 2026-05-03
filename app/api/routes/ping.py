import datetime

from fastapi import APIRouter

from app.schemas.ping import PingResponse

router = APIRouter()


@router.get(
    "/ping",
    response_model=PingResponse,
    summary="Liveness probe",
    description="Returns a pong response with the server's current UTC timestamp. No authentication required.",
    tags=["liveness"],
)
async def ping() -> PingResponse:
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"
    return PingResponse(pong=True, timestamp=timestamp)
