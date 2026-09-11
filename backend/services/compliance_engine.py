import os
from typing import Any

from .audit_log import write_audit_entry
from .supabase_client import supabase
from .verification_engine import run_verification


WEIGHT_GOVERNMENT_VERIFICATION = 0.40
WEIGHT_CROSS_DOCUMENT = 0.20
WEIGHT_TENDER_REQUIREMENTS = 0.25
WEIGHT_POLICY_ELIGIBILITY = 0.15
SCORING_WEIGHTS = {
    "government_verification": WEIGHT_GOVERNMENT_VERIFICATION,
    "cross_document": WEIGHT_CROSS_DOCUMENT,
    "tender_requirements": WEIGHT_TENDER_REQUIREMENTS,
    "policy_eligibility": WEIGHT_POLICY_ELIGIBILITY,
}
COMPLIANCE_PASS_THRESHOLD = 80.0
COMPLIANCE_REVIEW_THRESHOLD = 60.0


def _threshold(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _risk_level(score: float, hard_stop: bool = False) -> str:
    if hard_stop or score < _threshold("COMPLIANCE_REVIEW_THRESHOLD", COMPLIANCE_REVIEW_THRESHOLD):
        return "HIGH"
    if score < _threshold("COMPLIANCE_PASS_THRESHOLD", COMPLIANCE_PASS_THRESHOLD):
        return "MEDIUM"
    return "LOW"


def _category(check: dict[str, Any]) -> str:
    verification_type = str(check.get("verification_type", "")).upper()
    if verification_type.startswith("TENDER"):
        return "tender_requirements"
    if "MATCH" in verification_type or verification_type.startswith("DOCUMENT"):
        return "cross_document"
    if verification_type in {"MCA21", "INCOME_TAX", "EPFO_ESIC", "MAKE_IN_INDIA"}:
        return "policy_eligibility"
    return "government_verification"


def _score_checks(checks: list[dict[str, Any]]) -> tuple[float, dict[str, float]]:
    buckets = {category: [] for category in SCORING_WEIGHTS}
    for check in checks:
        buckets[_category(check)].append(check)
    breakdown = {}
    for category, weight in SCORING_WEIGHTS.items():
        category_checks = buckets[category]
        ratio = (
            sum(1 for check in category_checks if check.get("status") == "PASS") / len(category_checks)
            if category_checks
            else 0.0
        )
        breakdown[category] = round(ratio * weight * 100, 2)
    return round(sum(breakdown.values()), 2), breakdown


def _latest_ai_result(bidder_id: str) -> dict[str, Any] | None:
    response = (
        supabase.table("audit_log")
        .select("details,created_at")
        .eq("bidder_id", bidder_id)
        .eq("action", "AI_REASONING_COMPLETED")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0].get("details") if rows else None


def calculate_compliance(bidder_id: str) -> dict[str, Any]:
    verification = run_verification(bidder_id)
    checks = verification.get("checks", [])
    hard_stop = bool(verification.get("blacklist_hard_stop"))
    score, breakdown = _score_checks(checks)
    ai_result = None if hard_stop else _latest_ai_result(bidder_id)
    failed_checks = [check for check in checks if check.get("status") == "FAIL"]
    review_checks = [check for check in checks if check.get("status") == "REVIEW"]
    reasons = [check.get("finding") for check in failed_checks + review_checks if check.get("finding")]

    if hard_stop:
        decision = "FAIL"
        recommendation = "FAIL"
        score = 0.0
        risk_level = "HIGH"
        reasons.insert(0, "Blacklist/debarment hard-stop")
    elif failed_checks:
        decision = "FAIL"
        recommendation = "FAIL"
        risk_level = _risk_level(score)
    elif review_checks or (ai_result and (ai_result.get("unresolved") or ai_result.get("requires_human_review"))):
        decision = "REVIEW"
        recommendation = "REVIEW"
        risk_level = _risk_level(score)
        if ai_result and ai_result.get("unresolved"):
            reasons.append("AI marked the verification result unresolved")
    elif score >= _threshold("COMPLIANCE_PASS_THRESHOLD", COMPLIANCE_PASS_THRESHOLD):
        decision = "PASS"
        recommendation = "PASS"
        risk_level = _risk_level(score)
    else:
        decision = "REVIEW" if score >= _threshold("COMPLIANCE_REVIEW_THRESHOLD", COMPLIANCE_REVIEW_THRESHOLD) else "FAIL"
        recommendation = decision
        risk_level = _risk_level(score)

    return {
        "bidder_id": bidder_id,
        "score": score,
        "risk_level": risk_level,
        "decision": decision,
        "recommendation": recommendation,
        "breakdown": breakdown,
        "reasons": reasons,
        "failed_checks": failed_checks,
        "review_checks": review_checks,
        "evidence_references": [check.get("source_reference") for check in checks if check.get("source_reference")],
        "ai_summary": ai_result,
        "verification": verification,
    }


def persist_compliance(result: dict[str, Any]) -> dict[str, Any]:
    row = {
        "bidder_id": result["bidder_id"],
        "score": result["score"],
        "risk_level": result["risk_level"],
        "recommendation": result["recommendation"],
        "ai_summary": result.get("ai_summary"),
    }
    response = supabase.table("compliance_scores").upsert(row, on_conflict="bidder_id").execute()
    write_audit_entry(
        result["bidder_id"],
        "COMPLIANCE_SCORE_CALCULATED",
        {
            "score": result["score"],
            "breakdown": result["breakdown"],
            "risk_level": result["risk_level"],
            "decision": result["decision"],
            "reasons": result["reasons"],
        },
    )
    return response.data[0] if isinstance(response.data, list) and response.data else response.data