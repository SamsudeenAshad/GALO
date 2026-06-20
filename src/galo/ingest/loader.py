"""Document loading: raw input → normalized text + a stable content hash.

M1 handles plain text and markdown (and treats unknown types as UTF-8 text).
PDF/HTML loaders are deferred; the ``load`` seam is where they plug in.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class LoadedDocument:
    id: uuid.UUID
    title: str | None
    source_uri: str | None
    text: str
    content_hash: str


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_id(content_hash: str) -> uuid.UUID:
    """Derive a deterministic document id from content so re-ingesting identical
    content maps to the same row (idempotency)."""
    return uuid.uuid5(uuid.NAMESPACE_URL, content_hash)


def load_text(text: str, *, title: str | None = None, source_uri: str | None = None) -> LoadedDocument:
    """Load already-decoded text. Normalizes line endings and trims trailing
    whitespace so the content hash is stable across trivial formatting diffs."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    ch = _content_hash(normalized)
    return LoadedDocument(
        id=_stable_id(ch),
        title=title,
        source_uri=source_uri,
        text=normalized,
        content_hash=ch,
    )


def load_bytes(
    data: bytes, *, title: str | None = None, source_uri: str | None = None
) -> LoadedDocument:
    """Load raw bytes as UTF-8 text (lossy on invalid bytes)."""
    return load_text(data.decode("utf-8", errors="replace"), title=title, source_uri=source_uri)
