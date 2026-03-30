# Tree-Sitter Semantic Chunking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed sliding-window chunker with a tree-sitter AST-aware chunker that extracts semantically complete units (functions, classes, methods) as individual chunks.

**Architecture:** New `chunker.py` module with single public function `chunk_file(filepath, lines)`. Language maps (extension → grammar, language → node types) and parser caching live there. `_chunk_lines_fallback()` (the existing line-based logic) lives there too as the fallback for unsupported languages, parse failures, and files with no extractable nodes. `index_project.py` swaps its `chunk_lines()` call for `chunk_file()` and loses the three chunking constants.

**Tech Stack:** `tree-sitter-languages` (PyPI, bundles ~100 grammars), `tree-sitter`, Python 3.12

**Note on spec deviation:** The spec says chunking constants stay in `index_project.py` and are imported by `chunker.py`. This creates a circular import (`index_project` → `chunker` → `index_project`). The plan moves the constants into `chunker.py` instead and removes them from `index_project.py`. No behavior change.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `chunker.py` | **Create** | All chunking logic: fallback, language maps, parser cache, extraction, gap coverage, sub-chunking |
| `tests/test_chunker.py` | **Create** | Unit tests for chunker |
| `tests/fixtures/sample.py` | **Create** | Python fixture with 2 top-level functions + 1 class with 3 methods |
| `tests/fixtures/sample.c` | **Create** | C fixture with 2 functions + 1 struct |
| `tests/fixtures/sample.js` | **Create** | JS fixture with 2 functions + 1 class |
| `tests/fixtures/sample_large_func.py` | **Create** | Python fixture with a single function >120 lines |
| `tests/fixtures/sample_unsupported.yaml` | **Create** | YAML fixture for fallback test |
| `index_project.py` | **Modify** | Remove `chunk_lines()` + 3 constants, add `from chunker import chunk_file`, swap call site |
| `install.sh` | **Modify** | Add `chunker.py` to `_CS_FILES`, add `tree-sitter-languages` to pip install |

---

## Task 1: Install tree-sitter-languages and create chunker.py skeleton

**Files:**
- Create: `chunker.py`

- [ ] **Step 1: Install tree-sitter-languages in the venv**

```bash
cd /path/to/your/repo
source .venv/bin/activate
pip install "tree-sitter-languages>=1.10"
```

Expected: installs without errors. If `tree-sitter-languages` conflicts, try `pip install "tree-sitter-languages"` without the version pin.

- [ ] **Step 2: Verify the package works**

```bash
.venv/bin/python3 -c "
from tree_sitter_languages import get_parser
p = get_parser('python')
tree = p.parse(b'def foo():\n    return 1\n')
print(tree.root_node.type)
print([c.type for c in tree.root_node.children])
"
```

Expected output:
```
module
['function_definition', 'newline']
```

- [ ] **Step 3: Create chunker.py skeleton**

Create `chunker.py` in the repo root:

