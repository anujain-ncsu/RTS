# Relevant Test Selector — Technical Plan

## Problem Statement

As codebases grow, running the full test suite on every change becomes prohibitively slow. We need a system that:
1. **Indexes** a Python codebase to build a model of code-to-test relationships
2. **Selects** relevant tests for a given diff, at configurable thoroughness levels

The system is a **CLI tool** designed to be downloaded and run locally on any machine.

---

## Target Repository

**Selected: [marshmallow-code/marshmallow](https://github.com/marshmallow-code/marshmallow)**

| Attribute | Value |
|-----------|-------|
| Commits | 2,957 (non-merge) |
| Contributors | 200+ |
| Layout | `src/marshmallow/` (source) + `tests/` (tests) |
| Test framework | pytest |
| Tests | 1,240 tests |
| License | MIT |

**Why marshmallow:**
- Pure in-memory data transformation — **zero network/server dependencies** in tests
- Clean `src/marshmallow/` + `tests/` layout with clear separation
- Rich internal dependency graph (schema, fields, decorators, validators, utils, error_store, class_registry, etc.)
- Well-known, mature Python library with clear import structure
- Tests run in seconds with no timeouts — ideal for historical commit validation

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                     CLI (click)                     │
│          rts index <repo>  |  rts select <diff>     │
└──────────┬──────────────────────────┬───────────────┘
           │                          │
    ┌──────▼──────┐           ┌───────▼───────┐
    │   Indexer   │           │   Selector    │
    │             │           │               │
    │ ┌─────────┐ │           │ ┌───────────┐ │
    │ │AST      │ │   reads   │ │Diff Parser│ │
    │ │Parser   │ │ ────────► │ │           │ │
    │ │         │ │  .rts/    │ │Graph      │ │
    │ │Import   │ │  index    │ │Traversal  │ │
    │ │Graph    │ │  .json    │ │           │ │
    │ │Builder  │ │           │ │Confidence │ │
    │ │         │ │           │ │Scorer     │ │
    │ │Test     │ │           │ └───────────┘ │
    │ │Mapper   │ │           │               │
    │ │         │ │           │               │
    │ │Heuristic│ │           │               │
    │ │Analyzer │ │           │               │
    │ └─────────┘ │           │               │
    └─────────────┘           └───────────────┘
```

---

## Core Components

### 1. Indexer (`rts index`)

**Input:** Path to a Python repository
**Output:** `.rts/index.json` — a persisted dependency graph + test mapping

#### Step-by-step pipeline:

| Step | What it does | Technique |
|------|-------------|-----------|
| **1. Discovery** | Find all `.py` files in the repo | `os.walk` / `pathlib.rglob` |
| **2. AST Parsing (primary)** | Parse each file into an AST | `ast.parse()` — stdlib, zero deps |
| **2b. Regex Fallback** | For files that fail AST parsing (syntax errors, partial files) | Regex patterns for `import X` / `from X import Y` |
| **3. Import Extraction** | Extract all `import` and `from X import Y` statements | AST visitor on `Import` / `ImportFrom` nodes (+ regex fallback) |
| **4. Symbol Extraction** | Extract defined classes, functions, top-level names | AST visitor on `ClassDef` / `FunctionDef` / `Assign` nodes |
| **5. Import Resolution** | Resolve relative/absolute imports to file paths | Custom resolver using `sys.path`-like logic |
| **6. Graph Construction** | Build a directed dependency graph: file → [files it imports] | `dict[str, set[str]]` adjacency list |
| **7. Test Classification** | Classify files as "test" or "source" | Heuristics: path contains `test`, file starts with `test_`, function names start with `test_` |
| **8. Test Mapping** | Map source files → test files that depend on them (directly or transitively) | Reverse the dependency graph edges, then BFS/DFS from each source file |
| **9. Heuristic Enrichment** | Add naming-convention matches (e.g., `_models.py` ↔ `test_models.py`) | String matching and path-based conventions |
| **10. Persistence** | Serialize the index to JSON | `json.dump()` to `.rts/index.json` |
| **11. Incremental Update** | Re-index only changed files | Compare `mtime` and `size` with existing index |

### 1.1 Incremental Indexing

To avoid full re-indexing on every run, the indexer supports an incremental mode:
- **Change Detection**: Stores file `mtime` (modified time) and `size` (bytes) in `.rts/index.json`.
- **Selective Parsing**: On subsequent runs, only files with changed `mtime` or `size` are re-processed via the AST parser.
- **Graph Reconstruction**: While all files are part of the graph, only the relationship data for changed/new files is updated. Deleted files are automatically pruned from the graph.
- **Performance**: Reduces indexing time to < 100ms for typical incremental changes in a medium-sized repo.

#### Index Schema (`.rts/index.json`):

```json
{
  "version": "1.0",
  "repository": "/path/to/repo",
  "created_at": "2026-03-08T21:00:00Z",
  "files": {
    "src/marshmallow/fields.py": {
      "type": "source",
      "imports": ["src/marshmallow/utils.py", "src/marshmallow/validate.py"],
      "symbols": ["String", "Integer", "Nested"],
      "imported_by": ["tests/test_fields.py", "tests/test_schema.py"]
    },
    "tests/test_fields.py": {
      "type": "test",
      "imports": ["src/marshmallow/fields.py"],
      "test_functions": ["test_string_field", "test_integer_field"]
    }
  },
  "source_to_tests": {
    "src/marshmallow/fields.py": [
      {"test_file": "tests/test_fields.py", "relationship": "direct_import", "confidence": 0.95},
      {"test_file": "tests/test_schema.py", "relationship": "transitive", "confidence": 0.70}
    ]
  },
  "test_to_sources": {
    "tests/test_fields.py": ["src/marshmallow/fields.py"]
  }
}
```

### 2. Selector (`rts select`)

**Input:** Index + diff + thoroughness level
**Output:** JSON list of tests with confidence scores

#### Input Formats Supported:

| Format | Flag | Example |
|--------|------|---------|
| Unified diff (stdin/file) | `--diff <file>` or pipe | `git diff \| rts select --diff -` |
| Commit range | `--commit-range <range>` | `rts select --commit-range HEAD~3..HEAD` |
| Changed files | `--files <files>` | `rts select --files httpx/_models.py,httpx/_client.py` |

#### Selection Algorithm by Thoroughness:

| Level | What's selected | Expected precision | Expected recall |
|-------|----------------|-------------------|-----------------|
| `quick` | Tests that **directly import** any changed file | High | Low-Medium |
| `standard` | `quick` + tests that **transitively depend** on changed files (max depth: 3) | Medium | Medium-High |
| `thorough` | `standard` + **naming convention matches** + **same-package tests** + unlimited transitive depth | Lower | High |

#### Confidence Scoring:

Each selected test gets a confidence score (0.0 – 1.0):

| Signal | Weight |
|--------|--------|
| Direct import of changed file | 0.95 |
| Transitive import (depth 1) | 0.75 |
| Transitive import (depth 2) | 0.55 |
| Transitive import (depth 3+) | 0.35 |
| Naming convention match | 0.60 |
| Same package/directory | 0.40 |

Scores combine additively (capped at 1.0) when multiple signals match.

#### Output Format:

```json
{
  "changed_files": ["httpx/_models.py"],
  "thoroughness": "standard",
  "selected_tests": [
    {
      "test_file": "tests/test_models.py",
      "test_functions": ["test_request", "test_response"],
      "confidence": 0.95,
      "reasons": ["direct_import"]
    },
    {
      "test_file": "tests/test_api.py",
      "confidence": 0.70,
      "reasons": ["transitive_import(depth=1)"]
    }
  ],
  "total_tests_selected": 2,
  "total_tests_in_suite": 38,
  "selection_time_ms": 8
}
```

---

## Project Structure

```
RTS/
├── rts/                        # Main package
│   ├── __init__.py
│   ├── cli.py                  # Click-based CLI entry point
│   ├── indexer/
│   │   ├── __init__.py
│   │   ├── ast_parser.py       # AST parsing and import/symbol extraction
│   │   ├── regex_parser.py     # Regex-based fallback for broken/partial files
│   │   ├── import_resolver.py  # Resolves import strings to file paths
│   │   ├── graph_builder.py    # Builds the dependency graph
│   │   ├── test_classifier.py  # Classifies files as test vs source
│   │   └── index_store.py      # Serialization / deserialization of the index
│   ├── selector/
│   │   ├── __init__.py
│   │   ├── diff_parser.py      # Parses unified diffs, commit ranges, file lists
│   │   ├── graph_traversal.py  # Walks the dependency graph at various depths
│   │   ├── heuristics.py       # Naming convention & path-based matching
│   │   └── scorer.py           # Confidence scoring logic
│   └── models.py               # Shared data models (dataclasses)
├── tests/                      # Our own tests for RTS
│   ├── __init__.py
│   ├── test_ast_parser.py
│   ├── test_regex_parser.py
│   ├── test_import_resolver.py
│   ├── test_graph_builder.py
│   ├── test_diff_parser.py
│   ├── test_graph_traversal.py
│   ├── test_heuristics.py
│   ├── test_scorer.py
│   └── test_cli.py
├── decisions.md                # Design decisions from Q&A
├── tech_plan.md                # This file
├── README.md                   # Usage docs (created after implementation)
├── requirements.txt            # Dependencies
├── setup.py                    # Package setup (for pip install -e .)
└── Procfile                    # Heroku (placeholder, CLI-focused)
```

---

## Algorithmic Complexity

| Operation | Time | Space | Notes |
|-----------|------|-------|-------|
| **Indexing: File discovery** | O(N) | O(N) | N = number of files |
| **Indexing: AST parsing** | O(N × L) | O(N × S) | L = avg lines/file, S = avg symbols/file |
| **Indexing: Import resolution** | O(N × I) | O(N × I) | I = avg imports/file |
| **Indexing: Graph construction** | O(N + E) | O(N + E) | E = number of edges (imports) |
| **Indexing: Reverse graph** | O(N + E) | O(N + E) | One-time inversion |
| **Selection: Diff parsing** | O(D) | O(D) | D = diff size |
| **Selection: Graph traversal** | O(C × (N + E)) | O(N) | C = changed files, worst-case BFS |
| **Selection: Scoring** | O(T) | O(T) | T = selected tests |
| **Overall Indexing** | O(N × L) | O(N + E) | Dominated by AST parsing |
| **Overall Selection** | O(C × (N + E)) | O(N) | Fast for small C (typical diffs) |

For marshmallow (~13 Python source files, ~50 import edges): indexing should take **< 1 second**, selection should be **< 20ms**.

---

## Tradeoffs Considered

### 1. AST Parsing + Regex Fallback (Dual Strategy)

| Approach | Role | Pros | Cons |
|----------|------|------|------|
| **AST (primary)** | First pass on all files | Accurate, handles multi-line imports, conditional imports visible | Requires valid Python syntax |
| **Regex (secondary)** | Fallback for AST failures + fast re-scan mode | Very fast, works on partial/broken files | Fragile, misses complex import patterns |

**Decision: AST primary, Regex secondary.** AST is used first for accuracy. If a file fails AST parsing (syntax errors, encoding issues, partial files), the regex parser kicks in as a fallback. The regex parser can also be used independently for a "fast scan" mode in future enhancements.

### 2. Index Format: JSON vs. SQLite vs. Pickle

| Format | Pros | Cons |
|--------|------|------|
| **JSON (chosen)** | Human-readable, debuggable, portable | Slower for very large repos |
| **SQLite** | Fast queries, handles large data | Heavier dependency, harder to debug |
| **Pickle** | Fastest serialization | Not human-readable, security concerns |

**Decision: JSON** — debuggability and portability are key for a CLI tool. Can migrate to SQLite later if needed.

### 3. Graph Traversal: BFS vs. DFS

| Approach | Pros | Cons |
|----------|------|------|
| **BFS (chosen)** | Natural depth tracking (needed for thoroughness levels) | Slightly more memory |
| **DFS** | Lower memory footprint | Harder to track depth consistently |

**Decision: BFS** — depth tracking is essential for thoroughness levels and confidence scoring.

### 4. CLI Framework: Click vs. argparse

| Framework | Pros | Cons |
|-----------|------|------|
| **Click (chosen)** | Subcommands, testing support, cleaner API | External dependency |
| **argparse** | Zero dependencies (stdlib) | More boilerplate, weaker subcommand support |

**Decision: Click** — better developer experience, smaller install footprint than alternatives.

---

## Dependencies

```
click>=8.0          # CLI framework
```

That's it — the core logic uses only Python stdlib (`ast`, `json`, `os`, `pathlib`, `subprocess`, `collections`). Minimal dependency footprint by design.

**Dev dependencies:**
```
pytest>=7.0         # Testing
pytest-cov          # Coverage
```

---

## Verification Plan

### Automated Tests (RTS's own test suite)

We will write unit tests for each module and integration tests for end-to-end flows:

```bash
# Run all tests
cd /Users/macmini/Desktop/Antigravity/RTS
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ -v --cov=rts --cov-report=term-missing
```

**Key test scenarios:**
1. `test_ast_parser.py` — Verify import extraction from various Python patterns (absolute, relative, conditional, `from X import *`)
2. `test_regex_parser.py` — Verify regex fallback catches imports in broken/partial files
3. `test_import_resolver.py` — Verify import strings resolve to correct file paths
4. `test_graph_builder.py` — Verify dependency graph is correct for known module structures
5. `test_diff_parser.py` — Verify parsing of unified diffs, commit ranges, and file lists
6. `test_graph_traversal.py` — Verify BFS at different depths returns expected test sets
7. `test_heuristics.py` — Verify naming convention matching (e.g., `_models.py` ↔ `test_models.py`)
8. `test_scorer.py` — Verify confidence scores combine correctly
9. `test_cli.py` — Integration tests using Click's `CliRunner`

### Live Validation Against marshmallow

```bash
# Clone marshmallow (checkout 3.x for Python 3.9 compat)
git clone https://github.com/marshmallow-code/marshmallow /path/to/marshmallow-test
cd /path/to/marshmallow-test && git checkout 3.26.2

# Index it
cd /Users/macmini/Desktop/Antigravity/RTS
python -m rts index /path/to/marshmallow-test

# Simulate a change to src/marshmallow/fields.py and select tests
python -m rts select --repo /path/to/marshmallow-test --files src/marshmallow/fields.py --thoroughness standard

# Verify output contains expected tests (e.g., test_fields.py should appear)
```

### Performance Benchmarks

```bash
# Time the indexer
time python -m rts index /path/to/marshmallow-test

# Time the selector (should be < 1 second)
time python -m rts select --repo /path/to/marshmallow-test --files src/marshmallow/fields.py --thoroughness thorough
```

---

## Potential Enhancements

1. **Coverage-based refinement** — Run tests with `coverage.py` and use actual coverage data to refine the index (increases accuracy at the cost of heavier indexing)
2. **Git history analysis** — Analyze co-change patterns: files that historically change together likely need the same tests
3. **Function-level granularity** — Track dependencies at the function/class level rather than file level
4. **Multi-language support** — Add Go and Rust analyzers using tree-sitter for AST parsing
6. **Watch mode** — Re-index automatically on file change using `watchdog`
7. **CI integration** — Output in JUnit XML or GitHub Actions-compatible format
8. **Caching layer** — Cache selector results for identical diffs
9. **SQLite backend** — Migrate from JSON to SQLite for repos with 10,000+ files
10. **pytest plugin** — Integrate directly as a pytest plugin (`pytest --rts`)
