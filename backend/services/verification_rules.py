import re
from difflib import SequenceMatcher
from typing import Any


PASS_STATUSES = {"VERIFIED", "ACTIVE", "VALID", "CLEAR", "COMPLIANT", "MATCH", "ELIGIBLE"}
REVIEW_STATUSES = {"MISSING", "NOT_FOUND", "PENDING", "EXPIRED", "MISMATCH", "INCONSISTENT"}
FAIL_STATUSES = {"BLACKLISTED", "DEBARRED"}

DOCUMENT_TYPE_ALIASES = {
    "PAN": ("PAN",),
    "GST": ("GST", "GSTIN"),
    "UDYAM": ("UDYAM", "MSME"),
}


def normalize_status(status: str | None) -> str:
    value = (status or "").upper().strip()
    if value in PASS_STATUSES:
        return "PASS"
    if value in FAIL_STATUSES:
        return "FAIL"
    if value in REVIEW_STATUSES:
        return "REVIEW"
    return "REVIEW"


def normalize_name(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9 ]", " ", str(value or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    suffixes = (" private limited", " pvt ltd", " pvt limited", " limited", " ltd")
    for suffix in suffixes:
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].strip()
            break
    return normalized


def compare_names(left: str | None, right: str | None) -> tuple[str, float]:
    left_normalized = normalize_name(left)
    right_normalized = normalize_name(right)
    if not left_normalized or not right_normalized:
        return "REVIEW", 0.0
    confidence = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    return ("PASS" if confidence >= 0.86 else "REVIEW"), round(confidence, 2)


def document_value(document: dict[str, Any], *keys: str) -> str | None:
    data = document.get("extracted_data") or {}
    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    return None


def cross_document_checks(documents: list[dict[str, Any]], bidder_id: str) -> list[dict[str, Any]]:
    by_type = {str(document.get("document_type", "")).upper(): document for document in documents}
    values = {
        "PAN": (document_value(by_type.get("PAN", {}), "name"), "PAN"),
        "GST": (document_value(by_type.get("GST", {}), "legal_business_name", "legal_name"), "GST"),
        "UDYAM": (document_value(by_type.get("UDYAM", {}), "enterprise_name", "company_name"), "UDYAM"),
    }
    checks = []
    pairs = (("PAN", "GST", "PAN_GST_NAME_MATCH"), ("PAN", "UDYAM", "PAN_UDYAM_NAME_MATCH"), ("GST", "UDYAM", "GST_UDYAM_NAME_MATCH"))
    for left_type, right_type, verification_type in pairs:
        left_name, left_label = values[left_type]
        right_name, right_label = values[right_type]
        if left_type not in by_type or right_type not in by_type:
            continue
        if left_name and right_name:
            status, confidence = compare_names(left_name, right_name)
            finding = "Legal names match" if status == "PASS" else "Legal names differ"
            evidence = f"{left_label}: {left_name} | {right_label}: {right_name}"
        else:
            status, confidence = "REVIEW", 0.0
            finding = "Required document name data is missing"
            evidence = f"{left_label}: {left_name or 'missing'} | {right_label}: {right_name or 'missing'}"
        checks.append({"verification_type": verification_type, "status": status, "finding": finding, "evidence": evidence, "confidence": confidence, "source": "documents", "bidder_id": bidder_id})

    addresses = [document_value(document, "address", "registered_address", "business_address") for document in documents]
    addresses = [address for address in addresses if address]
    if len(addresses) > 1:
        status, confidence = compare_names(addresses[0], addresses[1])
        checks.append({"verification_type": "DOCUMENT_ADDRESS_MATCH", "status": status, "finding": "Document addresses match" if status == "PASS" else "Document addresses differ", "evidence": " | ".join(addresses), "confidence": confidence, "source": "documents", "bidder_id": bidder_id})
    return checks


def requirement_document_type(requirement: dict[str, Any]) -> str | None:
    text = f"{requirement.get('requirement_name', '')} {requirement.get('description', '')}".upper()
    for document_type, aliases in DOCUMENT_TYPE_ALIASES.items():
        if any(alias in text for alias in aliases):
            return document_type
    return None


def tender_requirement_checks(requirements: list[dict[str, Any]], documents: list[dict[str, Any]], bidder: dict[str, Any]) -> list[dict[str, Any]]:
    document_types = {str(document.get("document_type", "")).upper() for document in documents}
    checks = []
    for requirement in requirements:
        if not requirement.get("mandatory", True):
            continue
        requirement_type = str(requirement.get("requirement_type", "")).upper()
        mapped_type = requirement_document_type(requirement) if requirement_type == "DOCUMENT" else None
        if requirement_type == "DOCUMENT" and mapped_type:
            status = "PASS" if mapped_type in document_types else "REVIEW"
            finding = "Mandatory document submitted" if status == "PASS" else "Mandatory document is missing"
            evidence = f"Required: {mapped_type} | Submitted: {', '.join(sorted(document_types)) or 'none'}"
        elif requirement_type == "DOCUMENT":
            status = "REVIEW"
            finding = "Mandatory tender document requirement is unresolved"
            evidence = f"Required: {requirement.get('requirement_name') or 'document'} | Submitted: {', '.join(sorted(document_types)) or 'none'}"
        else:
            status = "PASS"
            finding = "Tender policy requirement recorded for downstream policy review"
            evidence = requirement.get("description") or requirement.get("requirement_name") or "Tender requirement"
        checks.append({"verification_type": "TENDER_REQUIREMENT", "status": status, "finding": finding, "evidence": evidence, "confidence": 1.0, "source": "tender_requirements", "requirement_id": requirement.get("id"), "bidder_id": bidder.get("id")})
    return checks