```python
"""Tree-sitter semantic chunker with line-based fallback.

Public API:
    chunk_file(filepath, lines) -> list[tuple[int, int, str]]
        Returns (start_line_1indexed, end_line_1indexed, text) tuples.
"""
from pathlib import Path

# Chunking constants (moved from index_project.py)
CHUNK_TARGET = 60
CHUNK_OVERLAP = 10
CHUNK_MAX = 120

# Maps file extensions to tree-sitter grammar names
_EXT_GRAMMAR = {
    ".py": "python", ".pyw": "python", ".pyi": "python",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hh": "cpp",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby", ".rake": "ruby",
    ".kt": "kotlin", ".kts": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".cs": "csharp",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".php": "php",
    ".lua": "lua",
    ".hs": "haskell",
    ".ex": "elixir", ".exs": "elixir",
    ".erl": "erlang",
    ".ml": "ocaml", ".mli": "ocaml",
    ".kt": "kotlin",
}

# Maps grammar name to AST node types that represent semantic units
_NODE_TYPES = {
    "python": ["function_definition", "class_definition", "decorated_definition"],
    "c": ["function_definition", "struct_specifier", "enum_specifier"],
    "cpp": ["function_definition", "class_specifier", "struct_specifier"],
    "java": ["method_declaration", "class_declaration", "interface_declaration"],
    "javascript": ["function_declaration", "method_definition", "class_declaration"],
    "typescript": ["function_declaration", "method_definition", "class_declaration"],
    "go": ["function_declaration", "method_declaration", "type_declaration"],
    "rust": ["function_item", "impl_item", "struct_item", "enum_item", "trait_item"],
    "ruby": ["method", "singleton_method", "class", "module"],
    "kotlin": ["function_declaration", "class_declaration", "object_declaration"],
    "swift": ["function_declaration", "class_declaration", "struct_declaration", "protocol_declaration"],
    "scala": ["function_definition", "class_definition", "object_definition", "trait_definition"],
    "csharp": ["method_declaration", "class_declaration", "interface_declaration", "struct_declaration"],
    "bash": ["function_definition"],
    "php": ["function_definition", "method_declaration", "class_declaration"],
    "lua": ["function_definition"],
    "haskell": ["function"],
    "elixir": ["def", "defp", "defmodule"],
    "erlang": ["function"],
    "ocaml": ["let_binding", "type_definition"],
}

# Parser cache: grammar name -> Parser instance
_PARSER_CACHE = {}


def chunk_file(filepath, lines):
    """Chunk a file using tree-sitter semantic boundaries where possible.

    Falls back to line-based chunking for:
    - Unsupported/unknown file extensions
    - Parse failures
    - Files with no extractable nodes

    Returns list of (start_line_1indexed, end_line_1indexed, text) tuples.
    """
    raise NotImplementedError


def _chunk_lines_fallback(lines):
    raise NotImplementedError
```

- [ ] **Step 4: Commit skeleton**

```bash
git add chunker.py
git commit -m "feat: add chunker.py skeleton"
```

---

## Task 2: Implement `_chunk_lines_fallback` and its tests

**Files:**
- Modify: `chunker.py`
- Create: `tests/test_chunker.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_chunker.py`:

```python
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chunker import _chunk_lines_fallback, CHUNK_TARGET, CHUNK_MAX


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
        full_text = "".join(lines)
        chunk_text = "".join(t for _, _, t in chunks)
        for line in lines:
            assert line in chunk_text

    def test_no_chunk_exceeds_chunk_max(self):
        lines = [f"line {i}\n" for i in range(CHUNK_MAX * 3)]
        chunks = _chunk_lines_fallback(lines)
        for start, end, text in chunks:
            assert (end - start + 1) <= CHUNK_MAX + 1  # +1 for blank line extension
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python3 -m pytest tests/test_chunker.py::TestChunkLinesFallback -v
```

Expected: all tests FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement _chunk_lines_fallback**

Replace the `raise NotImplementedError` in `_chunk_lines_fallback`:

```python
def _chunk_lines_fallback(lines):
    """Fixed sliding window chunking (language-agnostic fallback).

    Returns list of (start_line_1indexed, end_line_1indexed, text) tuples.
    """
    chunks = []
    i = 0
    overlap_lines = []
    while i < len(lines):
        chunk = overlap_lines + []
        start = i - len(overlap_lines)
        # accumulate up to target
        while i < len(lines) and (i - start) < CHUNK_TARGET:
            chunk.append(lines[i])
            i += 1
        # extend to next blank line, up to hard max
        while i < len(lines) and (i - start) < CHUNK_MAX:
            if lines[i].strip() == "":
                chunk.append(lines[i])
                i += 1
                break
            chunk.append(lines[i])
            i += 1
        if not chunk:
            break
        chunk_start = start + 1  # 1-indexed
        chunk_end = start + len(chunk)
        chunks.append((chunk_start, chunk_end, "".join(chunk)))
        overlap_lines = lines[max(0, i - CHUNK_OVERLAP):i]
    return chunks
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_chunker.py::TestChunkLinesFallback -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add chunker.py tests/test_chunker.py
git commit -m "feat: implement _chunk_lines_fallback with tests"
```

---

## Task 3: Create test fixtures

**Files:**
- Create: `tests/fixtures/sample.py`
- Create: `tests/fixtures/sample.c`
- Create: `tests/fixtures/sample.js`
- Create: `tests/fixtures/sample_large_func.py`
- Create: `tests/fixtures/sample_unsupported.yaml`

- [ ] **Step 1: Create tests/fixtures/ directory and sample.py**

```bash
mkdir -p tests/fixtures
```

