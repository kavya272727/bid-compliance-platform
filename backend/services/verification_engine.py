from typing import Any

from .supabase_client import supabase


SOURCE_ORDER = [
    "GST",
    "UDYAM",
    "PAN",
    "INCOME_TAX",
    "MCA21",
    "EPFO_ESIC",
    "MAKE_IN_INDIA",
    "BLACKLIST",
]


def get_bidder(bidder_id: str) -> dict[str, Any]:
    response = (
        supabase.table("bidders")
        .select("*")
        .eq("id", bidder_id)
        .single()
        .execute()
    )

    if not response.data:
        raise ValueError(f"Bidder not found: {bidder_id}")

    return response.data


def get_mock_records(bidder_id: str) -> list[dict[str, Any]]:
    response = (
        supabase.table("mock_government_verification_records")
        .select("*")
        .eq("bidder_id", bidder_id)
        .execute()
    )
    return response.data or []


def normalize_status(status: str | None) -> str:
    value = (status or "").upper().strip()

    if value in {"VERIFIED", "ACTIVE", "VALID", "CLEAR", "COMPLIANT", "MATCH"}:
        return "PASS"

    if value in {"BLACKLISTED", "DEBARRED"}:
        return "FAIL"

    if value in {"MISSING", "NOT_FOUND", "PENDING", "EXPIRED", "MISMATCH", "INCONSISTENT"}:
        return "REVIEW"

    return "REVIEW"


def run_verification(bidder_id: str) -> dict[str, Any]:
    bidder = get_bidder(bidder_id)
    records = get_mock_records(bidder_id)

    checks = []
    blacklist_hit = False

    for record in records:
        source = record.get("source_type")
        status = record.get("status")
        normalized = normalize_status(status)

        if source == "BLACKLIST" and normalized == "FAIL":
            blacklist_hit = True

        checks.append(
            {
                "source": source,
                "identifier": record.get("identifier"),
                "status": status,
                "decision": normalized,
                "legal_name": record.get("legal_name"),
                "evidence": record.get("returned_data") or {},
                "source_reference": record.get("source_reference"),
                "verified_at": record.get("verified_at"),
            }
        )

    # Project rule: blacklist/debarment is a hard stop.
    if blacklist_hit:
        overall = "FAIL"
        recommendation = "Immediate FAIL: bidder appears in the blacklist/debarment registry."
    elif any(check["decision"] == "REVIEW" for check in checks):
        overall = "REVIEW"
        recommendation = "Manual review required because one or more government checks are unresolved or inconsistent."
    else:
        overall = "PASS"
        recommendation = "Government verification checks passed."

    return {
        "bidder": bidder,
        "overall_decision": overall,
        "recommendation": recommendation,
        "blacklist_hard_stop": blacklist_hit,
        "checks": checks,
        "summary": {
            "total_checks": len(checks),
            "passed": sum(c["decision"] == "PASS" for c in checks),
            "review": sum(c["decision"] == "REVIEW" for c in checks),
            "failed": sum(c["decision"] == "FAIL" for c in checks),
        },
    }
