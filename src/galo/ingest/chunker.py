"""Chunking: split document text into overlapping windows.

A simple, deterministic character-window chunker with overlap. It prefers to
break on paragraph/sentence boundaries near the window edge so chunks don't cut
mid-sentence, falling back to a hard cut when no boundary is close.
"""

from __future__ import annotations

from dataclasses import dataclass

# Boundary markers, in order of preference, searched for near a window's end.
_BOUNDARIES = ("\n\n", "\n", ". ", "? ", "! ")


@dataclass(frozen=True)
class Chunk:
    ord: int
    text: str


def chunk_text(text: str, *, size: int = 800, overlap: int = 120) -> list[Chunk]:
    """Split ``text`` into chunks of ~``size`` chars overlapping by ``overlap``.

    Raises ValueError on nonsensical params. Empty/whitespace input yields [].
    """
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be in [0, size)")

    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [Chunk(ord=0, text=text)]

    chunks: list[Chunk] = []
    start = 0
    ordinal = 0
    n = len(text)

    while start < n:
        end = min(start + size, n)
        if end < n:  # not the last chunk — try to land on a boundary
            window = text[start:end]
            cut = _best_boundary(window)
            if cut is not None:
                end = start + cut
        piece = text[start:end].strip()
        if piece:
            chunks.append(Chunk(ord=ordinal, text=piece))
            ordinal += 1
        if end >= n:
            break
        start = max(end - overlap, start + 1)  # guarantee forward progress

    return chunks


def _best_boundary(window: str) -> int | None:
    """Index just past the best boundary in the latter half of ``window``,
    or None if no preferred boundary is found there."""
    half = len(window) // 2
    best: int | None = None
    for marker in _BOUNDARIES:
        idx = window.rfind(marker)
        if idx >= half:
            end = idx + len(marker)
            if best is None or end > best:
                best = end
    return best
