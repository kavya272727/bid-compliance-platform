from fastapi import APIRouter, HTTPException

from backend.services.compliance_engine import calculate_compliance, persist_compliance

router = APIRouter(prefix="/api/compliance", tags=["Compliance"])


@router.post("/score/{bidder_id}")
def score_bidder(bidder_id: str):
    try:
        result = calculate_compliance(bidder_id)
        try:
            persist_compliance(result)
            result["score_persisted"] = True
            result["audit_persisted"] = True
        except Exception as exc:
            result["score_persisted"] = False
            result["audit_persisted"] = False
            result["persistence_error"] = str(exc)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Compliance scoring failed: {exc}") from exc