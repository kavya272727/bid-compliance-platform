import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import verification_engine


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, tables, table_name):
        self.tables = tables
        self.table_name = table_name
        self.filters = {}

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, _count):
        return self

    def single(self):
        return self

    def execute(self):
        records = [
            record
            for record in self.tables.get(self.table_name, [])
            if all(record.get(column) == value for column, value in self.filters.items())
        ]
        return FakeResponse(records[0] if self.filters.get("id") else records)


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, table_name):
        return FakeQuery(self.tables, table_name)


class MockGovernmentRouteTests(unittest.TestCase):
    client = TestClient(app)

    def test_gst_endpoint_returns_record(self):
        record = {"source_type": "GST", "identifier": "GST123", "status": "ACTIVE"}
        with patch("backend.routes.mock_government.get_gst_status", return_value=record):
            response = self.client.get("/api/mock/gst/GST123")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), record)

    def test_udyam_endpoint_returns_record(self):
        record = {"source_type": "UDYAM", "identifier": "UDYAM123", "status": "VALID"}
        with patch("backend.routes.mock_government.get_udyam_status", return_value=record):
            response = self.client.get("/api/mock/udyam/UDYAM123")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), record)

    def test_pan_endpoint_returns_record(self):
        record = {"source_type": "PAN", "identifier": "PAN123", "status": "MATCH"}
        with patch("backend.routes.mock_government.get_pan_status", return_value=record):
            response = self.client.get("/api/mock/pan/PAN123")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), record)

    def test_blacklist_endpoint_returns_record(self):
        record = {"source_type": "BLACKLIST", "identifier": "PAN123", "status": "CLEAR"}
        with patch("backend.routes.mock_government.get_blacklist_status", return_value=record):
            response = self.client.get("/api/mock/blacklist/PAN123")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), record)

    def test_missing_record_returns_not_found(self):
        with patch("backend.routes.mock_government.get_pan_status", return_value=None):
            response = self.client.get("/api/mock/pan/UNKNOWN")
        self.assertEqual(response.status_code, 404)

    def test_blank_identifier_returns_bad_request(self):
        with patch(
            "backend.routes.mock_government.get_pan_status",
            side_effect=ValueError("Identifier cannot be blank"),
        ):
            response = self.client.get("/api/mock/pan/%20")
        self.assertEqual(response.status_code, 400)


class VerificationEngineTests(unittest.TestCase):
    def run_for(self, bidder_id, records):
        tables = {
            "bidders": [{
                "id": bidder_id,
                "name": bidder_id,
                "pan": next((record.get("identifier") for record in records if record.get("source_type") == "BLACKLIST"), "TESTPAN1234"),
            }],
            "mock_government_verification_records": records,
        }
        blacklist_record = next(
            (record for record in records if record.get("source_type") == "BLACKLIST"),
            None,
        )
        with patch.object(verification_engine, "supabase", FakeSupabase(tables)):
            with patch.object(
                verification_engine,
                "get_blacklist_status",
                return_value=blacklist_record,
            ):
                return verification_engine.run_verification(bidder_id)

    def test_blacklist_is_hard_stop(self):
        result = self.run_for(
            "BLACKLISTED",
            [{
                "bidder_id": "BLACKLISTED",
                "source_type": "BLACKLIST",
                "identifier": "BLACK3456J",
                "status": "BLACKLISTED",
            }],
        )
        self.assertEqual(result["overall_decision"], "FAIL")
        self.assertTrue(result["blacklist_hard_stop"])

    def test_clean_bidder_passes(self):
        result = self.run_for(
            "CLEAN",
            [{"bidder_id": "CLEAN", "source_type": "GST", "status": "ACTIVE"}],
        )
        self.assertEqual(result["overall_decision"], "PASS")

    def test_inconsistent_bidder_requires_review(self):
        result = self.run_for(
            "INCONSISTENT",
            [{"bidder_id": "INCONSISTENT", "source_type": "PAN", "status": "MISMATCH"}],
        )
        self.assertEqual(result["overall_decision"], "REVIEW")

    def test_missing_data_bidder_requires_review(self):
        result = self.run_for(
            "MISSING_DATA",
            [{"bidder_id": "MISSING_DATA", "source_type": "GST", "status": "MISSING"}],
        )
        self.assertEqual(result["overall_decision"], "REVIEW")


if __name__ == "__main__":
    unittest.main()