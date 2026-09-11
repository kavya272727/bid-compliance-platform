import os
from typing import Any

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_groq_spec = spec_from_file_location(
    "phase4_groq_client", Path(__file__).parents[2] / "ai-engine" / "groq_client.py"
)
if _groq_spec is None or _groq_spec.loader is None:
    raise ImportError("Unable to load the Phase 4 Groq client")
_groq_module = module_from_spec(_groq_spec)
_groq_spec.loader.exec_module(_groq_module)
AIReasoningResult = _groq_module.AIReasoningResult
reason_about_verification = _groq_module.reason_about_verification
from .audit_log import write_audit_entry
from .verification_engine import run_verification


AI_CONFIDENCE_THRESHOLD = 0.70


def confidence_threshold() -> float:
    try:
        value = float(os.getenv("AI_CONFIDENCE_THRESHOLD", str(AI_CONFIDENCE_THRESHOLD)))
    except ValueError:
        return AI_CONFIDENCE_THRESHOLD
    return min(max(value, 0.0), 1.0)


def _ai_input(verification: dict[str, Any]) -> dict[str, Any]:
    return {
        "bidder_id": verification["bidder"].get("id"),
        "overall_decision": verification["overall_decision"],
        "checks": [
            {
                key: check.get(key)
                for key in ("verification_type", "status", "finding", "evidence", "confidence")
            }
            for check in verification.get("checks", [])
        ],
    }


def _final_confidence(result: AIReasoningResult, verification: dict[str, Any]) -> float:
    checks = verification.get("checks", [])
    if result.unresolved or not checks:
        evidence_quality = 0.60
    elif any(check.get("status") == "REVIEW" for check in checks):
        evidence_quality = 0.75
    else:
        evidence_quality = 0.90
    # Transparent MVP policy: average model confidence with evidence quality.
    return round((result.confidence + evidence_quality) / 2, 2)


def reason_for_bidder(bidder_id: str) -> dict[str, Any]:
    verification = run_verification(bidder_id)
    try:
        ai_result = reason_about_verification(_ai_input(verification))
        confidence = _final_confidence(ai_result, verification)
        threshold = confidence_threshold()
        requires_review = ai_result.unresolved or confidence < threshold
        response = {
            "bidder_id": bidder_id,
            "ai_status": "COMPLETED",
            "finding": ai_result.finding,
            "reasoning": ai_result.reasoning,
            "recommended_action": ai_result.recommended_action,
            "confidence": confidence,
            "unresolved": ai_result.unresolved,
            "requires_human_review": requires_review,
            "human_review_reason": "AI confidence below threshold" if confidence < threshold else "AI marked result unresolved" if ai_result.unresolved else None,
            "verification": verification,
        }
        write_audit_entry(bidder_id, "AI_REASONING_COMPLETED", {key: response[key] for key in ("finding", "reasoning", "recommended_action", "confidence", "unresolved", "requires_human_review")})
        return response
    except Exception as exc:
        try:
            write_audit_entry(bidder_id, "AI_REASONING_FAILED", {"error": str(exc), "requires_human_review": True})
        except Exception:
            pass
        return {
            "bidder_id": bidder_id,
            "ai_status": "FAILED",
            "requires_human_review": True,
            "human_review_reason": "AI reasoning service unavailable",
            "verification": verification,
        }