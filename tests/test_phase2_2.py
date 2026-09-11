import unittest
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import document_processing
from backend.services.document_extractor import extract_document_data
from backend.services import ocr_service


class FakeResponse:
    def __init__(self, data):
        self.data = data


class DocumentQuery:
    def __init__(self, database, operation="select", values=None):
        self.database = database
        self.operation = operation
        self.values = values
        self.document_id = None

    def select(self, _columns):
        self.operation = "select"
        return self

    def update(self, values):
        self.operation = "update"
        self.values = values
        return self

    def eq(self, column, value):
        if column == "id":
            self.document_id = value
        return self

    def limit(self, _count):
        return self

    def execute(self):
        if self.operation == "select":
            document = self.database.get(self.document_id)
            return FakeResponse([document] if document else [])
        self.database[self.document_id].update(self.values)
        return FakeResponse([self.database[self.document_id]])


class FakeSupabase:
    def __init__(self, documents):
        self.documents = documents

    def table(self, _table_name):
        return DocumentQuery(self.documents)


def document(document_type):
    return {
        "id": "document-1",
        "bidder_id": "bidder-1",
        "document_type": document_type,
        "file_name": f"{document_type.lower()}.pdf",
        "storage_path": f"bidder-1/{document_type}/document.pdf",
        "ocr_status": "PENDING",
    }


class DocumentProcessingTests(unittest.TestCase):
    def process_with_text(self, document_type, text):
        documents = {"document-1": document(document_type)}
        with patch.object(document_processing, "supabase", FakeSupabase(documents)):
            with patch.object(document_processing, "extract_text", return_value=text):
                result = document_processing.process_document("document-1")
        return result, documents["document-1"]

    def test_successful_pan_ocr_and_extraction(self):
        result, stored = self.process_with_text(
            "PAN", "Name: ACME TEST COMPANY\nPAN Number: ABCDE1234F"
        )
        self.assertEqual(result["ocr_status"], "COMPLETED")
        self.assertEqual(result["extracted_data"]["pan_number"], "ABCDE1234F")
        self.assertEqual(result["extracted_data"]["name"], "ACME TEST COMPANY")
        self.assertEqual(stored["ocr_status"], "COMPLETED")
        self.assertEqual(stored["extracted_text"], "Name: ACME TEST COMPANY\nPAN Number: ABCDE1234F")

    def test_successful_udyam_ocr_and_extraction(self):
        result, stored = self.process_with_text(
            "UDYAM",
            "Enterprise Name: ACME INDUSTRIES\nUdyam Registration Number: UDYAM-MH-12-1234567",
        )
        self.assertEqual(result["ocr_status"], "COMPLETED")
        self.assertEqual(
            result["extracted_data"]["udyam_registration_number"],
            "UDYAM-MH-12-1234567",
        )
        self.assertEqual(result["extracted_data"]["enterprise_name"], "ACME INDUSTRIES")
        self.assertEqual(stored["ocr_status"], "COMPLETED")

    def test_successful_gst_ocr_and_extraction(self):
        result, stored = self.process_with_text(
            "GST",
            "Legal Name: ACME TRADING\nGSTIN: 27ABCDE1234F1Z5",
        )
        self.assertEqual(result["ocr_status"], "COMPLETED")
        self.assertEqual(result["extracted_data"]["gstin"], "27ABCDE1234F1Z5")
        self.assertEqual(result["extracted_data"]["legal_business_name"], "ACME TRADING")
        self.assertEqual(stored["ocr_status"], "COMPLETED")

    def test_ocr_failure_updates_database_to_failed(self):
        documents = {"document-1": document("PAN")}
        with patch.object(document_processing, "supabase", FakeSupabase(documents)):
            with patch.object(
                document_processing, "extract_text", side_effect=RuntimeError("OCR unavailable")
            ):
                with self.assertRaises(RuntimeError):
                    document_processing.process_document("document-1")
        self.assertEqual(documents["document-1"]["ocr_status"], "FAILED")

    def test_missing_document(self):
        with patch.object(document_processing, "supabase", FakeSupabase({})):
            with self.assertRaises(LookupError):
                document_processing.process_document("missing")

    def test_unsupported_document_type(self):
        documents = {"document-1": document("INVOICE")}
        with patch.object(document_processing, "supabase", FakeSupabase(documents)):
            with self.assertRaises(ValueError):
                document_processing.process_document("document-1")


