import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chunker import _chunk_lines_fallback, CHUNK_TARGET, CHUNK_MAX

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name):
    with open(os.path.join(FIXTURE_DIR, name)) as f:
        return f.readlines()


class TestChunkLinesFallback:
    def test_empty_input_returns_empty(self):
        assert _chunk_lines_fallback([]) == []

    def test_single_chunk_for_short_file(self):
        lines = [f"line {i}\n" for i in range(10)]
        chunks = _chunk_lines_fallback(lines)
        assert len(chunks) == 1
        start, end, text = chunks[0]
        assert start == 1
        assert end == 10
        assert text == "".join(lines)

    def test_multiple_chunks_for_long_file(self):
        lines = [f"line {i}\n" for i in range(CHUNK_TARGET * 3)]
        chunks = _chunk_lines_fallback(lines)
        assert len(chunks) > 1

    def test_return_type_is_tuples(self):
        lines = ["a\n", "b\n", "c\n"]
        chunks = _chunk_lines_fallback(lines)
        assert isinstance(chunks, list)
        for item in chunks:
            assert isinstance(item, tuple)
            assert len(item) == 3
            start, end, text = item
            assert isinstance(start, int)
            assert isinstance(end, int)
            assert isinstance(text, str)

    def test_line_numbers_are_one_indexed(self):
        lines = [f"line {i}\n" for i in range(5)]
        chunks = _chunk_lines_fallback(lines)
        assert chunks[0][0] == 1  # first chunk starts at line 1

    def test_coverage_no_line_gaps(self):
        """Every line in input appears in exactly one chunk (ignoring overlap)."""
        lines = [f"x{i}\n" for i in range(CHUNK_TARGET * 2 + 5)]
        chunks = _chunk_lines_fallback(lines)
        # All content appears in output (overlap means lines repeat, but none skipped)
        chunk_text = "".join(t for _, _, t in chunks)
        for line in lines:
            assert line in chunk_text

    def test_no_chunk_exceeds_chunk_max(self):
        lines = [f"line {i}\n" for i in range(CHUNK_MAX * 3)]
        chunks = _chunk_lines_fallback(lines)
        for start, end, text in chunks:
            assert (end - start + 1) <= CHUNK_MAX + 1  # +1 for blank line extension
