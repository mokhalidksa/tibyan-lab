"""The one interface every model provider implements for invoice extraction.

The pipeline never talks to a vendor SDK directly. A provider receives the document
in memory and returns raw field readings; the pipeline validates, checks and shapes
them into tibyan-lab/document-extraction@1. Providers read their API keys from the
environment only (CLAUDE.md, rule 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

FIELD_IDS = ("vendor", "invoice_number", "invoice_date", "due_date", "currency", "subtotal", "tax", "total")


@dataclass(frozen=True)
class Document:
    """An uploaded document, held in memory only."""

    data: bytes
    media_type: str  # application/pdf, image/png, image/jpeg or image/webp
    pages: int


@dataclass
class Reading:
    """One value as the model read it."""

    value: str | None
    page: int | None = None
    #: [x0, y0, x1, y1] as fractions of the page, from the top-left corner.
    box: tuple[float, float, float, float] | None = None
    #: The exact text the value was read from.
    text: str | None = None
    #: The model's own confidence, 0 to 1.
    confidence: float = 0.0


@dataclass
class LineItem:
    description: Reading
    quantity: Reading
    unit_price: Reading
    amount: Reading


@dataclass
class ProviderResult:
    fields: dict[str, Reading]
    line_items: list[LineItem] = field(default_factory=list)
    provider: str = ""
    model: str = ""


class Provider(Protocol):
    name: str

    def extract(self, document: Document) -> ProviderResult: ...
