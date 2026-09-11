from pathlib import PurePosixPath

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.services.document_storage import (
    SUPPORTED_DOCUMENT_TYPES,
    SUPPORTED_EXTENSIONS,
    bidder_exists,
    upload_document,
)
from backend.services.document_processing import process_document

router = APIRouter(prefix="/api/documents", tags=["Documents"])


@router.post("/{document_id}/process")
def process_uploaded_document(document_id: str):
    try:
        return process_document(document_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "OCR processing failed. Please manually re-upload a clearer or "
                "corrected document."
            ),
        ) from exc


@router.post("/upload")
async def upload_bidder_document(
    bidder_id: str = Form(...),
    document_type: str = Form(...),
    uploaded_file: UploadFile = File(...),
):
    bidder_id = bidder_id.strip()
    document_type = document_type.strip().upper()

    if not bidder_id:
        raise HTTPException(status_code=400, detail="bidder_id is required")
    if document_type not in SUPPORTED_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="document_type must be one of PAN, UDYAM, or GST",
        )
    try:
        bidder_found = bidder_exists(bidder_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Bidder lookup failed: {exc}") from exc
    if not bidder_found:
        raise HTTPException(status_code=404, detail=f"Bidder not found: {bidder_id}")

    extension = PurePosixPath(uploaded_file.filename or "").suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Accepted formats: PDF, PNG, JPG, JPEG",
        )

    try:
        file_content = await uploaded_file.read()
        return upload_document(
            bidder_id=bidder_id,
            document_type=document_type,
            file_name=uploaded_file.filename or "document" + extension,
            content_type=uploaded_file.content_type or "application/octet-stream",
            file_content=file_content,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Document upload failed: {exc}") from exc