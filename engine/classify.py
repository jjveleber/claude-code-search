"""Language detection and file-type classification. Light imports only."""
from pathlib import Path
from collections import Counter

# --- Language detection ---

LANG_MAP = {
    # --- Major languages ---
    ".py": "python", ".pyw": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".scala": "scala", ".go": "go", ".rs": "rust",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
    ".cc": "cpp", ".cxx": "cpp", ".hh": "cpp",
    ".cs": "csharp", ".vb": "visualbasic",
    ".swift": "swift", ".m": "objective-c", ".mm": "objective-cpp",
    ".php": "php", ".rb": "ruby", ".rake": "ruby",
    ".pl": "perl", ".pm": "perl", ".lua": "lua",

    # --- Shell / scripting ---
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".fish": "shell", ".ps1": "powershell",
    ".psm1": "powershell", ".psd1": "powershell",
    ".bat": "batch", ".cmd": "batch",

    # --- Web / templating ---
    ".html": "html", ".htm": "html", ".css": "css",
    ".scss": "scss", ".sass": "sass", ".less": "less",
    ".vue": "vue", ".svelte": "svelte",
    ".ejs": "ejs", ".hbs": "handlebars",
    ".mustache": "mustache", ".jinja": "jinja",
    ".jinja2": "jinja", ".twig": "twig",

    # --- Data / config ---
    ".json": "json", ".jsonc": "json",
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".ini": "ini", ".cfg": "ini",
    ".conf": "config", ".env": "dotenv",
    ".properties": "properties",

    # --- Build systems ---
    ".gradle": "gradle", ".gradle.kts": "gradle",
    ".pom": "maven", ".xml": "xml",
    ".makefile": "make", ".mk": "make",
    ".cmake": "cmake", ".bazel": "bazel",
    ".bzl": "bazel", ".ninja": "ninja",

    # --- Infrastructure / DevOps ---
    ".tf": "terraform", ".tfvars": "terraform",
    ".dockerfile": "docker", ".dockerignore": "docker",
    ".compose": "docker-compose",
    ".helm": "helm", ".chart": "helm",
    ".k8s": "kubernetes",

    # --- SQL / DB ---
    ".sql": "sql", ".psql": "sql", ".mysql": "sql",
    ".sqlite": "sql",

    # --- Functional languages ---
    ".hs": "haskell", ".lhs": "haskell",
    ".ml": "ocaml", ".mli": "ocaml",
    ".elm": "elm", ".clj": "clojure",
    ".cljs": "clojure", ".cljc": "clojure",
    ".erl": "erlang", ".hrl": "erlang",
    ".ex": "elixir", ".exs": "elixir",

    # --- GPU / shader languages ---
    ".glsl": "glsl", ".vert": "glsl", ".frag": "glsl",
    ".hlsl": "hlsl", ".metal": "metal",

    # --- Misc scripting ---
    ".r": "r", ".rmd": "rmarkdown",
    ".jl": "julia", ".dart": "dart",
    ".nim": "nim", ".zig": "zig",
    ".vala": "vala",

    # --- DSLs / niche ---
    ".proto": "protobuf", ".thrift": "thrift",
    ".graphql": "graphql", ".gql": "graphql",
    ".asm": "assembly", ".s": "assembly",
    ".ahk": "autohotkey", ".tex": "latex",
    ".bib": "bibtex", ".md": "markdown",
    ".rst": "restructuredtext",
}


# --- File type classification ---

_TEST_DIRS = frozenset({
    "test", "tests", "__tests__", "spec", "specs",
    "e2e", "testdata", "test_data", "fixtures",
})
_DOC_DIRS = frozenset({
    "doc", "docs", "documentation", "Doc", "pydoc_data",
    "man", "_site",
})
_GEN_DIRS = frozenset({
    "clinic", "generated", "__generated__", "auto-generated",
})
_DOC_EXTS = frozenset({".md", ".rst", ".adoc", ".txt"})


def classify_file(filepath):
    """Classify a file as prod/test/doc/generated based on path heuristics.

    Order: doc → generated → test → prod (prod is the default).
    Biased toward prod when uncertain — a prod file misclassified as test
    is excluded from default searches, which is worse than test noise.
    """
    p = Path(filepath)
    parts = p.parts
    name = p.name
    suffix = p.suffix.lower()

    # Doc: extension-based
    if suffix in _DOC_EXTS:
        return "doc"

    # Doc: directory-based
    if any(part in _DOC_DIRS for part in parts):
        return "doc"

    # Generated: directory-based
    if any(part in _GEN_DIRS for part in parts):
        return "generated"

    # Generated: file naming
    if name.endswith(("_pb2.py", "_pb2_grpc.py")):
        return "generated"
    if ".generated." in name or name.endswith(".generated"):
        return "generated"

    # Test: directory-based
    if any(part in _TEST_DIRS for part in parts):
        return "test"

    # Test: filename patterns
    if name.startswith("test_") or name.endswith((
        "_test.py", "_test.go", "_test.rb", "_test.rs",
        "_spec.rb", "_test.c", "_test.cpp",
    )):
        return "test"
    if any(name.endswith(ext) for ext in (
        ".test.ts", ".spec.ts", ".test.js", ".spec.js",
        ".test.tsx", ".spec.tsx", ".test.jsx", ".spec.jsx",
    )):
        return "test"
    if name.endswith(("Test.java", "Tests.java", "Spec.java", "IT.java")):
        return "test"

    return "prod"


def detect_languages(files):
    langs = []
    for f in files:
        ext = Path(f).suffix.lower()
        if ext in LANG_MAP:
            langs.append(LANG_MAP[ext])
    return Counter(langs)


def choose_model(lang_counts):
    """Return the embedding model to use."""
    return "nomic-ai/CodeRankEmbed"
