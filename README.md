# RTS — Relevant Test Selector

A CLI tool that analyzes Python codebases to understand code-to-test relationships and predicts which tests are relevant for a given diff.

## Overview

RTS solves the "which tests should I run?" problem by:

1. **Indexing** a Python repository to build a dependency graph mapping source files to their related tests
2. **Selecting** relevant tests for a given diff at configurable thoroughness levels

The result: sub-second test selection instead of running the entire test suite.

## Quick Start

```bash
# Install
pip install -e .

# Index a repository
rts index /path/to/your/repo

# Select tests for changed files
rts select --repo /path/to/your/repo --files src/module.py --thoroughness standard
```

## Installation

```bash
# Clone the repo
git clone <repo-url>
cd RTS

# Install in development mode
pip install -e ".[dev]"
```

**Requirements:** Python 3.9+, click >= 8.0

## Commands

### `rts index <repo>`

Builds the dependency index for a Python repository.

```bash
# Basic usage
rts index /path/to/repo

# With custom output directory
rts index /path/to/repo --output-dir /custom/path

# Verbose mode
rts -v index /path/to/repo
```

**Output:** Creates `.rts/index.json` inside the repository with:
- File dependency graph (imports/imported_by)
- Source-to-test mappings with relationship types
- Test function inventory

### `rts select`

Selects relevant tests for a given diff. Supports three input formats:

```bash
# From a list of changed files
rts select --repo /path/to/repo --files src/models.py,src/utils.py --thoroughness standard

# From a unified diff (pipe from git)
git diff | rts select --repo /path/to/repo --diff - --thoroughness quick

# From a diff file
rts select --repo /path/to/repo --diff changes.patch --thoroughness thorough

# From a git commit range
rts select --repo /path/to/repo --commit-range HEAD~3..HEAD --thoroughness standard
```

### `rts info`

Shows statistics about an existing index.

```bash
rts info --repo /path/to/repo
```

## Thoroughness Levels

| Level | Behavior | Use Case |
|-------|----------|----------|
| `quick` | Only tests that **directly import** changed files | Fast local iteration |
| `standard` | Quick + **transitively affected** tests (depth ≤ 3) | PR/commit validation |
| `thorough` | Standard + **naming heuristics** + **same-package** tests + unlimited depth | Pre-merge confidence |

## Output Format

JSON with confidence scores (0.0 – 1.0):

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
    }
  ],
  "total_tests_selected": 1,
  "total_tests_in_suite": 37,
  "selection_time_ms": 0.5
}
```

## Confidence Scoring

| Signal | Score |
|--------|-------|
| Direct import | 0.95 |
| Transitive (depth 1) | 0.75 |
| Transitive (depth 2) | 0.55 |
| Transitive (depth 3+) | 0.35 |
| Naming convention match | 0.60 |
| Same package | 0.40 |

Scores combine additively, capped at 1.0.

## Architecture

```
rts/
├── cli.py                  # Click CLI entry point
├── models.py               # Shared data models
├── indexer/
│   ├── ast_parser.py       # Primary AST-based parser
│   ├── regex_parser.py     # Regex fallback for broken files
│   ├── import_resolver.py  # Resolves imports to file paths
│   ├── graph_builder.py    # Builds dependency graph + test mappings
│   ├── test_classifier.py  # Classifies files as test vs source
│   └── index_store.py      # JSON persistence
└── selector/
    ├── diff_parser.py      # Parses diffs, commit ranges, file lists
    ├── graph_traversal.py  # BFS at configurable depth
    ├── heuristics.py       # Naming/path-based matching
    └── scorer.py           # Confidence scoring
```

## How It Works

### Indexer Pipeline

1. **Discover** all `.py` files (excluding `__pycache__`, `.git`, `venv`, etc.)
2. **Parse** each file using Python's `ast` module (regex fallback for syntax errors)
3. **Extract** imports, symbols (classes/functions), and test functions
4. **Resolve** import strings to actual file paths in the repo
5. **Build** a directed dependency graph (file → files it imports)
6. **Classify** files as test or source using path/name heuristics
7. **Map** source files to test files using BFS traversal of the reverse graph
8. **Enrich** with naming convention matches (e.g., `_models.py` ↔ `test_models.py`)
9. **Persist** to `.rts/index.json`

### Selector Pipeline

1. **Parse** the diff input (unified diff, commit range, or file list)
2. **Load** the persisted index
3. **Traverse** the reverse dependency graph via BFS at thoroughness-controlled depth
4. **Score** each affected test based on depth and relationship type
5. **Apply heuristics** (at `thorough` level) for naming convention matches
6. **Output** sorted JSON with confidence scores

## Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ -v --cov=rts --cov-report=term-missing
```

## Deployment to a Server

RTS is a CLI tool designed to be installed and run locally on any server:

```bash
# On the server
pip install .

# Cron job for nightly indexing
0 2 * * * cd /path/to/repo && rts index .

# CI integration example
git diff origin/main...HEAD | rts select --repo . --diff - --thoroughness standard
```

## Assumptions

- Target codebases are Python 3.x
- Test files follow standard naming conventions (`test_*.py`, `*_test.py`, or under `tests/` directories)
- Import resolution covers absolute and relative imports within the repo (external packages are filtered out)
- The index is file-level granularity (not function-level)

## Potential Enhancements

1. **Coverage-based refinement** — Use `coverage.py` data to refine mappings beyond static analysis
2. **Git history analysis** — Analyze co-change patterns to find correlated files
3. **Function-level granularity** — Track dependencies at function/class level for finer selection
4. **Incremental indexing** — Only re-parse changed files instead of full re-index
5. **Multi-language support** — Add Go/Rust analyzers using tree-sitter
6. **Watch mode** — Auto-re-index on file changes using `watchdog`
7. **CI output formats** — JUnit XML, GitHub Actions annotations
8. **Caching** — Cache selector results for identical diffs
9. **SQLite backend** — For repos with 10,000+ files
10. **pytest plugin** — Integrate as `pytest --rts` for seamless usage
