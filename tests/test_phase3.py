import unittest
from unittest.mock import patch

from backend.services import verification_engine
from backend.services.verification_rules import cross_document_checks, tender_requirement_checks


class FakeResponse:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, tables, table_name):
        self.tables = tables
        self.table_name = table_name
        self.filters = {}
        self.inserted = None

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, _count):
        return self

    def single(self):
        return self

    def insert(self, rows):
        self.inserted = rows
        self.tables.setdefault("verification_checks", []).extend(rows)
        return self

    def execute(self):
        records = [
            row for row in self.tables.get(self.table_name, [])
            if all(row.get(key) == value for key, value in self.filters.items())
        ]
        return FakeResponse(records[0] if self.filters.get("id") else records)


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables
        self.queries = []

    def table(self, table_name):
        query = Query(self.tables, table_name)
        self.queries.append(query)
        return query


def bidder(name="Acme Security Pvt Ltd"):
    return {
        "id": "bidder-1",
        "tender_id": "tender-1",
        "company_name": name,
        "pan": "ABCDE1234F",
        "gstin": "27ABCDE1234F1Z5",
        "udyam_number": "UDYAM-DL-01-1234567",
    }


class Phase3EngineTests(unittest.TestCase):
    def test_blacklisted_bidder_short_circuits_before_remaining_pipeline(self):
        fake = FakeSupabase({"bidders": [bidder()]})
        blacklist = {"source_type": "BLACKLIST", "status": "BLACKLISTED", "identifier": "ABCDE1234F"}
        with patch.object(verification_engine, "supabase", fake):
            with patch.object(verification_engine, "get_blacklist_status", return_value=blacklist):
                with patch.object(verification_engine, "get_mock_records") as government:
                    with patch.object(verification_engine, "get_documents") as documents:
                        with patch.object(verification_engine, "get_tender_requirements") as requirements:
                            result = verification_engine.run_verification("bidder-1")
        self.assertEqual(result["overall_decision"], "FAIL")
        self.assertTrue(result["blacklist_hard_stop"])
        government.assert_not_called()
        documents.assert_not_called()
        requirements.assert_not_called()

    def test_structured_government_checks_persist(self):
        fake = FakeSupabase({"bidders": [bidder()]})
        records = [{"source_type": "GST", "status": "ACTIVE", "identifier": "27ABCDE1234F1Z5"}]
        with patch.object(verification_engine, "supabase", fake):
            with patch.object(verification_engine, "get_blacklist_status", return_value=None):
                with patch.object(verification_engine, "get_mock_records", return_value=records):
                    with patch.object(verification_engine, "get_documents", return_value=[]):
                        with patch.object(verification_engine, "get_tender_requirements", return_value=[]):
                            result = verification_engine.run_verification("bidder-1")
        self.assertEqual(result["overall_decision"], "PASS")
        self.assertEqual(result["checks"][0]["verification_type"], "GST")
        self.assertTrue(fake.tables["verification_checks"])
        self.assertEqual(fake.tables["verification_checks"][0]["status"], "PASS")


class CrossDocumentTests(unittest.TestCase):
    def docs(self, gst_name="Acme Security Pvt Ltd", udyam_name="Acme Security Pvt Ltd"):
        return [
            {"document_type": "PAN", "extracted_data": {"name": "Acme Security Pvt Ltd"}},
            {"document_type": "GST", "extracted_data": {"legal_business_name": gst_name}},
            {"document_type": "UDYAM", "extracted_data": {"enterprise_name": udyam_name}},
        ]

    def test_exact_names_pass(self):
        checks = cross_document_checks(self.docs(), "bidder-1")
        self.assertTrue(all(check["status"] == "PASS" for check in checks))

    def test_minor_name_variation_is_not_failure(self):
        checks = cross_document_checks(self.docs("ACME SECURITY PVT. LTD"), "bidder-1")
        self.assertIn(checks[0]["status"], {"PASS", "REVIEW"})
        self.assertNotEqual(checks[0]["status"], "FAIL")

    def test_major_name_mismatch_requires_review(self):
        checks = cross_document_checks(self.docs("Different Trading Company"), "bidder-1")
        self.assertEqual(checks[0]["status"], "REVIEW")


class TenderRuleTests(unittest.TestCase):
    def requirement(self, name):
        return {"id": name, "requirement_type": "DOCUMENT", "requirement_name": name, "mandatory": True}

    def test_mandatory_document_missing_requires_review(self):
        checks = tender_requirement_checks([self.requirement("PAN Certificate")], [], bidder())
        self.assertEqual(checks[0]["status"], "REVIEW")

    def test_mandatory_document_present_passes(self):
        checks = tender_requirement_checks(
            [self.requirement("PAN Certificate")],
            [{"document_type": "PAN"}],
            bidder(),
        )
        self.assertEqual(checks[0]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()