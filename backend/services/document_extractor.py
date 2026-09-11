import re


PAN_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
UDYAM_PATTERN = re.compile(r"\bUDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7}\b", re.IGNORECASE)
GSTIN_PATTERN = re.compile(
    r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b"
)


def _label_value(text: str, labels: tuple[str, ...]) -> str | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{label_pattern})\s*[:\-]?\s*([^\n\r]+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def extract_pan_data(text: str) -> dict[str, str | None]:
    return {
        "pan_number": next((match.upper() for match in PAN_PATTERN.findall(text)), None),
        "name": _label_value(text, ("Name", "Holder Name")),
    }


def extract_udyam_data(text: str) -> dict[str, str | None]:
    return {
        "udyam_registration_number": next(
            (match.upper() for match in UDYAM_PATTERN.findall(text)), None
        ),
        "enterprise_name": _label_value(text, ("Enterprise Name", "Company Name")),
    }


def extract_gst_data(text: str) -> dict[str, str | None]:
    return {
        "gstin": next((match.upper() for match in GSTIN_PATTERN.findall(text)), None),
        "legal_business_name": _label_value(
            text, ("Legal Name", "Legal Business Name", "Business Name")
        ),
    }


def extract_document_data(document_type: str, text: str) -> dict[str, str | None]:
    normalized_type = document_type.strip().upper()
    if normalized_type == "PAN":
        return extract_pan_data(text)
    if normalized_type == "UDYAM":
        return extract_udyam_data(text)
    if normalized_type == "GST":
        return extract_gst_data(text)
    raise ValueError("Unsupported document type. Supported types: PAN, UDYAM, GST")