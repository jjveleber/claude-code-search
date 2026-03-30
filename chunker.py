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
