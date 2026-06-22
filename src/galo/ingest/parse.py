"""Document parsing: extract plain text from uploaded files (self-hosted).

Local parsers only — no external API. Routes by file extension / content type:
  - PDF            → pypdf (page text concatenated)
  - DOCX           → python-docx (paragraph text)
  - md / txt / etc → decoded as UTF-8 text

Returns extracted text; the ingestion pipeline then chunks/embeds it as usual.
"""

from __future__ import annotations

import io
from pathlib import PurePosixPath

# Extensions we treat as already-plain-text.
_TEXT_EXTS = {".txt", ".md", ".markdown", ".rst", ".text", ".csv", ".json", ".log"}


class UnsupportedFileType(ValueError):
    """Raised when a file's type has no parser."""


def parse_document(filename: str, data: bytes) -> str:
    """Extract text from ``data`` based on ``filename``'s extension.

    Raises UnsupportedFileType for types we can't parse, and ValueError if the
    file is parseable in principle but yields no text.
    """
    ext = PurePosixPath(filename or "").suffix.lower()

    if ext == ".pdf":
        text = _parse_pdf(data)
    elif ext == ".docx":
        text = _parse_docx(data)
    elif ext in _TEXT_EXTS or ext == "":
        text = data.decode("utf-8", errors="replace")
    else:
        raise UnsupportedFileType(f"unsupported file type: {ext or '(none)'}")

    text = text.strip()
    if not text:
        raise ValueError(f"no extractable text in {filename!r}")
    return text


def _parse_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(p.strip() for p in pages if p.strip())


def _parse_docx(data: bytes) -> str:
    import docx  # python-docx

    document = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs if p.text.strip())
