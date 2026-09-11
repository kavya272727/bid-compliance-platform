from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from .supabase_client import supabase


STORAGE_BUCKET = "bidder-documents"
SUPPORTED_DOCUMENT_TYPES = {"PAN", "UDYAM", "GST"}
SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


def bidder_exists(bidder_id: str) -> bool:
    response = (
        supabase.table("bidders")
        .select("id")
        .eq("id", bidder_id)
        .limit(1)
        .execute()
    )
    return bool(response.data)


def upload_document(
    bidder_id: str,
    document_type: str,
    file_name: str,
    content_type: str,
    file_content: bytes,
) -> dict[str, Any]:
    extension = PurePosixPath(file_name).suffix.lower()
    storage_path = (
        f"{bidder_id}/{document_type}/{uuid4().hex}{extension}"
    )
    storage = supabase.storage.from_(STORAGE_BUCKET)

    storage.upload(
        storage_path,
        file_content,
        {"content-type": content_type, "upsert": False},
    )

    metadata = {
        "bidder_id": bidder_id,
        "document_type": document_type,
        "file_name": file_name,
        "storage_path": storage_path,
        "ocr_status": "PENDING",
    }

    try:
        response = supabase.table("documents").insert(metadata).execute()
    except Exception:
        try:
            storage.remove([storage_path])
        except Exception:
            pass
        raise

    inserted = response.data[0] if isinstance(response.data, list) else response.data
    if not inserted:
        raise RuntimeError("Document metadata was not created")

    return {
        "document_id": inserted.get("id"),
        **metadata,
    }