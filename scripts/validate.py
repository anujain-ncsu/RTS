#!/usr/bin/env python3
"""Validation script for the Relevant Test Selector.

Analyzes historical commits from a repository, runs the selector on each,
then runs the actual test suite at each commit to compare predictions vs reality.

Approach:
  1. Build the index at HEAD.
  2. For each historical commit:
     a. Determine changed matching files.
     b. Run the selector to predict relevant tests.
     c. Checkout that commit.
     d. Run ALL tests (with per-test timeout to handle network tests).
     e. Record which tests passed/failed/errored.
     f. Compute miss: tests that failed but were NOT selected.

Miss Rate = (# of test files that failed but were NOT selected) /
            (# of test files that failed)

Usage:
    python3 scripts/validate.py --repo /tmp/httpx-test --commits 30 --language python
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rts.indexer.graph_builder import GraphBuilder
from rts.indexer.index_store import IndexStore
from rts.models import FileType, Thoroughness
from rts.selector.diff_parser import DiffParser
from rts.selector.graph_traversal import GraphTraversal
from rts.selector.heuristics import Heuristics
from rts.selector.scorer import Scorer

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


import shutil

def _find_go_binary() -> str:
    """Find the Go binary, searching common install paths."""
    # Try PATH first
    go_path = shutil.which("go")
    if go_path:
        return go_path
    
    # Common locations on macOS / Linux
    candidates = [
        "/usr/local/go/bin/go",
        "/opt/homebrew/bin/go",
        "/opt/homebrew/Cellar/go/*/bin/go",  # Homebrew cellar
        "/usr/local/bin/go",
        os.path.expanduser("~/go/bin/go"),
        os.path.expanduser("~/sdk/go/bin/go"),
    ]
    
    import glob
    for pattern in candidates:
        matches = glob.glob(pattern)
        for match in matches:
            if os.path.isfile(match) and os.access(match, os.X_OK):
                return match
    
    # Fall back to bare "go" and let the caller handle the error
    return "go"

def get_commits_with_changes(repo_path: str, count: int, file_ext: str) -> list[dict]:
    """Get recent non-merge commits that modified source or test files."""
    result = subprocess.run(
        [
            "git", "log", "--oneline", "--no-merges",
            "--format=%H|%s",
            "--", f"*{file_ext}",
        ],
        cwd=repo_path,
        capture_output=True, text=True, check=True,
    )

    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 1)
        if len(parts) == 2:
            commits.append({"hash": parts[0], "message": parts[1]})
        if len(commits) >= count:
            break

    return commits


def get_changed_files(repo_path: str, commit_hash: str) -> list[str]:
    """Get files changed in a specific commit (compared to its parent)."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{commit_hash}~1..{commit_hash}"],
        cwd=repo_path,
        capture_output=True, text=True, check=True,
    )
    return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]