Create `tests/fixtures/sample.py`:

```python
"""Sample Python module for chunker tests."""
import os

CONSTANT = 42


def add(a, b):
    """Add two numbers."""
    return a + b


def multiply(a, b):
    """Multiply two numbers."""
    return a * b


class Calculator:
    """A simple calculator."""

    def __init__(self):
        self.result = 0

    def add(self, x):
        """Add x to result."""
        self.result += x
        return self

    def reset(self):
        """Reset result."""
        self.result = 0
```

- [ ] **Step 2: Create tests/fixtures/sample.c**

```c
/* Sample C file for chunker tests */
#include <stdio.h>
#define MAX 100

int add(int a, int b) {
    return a + b;
}

int multiply(int a, int b) {
    return a * b;
}

struct Point {
    int x;
    int y;
};
```

- [ ] **Step 3: Create tests/fixtures/sample.js**

```javascript
// Sample JS file for chunker tests
const PI = 3.14159;

function add(a, b) {
    return a + b;
}

function multiply(a, b) {
    return a * b;
}

class Calculator {
    constructor() {
        this.result = 0;
    }

    add(x) {
        this.result += x;
        return this;
    }
}
```

- [ ] **Step 4: Create tests/fixtures/sample_large_func.py**

This file must have a single function with a body exceeding CHUNK_MAX (120) lines:

```python
def large_function(n):
    """A very long function for testing sub-chunking.
    This function body intentionally exceeds CHUNK_MAX (120) lines.
    """
    result = 0
    x000 = n + 0
    x001 = n + 1
    x002 = n + 2
    x003 = n + 3
    x004 = n + 4
    x005 = n + 5
    x006 = n + 6
    x007 = n + 7
    x008 = n + 8
    x009 = n + 9
    x010 = n + 10
    x011 = n + 11
    x012 = n + 12
    x013 = n + 13
    x014 = n + 14
    x015 = n + 15
    x016 = n + 16
    x017 = n + 17
    x018 = n + 18
    x019 = n + 19
    x020 = n + 20
    x021 = n + 21
    x022 = n + 22
    x023 = n + 23
    x024 = n + 24
    x025 = n + 25
    x026 = n + 26
    x027 = n + 27
    x028 = n + 28
    x029 = n + 29
    x030 = n + 30
    x031 = n + 31
    x032 = n + 32
    x033 = n + 33
    x034 = n + 34
    x035 = n + 35
    x036 = n + 36
    x037 = n + 37
    x038 = n + 38
    x039 = n + 39
    x040 = n + 40
    x041 = n + 41
    x042 = n + 42
    x043 = n + 43
    x044 = n + 44
    x045 = n + 45
    x046 = n + 46
    x047 = n + 47
    x048 = n + 48
    x049 = n + 49
    x050 = n + 50
    x051 = n + 51
    x052 = n + 52
    x053 = n + 53
    x054 = n + 54
    x055 = n + 55
    x056 = n + 56
    x057 = n + 57
    x058 = n + 58
    x059 = n + 59
    x060 = n + 60
    x061 = n + 61
    x062 = n + 62
    x063 = n + 63
    x064 = n + 64
    x065 = n + 65
    x066 = n + 66
    x067 = n + 67
    x068 = n + 68
    x069 = n + 69
    x070 = n + 70
    x071 = n + 71
    x072 = n + 72
    x073 = n + 73
    x074 = n + 74
    x075 = n + 75
    x076 = n + 76
    x077 = n + 77
    x078 = n + 78
    x079 = n + 79
    x080 = n + 80
    x081 = n + 81
    x082 = n + 82
    x083 = n + 83
    x084 = n + 84
    x085 = n + 85
    x086 = n + 86
    x087 = n + 87
    x088 = n + 88
    x089 = n + 89
    x090 = n + 90
    x091 = n + 91
    x092 = n + 92
    x093 = n + 93
    x094 = n + 94
    x095 = n + 95
    x096 = n + 96
    x097 = n + 97
    x098 = n + 98
    x099 = n + 99
    x100 = n + 100
    x101 = n + 101
    x102 = n + 102
    x103 = n + 103
    x104 = n + 104
    x105 = n + 105
    x106 = n + 106
    x107 = n + 107
    x108 = n + 108
    x109 = n + 109
    x110 = n + 110
    x111 = n + 111
    x112 = n + 112
    x113 = n + 113
    x114 = n + 114
    x115 = n + 115
    return result + x000 + x115
```

