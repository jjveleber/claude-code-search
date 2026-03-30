# Tree-Sitter Semantic Chunking — Design Spec

**Date:** 2026-03-29
**Status:** Approved

## Problem

The current chunking strategy in `index_project.py` is a fixed sliding window: 60-line chunks with 10-line overlap, language-agnostic. This means:
- A 200-line function is split across 3–4 chunks
- A chunk may span two unrelated functions
- The embedding model receives semantically incoherent fragments, degrading retrieval quality

## Goal

Replace line-based chunking with tree-sitter AST-aware chunking that extracts semantically complete units (functions, classes, methods) as individual chunks. Fall back to line-based chunking for unsupported languages or parse failures.

## Architecture

### New module: `chunker.py`

Single public function:

```python
def chunk_file(filepath: str, lines: list[str]) -> list[tuple[int, int, str]]:
    ...
```

Returns the same `(start_line_1indexed, end_line_1indexed, text)` tuples as the current `chunk_lines()` — drop-in compatible with `index_project.py`'s call site.

The existing `chunk_lines()` logic moves into `chunker.py` as `_chunk_lines_fallback()`. Constants (`CHUNK_TARGET`, `CHUNK_OVERLAP`, `CHUNK_MAX`) stay in `index_project.py` and are imported by `chunker.py`.

### Grammar library

`tree-sitter-languages` (single pip package, bundles ~100 grammars). No per-language packages needed.

### Language maps

**Grammar map** — `LANG_MAP` values → tree-sitter grammar name (most are identical; exceptions: `"shell"` → `"bash"`, `"csharp"` → `"c_sharp"`, `"objective-c"` → `"objc"`, etc.).

**Node type map** — language → list of AST node type strings representing meaningful semantic units:

| Language | Node types |
|---|---|
| python | `function_definition`, `class_definition`, `decorated_definition` |
| c | `function_definition`, `struct_specifier`, `enum_specifier` |
| cpp | `function_definition`, `class_specifier`, `struct_specifier` |
| java | `method_declaration`, `class_declaration`, `interface_declaration` |
| javascript | `function_declaration`, `method_definition`, `class_declaration` |
| typescript | `function_declaration`, `method_definition`, `class_declaration` |
| go | `function_declaration`, `method_declaration`, `type_declaration` |
| rust | `function_item`, `impl_item`, `struct_item`, `enum_item`, `trait_item` |
| ruby | `method`, `singleton_method`, `class`, `module` |
| kotlin | `function_declaration`, `class_declaration`, `object_declaration` |
| swift | `function_declaration`, `class_declaration`, `struct_declaration`, `protocol_declaration` |
| scala | `function_definition`, `class_definition`, `object_definition`, `trait_definition` |
| csharp | `method_declaration`, `class_declaration`, `interface_declaration`, `struct_declaration` |

Languages not in the node type map fall through to `_chunk_lines_fallback()`.

## Extraction Logic

1. Parse the file with tree-sitter using the appropriate grammar.
2. Walk the AST depth-first, collecting all nodes whose type is in the target set.
3. **Prefer most specific match:** walk depth-first. When a node matches a target type, check whether any of its descendants also match a target type. If yes — skip this node and keep recursing (prefer the more specific children). If no — add this node and stop recursing. This means a `class_definition` is skipped in favour of the `function_definition` nodes it contains; a `function_definition` with no nested function nodes is extracted as a unit.
4. Sort extracted nodes by start line.
5. **Cover gaps:** for line ranges not covered by any extracted node (imports, top-level constants, global variables), apply `_chunk_lines_fallback()` on the gap text so no content is silently dropped.
6. **Sub-chunk large nodes:** any extracted node exceeding `CHUNK_MAX` lines is passed to `_chunk_lines_fallback()`, with the node's first 3 lines prepended to each sub-chunk as a signature prefix. This ensures every sub-chunk of a large function carries the function name and signature as context.

## Parser Caching

`Parser` instances are cached in a module-level dict keyed by language name, loaded once per process.

## Fallback Conditions

All three fall through silently to `_chunk_lines_fallback(lines)`:

1. Language not in node type map
2. Parse failure (tree-sitter error or exception)
3. No matching nodes extracted (e.g. a C file with only macros)

## Integration Points

### `index_project.py`

One-line change at the call site:
```python
# before
chunks = chunk_lines(lines)
# after
chunks = chunk_file(filepath, lines)
```

Import added at top of file:
```python
from chunker import chunk_file
```

### `install.sh`

`chunker.py` added to `_CS_FILES` list.

`tree-sitter-languages` added to the pip install block.

## Testing

New file: `tests/test_chunker.py`

Fixtures: `tests/fixtures/` — small representative files per language.

**Test categories:**

1. **Semantic boundary tests** — for Python, C, and JS fixtures, verify extracted chunk boundaries align with function/class definitions (chunk start line matches the definition line; no chunk spans two unrelated top-level functions).
2. **Sub-chunking test** — fixture with a function >120 lines; verify multiple chunks are produced, each prefixed with the function signature.
3. **Fallback tests** — unsupported language, malformed/unparseable file, file with no extractable nodes — all must return output identical to `_chunk_lines_fallback()` on the same input.
