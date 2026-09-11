import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from .supabase_client import supabase


def write_audit_entry(bidder_id: str, action: str, details: dict[str, Any]) -> dict[str, Any]:
    previous = (
        supabase.table("audit_log")
        .select("entry_hash")
        .eq("bidder_id", bidder_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    previous_rows = previous.data or []
    prev_hash = previous_rows[0].get("entry_hash") if previous_rows else None
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "bidder_id": bidder_id,
        "action": action,
        "details": details,
        "created_at": created_at,
        "prev_hash": prev_hash,
    }
    entry_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    row = {**payload, "entry_hash": entry_hash}
    response = supabase.table("audit_log").insert(row).execute()
    return response.data[0] if isinstance(response.data, list) else response.data