def run_tests_at_commit(repo_path: str, commit_hash: str, language: str) -> dict:
    """Checkout a commit and run ALL tests, capturing per-test outcomes.

    Uses appropriate timeouts for network-heavy tests.

    Returns:
        dict with keys:
          - passed_tests: list of test identifiers that passed
          - failed_tests: list of test identifiers that failed
          - errored_tests: list of test identifiers that errored (timeout, import err)
          - total_run: total tests executed
          - run_error: string if the entire run errored
    """
    # Checkout the commit
    subprocess.run(
        ["git", "checkout", "--force", commit_hash],
        cwd=repo_path,
        capture_output=True, text=True, check=True,
    )

    passed, failed, errored = [], [], []
    run_error = None

    if language == "go":
        go_bin = _find_go_binary()
        try:
            # We must use go test -json ./...
            result = subprocess.run(
                [go_bin, "test", "-json", "./...", "-timeout=15s"],
                cwd=repo_path,
                capture_output=True, text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            return {
                "passed_tests": [], "failed_tests": [], "errored_tests": [],
                "total_run": 0, "run_error": "Overall test run timed out (600s)",
            }
        except Exception as e:
            return {
                "passed_tests": [], "failed_tests": [], "errored_tests": [],
                "total_run": 0, "run_error": str(e),
            }

        passed_set, failed_set = set(), set()
        
        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
                
            if "Test" in event and "Action" in event:
                test_name = event["Test"]
                action = event["Action"]
                pkg = event.get("Package", "")
                
                # nodeid to be processed later by looking up test functions
                nodeid = f"{pkg}::{test_name}"
                
                if action == "pass":
                    passed_set.add(nodeid)
                elif action == "fail":
                    failed_set.add(nodeid)
        
        passed = list(passed_set)
        failed = list(failed_set)

        if result.returncode != 0 and not failed and not passed:
            stderr_snippet = (result.stderr or "")[:800]
            stdout_snippet = (result.stdout or "")[:800]
            run_error = f"go test exit code {result.returncode}. stderr: {stderr_snippet}. stdout: {stdout_snippet}"

    else:
        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pytest",
                    "tests/", "-v", "--tb=no", "--no-header",
                    "--timeout=15",
                ],
                cwd=repo_path,
                capture_output=True, text=True,
                timeout=600,  # Overall 10-minute cap
            )
        except subprocess.TimeoutExpired:
            return {
                "passed_tests": [], "failed_tests": [], "errored_tests": [],
                "total_run": 0, "run_error": "Overall test run timed out (600s)",
            }
        except Exception as e:
            return {
                "passed_tests": [], "failed_tests": [], "errored_tests": [],
                "total_run": 0, "run_error": str(e),
            }

        # Parse pytest -v output lines:
        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line or "::" not in line:
                continue

            if " PASSED" in line:
                nodeid = line.rsplit(" PASSED", 1)[0].strip()
                passed.append(nodeid)
            elif " FAILED" in line:
                nodeid = line.rsplit(" FAILED", 1)[0].strip()
                failed.append(nodeid)
            elif " ERROR" in line:
                nodeid = line.rsplit(" ERROR", 1)[0].strip()
                errored.append(nodeid)
            elif " XFAIL" in line or " XPASS" in line or " SKIPPED" in line:
                pass  # Ignore expected failures/skips

        if result.returncode != 0 and not failed and not errored and not passed:
            # Collection error or setup failure
            stderr_snippet = (result.stderr or "")[:800]
            stdout_snippet = (result.stdout or "")[:800]
            run_error = f"pytest exit code {result.returncode}. stderr: {stderr_snippet}. stdout: {stdout_snippet}"

    return {
        "passed_tests": passed,
        "failed_tests": failed,
        "errored_tests": errored,
        "total_run": len(passed) + len(failed) + len(errored),
        "run_error": run_error,
    }


def run_selector(index_data, changed_files, thoroughness, language="python"):
    """Run the selector and return dict of selected test_file -> info."""
    traversal = GraphTraversal(index_data)
    scorer = Scorer()

    affected = traversal.find_affected_tests(changed_files, thoroughness)

    selected = {}
    for test_file, depth in affected.items():
        score = scorer.score_from_depth(depth)
        reason = scorer.depth_to_reason(depth)
        selected[test_file] = {
            "confidence": round(score, 4),
            "reasons": [reason],
        }

    if thoroughness == Thoroughness.THOROUGH:
        heuristics = Heuristics(index_data)
        heuristic_matches = heuristics.find_related_tests(
            changed_files,
            already_selected=set(selected.keys()),
        )
        for test_file, reasons in heuristic_matches.items():
            heur_score = scorer.score_from_reasons(reasons)
            selected[test_file] = {
                "confidence": round(heur_score, 4),
                "reasons": reasons,
            }

    import re
    if language == "go":
        test_pattern = re.compile(r".*_test\.go$")
    else:
        test_pattern = re.compile(r"^tests/.*_test.*\.py|.*test_.*\.py")
        
    for changed_file in changed_files:
        if test_pattern.search(changed_file) or (
            changed_file in index_data.files and index_data.files[changed_file].file_type == FileType.TEST
        ):
            if changed_file not in selected:
                selected[changed_file] = {
                    "confidence": 1.0,
                    "reasons": ["directly_modified_test"],
                }

    return selected


def nodeid_to_file(nodeid: str) -> str:
    """Extract file path from pytest node ID: tests/foo.py::test_x -> tests/foo.py"""
    return nodeid.split("::")[0]


