from typing import Any

from .document_extractor import extract_document_data
from .document_storage import SUPPORTED_DOCUMENT_TYPES
from .ocr_service import extract_text
from .supabase_client import supabase


def get_document(document_id: str) -> dict[str, Any] | None:
    response = (
        supabase.table("documents")
        .select("id,bidder_id,document_type,file_name,storage_path,ocr_status")
        .eq("id", document_id)
        .limit(1)
        .execute()
    )
    documents = response.data or []
    return documents[0] if documents else None


def _update_document(document_id: str, values: dict[str, Any]) -> None:
    supabase.table("documents").update(values).eq("id", document_id).execute()


def process_document(document_id: str) -> dict[str, Any]:
    document = get_document(document_id)
    if document is None:
        raise LookupError(f"Document not found: {document_id}")

    document_type = (document.get("document_type") or "").upper()
    if document_type not in SUPPORTED_DOCUMENT_TYPES:
        raise ValueError("Unsupported document type. Supported types: PAN, UDYAM, GST")

    try:
        text = extract_text(document["storage_path"])
        extracted_data = extract_document_data(document_type, text)
        _update_document(
            document_id,
            {
                "extracted_text": text,
                "extracted_data": extracted_data,
                "ocr_status": "COMPLETED",
            },
        )
        return {
            "document_id": document_id,
            "document_type": document_type,
            "ocr_status": "COMPLETED",
            "extracted_data": extracted_data,
        }
    except Exception:
        try:
            _update_document(document_id, {"ocr_status": "FAILED"})
        except Exception:
            pass
        raise