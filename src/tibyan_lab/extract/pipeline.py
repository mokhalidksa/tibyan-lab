"""Invoice extraction: checks the upload, asks the provider, then validates and shapes
the answer into tibyan-lab/document-extraction@1 (tibyan-web docs/lab-api.md).

* Upload: PDF, PNG, JPEG or WebP, at most 5 MB and 3 pages, read in memory.
* Fields: every ID in FIELD_IDS is always present; a missing one has value null.
* Values: dates normalised to ISO 8601, money to a decimal string, currency to a
  three-letter code. A value that does not parse is kept as read and flagged low.
* Confidence: "high" only when the model is at least 0.8 sure, the value parsed and
  no check failed. Everything else is "low", for a person to review.
* Check: the line item amounts must add up to the subtotal. When they do not, the
  subtotal and every line amount are flagged low.
"""

from __future__ import annotations

import base64
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .. import errors
from ..settings import Settings
from .provider import FIELD_IDS, Document, LineItem, Provider, Reading

FIELD_NAMES = {
    "vendor": "Vendor",
    "invoice_number": "Invoice number",
    "invoice_date": "Invoice date",
    "due_date": "Due date",
    "currency": "Currency",
    "subtotal": "Subtotal",
    "tax": "Tax",
    "total": "Total",
}
FIELD_TYPES = {
    "vendor": "text",
    "invoice_number": "identifier",
    "invoice_date": "date",
    "due_date": "date",
    "currency": "currency",
    "subtotal": "money",
    "tax": "money",
    "total": "money",
}
LINE_ITEM_FIELDS = {
    "description": ("Description", "text"),
    "quantity": ("Quantity", "number"),
    "unit_price": ("Unit price", "money"),
    "amount": ("Amount", "money"),
}
CONFIDENT = 0.8
MEDIA_TYPES = {
    b"%PDF-": "application/pdf",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}


def sniff(data: bytes) -> str:
    """The media type from the file's own first bytes, never from its name."""
    for magic, media_type in MEDIA_TYPES.items():
        if data.startswith(magic):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise errors.LabError("unsupported_type", 415, "The file must be a PDF, PNG, JPEG or WebP image.")


def count_pages(data: bytes, media_type: str) -> int:
    if media_type != "application/pdf":
        return 1
    return max(1, len(re.findall(rb"/Type\s*/Page(?![s\w])", data)))


def load_document(data: bytes, settings: Settings) -> Document:
    if len(data) > settings.max_upload_bytes:
        raise errors.too_large(settings.max_upload_bytes)
    media_type = sniff(data)
    pages = count_pages(data, media_type)
    if pages > settings.max_pages:
        raise errors.LabError(
            "too_many_pages", 422, f"The document has more than {settings.max_pages} pages."
        )
    return Document(data=data, media_type=media_type, pages=pages)


def normalise(kind: str, raw: str | None) -> tuple[str | None, bool]:
    """(value, parsed). Values that do not parse come back as read, marked unparsed."""
    if raw is None or not raw.strip():
        return None, False
    text = raw.strip()
    if kind == "date":
        try:
            return date.fromisoformat(text).isoformat(), True
        except ValueError:
            return text, False
    if kind in {"money", "number"}:
        cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
        try:
            amount = Decimal(cleaned)
        except InvalidOperation:
            return text, False
        return (f"{amount:.2f}" if kind == "money" else format(amount.normalize(), "f")), True
    if kind == "currency":
        code = text.upper()
        return (code, True) if re.fullmatch(r"[A-Z]{3}", code) else (text, False)
    return text, True


def shape(reading: Reading, name: str, kind: str, flagged: bool = False) -> dict[str, Any]:
    value, parsed = normalise(kind, reading.value)
    source = None
    if reading.page is not None and (reading.box is not None or reading.text):
        source = {
            "page": reading.page,
            "box": list(reading.box) if reading.box else None,
            "text": reading.text,
        }
    confident = value is not None and parsed and reading.confidence >= CONFIDENT and not flagged
    return {
        "name": name,
        "type": kind,
        "value": value,
        "source": source,
        "confidence": "high" if confident else "low",
    }


def run(data: bytes, provider: Provider, settings: Settings, name: str = "upload") -> dict[str, Any]:
    document = load_document(data, settings)
    result = provider.extract(document)
    readings = {field_id: result.fields.get(field_id, Reading(value=None)) for field_id in FIELD_IDS}

    # The arithmetic check: line amounts against the stated subtotal.
    subtotal, subtotal_ok = normalise("money", readings["subtotal"].value)
    amounts = [normalise("money", item.amount.value) for item in result.line_items]
    check = None
    if result.line_items and subtotal_ok and all(ok for _, ok in amounts):
        actual = sum((Decimal(value) for value, _ in amounts if value is not None), Decimal("0"))
        check = {
            "id": "line_items_sum",
            "passed": actual == Decimal(subtotal or "0"),
            "expected": subtotal,
            "actual": f"{actual:.2f}",
        }
    failed = check is not None and not check["passed"]

    fields = [
        {
            "id": field_id,
            **shape(
                readings[field_id],
                FIELD_NAMES[field_id],
                FIELD_TYPES[field_id],
                failed and field_id == "subtotal",
            ),
        }
        for field_id in FIELD_IDS
    ]
    line_items = [
        {
            key: shape(getattr(item, key), label, kind, failed and key == "amount")
            for key, (label, kind) in LINE_ITEM_FIELDS.items()
        }
        for item in result.line_items
    ]

    pages = [{"page": number, "width": None, "height": None} for number in range(1, document.pages + 1)]
    if document.media_type != "application/pdf":
        # The uploaded image is the page; the site shows it from a blob: URL. PDFs are not rendered here.
        pages[0]["image_base64"] = base64.b64encode(data).decode("ascii")
        pages[0]["media_type"] = document.media_type

    return {
        "schema": "tibyan-lab/document-extraction@1",
        "document": {"id": "upload", "name": name, "pages": pages},
        "fields": fields,
        "line_items": line_items,
        "checks": [check] if check else [],
        "model": {"provider": result.provider or provider.name, "name": result.model},
    }


__all__ = ["LineItem", "load_document", "run"]
