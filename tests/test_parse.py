"""Document parser tests — TXT, DOCX, PDF, and rejection of unknown types."""

from __future__ import annotations

import io

import pytest

from galo.ingest.parse import UnsupportedFileType, parse_document


def test_txt_passthrough() -> None:
    assert parse_document("notes.txt", b"hello world") == "hello world"


def test_markdown_passthrough() -> None:
    assert "# Title" in parse_document("doc.md", b"# Title\n\nbody")


def test_no_extension_treated_as_text() -> None:
    assert parse_document("README", b"plain") == "plain"


def test_unsupported_type_rejected() -> None:
    with pytest.raises(UnsupportedFileType):
        parse_document("image.png", b"\x89PNG\r\n")


def test_empty_text_rejected() -> None:
    with pytest.raises(ValueError, match="no extractable text"):
        parse_document("blank.txt", b"   \n  ")


def test_docx_extraction() -> None:
    docx = pytest.importorskip("docx")
    buf = io.BytesIO()
    d = docx.Document()
    d.add_paragraph("First paragraph.")
    d.add_paragraph("Second paragraph.")
    d.save(buf)
    out = parse_document("doc.docx", buf.getvalue())
    assert "First paragraph." in out and "Second paragraph." in out


def test_pdf_extraction() -> None:
    rl = pytest.importorskip("reportlab.pdfgen.canvas")
    buf = io.BytesIO()
    c = rl.Canvas(buf)
    c.drawString(72, 720, "Extracted PDF line.")
    c.save()
    out = parse_document("doc.pdf", buf.getvalue())
    assert "Extracted PDF line." in out
