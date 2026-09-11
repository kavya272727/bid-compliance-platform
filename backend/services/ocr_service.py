from io import BytesIO
import os
from pathlib import PurePosixPath
import shutil

import pypdfium2 as pdfium
import pytesseract
from PIL import Image

from .document_storage import STORAGE_BUCKET
from .supabase_client import supabase


DEFAULT_TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def configure_tesseract() -> str | None:
    configured_command = os.getenv("TESSERACT_CMD")
    if configured_command and os.path.isfile(configured_command):
        pytesseract.pytesseract.tesseract_cmd = configured_command
        return configured_command

    if os.path.isfile(DEFAULT_TESSERACT_CMD):
        pytesseract.pytesseract.tesseract_cmd = DEFAULT_TESSERACT_CMD
        return DEFAULT_TESSERACT_CMD

    path_command = shutil.which("tesseract")
    if path_command:
        pytesseract.pytesseract.tesseract_cmd = path_command
        return path_command

    return None


configure_tesseract()


def _download_document(storage_path: str) -> bytes:
    return supabase.storage.from_(STORAGE_BUCKET).download(storage_path)


def _ocr_image(image: Image.Image) -> str:
    text = pytesseract.image_to_string(image)
    if not text.strip():
        raise RuntimeError("OCR returned no text")
    return text.strip()


def _ocr_pdf(file_content: bytes) -> str:
    pdf = pdfium.PdfDocument(file_content)
    pages = []
    for page_index in range(len(pdf)):
        page = pdf[page_index]
        bitmap = page.render(scale=2)
        pages.append(_ocr_image(bitmap.to_pil()))
        page.close()
    text = "\n".join(pages).strip()
    if not text:
        raise RuntimeError("OCR returned no text")
    return text


def extract_text(storage_path: str) -> str:
    file_content = _download_document(storage_path)
    extension = PurePosixPath(storage_path).suffix.lower()

    if extension == ".pdf":
        return _ocr_pdf(file_content)
    if extension in {".png", ".jpg", ".jpeg"}:
        with Image.open(BytesIO(file_content)) as image:
            return _ocr_image(image)
    raise ValueError("Unsupported document format for OCR")