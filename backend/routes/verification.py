from fastapi import APIRouter, HTTPException

from backend.services.verification_engine import run_verification

router = APIRouter(prefix="/api/verification", tags=["Verification"])


@router.get("/bidder/{bidder_id}")
def verify_bidder(bidder_id: str):
    try:
        return run_verification(bidder_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Verification failed: {exc}",
        ) from exc
