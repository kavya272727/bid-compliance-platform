from typing import Any

from .government_adapter import get_blacklist_status
from .supabase_client import supabase
from .verification_rules import (
    cross_document_checks,
    normalize_status,
    tender_requirement_checks,
)


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


def get_documents(bidder_id: str) -> list[dict[str, Any]]:
    response = (
        supabase.table("documents")
        .select("*")
        .eq("bidder_id", bidder_id)
        .execute()
    )
    return response.data or []


def get_tender_requirements(tender_id: str) -> list[dict[str, Any]]:
    response = (
        supabase.table("tender_requirements")
        .select("*")
        .eq("tender_id", tender_id)
        .execute()
    )
    return response.data or []


def _structured_check(
    source: str,
    record: dict[str, Any],
    bidder_id: str,
    bidder: dict[str, Any],
) -> dict[str, Any]:
    status = normalize_status(record.get("status"))
    source_type = record.get("source_type") or source
    returned_data = record.get("returned_data") or {}
    expected_identifier = {
        "GST": bidder.get("gstin"),
        "PAN": bidder.get("pan"),
        "UDYAM": bidder.get("udyam_number"),
    }.get(source_type)
    identifier_mismatch = expected_identifier and record.get("identifier") != expected_identifier
    evidence_state = returned_data.get("state") or returned_data.get("registered_state")
    bidder_address = str(bidder.get("address") or "").lower()
    state_mismatch = evidence_state and str(evidence_state).lower() not in bidder_address
    name_mismatch = record.get("legal_name") and record.get("legal_name") != bidder.get("company_name")
    evidence_mismatch = identifier_mismatch or state_mismatch or name_mismatch
    if status == "PASS" and evidence_mismatch:
        status = "REVIEW"
    check = {
        "verification_type": source_type,
        "status": status,
        "finding": (
            f"{source_type} evidence does not match bidder data"
            if evidence_mismatch
            else f"{source_type} status: {record.get('status') or 'unknown'}"
        ),
        "evidence": returned_data,
        "confidence": 1.0,
        "source": source_type,
        "bidder_id": bidder_id,
        "identifier": record.get("identifier"),
        "legal_name": record.get("legal_name"),
        "source_reference": record.get("source_reference"),
        "verified_at": record.get("verified_at"),
        # Retained for clients of the Phase 1 response.
        "decision": status,
        "raw_status": record.get("status"),
    }
    return check


def _persist_checks(checks: list[dict[str, Any]]) -> None:
    if not checks:
        return
    table = supabase.table("verification_checks")
    if not hasattr(table, "insert"):
        return
    rows = [
        {
            "bidder_id": check.get("bidder_id"),
            "verification_type": check.get("verification_type"),
            "status": check.get("status"),
            "finding": check.get("finding"),
            "evidence": check.get("evidence") or {},
            "confidence": check.get("confidence"),
            "source": check.get("source"),
            "requirement_id": check.get("requirement_id"),
        }
        for check in checks
    ]
    table.insert(rows).execute()


def _response(
    bidder: dict[str, Any],
    checks: list[dict[str, Any]],
    blacklist_hard_stop: bool,
    recommendation: str,
) -> dict[str, Any]:
    return {
        "bidder": bidder,
        "overall_decision": (
            "FAIL"
            if any(check["status"] == "FAIL" for check in checks)
            else "REVIEW"
            if any(check["status"] == "REVIEW" for check in checks)
            else "PASS"
        ),
        "recommendation": recommendation,
        "blacklist_hard_stop": blacklist_hard_stop,
        "checks": checks,
        "summary": {
            "total_checks": len(checks),
            "passed": sum(check["status"] == "PASS" for check in checks),
            "review": sum(check["status"] == "REVIEW" for check in checks),
            "failed": sum(check["status"] == "FAIL" for check in checks),
        },
    }


def run_verification(bidder_id: str) -> dict[str, Any]:
    bidder = get_bidder(bidder_id)
    # This is deliberately the only pipeline step before the hard-stop return.
    bidder_pan = bidder.get("pan")
    blacklist_record = get_blacklist_status(bidder_pan) if bidder_pan else None
    if blacklist_record and normalize_status(blacklist_record.get("status")) == "FAIL":
        checks = [_structured_check("BLACKLIST", blacklist_record, bidder_id, bidder)]
        _persist_checks(checks)
        result = _response(
            bidder,
            checks,
            True,
            "Immediate FAIL: bidder appears in the blacklist/debarment registry.",
        )
        result["overall_decision"] = "FAIL"
        return result

    records = get_mock_records(bidder_id)
    checks = [
        _structured_check(record.get("source_type") or "government", record, bidder_id, bidder)
        for record in records
        if record.get("source_type") != "BLACKLIST"
    ]
    documents = get_documents(bidder_id)
    checks.extend(cross_document_checks(documents, bidder_id))
    requirements = get_tender_requirements(bidder.get("tender_id") or "")
    checks.extend(tender_requirement_checks(requirements, documents, bidder))
    _persist_checks(checks)

    recommendation = (
        "FAIL: one or more verification checks failed."
        if any(check["status"] == "FAIL" for check in checks)
        else "Manual review required because one or more checks are unresolved or inconsistent."
        if any(check["status"] == "REVIEW" for check in checks)
        else "All applicable verification checks passed."
    )
    return _response(bidder, checks, False, recommendation)
