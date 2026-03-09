# Relevant Test Selector — Design Decisions

> Captured from Q&A session on 2026-03-08

## Confirmed Decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Language to analyze | **Python** — leverage `ast` module for static analysis |
| 2 | Public repository | **marshmallow-code/marshmallow** — pure Python serialization, no network deps, rich internal dependency graph |
| 3 | Interface | **CLI only** — no web service for now |
| 4 | Index persistence | **Local file-based** (JSON) |
| 5 | Diff input formats | **All three**: raw unified diff, commit range, list of changed files |
| 6 | Thoroughness levels | `quick` (direct imports only), `standard` (transitive deps), `thorough` (standard + heuristics/naming) |
| 7 | Output format | **JSON with confidence scores** |
| 8 | Deployment model | **CLI tool** downloaded and run locally on a server — not a web service |
| 9 | Authentication | **None** needed |
| 10 | Parsing strategy | **AST primary + Regex secondary** — AST for accuracy, regex fallback for broken/partial files |

## Thoroughness Semantics (Agreed)

- **`quick`** — Only tests that *directly* import or test the changed modules
- **`standard`** — Tests that are *transitively* affected (changed module → imported by module B → tested by test C)
- **`thorough`** — Standard + tests matched by naming conventions/heuristics + broader impact radius
