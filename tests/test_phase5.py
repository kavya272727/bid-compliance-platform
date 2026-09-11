import hashlib
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import audit_verification, compliance_engine


def verification(overall="PASS", hard_stop=False, statuses=None):
    statuses = statuses or ["PASS"]
    return {
        "bidder": {"id": "bidder-1"},
        "overall_decision": overall,
        "blacklist_hard_stop": hard_stop,
        "checks": [
            {"verification_type": "GST", "status": status, "finding": f"{status} check", "source_reference": "ref"}
            for status in statuses
        ],
    }


class FakeQuery:
    def __init__(self, rows, table_name):
        self.rows = rows
        self.table_name = table_name
        self.filters = {}
        self.values = None

    def select(self, _columns): return self
    def eq(self, key, value): self.filters[key] = value; return self
    def order(self, _column, desc=False): return self
    def limit(self, _count): return self
    def upsert(self, values, on_conflict=None): self.values = values; return self
    def insert(self, values): self.values = values; return self
    def execute(self):
        matching = [row for row in self.rows if all(row.get(key) == value for key, value in self.filters.items())]
        if self.values is not None:
            if isinstance(self.values, list): self.rows.extend(self.values)
            else: self.rows.append(self.values)
            return type("Response", (), {"data": self.values if isinstance(self.values, list) else [self.values]})()
        return type("Response", (), {"data": matching})()


class FakeSupabase:
    def __init__(self):
        self.tables = {"compliance_scores": [], "audit_log": []}

    def table(self, table_name): return FakeQuery(self.tables[table_name], table_name)


class ComplianceTests(unittest.TestCase):
    def run_result(self, verification_result, ai=None):
        with patch.object(compliance_engine, "run_verification", return_value=verification_result):
            with patch.object(compliance_engine, "_latest_ai_result", return_value=ai):
                return compliance_engine.calculate_compliance("bidder-1")

    def test_weights_sum_to_100_and_breakdown_is_transparent(self):
        result = self.run_result(verification())
        self.assertEqual(sum(compliance_engine.SCORING_WEIGHTS.values()), 1.0)
        self.assertEqual(set(result["breakdown"]), set(compliance_engine.SCORING_WEIGHTS))

    def test_blacklist_forces_zero_high_fail(self):
        result = self.run_result(verification("FAIL", True, ["PASS"]))
        self.assertEqual((result["score"], result["risk_level"], result["decision"]), (0.0, "HIGH", "FAIL"))

    def test_explicit_fail_precedes_review(self):
        result = self.run_result(verification("FAIL", False, ["FAIL", "REVIEW"]))
        self.assertEqual(result["decision"], "FAIL")

    def test_review_condition_prevents_pass(self):
        result = self.run_result(verification("REVIEW", False, ["REVIEW"]))
        self.assertEqual(result["decision"], "REVIEW")

    def test_low_confidence_ai_requires_review(self):
        result = self.run_result(verification(), {"confidence": 0.55, "unresolved": False, "requires_human_review": True})
        self.assertEqual(result["decision"], "REVIEW")

    def test_unresolved_ai_requires_review(self):
        result = self.run_result(verification(), {"confidence": 0.95, "unresolved": True, "requires_human_review": True})
        self.assertEqual(result["decision"], "REVIEW")

    def test_score_and_audit_persist(self):
        fake = FakeSupabase()
        result = self.run_result(verification())
        with patch.object(compliance_engine, "supabase", fake):
            with patch.object(compliance_engine, "write_audit_entry") as audit:
                row = compliance_engine.persist_compliance(result)
        self.assertEqual(row["score"], result["score"])
        audit.assert_called_once()


class AuditVerificationTests(unittest.TestCase):
    def make_entry(self, previous, details, created_at, entry_id):
        entry = {"id": entry_id, "bidder_id": "bidder-1", "action": "TEST", "actor": None, "details": details, "created_at": created_at, "prev_hash": previous}
        payload = {key: entry[key] for key in ("bidder_id", "action", "details", "created_at", "prev_hash")}
        entry["entry_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        return entry

    def test_chain_valid_then_tamper_is_detected(self):
        first = self.make_entry(None, {"step": 1}, "2026-01-01T00:00:00+00:00", "entry-1")
        second = self.make_entry(first["entry_hash"], {"step": 2}, "2026-01-01T00:00:01+00:00", "entry-2")
        rows = [first, second]
        fake = type("Supabase", (), {"table": lambda _self, _name: FakeQuery(rows, "audit_log")})()
        with patch.object(audit_verification, "supabase", fake):
            self.assertTrue(audit_verification.verify_audit_chain("bidder-1")["valid"])
            second["details"]["step"] = "tampered"
            result = audit_verification.verify_audit_chain("bidder-1")
        self.assertFalse(result["valid"])
        self.assertEqual(result["first_invalid_entry"], "entry-2")


class ComplianceRouteTests(unittest.TestCase):
    client = TestClient(app)

    def test_score_endpoint_returns_persistence_flags(self):
        result = {"bidder_id": "bidder-1", "score": 82.5, "risk_level": "LOW", "decision": "PASS"}
        with patch("backend.routes.compliance.calculate_compliance", return_value=result):
            with patch("backend.routes.compliance.persist_compliance"):
                response = self.client.post("/api/compliance/score/bidder-1")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["score_persisted"])
        self.assertTrue(response.json()["audit_persisted"])

    def test_score_endpoint_reports_persistence_failure(self):
        result = {"bidder_id": "bidder-1", "score": 82.5, "risk_level": "LOW", "decision": "PASS"}
        with patch("backend.routes.compliance.calculate_compliance", return_value=result):
            with patch("backend.routes.compliance.persist_compliance", side_effect=RuntimeError("database unavailable")):
                response = self.client.post("/api/compliance/score/bidder-1")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["score_persisted"])
        self.assertIn("database unavailable", response.json()["persistence_error"])


if __name__ == "__main__":
    unittest.main()