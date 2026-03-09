# Marshmallow Validation Summary (30 Commits)

**Repository:** marshmallow-code/marshmallow (tag 3.26.2)
**Date:** 2026-03-09
**Miss rate:** 0.00%

| # | Commit | Message | Changed | Selected | Failed | Thoroughness |
|---|--------|---------|:---:|:---:|:---:|---|
| 1 | `70fb5995` | More linking to marshmallow.Schema.Meta | 1 | **16** | 0 | standard |
| 2 | `ff82d87d` | Remove unnecessary import alias | 1 | **16** | 0 | standard |
| 3 | `a3ff44eb` | Improve readability of summary tables | 2 | **16** | 0 | standard |
| 4 | `36cfabf3` | Only show types in arg descriptions | 1 | **0** | 0 | standard |
| 5 | `10332c59` | Fix type annotations in fields/class_registry | 2 | **16** | 0 | standard |
| 6 | `f907ced0` | Use Validator type | 1 | **16** | 0 | standard |
| 7 | `2c0c75fe` | Add config for view button | 1 | **0** | 0 | standard |
| 8 | `fe53fd0b` | More documentation improvements | 1 | **0** | 0 | standard |
| 9 | `05cdf8ce` | Document base field deprecations in API docs | 1 | **16** | 0 | standard |
| 10 | `1d086ffc` | Migrate docs theme to furo | 1 | **0** | 0 | standard |
| 11 | `83c409d5` | Minor documentation improvements | 8 | **16** | 0 | standard |
| 12 | `e2038e00` | Restore SchemaABC for backwards-compat | 2 | **16** | 0 | standard |
| 13 | `5eb22423` | Fix opts typing | 1 | **16** | 0 | standard |
| 14 | `73a35694` | Improve types for get_declared_fields | 1 | **16** | 0 | standard |
| 15 | `953a6a59` | Avoid breaking inspect.signature on fields | 1 | **16** | 0 | standard |
| 16 | `6c1a95d1` | Add top-level API to API docs | 4 | **16** | 0 | standard |
| 17 | `09029410` | Fix typing for class_registry.get_class | 2 | **16** | 0 | standard |
| 18 | `8ca596d9` | Deprecation warnings for marshmallow 4 | 9 | **16** | 0 | standard |
| 19 | `71ab95a9` | Deprecate context | 4 | **16** | 0 | standard |
| 20 | `ea2b0edc` | Make casing consistent across docs | 1 | **0** | 0 | standard |
| 21 | `54ce7095` | Update pypi links | 1 | **0** | 0 | quick |
| 22 | `755a074f` | Prevent false from appearing under logo | 1 | **0** | 0 | quick |
| 23 | `f98ad7fc` | Bump alabaster from 0.7.13 to 0.7.15 | 1 | **0** | 0 | quick |
| 24 | `b1857ef1` | Bump autodocsumm from 0.2.11 to 0.2.12 | 1 | **0** | 0 | quick |
| 25 | `75bf11c8` | Bump mypy from 1.7.0 to 1.7.1 | 1 | **0** | 0 | quick |
| 26 | `5165baab` | Bump mypy from 1.6.1 to 1.7.0 | 1 | **0** | 0 | quick |
| 27 | `170dc700` | Bump mypy from 1.5.1 to 1.6.1 | 1 | **0** | 0 | quick |
| 28 | `63a4bab9` | Update legacy timezone US/Central→America/Chicago | 1 | **7** | 0 | quick |
| 29 | `c227d3b0` | Add support for Python 3.12 | 1 | **0** | 0 | quick |
| 30 | `26fa0f51` | Bump sphinx from 7.2.5 to 7.2.6 | 1 | **0** | 0 | quick |

## Key Observations

- **Standard (depth ≤ 3):** All source-file changes select **16/18 test files** due to marshmallow's tight coupling via `__init__.py`
- **Quick (depth 0):** Commit #28 shows real differentiation — **7 tests** selected for a test-file-only change
- **Docs/config changes** correctly get **0 tests** selected at both thoroughness levels
- **0 test failures missed** across all 30 commits
