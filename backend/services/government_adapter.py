from typing import Any

from .supabase_client import supabase


SOURCE_TYPES = {
    "gst": "GST",
    "udyam": "UDYAM",
    "pan": "PAN",
    "blacklist": "BLACKLIST",
}


def _get_record(source_type: str, identifier: str) -> dict[str, Any] | None:
    normalized_identifier = identifier.strip()
    if not normalized_identifier:
        raise ValueError("Identifier cannot be blank")

    response = (
        supabase.table("mock_government_verification_records")
        .select("*")
        .eq("source_type", source_type)
        .eq("identifier", normalized_identifier)
        .limit(1)
        .execute()
    )
    records = response.data or []
    return records[0] if records else None


def get_gst_status(gstin: str) -> dict[str, Any] | None:
    return _get_record(SOURCE_TYPES["gst"], gstin)


def get_udyam_status(udyam_number: str) -> dict[str, Any] | None:
    return _get_record(SOURCE_TYPES["udyam"], udyam_number)


def get_pan_status(pan: str) -> dict[str, Any] | None:
    return _get_record(SOURCE_TYPES["pan"], pan)


def get_blacklist_status(pan: str) -> dict[str, Any] | None:
    return _get_record(SOURCE_TYPES["blacklist"], pan)