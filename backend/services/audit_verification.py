import hashlib
import json
from typing import Any

from .supabase_client import supabase


def _canonical_entry(entry: dict[str, Any]) -> bytes:
    payload = {
        "bidder_id": entry.get("bidder_id"),
        "action": entry.get("action"),
        "details": entry.get("details"),
        "created_at": entry.get("created_at"),
        "prev_hash": entry.get("prev_hash"),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()


def _entry_hash(entry: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_entry(entry)).hexdigest()


def verify_audit_chain(bidder_id: str) -> dict[str, Any]:
    response = (
        supabase.table("audit_log")
        .select("id,bidder_id,action,actor,details,prev_hash,entry_hash,created_at")
        .eq("bidder_id", bidder_id)
        .order("created_at")
        .order("id")
        .execute()
    )
    previous_hash = None
    for index, entry in enumerate(response.data or [], start=1):
        if entry.get("prev_hash") != previous_hash:
            return {"valid": False, "entries_checked": index, "first_invalid_entry": entry.get("id"), "error": "Previous hash mismatch"}
        if entry.get("entry_hash") != _entry_hash(entry):
            return {"valid": False, "entries_checked": index, "first_invalid_entry": entry.get("id"), "error": "Entry hash mismatch"}
        previous_hash = entry.get("entry_hash")
    return {"valid": True, "entries_checked": len(response.data or []), "first_invalid_entry": None, "error": None}