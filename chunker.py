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


def chunk_file(filepath, lines):
    """Chunk a file using tree-sitter semantic boundaries where possible.

    Falls back to line-based chunking for:
    - Unsupported/unknown file extensions
    - Parse failures
    - Files with no extractable nodes

    Returns list of (start_line_1indexed, end_line_1indexed, text) tuples.
    """
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
