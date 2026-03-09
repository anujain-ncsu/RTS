# TODO — Relevant Test Selector

> Prioritized list of what to work on next.

---

## 🔴 High Priority

### Accuracy & Coverage

- [ ] **Coverage-based refinement** — Run tests with `coverage.py` and use actual line-level coverage data to refine the dependency index, replacing static-analysis guesses with ground-truth mappings
- [ ] **Function-level granularity** — Track dependencies at the function/class level instead of file-level to avoid over-selecting tests (marshmallow currently selects 16/18 test files for any source change due to tight coupling via `__init__.py`)
- [ ] **Git co-change analysis** — Mine commit history for files that historically change together and correlate those patterns with test outcomes

### Language Support

- [ ] **Harden Go analyzer** — Validate on more Go repos beyond logrus; handle `go:embed`, build tags, and `internal/` packages
- [ ] **Harden Rust analyzer** — Validate on real Rust repos; improve `mod.rs` resolution, handle `#[cfg(test)]` inline test modules and workspace crates
- [ ] **Add TypeScript/JavaScript analyzer** — High-demand language; parse `import`/`require` via regex or tree-sitter

---

## 🟡 Medium Priority

### Developer Experience

- [ ] **pytest plugin** — Integrate as `pytest --rts` so users don't need a separate CLI step; auto-detect changed files from git
- [ ] **Watch mode** — Auto-re-index on file changes using `watchdog` for a tight dev-loop experience
- [ ] **CI output formats** — Support JUnit XML, GitHub Actions annotations (`::warning`), and GitLab CI report formats
- [ ] **GitHub Action / CI template** — Provide a ready-to-use Action or config snippet for common CI systems

### Robustness

- [ ] **Better validation harness** — Extend `validate.py` to compute precision (% of selected tests that actually exercise changed code) in addition to recall/miss-rate
- [ ] **Handle monorepos** — Support multiple language roots, separate `index.json` per sub-project, and workspace-level dependency graphs
- [ ] **Parallel indexing** — Use `multiprocessing` or `concurrent.futures` to parse files in parallel for large repos

### Index & Storage

- [ ] **SQLite backend** — Migrate from JSON to SQLite for repos with 10,000+ files where JSON serialization becomes a bottleneck
- [ ] **Caching layer** — Cache selector results for identical diffs to avoid redundant graph traversals
- [ ] **Index diffing** — Show what changed between two index snapshots for debugging

---

## 🟢 Low Priority / Nice-to-Have

### Polish

- [ ] **`rts explain`** — Add a command that shows *why* a particular test was selected (trace the dependency path)
- [ ] **Config file support** — Allow `.rts.yaml` or `pyproject.toml [tool.rts]` for default thoroughness, excluded paths, custom test patterns, etc.
- [ ] **Rich CLI output** — Use `rich` for colored tables, progress bars during indexing, and interactive test selection
- [ ] **Dry-run mode for select** — Show what *would* be selected without producing full JSON, useful for quick sanity checks

### Testing & Quality

- [ ] **Increase own test coverage** — Add tests for multi-language analyzers (`go_analyzer.py`, `rust_analyzer.py`); current tests only cover Python paths
- [ ] **Property-based testing** — Use `hypothesis` to fuzz the diff parser and import resolver
- [ ] **Benchmark suite** — Automated perf benchmarks tracking indexing/selection time across releases

### Documentation

- [ ] **Architecture diagram** — Add a visual Mermaid diagram to the README showing the indexer → index → selector data flow
- [ ] **Contributing guide** — Document how to add a new language analyzer plugin
- [ ] **Changelog** — Start tracking changes per version

---

## ✅ Done

- [x] Core indexer with AST + regex fallback parsing
- [x] Selector with quick / standard / thorough levels
- [x] Confidence scoring system
- [x] CLI with `index`, `select`, `info` commands
- [x] Multi-language analyzer plugin architecture (Python, Go, Rust)
- [x] Incremental indexing (mtime + size change detection)
- [x] Validation harness (`validate.py`) with historical commit replay
- [x] Marshmallow validation — 30 commits, 0% miss rate
- [x] Logrus (Go) validation