# Commit message patterns that indicate trivial (non-business-logic) changes
_TRIVIAL_MSG_PATTERNS = [
    # Linting / formatting
    r"(?i)\b(lint|delint|flake8|ruff|black|isort|autopep|pep8|pyflakes|pylint)\b",
    r"(?i)^\s*(style|formatting|format|reformat)",
    r"(?i)\bcode\s*style\b",
    # Pre-commit / CI bots
    r"(?i)\[pre-commit",
    r"(?i)pre-commit\s+(auto|hook)",
    r"(?i)\[ci\s+skip\]",
    # Typo / comment / docstring only
    r"(?i)^\s*(fix|correct)\s+(typo|spelling|whitespace|comment)",
    r"(?i)^\s*typo",
    r"(?i)^\s*(update|fix)\s+docstring",
    r"(?i)^\s*fix\s+docstring\s+typo",
    # Version bumps
    r"(?i)^\s*(bump|release)\s+(version|v?\d)",
    # Changelog-only
    r"(?i)^\s*(update|add)\s+changelog",
    # Merge commits that slipped through
    r"(?i)^\s*merge\s+(branch|pull|pr|request)",
]
_TRIVIAL_MSG_RE = [__import__("re").compile(p) for p in _TRIVIAL_MSG_PATTERNS]


