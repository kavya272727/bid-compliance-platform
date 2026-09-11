from fastapi import APIRouter, HTTPException

from backend.services.ai_reasoning import reason_for_bidder

router = APIRouter(prefix="/api/ai", tags=["AI Reasoning"])


@router.post("/reason/{bidder_id}")
def reason(bidder_id: str):
    try:
        return reason_for_bidder(bidder_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI reasoning failed: {exc}") from exc