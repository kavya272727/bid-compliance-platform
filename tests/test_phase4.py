import hashlib
import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import ai_reasoning, audit_log
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_groq_spec = spec_from_file_location("test_groq_client", Path(__file__).parents[1] / "ai-engine" / "groq_client.py")
_groq_module = module_from_spec(_groq_spec)
_groq_spec.loader.exec_module(_groq_module)


class FakeResult:
    def __init__(self, **values):
        self.__dict__.update(values)


def verification_result(status="REVIEW"):
    return {
        "bidder": {"id": "bidder-1"},
        "overall_decision": status,
        "checks": [{
            "verification_type": "PAN_GST_NAME_MATCH",
            "status": status,
            "finding": "Legal names differ",
            "evidence": "PAN: ACME | GST: OTHER",
            "confidence": 0.9,
        }],
    }


class AIReasoningTests(unittest.TestCase):
    def call(self, result):
        with patch.object(ai_reasoning, "run_verification", return_value=verification_result()):
            with patch.object(ai_reasoning, "reason_about_verification", return_value=result):
                with patch.object(ai_reasoning, "write_audit_entry") as audit:
                    response = ai_reasoning.reason_for_bidder("bidder-1")
        return response, audit

    def test_high_confidence_result_does_not_require_review(self):
        result, audit = self.call(FakeResult(
            finding="Names require clarification", reasoning="The structured flag reports a mismatch.",
            recommended_action="Request clarification.", confidence=0.95, unresolved=False,
        ))
        self.assertEqual(result["ai_status"], "COMPLETED")
        self.assertFalse(result["requires_human_review"])
        audit.assert_called_once()

    def test_low_confidence_requires_review(self):
        result, _ = self.call(FakeResult(finding="unclear", reasoning="insufficient", recommended_action="Review", confidence=0.55, unresolved=False))
        self.assertTrue(result["requires_human_review"])

    def test_unresolved_requires_review(self):
        result, _ = self.call(FakeResult(finding="unresolved", reasoning="missing evidence", recommended_action="Review", confidence=0.95, unresolved=True))
        self.assertTrue(result["requires_human_review"])

    def test_groq_failure_routes_to_review(self):
        with patch.object(ai_reasoning, "run_verification", return_value=verification_result()):
            with patch.object(ai_reasoning, "reason_about_verification", side_effect=RuntimeError("timeout")):
                with patch.object(ai_reasoning, "write_audit_entry"):
                    result = ai_reasoning.reason_for_bidder("bidder-1")
        self.assertEqual(result["ai_status"], "FAILED")
        self.assertTrue(result["requires_human_review"])

    def test_missing_api_key_routes_to_review(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(ai_reasoning, "run_verification", return_value=verification_result()):
                with patch.object(ai_reasoning, "reason_about_verification", side_effect=RuntimeError("missing key")):
                    with patch.object(ai_reasoning, "write_audit_entry"):
                        result = ai_reasoning.reason_for_bidder("bidder-1")
        self.assertEqual(result["ai_status"], "FAILED")
        self.assertTrue(result["requires_human_review"])

    def test_malformed_or_invalid_structured_result_is_failure(self):
        with patch.object(ai_reasoning, "run_verification", return_value=verification_result()):
            with patch.object(ai_reasoning, "reason_about_verification", side_effect=ValueError("invalid JSON")):
                with patch.object(ai_reasoning, "write_audit_entry"):
                    result = ai_reasoning.reason_for_bidder("bidder-1")
        self.assertEqual(result["ai_status"], "FAILED")

    def test_ai_input_contains_only_structured_flags(self):
        result = verification_result()
        payload = ai_reasoning._ai_input(result)
        self.assertEqual(set(payload), {"bidder_id", "overall_decision", "checks"})
        self.assertEqual(set(payload["checks"][0]), {"verification_type", "status", "finding", "evidence", "confidence"})
        self.assertNotIn("Ignore previous instructions", json.dumps(payload))

    def test_confidence_threshold_is_configurable(self):
        with patch.dict(os.environ, {"AI_CONFIDENCE_THRESHOLD": "0.85"}):
            self.assertEqual(ai_reasoning.confidence_threshold(), 0.85)


class GroqSchemaTests(unittest.TestCase):
    def test_response_schema_rejects_extra_evidence(self):
        with self.assertRaises(Exception):
            _groq_module.AIReasoningResult.model_validate({
                "finding": "x", "reasoning": "y", "recommended_action": "z",
                "confidence": 0.9, "unresolved": False, "evidence": "invented",
            })

    def test_response_schema_rejects_invalid_confidence(self):
        with self.assertRaises(Exception):
            _groq_module.AIReasoningResult.model_validate({
                "finding": "x", "reasoning": "y", "recommended_action": "z",
                "confidence": 1.5, "unresolved": False,
            })


class AuditChainTests(unittest.TestCase):
    def test_audit_entry_hash_chains_from_previous_entry(self):
        rows = [{"entry_hash": "previous-hash"}]

        class Query:
            def select(self, _columns): return self
            def eq(self, _column, _value): return self
            def order(self, _column, desc=False): return self
            def limit(self, _count): return self
            def insert(self, row): self.inserted = row; return self
            def execute(self): return type("Response", (), {"data": rows if not hasattr(self, "inserted") else [self.inserted]})()

        class Supabase:
            def table(self, _table): return Query()

        with patch.object(audit_log, "supabase", Supabase()):
            row = audit_log.write_audit_entry("bidder-1", "AI_REASONING_COMPLETED", {"confidence": 0.9})
        self.assertEqual(row["prev_hash"], "previous-hash")
        payload = {key: row[key] for key in ("bidder_id", "action", "details", "created_at", "prev_hash")}
        expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        self.assertEqual(row["entry_hash"], expected)


class AIRouteTests(unittest.TestCase):
    def test_route_returns_failure_safely(self):
        client = TestClient(app)
        result = {"ai_status": "FAILED", "requires_human_review": True, "human_review_reason": "AI reasoning service unavailable"}
        with patch("backend.routes.ai_reasoning.reason_for_bidder", return_value=result):
            response = client.post("/api/ai/reason/bidder-1")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["requires_human_review"])


if __name__ == "__main__":
    unittest.main()