"""Chunker tests — pure, no dependencies."""

from __future__ import annotations

import pytest

from galo.ingest.chunker import chunk_text


def test_empty_input_yields_nothing() -> None:
    assert chunk_text("   \n  ") == []


def test_short_input_is_single_chunk() -> None:
    chunks = chunk_text("hello world", size=800)
    assert len(chunks) == 1
    assert chunks[0].ord == 0
    assert chunks[0].text == "hello world"


def test_long_input_splits_with_increasing_ords() -> None:
    text = ". ".join(f"sentence number {i}" for i in range(200))
    chunks = chunk_text(text, size=200, overlap=40)
    assert len(chunks) > 1
    assert [c.ord for c in chunks] == list(range(len(chunks)))
    # every chunk respects the size budget (boundary cut never exceeds it)
    assert all(len(c.text) <= 200 for c in chunks)


def test_overlap_makes_progress_no_infinite_loop() -> None:
    text = "x" * 5000  # no boundaries at all → hard cuts
    chunks = chunk_text(text, size=100, overlap=20)
    assert len(chunks) > 1
    assert "".join(c.text for c in chunks).count("x") >= 5000  # full coverage


def test_invalid_overlap_rejected() -> None:
    with pytest.raises(ValueError):
        chunk_text("abc", size=10, overlap=10)
