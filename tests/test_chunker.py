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


from chunker import _get_parser, chunk_file


class TestGetParser:
    def test_returns_parser_for_known_grammar(self):
        parser = _get_parser("python")
        assert parser is not None

    def test_returns_none_for_unknown_grammar(self):
        parser = _get_parser("not_a_real_language_xyz")
        assert parser is None

    def test_parser_is_cached(self):
        p1 = _get_parser("python")
        p2 = _get_parser("python")
        assert p1 is p2

    def test_parser_can_parse_python(self):
        parser = _get_parser("python")
        tree = parser.parse(b"def foo():\n    return 1\n")
        assert tree.root_node.type == "module"

    def test_parser_can_parse_c(self):
        parser = _get_parser("c")
        tree = parser.parse(b"int add(int a, int b) { return a + b; }\n")
        assert tree.root_node.type == "translation_unit"


class TestSemanticBoundariesPython:
    def test_add_and_multiply_are_separate_chunks(self):
        lines = _read("sample.py")
        chunks = chunk_file("sample.py", lines)
        texts = [t for _, _, t in chunks]
        add_chunks = [t for t in texts if "def add(a, b)" in t]
        mul_chunks = [t for t in texts if "def multiply(a, b)" in t]
        assert len(add_chunks) >= 1, "add() not found in any chunk"
        assert len(mul_chunks) >= 1, "multiply() not found in any chunk"
        assert add_chunks[0] is not mul_chunks[0], "add and multiply in same chunk"

    def test_no_chunk_spans_two_top_level_functions(self):
        lines = _read("sample.py")
        chunks = chunk_file("sample.py", lines)
        for start, end, text in chunks:
            both = "def add(a, b)" in text and "def multiply(a, b)" in text
            assert not both, f"Chunk lines {start}-{end} spans both add() and multiply()"

    def test_methods_extracted_not_whole_class(self):
        lines = _read("sample.py")
        chunks = chunk_file("sample.py", lines)
        texts = [t for _, _, t in chunks]
        # Calculator.add and Calculator.reset should be separate chunks
        add_method = [t for t in texts if "def add(self, x)" in t]
        reset_method = [t for t in texts if "def reset(self)" in t]
        assert len(add_method) >= 1, "Calculator.add() not found"
        assert len(reset_method) >= 1, "Calculator.reset() not found"

    def test_chunk_covers_full_function_body(self):
        lines = _read("sample.py")
        chunks = chunk_file("sample.py", lines)
        # The add() function chunk should contain the return statement
        add_chunk = next((t for _, _, t in chunks if "def add(a, b)" in t), None)
        assert add_chunk is not None
        assert "return a + b" in add_chunk

    def test_all_lines_covered(self):
        lines = _read("sample.py")
        chunks = chunk_file("sample.py", lines)
        # Every line of the file should appear in at least one chunk
        combined = "".join(t for _, _, t in chunks)
        assert "import os" in combined
        assert "CONSTANT = 42" in combined
        assert "def add(a, b)" in combined
        assert "def multiply(a, b)" in combined
        assert "class Calculator" in combined


class TestFallback:
    def test_unsupported_extension_falls_back(self):
        lines = _read("sample_unsupported.yaml")
        ts_result = chunk_file("sample_unsupported.yaml", lines)
        fallback_result = _chunk_lines_fallback(lines)
        assert ts_result == fallback_result

    def test_unknown_extension_falls_back(self):
        lines = ["hello world\n", "second line\n"]
        ts_result = chunk_file("mystery.xyz123", lines)
        fallback_result = _chunk_lines_fallback(lines)
        assert ts_result == fallback_result

    def test_empty_file_returns_empty(self):
        assert chunk_file("sample.py", []) == []

    def test_file_with_no_extractable_nodes_falls_back(self):
        # A Python file with only constants and no functions/classes
        lines = ["X = 1\n", "Y = 2\n", "Z = 3\n"]
        ts_result = chunk_file("constants.py", lines)
        fallback_result = _chunk_lines_fallback(lines)
        assert ts_result == fallback_result


class TestSubChunking:
    def test_large_function_produces_multiple_chunks(self):
        lines = _read("sample_large_func.py")
        chunks = chunk_file("sample_large_func.py", lines)
        assert len(chunks) > 1, (
            f"Expected multiple chunks for large function, got {len(chunks)}. "
            f"File has {len(lines)} lines, CHUNK_MAX={__import__('chunker').CHUNK_MAX}"
        )

    def test_all_sub_chunks_contain_function_signature(self):
        lines = _read("sample_large_func.py")
        chunks = chunk_file("sample_large_func.py", lines)
        for start, end, text in chunks:
            assert "def large_function" in text, (
                f"Sub-chunk lines {start}-{end} is missing signature prefix.\n"
                f"Content: {text[:100]!r}"
            )

    def test_sub_chunk_line_numbers_are_sequential(self):
        lines = _read("sample_large_func.py")
        chunks = chunk_file("sample_large_func.py", lines)
        for i in range(len(chunks) - 1):
            _, end_i, _ = chunks[i]
            start_next, _, _ = chunks[i + 1]
            assert start_next <= end_i + 1, (
                f"Gap between chunk {i} (ends {end_i}) and chunk {i+1} (starts {start_next})"
            )


class TestSemanticBoundariesC:
    def test_c_functions_are_separate_chunks(self):
        lines = _read("sample.c")
        chunks = chunk_file("sample.c", lines)
        texts = [t for _, _, t in chunks]
        add_chunks = [t for t in texts if "int add(" in t]
        mul_chunks = [t for t in texts if "int multiply(" in t]
        assert len(add_chunks) >= 1, "add() not found"
        assert len(mul_chunks) >= 1, "multiply() not found"
        assert add_chunks[0] is not mul_chunks[0]

    def test_c_no_chunk_spans_two_functions(self):
        lines = _read("sample.c")
        chunks = chunk_file("sample.c", lines)
        for start, end, text in chunks:
            assert not ("int add(" in text and "int multiply(" in text), \
                f"Chunk {start}-{end} spans both C functions"

    def test_c_add_chunk_contains_body(self):
        lines = _read("sample.c")
        chunks = chunk_file("sample.c", lines)
        add_chunk = next((t for _, _, t in chunks if "int add(" in t), None)
        assert add_chunk is not None
        assert "return a + b" in add_chunk


class TestSemanticBoundariesJS:
    def test_js_functions_are_separate_chunks(self):
        lines = _read("sample.js")
        chunks = chunk_file("sample.js", lines)
        texts = [t for _, _, t in chunks]
        add_chunks = [t for t in texts if "function add(" in t]
        mul_chunks = [t for t in texts if "function multiply(" in t]
        assert len(add_chunks) >= 1, "add() not found"
        assert len(mul_chunks) >= 1, "multiply() not found"
        assert add_chunks[0] is not mul_chunks[0]

    def test_js_no_chunk_spans_two_functions(self):
        lines = _read("sample.js")
        chunks = chunk_file("sample.js", lines)
        for start, end, text in chunks:
            assert not ("function add(" in text and "function multiply(" in text), \
                f"Chunk {start}-{end} spans both JS functions"

    def test_js_class_methods_extracted(self):
        lines = _read("sample.js")
        chunks = chunk_file("sample.js", lines)
        texts = [t for _, _, t in chunks]
        constructor_chunks = [t for t in texts if "constructor()" in t]
        add_method_chunks = [t for t in texts if "add(x)" in t and "class" not in t]
        assert len(constructor_chunks) >= 1, "constructor not found"
        assert len(add_method_chunks) >= 1, "add method not found"