def _diff_is_whitespace_only(repo_path: str, commit_hash: str, file_ext: str = ".py") -> bool:
    """Return True if the commit's diffs are purely whitespace/comment changes."""
    try:
        result = subprocess.run(
            ["git", "diff", "-U0", "--ignore-all-space",
             f"{commit_hash}~1..{commit_hash}", "--", f"*{file_ext}"],
            cwd=repo_path, capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError:
        return False  # can't tell, assume non-trivial

    # If ignoring whitespace produces no diff lines, it's whitespace-only
    for line in result.stdout.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            content = line[1:].strip()
            # Skip blank lines and comment-only lines
            if content and not (content.startswith("#") or content.startswith("//")):
                return False
        elif line.startswith("-") and not line.startswith("---"):
            content = line[1:].strip()
            if content and not (content.startswith("#") or content.startswith("//")):
                return False
    return True


def is_trivial_commit(repo_path: str, commit_hash: str, commit_msg: str, file_ext: str = ".py") -> bool:
    """Return True if a commit is non-substantial (linting, formatting, comments, etc.)."""
    # 1. Check commit message against known trivial patterns
    for regex in _TRIVIAL_MSG_RE:
        if regex.search(commit_msg):
            return True

    # 2. Check if the actual diff is whitespace/comment-only
    if _diff_is_whitespace_only(repo_path, commit_hash, file_ext):
        return True

    return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Validate RTS selector against history")
    parser.add_argument("--repo", required=True, help="Path to the repository")
    parser.add_argument("--commits", type=int, default=30, help="Number of commits")
    parser.add_argument("--thoroughness", default="standard")
    parser.add_argument("--language", default="python", choices=["python", "go"])
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--skip-trivial", action="store_true",
                        help="Skip non-substantial commits (linting, formatting, typos, etc.)")
    args = parser.parse_args()

    repo_path = args.repo
    repo_name = Path(repo_path).name
    thoroughness = Thoroughness(args.thoroughness)
    output_dir = args.output_dir or str(Path(__file__).parent.parent / "Validation")
    os.makedirs(output_dir, exist_ok=True)
    
    file_ext = ".go" if args.language == "go" else ".py"

    print("=" * 60)
    print("RTS VALIDATION AGAINST HISTORICAL COMMITS")
    print("=" * 60)
    print(f"Repository:   {repo_path}")
    print(f"Language:     {args.language}")
    print(f"Thoroughness: {thoroughness.value}")
    print(f"Commits:      {args.commits}")
    print(f"Skip trivial: {args.skip_trivial}")
    print()

    # Save original HEAD
    head_result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_path,
        capture_output=True, text=True, check=True,
    )
    original_head = head_result.stdout.strip()

    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path,
        capture_output=True, text=True, check=True,
    )
    original_branch = branch_result.stdout.strip()

    # Build index at HEAD
    print("Building index at HEAD...")
    builder = GraphBuilder(Path(repo_path))
    index_data = builder.build_index()
    store = IndexStore(Path(repo_path))
    store.save(index_data)

    test_files_in_index = [
        fp for fp, info in index_data.files.items()
        if info.file_type == FileType.TEST
    ]
    print(f"Index: {len(index_data.files)} files, {len(test_files_in_index)} test files")
    print()

    # Get commits
    print(f"Fetching commits with {args.language} changes...")
    # Request extra to handle skips (more if filtering trivial commits)
    fetch_count = args.commits * 3 if args.skip_trivial else args.commits + 15
    all_commits = get_commits_with_changes(repo_path, fetch_count, file_ext)
    print(f"Found {len(all_commits)} candidate commits")
    print()

    trivial_skipped = 0

    # Analyze each commit
    results = []
    stats = {
        "total_missed": 0,
        "total_failed_files": 0,
        "total_correctly_selected_files": 0,
    }

    analyzed = 0
    for i, commit in enumerate(all_commits):
        if analyzed >= args.commits:
            break

        commit_hash = commit["hash"]
        short_hash = commit_hash[:8]
        commit_msg = commit["message"][:70]

        print(f"[{analyzed + 1}/{args.commits}] {short_hash}: {commit_msg}")

        # Get changed files
        try:
            all_changed = get_changed_files(repo_path, commit_hash)
            changed_target_files = [f for f in all_changed if f.endswith(file_ext)]
        except subprocess.CalledProcessError:
            print(f"  ⚠ Skipping (can't diff, possibly initial commit)")
            continue

        if not changed_target_files:
            print(f"  ⚠ No {args.language} files changed, skipping")
            continue

        # Skip trivial commits if requested
        if args.skip_trivial and is_trivial_commit(repo_path, commit_hash, commit["message"], file_ext):
            print(f"  ⚠ Trivial commit (linting/formatting/comments), skipping")
            trivial_skipped += 1
            continue

        # Run selector
        t0 = time.time()
        selected = run_selector(index_data, changed_target_files, thoroughness, args.language)
        select_ms = (time.time() - t0) * 1000
        selected_files = set(selected.keys())

        print(f"  Changed: {len(changed_target_files)} {file_ext} file(s)  |  Selected: {len(selected_files)} test(s) ({select_ms:.1f}ms)")

        # Run actual tests at this commit
        t1 = time.time()
        test_out = run_tests_at_commit(repo_path, commit_hash, args.language)
        test_secs = time.time() - t1

        if test_out["run_error"]:
            print(f"  ⚠ Run error: {test_out['run_error'][:100]}")

        # Aggregate failed files (count FAILED and ERROR separately)
        failed_file_set = set()
        for nodeid in test_out["failed_tests"]:
            if args.language == "go":
                test_name = nodeid.split("::")[-1]
                file_found = False
                for fp, info in index_data.files.items():
                    if test_name in info.test_functions:
                        failed_file_set.add(fp)
                        file_found = True
                        break
                if not file_found:
                    print(f"    ⚠ Could not map failed test {test_name} to a file")
            else:
                failed_file_set.add(nodeid_to_file(nodeid))

        errored_file_set = set()
        for nodeid in test_out["errored_tests"]:
            if args.language == "go":
                pass
            else:
                errored_file_set.add(nodeid_to_file(nodeid))

        # For miss rate, we focus on FAILED (genuine failures) not errors
        # (which are typically timeouts/import issues)
        missed_files = failed_file_set - selected_files
        correctly_selected = failed_file_set & selected_files

        stats["total_missed"] += len(missed_files)
        stats["total_failed_files"] += len(failed_file_set)
        stats["total_correctly_selected_files"] += len(correctly_selected)

        status_icon = "✅"
        if missed_files:
            status_icon = "❌"
        elif failed_file_set:
            status_icon = "✅"

        print(f"  Tests: {test_out['total_run']} run, "
              f"{len(test_out['failed_tests'])} failed, "
              f"{len(test_out['errored_tests'])} errors  "
              f"({test_secs:.1f}s)")

        if missed_files:
            print(f"  {status_icon} MISSED failures in: {sorted(missed_files)}")
        elif failed_file_set:
            print(f"  {status_icon} All {len(failed_file_set)} failed file(s) were selected")
        else:
            print(f"  {status_icon} No test failures")

        commit_result = {
            "commit_hash": commit_hash,
            "commit_message": commit["message"],
            "changed_files": all_changed,
            f"changed_{args.language}_files": changed_target_files,
            "selector": {
                "thoroughness": thoroughness.value,
                "time_ms": round(select_ms, 2),
                "selected_test_files": sorted(selected_files),
                "selected_count": len(selected_files),
                "details": {k: v for k, v in sorted(selected.items())},
            },
            "actual_test_run": {
                "total_tests_run": test_out["total_run"],
                "passed_count": len(test_out["passed_tests"]),
                "failed_count": len(test_out["failed_tests"]),
                "error_count": len(test_out["errored_tests"]),
                "run_error": test_out["run_error"],
                "failed_test_nodeids": test_out["failed_tests"],
                "error_test_nodeids": test_out["errored_tests"],
                "failed_test_files": sorted(failed_file_set),
                "errored_test_files": sorted(errored_file_set),
            },
            "analysis": {
                "failed_files_correctly_selected": sorted(correctly_selected),
                "failed_files_missed_by_selector": sorted(missed_files),
                "miss_count": len(missed_files),
                "fail_count": len(failed_file_set),
            },
        }
        results.append(commit_result)
        analyzed += 1

    # Restore HEAD
    print(f"\nRestoring to {original_branch}...")
    try:
        subprocess.run(
            ["git", "checkout", "--force", original_branch],
            cwd=repo_path, capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError:
        subprocess.run(
            ["git", "checkout", "--force", original_head],
            cwd=repo_path, capture_output=True, text=True, check=True,
        )

    # Compute overall metrics
    total_f = stats["total_failed_files"]
    total_m = stats["total_missed"]
    total_c = stats["total_correctly_selected_files"]
    miss_rate = total_m / total_f if total_f > 0 else 0.0

    commits_with_failures = sum(1 for r in results if r["analysis"]["fail_count"] > 0)
    commits_with_misses = sum(1 for r in results if r["analysis"]["miss_count"] > 0)

    summary = {
        "total_commits_analyzed": len(results),
        "commits_with_test_failures": commits_with_failures,
        "commits_with_selector_misses": commits_with_misses,
        "trivial_skipped": trivial_skipped,
        "total_failed_test_files_across_all_commits": total_f,
        "total_correctly_selected_failures": total_c,
        "total_missed_failures": total_m,
        "miss_rate": round(miss_rate, 4),
        "miss_rate_percentage": f"{miss_rate * 100:.2f}%",
        "miss_rate_definition": (
            "Fraction of test files that actually FAILED (not errored) "
            "but were NOT selected by the RTS selector. "
            "Lower is better. 0.00% = perfect recall."
        ),
    }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = {
        "metadata": {
            "repository_path": f"./{repo_name}",
            "repository_name": repo_name,
            "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            "rts_version": "0.1.0",
            "thoroughness_level": thoroughness.value,
            "language": args.language,
            "index_built_from": f"HEAD ({original_head[:8]})",
            "total_files_in_index": len(index_data.files),
            "total_test_files_in_index": len(test_files_in_index),
        },
        "summary": summary,
        "commits": results,
    }

    filename = f"validation_results_{repo_name}_{args.language}_{timestamp}.json"
    output_path = Path(output_dir) / filename
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    print(f"Commits analyzed:           {len(results)}")
    print(f"Trivial skipped:            {trivial_skipped}")
    print(f"Commits with failures:      {commits_with_failures}")
    print(f"Commits with misses:        {commits_with_misses}")
    print(f"Total failed test files:    {total_f}")
    print(f"Correctly selected:         {total_c}")
    print(f"Missed:                     {total_m}")
    print(f"MISS RATE:                  {miss_rate * 100:.2f}%")
    print()
    print(f"Results saved to: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