class DocumentProcessingRouteTests(unittest.TestCase):
    client = TestClient(app)

    def test_missing_document_endpoint_returns_not_found(self):
        with patch(
            "backend.routes.documents.process_document",
            side_effect=LookupError("Document not found: missing"),
        ):
            response = self.client.post("/api/documents/missing/process")
        self.assertEqual(response.status_code, 404)

    def test_successful_process_endpoint_returns_safe_metadata(self):
        result = {
            "document_id": "document-1",
            "document_type": "PAN",
            "ocr_status": "COMPLETED",
            "extracted_data": {"pan_number": "ABCDE1234F", "name": "ACME TEST"},
        }
        with patch("backend.routes.documents.process_document", return_value=result):
            response = self.client.post("/api/documents/document-1/process")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result)

    def test_unsupported_document_endpoint_returns_bad_request(self):
        with patch(
            "backend.routes.documents.process_document",
            side_effect=ValueError("Unsupported document type"),
        ):
            response = self.client.post("/api/documents/document-1/process")
        self.assertEqual(response.status_code, 400)

    def test_ocr_failure_endpoint_returns_server_error(self):
        with patch(
            "backend.routes.documents.process_document",
            side_effect=RuntimeError("OCR unavailable"),
        ):
            response = self.client.post("/api/documents/document-1/process")
        self.assertEqual(response.status_code, 500)
        self.assertIn("re-upload", response.json()["detail"])
        self.assertIn("corrected", response.json()["detail"])


class ExtractorTests(unittest.TestCase):
    def test_extractors_are_document_type_specific(self):
        self.assertEqual(
            extract_document_data("PAN", "ABCDE1234F")["pan_number"], "ABCDE1234F"
        )
        self.assertEqual(
            extract_document_data("UDYAM", "UDYAM-DL-01-1234567")["udyam_registration_number"],
            "UDYAM-DL-01-1234567",
        )
        self.assertEqual(
            extract_document_data("GST", "27ABCDE1234F1Z5")["gstin"],
            "27ABCDE1234F1Z5",
        )


class OcrServiceTests(unittest.TestCase):
    def test_tesseract_command_uses_environment_configuration(self):
        with patch.dict(os.environ, {"TESSERACT_CMD": "C:\\custom\\tesseract.exe"}):
            with patch.object(ocr_service.os.path, "isfile", return_value=True):
                with patch.object(ocr_service.pytesseract.pytesseract, "tesseract_cmd", "original"):
                    configured = ocr_service.configure_tesseract()
        self.assertEqual(configured, "C:\\custom\\tesseract.exe")

    def test_image_ocr_dispatches_to_tesseract(self):
        with patch.object(ocr_service, "_download_document", return_value=b"image"):
            with patch.object(ocr_service.Image, "open") as image_open:
                with patch.object(ocr_service, "_ocr_image", return_value="PAN text") as ocr:
                    self.assertEqual(ocr_service.extract_text("bidder/PAN/file.png"), "PAN text")
        image_open.assert_called_once()
        ocr.assert_called_once()

    def test_pdf_ocr_dispatches_to_pdf_processor(self):
        with patch.object(ocr_service, "_download_document", return_value=b"pdf"):
            with patch.object(ocr_service, "_ocr_pdf", return_value="GST text") as ocr:
                self.assertEqual(ocr_service.extract_text("bidder/GST/file.pdf"), "GST text")
        ocr.assert_called_once_with(b"pdf")


if __name__ == "__main__":
    unittest.main()