Verify it has > 120 lines:

```bash
wc -l tests/fixtures/sample_large_func.py
```

Expected: 128 or more.

- [ ] **Step 5: Create tests/fixtures/sample_unsupported.yaml**

```yaml
key: value
nested:
  inner: data
list:
  - item1
  - item2
```

- [ ] **Step 6: Commit fixtures**

```bash
git add tests/fixtures/
git commit -m "test: add chunker test fixtures"
```

---

## Task 4: Implement parser loading and write parser tests

**Files:**
- Modify: `chunker.py`
- Modify: `tests/test_chunker.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_chunker.py`:

```python
from chunker import _get_parser


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
```

- [ ] **Step 2: Run to verify failures**

```bash
.venv/bin/python3 -m pytest tests/test_chunker.py::TestGetParser -v
```

Expected: ImportError or AttributeError — `_get_parser` not yet importable.

- [ ] **Step 3: Implement _get_parser in chunker.py**

Replace the `_PARSER_CACHE = {}` line and add the function below it:

```python
# Parser cache: grammar name -> Parser instance
_PARSER_CACHE = {}


def _get_parser(grammar_name):
    """Load and cache a tree-sitter Parser for the given grammar name.

    Returns None if the grammar is unavailable or fails to load.
    """
    if grammar_name in _PARSER_CACHE:
        return _PARSER_CACHE[grammar_name]
    try:
        from tree_sitter_languages import get_parser
        parser = get_parser(grammar_name)
        _PARSER_CACHE[grammar_name] = parser
        return parser
    except Exception:
        _PARSER_CACHE[grammar_name] = None
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_chunker.py::TestGetParser -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add chunker.py tests/test_chunker.py
git commit -m "feat: implement _get_parser with caching"
```

---

## Task 5: Implement node extraction and semantic boundary tests (Python)

**Files:**
- Modify: `chunker.py`
- Modify: `tests/test_chunker.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_chunker.py`:

```python
import os
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

def _read(name):
    with open(os.path.join(FIXTURE_DIR, name)) as f:
        return f.readlines()

from chunker import chunk_file


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
        full_text = "".join(lines)
        combined = "".join(t for _, _, t in chunks)
        # Check key content appears (overlap means some lines appear twice, that's ok)
        assert "import os" in combined
        assert "CONSTANT = 42" in combined
        assert "def add(a, b)" in combined
        assert "def multiply(a, b)" in combined
        assert "class Calculator" in combined
```

- [ ] **Step 2: Run to verify failures**

```bash
.venv/bin/python3 -m pytest tests/test_chunker.py::TestSemanticBoundariesPython -v
```

Expected: all tests FAIL — `chunk_file` raises `NotImplementedError`.

- [ ] **Step 3: Implement the node extraction helpers**

Add these functions to `chunker.py` (before `chunk_file`):

```python
def _has_matching_descendant(node, target_types):
    """Return True if any direct or indirect child has a type in target_types."""
    for child in node.children:
        if child.type in target_types:
            return True
        if _has_matching_descendant(child, target_types):
            return True
    return False


def _extract_leaf_nodes(node, target_types):
    """Depth-first collection of the most specific matching nodes.

    If a node matches AND has matching descendants, skip the node and
    recurse to collect the more-specific descendants instead.
    If a node matches AND has NO matching descendants, collect it and stop.
    """
    results = []
    if node.type in target_types:
        if _has_matching_descendant(node, target_types):
            # Prefer the children — recurse past this node
            for child in node.children:
                results.extend(_extract_leaf_nodes(child, target_types))
        else:
            results.append(node)
    else:
        for child in node.children:
            results.extend(_extract_leaf_nodes(child, target_types))
    return results


def _node_lines(node, lines):
    """Return the source lines for a tree-sitter node (0-indexed slice of lines)."""
    start = node.start_point[0]   # 0-indexed
    end = node.end_point[0]       # 0-indexed, inclusive
    return lines[start:end + 1], start, end
```

- [ ] **Step 4: Implement chunk_file with fallback paths only**

Replace `raise NotImplementedError` in `chunk_file`:

