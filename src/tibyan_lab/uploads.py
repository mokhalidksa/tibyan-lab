"""Reading uploads entirely in memory (CLAUDE.md, rule 1).

Starlette's form parser spools files over 1 MB to a temporary file on disk, so the
service never calls it. It reads the request body itself, stopping as soon as the
size limit is passed, and parses the multipart form from that buffer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from python_multipart.multipart import MultipartParser, parse_options_header

from . import errors

#: Room for the multipart boundaries and headers around the file itself.
ENVELOPE_BYTES = 64 * 1024


@dataclass
class Part:
    name: str
    filename: str | None
    content_type: str | None
    data: bytes


async def read_body(stream: AsyncIterator[bytes], content_length: str | None, limit: int) -> bytes:
    """The whole body, refusing it as soon as it passes `limit` plus the multipart envelope."""
    ceiling = limit + ENVELOPE_BYTES
    if content_length and content_length.isdigit() and int(content_length) > ceiling:
        raise errors.too_large(limit)
    chunks: list[bytes] = []
    size = 0
    async for chunk in stream:
        size += len(chunk)
        if size > ceiling:
            raise errors.too_large(limit)
        chunks.append(chunk)
    return b"".join(chunks)


def parse_form(body: bytes, content_type: str | None) -> dict[str, Part]:
    """Parses multipart/form-data held in memory. Later fields with the same name replace earlier ones."""
    if not content_type:
        raise errors.file_missing()
    mime, options = parse_options_header(content_type)
    boundary = options.get(b"boundary")
    if mime != b"multipart/form-data" or not boundary:
        raise errors.file_missing()

    parts: dict[str, Part] = {}
    headers: dict[str, str] = {}
    field: list[bytes] = []
    value: list[bytes] = []
    data: list[bytes] = []

    def on_part_begin() -> None:
        headers.clear()
        data.clear()

    def on_header_field(buffer: bytes, start: int, end: int) -> None:
        field.append(buffer[start:end])

    def on_header_value(buffer: bytes, start: int, end: int) -> None:
        value.append(buffer[start:end])

    def on_header_end() -> None:
        headers[b"".join(field).decode("latin-1").lower()] = b"".join(value).decode("latin-1")
        field.clear()
        value.clear()

    def on_part_data(buffer: bytes, start: int, end: int) -> None:
        data.append(buffer[start:end])

    def on_part_end() -> None:
        _, disposition = parse_options_header(headers.get("content-disposition", ""))
        name = disposition.get(b"name")
        if name is None:
            return
        filename = disposition.get(b"filename")
        parts[name.decode("utf-8", "replace")] = Part(
            name=name.decode("utf-8", "replace"),
            filename=filename.decode("utf-8", "replace") if filename is not None else None,
            content_type=headers.get("content-type"),
            data=b"".join(data),
        )

    parser = MultipartParser(
        boundary,
        {
            "on_part_begin": on_part_begin,
            "on_header_field": on_header_field,
            "on_header_value": on_header_value,
            "on_header_end": on_header_end,
            "on_part_data": on_part_data,
            "on_part_end": on_part_end,
        },
    )
    try:
        parser.write(body)
        parser.finalize()
    except Exception as error:  # A malformed body says nothing useful to report back.
        raise errors.file_missing() from error
    return parts
