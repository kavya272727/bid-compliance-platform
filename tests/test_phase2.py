import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import document_storage


class DocumentUploadTests(unittest.TestCase):
    client = TestClient(app)

    def test_successful_upload(self):
        expected = {
            "document_id": "document-1",
            "bidder_id": "bidder-1",
            "document_type": "PAN",
            "file_name": "pan.pdf",
            "storage_path": "bidder-1/PAN/generated.pdf",
            "ocr_status": "PENDING",
        }
        with patch("backend.routes.documents.bidder_exists", return_value=True):
            with patch(
                "backend.routes.documents.upload_document", return_value=expected
            ) as upload:
                response = self.client.post(
                    "/api/documents/upload",
                    data={"bidder_id": "bidder-1", "document_type": "pan"},
                    files={"uploaded_file": ("pan.pdf", b"pdf-data", "application/pdf")},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        upload.assert_called_once_with(
            bidder_id="bidder-1",
            document_type="PAN",
            file_name="pan.pdf",
            content_type="application/pdf",
            file_content=b"pdf-data",
        )

    def test_invalid_bidder_id(self):
        with patch("backend.routes.documents.bidder_exists", return_value=False):
            response = self.client.post(
                "/api/documents/upload",
                data={"bidder_id": "unknown", "document_type": "PAN"},
                files={"uploaded_file": ("pan.pdf", b"pdf-data", "application/pdf")},
            )

        self.assertEqual(response.status_code, 404)

    def test_unsupported_file_type(self):
        with patch("backend.routes.documents.bidder_exists", return_value=True):
            response = self.client.post(
                "/api/documents/upload",
                data={"bidder_id": "bidder-1", "document_type": "PAN"},
                files={"uploaded_file": ("pan.txt", b"text-data", "text/plain")},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported file type", response.json()["detail"])

    def test_invalid_document_type(self):
        response = self.client.post(
            "/api/documents/upload",
            data={"bidder_id": "bidder-1", "document_type": "INVOICE"},
            files={"uploaded_file": ("invoice.pdf", b"pdf-data", "application/pdf")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("document_type", response.json()["detail"])

    def test_storage_service_uploads_and_inserts_metadata(self):
        class Storage:
            def from_(self, bucket):
                self.bucket = bucket
                return self

            def upload(self, path, content, options):
                self.uploaded = (path, content, options)

        class Query:
            def insert(self, metadata):
                self.metadata = metadata
                return self

            def execute(self):
                return type("Response", (), {"data": [{"id": "document-1"}]})()

        class Supabase:
            def __init__(self):
                self.storage = Storage()
                self.query = Query()

            def table(self, table_name):
                self.table_name = table_name
                return self.query

        fake_supabase = Supabase()
        with patch.object(document_storage, "supabase", fake_supabase):
            result = document_storage.upload_document(
                "bidder-1", "GST", "folder/report.pdf", "application/pdf", b"pdf-data"
            )

        self.assertEqual(result["document_id"], "document-1")
        self.assertEqual(result["ocr_status"], "PENDING")
        self.assertTrue(result["storage_path"].startswith("bidder-1/GST/"))
        self.assertTrue(result["storage_path"].endswith(".pdf"))
        self.assertEqual(fake_supabase.storage.bucket, "bidder-documents")
        self.assertEqual(fake_supabase.query.metadata["file_name"], "folder/report.pdf")


if __name__ == "__main__":
    unittest.main()