```python
def chunk_file(filepath, lines):
    """Chunk a file using tree-sitter semantic boundaries where possible."""
    if not lines:
        return []

    ext = Path(filepath).suffix.lower()
    grammar_name = _EXT_GRAMMAR.get(ext)
    target_types = _NODE_TYPES.get(grammar_name) if grammar_name else None

    if grammar_name is None or target_types is None:
        return _chunk_lines_fallback(lines)

    parser = _get_parser(grammar_name)
    if parser is None:
        return _chunk_lines_fallback(lines)

    try:
        source = "".join(lines).encode("utf-8")
        tree = parser.parse(source)
    except Exception:
        return _chunk_lines_fallback(lines)

    target_set = set(target_types)
    nodes = _extract_leaf_nodes(tree.root_node, target_set)

    if not nodes:
        return _chunk_lines_fallback(lines)

    nodes.sort(key=lambda n: n.start_point[0])
    return _build_chunks(nodes, lines)


def _build_chunks(nodes, lines):
    """Convert extracted nodes + gaps into chunk tuples."""
    chunks = []
    covered_up_to = 0  # 0-indexed, exclusive upper bound of covered lines

    for node in nodes:
        node_start_0 = node.start_point[0]  # 0-indexed

        # Cover gap before this node with line-based fallback
        if node_start_0 > covered_up_to:
            gap = lines[covered_up_to:node_start_0]
            for s, e, text in _chunk_lines_fallback(gap):
                chunks.append((covered_up_to + s, covered_up_to + e, text))

        # Emit chunk(s) for this node
        node_end_0 = node.end_point[0]  # 0-indexed, inclusive
        node_src, _, _ = _node_lines(node, lines)
        node_line_count = node_end_0 - node_start_0 + 1

        if node_line_count > CHUNK_MAX:
            signature = "".join(lines[node_start_0:min(node_start_0 + 3, node_end_0 + 1)])
            for s, e, text in _chunk_lines_fallback(node_src):
                abs_start = node_start_0 + s   # 1-indexed in file
                abs_end = node_start_0 + e     # 1-indexed in file
                chunks.append((abs_start, abs_end, signature + text))
        else:
            chunks.append((node_start_0 + 1, node_end_0 + 1, "".join(node_src)))

        covered_up_to = node_end_0 + 1  # next uncovered line (0-indexed)

    # Cover trailing content after last node
    if covered_up_to < len(lines):
        tail = lines[covered_up_to:]
        for s, e, text in _chunk_lines_fallback(tail):
            chunks.append((covered_up_to + s, covered_up_to + e, text))

    return chunks
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_chunker.py::TestSemanticBoundariesPython -v
```

Expected: all 5 tests PASS.

- [ ] **Step 6: Run all tests so far to check nothing broke**

```bash
.venv/bin/python3 -m pytest tests/test_chunker.py -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add chunker.py
git commit -m "feat: implement chunk_file with tree-sitter extraction and gap coverage"
```

---

## Task 6: Fallback tests

**Files:**
- Modify: `tests/test_chunker.py`

- [ ] **Step 1: Write fallback tests**

Add to `tests/test_chunker.py`:

```python
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
```

- [ ] **Step 2: Run to verify they pass (should pass with existing implementation)**

```bash
.venv/bin/python3 -m pytest tests/test_chunker.py::TestFallback -v
```

Expected: all 4 tests PASS. If any fail, debug `chunk_file`'s fallback paths.

- [ ] **Step 3: Commit**

```bash
git add tests/test_chunker.py
git commit -m "test: add fallback tests for chunk_file"
```

---

## Task 7: Sub-chunking tests for large functions

**Files:**
- Modify: `tests/test_chunker.py`

- [ ] **Step 1: Write sub-chunking tests**

Add to `tests/test_chunker.py`:

```python
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
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/python3 -m pytest tests/test_chunker.py::TestSubChunking -v
```

Expected: all 3 tests PASS. (Sub-chunking is already implemented in `_build_chunks`.)

If `test_large_function_produces_multiple_chunks` fails, verify `sample_large_func.py` has enough lines:

```bash
wc -l tests/fixtures/sample_large_func.py
python3 -c "from chunker import CHUNK_MAX; print('CHUNK_MAX:', CHUNK_MAX)"
```

The fixture must exceed `CHUNK_MAX` lines. If it doesn't, add more `xNNN = n + NNN` lines to the fixture.

