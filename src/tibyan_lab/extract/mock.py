"""A stand-in provider for tests and local runs. It never reads the document and never
calls anything outside the process; it returns whatever readings it was given."""

from __future__ import annotations

from dataclasses import dataclass, field

from .provider import Document, ProviderResult


@dataclass
class MockProvider:
    result: ProviderResult
    name: str = "mock"
    calls: list[int] = field(default_factory=list)

    def extract(self, document: Document) -> ProviderResult:
        self.calls.append(len(document.data))
        return self.result
