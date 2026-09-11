from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.services.government_adapter import (
    get_blacklist_status,
    get_gst_status,
    get_pan_status,
    get_udyam_status,
)

router = APIRouter(prefix="/api/mock", tags=["Mock Government"])


def _lookup(get_status: Callable[[str], dict[str, Any] | None], identifier: str):
    try:
        record = get_status(identifier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Mock lookup failed: {exc}") from exc

    if record is None:
        raise HTTPException(status_code=404, detail="Verification record not found")

    return record


@router.get("/gst/{gstin}")
def get_gst(gstin: str):
    return _lookup(get_gst_status, gstin)


@router.get("/udyam/{udyam_number}")
def get_udyam(udyam_number: str):
    return _lookup(get_udyam_status, udyam_number)


@router.get("/pan/{pan}")
def get_pan(pan: str):
    return _lookup(get_pan_status, pan)


@router.get("/blacklist/{pan}")
def get_blacklist(pan: str):
    return _lookup(get_blacklist_status, pan)