- [ ] **Step 3: Commit**

```bash
git add tests/test_chunker.py
git commit -m "test: add sub-chunking tests"
```

---

## Task 8: C and JavaScript semantic boundary tests

**Files:**
- Modify: `tests/test_chunker.py`

- [ ] **Step 1: Write C and JS tests**

Add to `tests/test_chunker.py`:

```python
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
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/python3 -m pytest tests/test_chunker.py::TestSemanticBoundariesC tests/test_chunker.py::TestSemanticBoundariesJS -v
```

Expected: all tests PASS.

- [ ] **Step 3: Run full test suite**

```bash
.venv/bin/python3 -m pytest tests/test_chunker.py -v
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_chunker.py
git commit -m "test: add C and JS semantic boundary tests"
```

---

## Task 9: Update index_project.py

**Files:**
- Modify: `index_project.py`

- [ ] **Step 1: Remove chunk_lines() and its constants from index_project.py**

In `index_project.py`, remove these lines:

```python
CHUNK_TARGET = 60
CHUNK_OVERLAP = 10
CHUNK_MAX = 120
```

And remove the entire `chunk_lines()` function:

```python
def chunk_lines(lines):
    """Yield (start_line_1indexed, end_line_1indexed, text) tuples."""
    chunks = []
    i = 0
    overlap_lines = []
    while i < len(lines):
        ...
    return chunks
```

- [ ] **Step 2: Add the chunker import**

At the top of `index_project.py`, after the existing imports, add:

```python
from chunker import chunk_file
```

- [ ] **Step 3: Swap the call site**

Find the line in `index_project.py`:
```python
chunks = chunk_lines(lines)
```

Replace it with:
```python
chunks = chunk_file(filepath, lines)
```

- [ ] **Step 4: Verify index_project.py has no remaining chunk_lines references**

```bash
grep -n "chunk_lines\|CHUNK_TARGET\|CHUNK_OVERLAP\|CHUNK_MAX" index_project.py
```

Expected: no output.

- [ ] **Step 5: Run existing tests to confirm nothing broke**

```bash
.venv/bin/python3 -m pytest tests/ -v --ignore=tests/test_install.sh 2>&1 | tail -20
```

Expected: all Python tests PASS.

- [ ] **Step 6: Smoke test indexing on a small git repo**

```bash
cd /tmp && git init smoke_test && cd smoke_test
echo "def foo(x):\n    return x + 1" > test.py
git add test.py && git commit -m "init"
cp /path/to/repo/index_project.py /path/to/repo/chunker.py .
.venv/bin/python3 index_project.py
echo "Indexing succeeded"
```

Replace `/path/to/repo` with the actual repo path.

Expected: no errors, `chroma_db/` created.

- [ ] **Step 7: Commit**

```bash
cd /path/to/repo
git add index_project.py
git commit -m "feat: swap chunk_lines for chunk_file in index_project"
```

---

## Task 10: Update install.sh and final commit

**Files:**
- Modify: `install.sh`

- [ ] **Step 1: Add chunker.py to _CS_FILES in install.sh**

Find the line:
```bash
_CS_FILES=(index_project.py search_code.py watch_index.py)
```

Replace with:
```bash
_CS_FILES=(index_project.py search_code.py watch_index.py chunker.py)
```

- [ ] **Step 2: Add tree-sitter-languages to pip install in install.sh**

Find the pip install block:
```bash
"$VENV_PATH/bin/pip" install \
  "chromadb>=1.0" \
  "watchdog>=3.0" \
  "sentence-transformers>=3.0" \
  "psutil>=5.9"
```

Replace with:
```bash
"$VENV_PATH/bin/pip" install \
  "chromadb>=1.0" \
  "watchdog>=3.0" \
  "sentence-transformers>=3.0" \
  "psutil>=5.9" \
  "tree-sitter-languages>=1.10"
```

- [ ] **Step 3: Run full test suite one final time**

```bash
.venv/bin/python3 -m pytest tests/test_chunker.py tests/test_index_project.py tests/test_search_code.py -v 2>&1 | tail -30
```

Expected: all tests PASS.

- [ ] **Step 4: Final commit**

```bash
git add install.sh
git commit -m "feat: add tree-sitter-languages to install.sh, add chunker.py to distributed files"
```
