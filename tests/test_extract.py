from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tibyan_lab.app import create_app
from tibyan_lab.extract.mock import MockProvider
from tibyan_lab.extract.pipeline import run
from tibyan_lab.extract.provider import LineItem, ProviderResult, Reading
from tibyan_lab.settings import Settings

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF_TWO_PAGES = (
    b"%PDF-1.7\n1 0 obj << /Type /Pages /Count 2 >>\n2 0 obj << /Type /Page >>\n3 0 obj << /Type /Page >>\n"
)
PDF_FOUR_PAGES = b"%PDF-1.7\n" + b"<< /Type /Page >>\n" * 4


def reading(value: str | None, confidence: float = 0.95, box=(0.1, 0.1, 0.3, 0.12)) -> Reading:
    return Reading(value=value, page=1, box=box, text=value, confidence=confidence)


def invoice(subtotal: str = "105.00", second_amount: str = "60.00", **overrides: Reading) -> ProviderResult:
    fields = {
        "vendor": reading("Lorem Supplies Ltd"),
        "invoice_number": reading("LS-0042"),
        "invoice_date": reading("2026-10-01"),
        "due_date": reading("2026-10-31"),
        "currency": reading("gbp"),
        "subtotal": reading(subtotal),
        "tax": reading("21.00", confidence=0.5),
        "total": reading("£126.00"),
        **overrides,
    }
    items = [
        LineItem(reading("Paper"), reading("10"), reading("4.50"), reading("45.00")),
        LineItem(reading("Toner"), reading("2"), reading("30.00"), reading(second_amount)),
    ]
    return ProviderResult(fields=fields, line_items=items, provider="mock", model="test")


def test_result_shape_and_normalisation() -> None:
    result = run(PNG, MockProvider(invoice()), Settings())
    assert result["schema"] == "tibyan-lab/document-extraction@1"
    fields = {f["id"]: f for f in result["fields"]}
    assert list(fields) == [
        "vendor",
        "invoice_number",
        "invoice_date",
        "due_date",
        "currency",
        "subtotal",
        "tax",
        "total",
    ]
    assert fields["currency"]["value"] == "GBP"
    assert fields["total"]["value"] == "126.00"
    assert fields["vendor"]["source"] == {
        "page": 1,
        "box": [0.1, 0.1, 0.3, 0.12],
        "text": "Lorem Supplies Ltd",
    }
    assert len(result["line_items"]) == 2
    assert result["document"]["pages"][0]["media_type"] == "image/png"


def test_low_model_confidence_is_flagged() -> None:
    fields = {f["id"]: f for f in run(PNG, MockProvider(invoice()), Settings())["fields"]}
    assert fields["tax"]["confidence"] == "low"
    assert fields["vendor"]["confidence"] == "high"


def test_missing_and_unparseable_values_are_low() -> None:
    result = invoice(invoice_date=reading("first of October"), due_date=Reading(value=None))
    fields = {f["id"]: f for f in run(PNG, MockProvider(result), Settings())["fields"]}
    assert fields["invoice_date"]["value"] == "first of October"
    assert fields["invoice_date"]["confidence"] == "low"
    assert fields["due_date"]["value"] is None and fields["due_date"]["source"] is None


def test_line_items_that_add_up_pass_the_check() -> None:
    check = run(PNG, MockProvider(invoice()), Settings())["checks"][0]
    assert check == {"id": "line_items_sum", "passed": True, "expected": "105.00", "actual": "105.00"}


def test_line_items_that_do_not_add_up_flag_the_amounts() -> None:
    result = run(PNG, MockProvider(invoice(second_amount="65.00")), Settings())
    assert result["checks"][0]["passed"] is False
    assert {f["id"]: f for f in result["fields"]}["subtotal"]["confidence"] == "low"
    assert all(item["amount"]["confidence"] == "low" for item in result["line_items"])


@pytest.mark.parametrize(
    ("data", "code"), [(b"GIF89a....", "unsupported_type"), (PDF_FOUR_PAGES, "too_many_pages")]
)
def test_bad_documents_are_refused(data: bytes, code: str) -> None:
    from tibyan_lab.errors import LabError

    with pytest.raises(LabError) as caught:
        run(data, MockProvider(invoice()), Settings())
    assert caught.value.code == code


def test_pdf_pages_are_counted_and_not_returned() -> None:
    result = run(PDF_TWO_PAGES, MockProvider(invoice()), Settings())
    assert [p["page"] for p in result["document"]["pages"]] == [1, 2]
    assert "image_base64" not in result["document"]["pages"][0]


def post(client: TestClient, data: bytes = PNG):
    return client.post("/extract", files={"file": ("invoice.png", data, "image/png")})


def test_endpoint_is_off_without_a_provider() -> None:
    response = post(TestClient(create_app(Settings())))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "unavailable"


def test_endpoint_with_the_mock_provider() -> None:
    provider = MockProvider(invoice())
    response = post(TestClient(create_app(Settings(rate_limit_requests=100), provider=provider)))
    assert response.status_code == 200
    assert response.json()["model"] == {"provider": "mock", "name": "test"}
    assert provider.calls == [len(PNG)]


def test_five_documents_a_day_per_address() -> None:
    client = TestClient(create_app(Settings(rate_limit_requests=100), provider=MockProvider(invoice())))
    assert [post(client).status_code for _ in range(5)] == [200] * 5
    sixth = post(client)
    assert sixth.status_code == 429
    assert sixth.json()["error"]["code"] == "rate_limited"


def test_global_daily_cap() -> None:
    settings = Settings(rate_limit_requests=100, extract_daily_per_ip=100, extract_daily_total=2)
    client = TestClient(create_app(settings, provider=MockProvider(invoice())))
    assert [post(client).status_code for _ in range(3)] == [200, 200, 429]


def test_refused_files_do_not_use_the_daily_quota() -> None:
    client = TestClient(create_app(Settings(rate_limit_requests=100), provider=MockProvider(invoice())))
    assert post(client, b"not an invoice").status_code == 415
    assert [post(client).status_code for _ in range(5)] == [200] * 5
