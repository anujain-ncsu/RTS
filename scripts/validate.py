#!/usr/bin/env python3
"""Validation script for the Relevant Test Selector.

Analyzes historical commits from a repository, runs the selector on each,
then runs the actual test suite to compare predictions vs reality.

Usage:
    python3 scripts/validate.py --repo /tmp/httpx-test --commits 30
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


def get_commits_with_python_changes(repo_path: str, count: int) -> list[dict]:
    """Get recent commits that modified Python files (non-merge only)."""
    result = subprocess.run(
        [
            "git", "log", "--oneline", "--no-merges",
            "--format=%H|%s",
            "--", "*.py",
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
    """Get files changed in a specific commit."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{commit_hash}~1..{commit_hash}"],
        cwd=repo_path,
        capture_output=True, text=True, check=True,
    )
    return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]


def get_changed_python_files(repo_path: str, commit_hash: str) -> list[str]:
    """Get only Python files changed in a specific commit."""
    all_files = get_changed_files(repo_path, commit_hash)
    return [f for f in all_files if f.endswith(".py")]


def run_tests_at_commit(repo_path: str, commit_hash: str, test_timeout: int = 120) -> dict:
    """Checkout a commit and run the test suite, returning pass/fail info.

    Returns dict with:
      - test_results: list of {name, outcome} for each test
      - total_tests: number of tests run
      - failed_tests: list of test names that failed
      - passed_tests: list of test names that passed
      - errors: list of test names that errored
      - run_error: string if test run itself failed
    """
    # Checkout the commit
    subprocess.run(
        ["git", "checkout", "--force", commit_hash],
        cwd=repo_path,
        capture_output=True, text=True, check=True,
    )

    # Run pytest with JSON-style output
    # Use --tb=no for speed, -q for brevity
    # --timeout to prevent hanging tests
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                "tests/", "-v", "--tb=no", "--no-header",
                f"--timeout={test_timeout}",
                "-x",  # Stop on first failure for efficiency (we record it)
            ],
            cwd=repo_path,
            capture_output=True, text=True,
            timeout=test_timeout * 2,  # Overall timeout
        )
    except subprocess.TimeoutExpired:
        return {
            "test_results": [],
            "total_tests": 0,
            "failed_tests": [],
            "passed_tests": [],
            "errors": [],
            "run_error": "Test run timed out",
        }
    except Exception as e:
        return {
            "test_results": [],
            "total_tests": 0,
            "failed_tests": [],
            "passed_tests": [],
            "errors": [],
            "run_error": str(e),
        }

    # Parse pytest verbose output
    failed_tests = []
    passed_tests = []
    errors = []
    test_results = []

    for line in result.stdout.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Pytest verbose format: tests/test_foo.py::test_bar PASSED
        if " PASSED" in line and "::" in line:
            test_name = line.split(" PASSED")[0].strip()
            test_results.append({"name": test_name, "outcome": "passed"})
            passed_tests.append(test_name)
        elif " FAILED" in line and "::" in line:
            test_name = line.split(" FAILED")[0].strip()
            test_results.append({"name": test_name, "outcome": "failed"})
            failed_tests.append(test_name)
        elif " ERROR" in line and "::" in line:
            test_name = line.split(" ERROR")[0].strip()
            test_results.append({"name": test_name, "outcome": "error"})
            errors.append(test_name)

    run_error = None
    if result.returncode != 0 and not failed_tests and not errors:
        # Test collection or setup error
        run_error = f"pytest exit code {result.returncode}"
        if result.stderr:
            run_error += f": {result.stderr[:500]}"

    return {
        "test_results": test_results,
        "total_tests": len(test_results),
        "failed_tests": failed_tests,
        "passed_tests": passed_tests,
        "errors": errors,
        "run_error": run_error,
    }


def run_selector(
    index_data,
    changed_python_files: list[str],
    thoroughness: Thoroughness,
) -> dict:
    """Run the selector and return results."""
    traversal = GraphTraversal(index_data)
    scorer = Scorer()

    affected = traversal.find_affected_tests(changed_python_files, thoroughness)

    selected_tests = {}
    for test_file, depth in affected.items():
        score = scorer.score_from_depth(depth)
        reason = scorer.depth_to_reason(depth)
        selected_tests[test_file] = {
            "confidence": round(score, 4),
            "reasons": [reason],
        }

    # Apply heuristics at thorough level
    if thoroughness == Thoroughness.THOROUGH:
        heuristics = Heuristics(index_data)
        heuristic_matches = heuristics.find_related_tests(
            changed_python_files,
            already_selected=set(selected_tests.keys()),
        )
        for test_file, reasons in heuristic_matches.items():
            heur_score = scorer.score_from_reasons(reasons)
            selected_tests[test_file] = {
                "confidence": round(heur_score, 4),
                "reasons": reasons,
            }

    return selected_tests


def extract_test_file_from_nodeid(nodeid: str) -> str:
    """Extract the file path from a pytest node ID.

    e.g., 'tests/test_models.py::test_request' -> 'tests/test_models.py'
    """
    return nodeid.split("::")[0]


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Validate RTS selector against historical commits")
    parser.add_argument("--repo", required=True, help="Path to the repository")
    parser.add_argument("--commits", type=int, default=30, help="Number of commits to analyze")
    parser.add_argument("--thoroughness", default="standard", help="Thoroughness level")
    parser.add_argument("--output-dir", default=None, help="Output directory for results")
    args = parser.parse_args()

    repo_path = args.repo
    repo_name = Path(repo_path).name
    thoroughness = Thoroughness(args.thoroughness)

    output_dir = args.output_dir or str(
        Path(__file__).parent.parent / "Validation"
    )
    os.makedirs(output_dir, exist_ok=True)

    print(f"=== RTS Validation Against Historical Commits ===")
    print(f"Repository: {repo_path}")
    print(f"Thoroughness: {thoroughness.value}")
    print(f"Target commits: {args.commits}")
    print()

    # Step 1: Get the current HEAD hash to restore later
    head_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path, capture_output=True, text=True, check=True,
    )
    original_head = head_result.stdout.strip()

    # Also get the branch name
    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_path, capture_output=True, text=True, check=True,
    )
    original_branch = branch_result.stdout.strip()

    # Step 2: Build index at HEAD
    print("Building index at HEAD...")
    builder = GraphBuilder(Path(repo_path))
    index_data = builder.build_index()

    store = IndexStore(Path(repo_path))
    store.save(index_data)

    total_test_files = [
        fp for fp, info in index_data.files.items()
        if info.file_type == FileType.TEST
    ]
    print(f"Index built: {len(index_data.files)} files, {len(total_test_files)} test files")
    print()

    # Step 3: Get commits to analyze
    print(f"Fetching {args.commits} commits with Python changes...")
    commits = get_commits_with_python_changes(repo_path, args.commits + 10)  # extras in case some fail
    print(f"Found {len(commits)} candidate commits")
    print()

    # Step 4: Analyze each commit
    results = []
    total_missed = 0
    total_failed = 0
    total_correctly_selected = 0

    for i, commit in enumerate(commits[:args.commits]):
        commit_hash = commit["hash"]
        commit_msg = commit["message"][:80]
        print(f"[{i+1}/{args.commits}] Analyzing {commit_hash[:8]}: {commit_msg}")

        try:
            changed_files = get_changed_files(repo_path, commit_hash)
            changed_py_files = [f for f in changed_files if f.endswith(".py")]
        except subprocess.CalledProcessError:
            print(f"  ⚠ Could not get changed files (initial commit?), skipping")
            continue

        if not changed_py_files:
            print(f"  ⚠ No Python files changed, skipping")
            continue

        # Run selector using HEAD index
        start = time.time()
        selected = run_selector(index_data, changed_py_files, thoroughness)
        select_time = (time.time() - start) * 1000

        selected_test_files = set(selected.keys())

        print(f"  Changed files: {len(changed_py_files)}")
        print(f"  Selector chose: {len(selected_test_files)} test files ({select_time:.1f}ms)")

        # Run actual tests at this commit
        test_results = run_tests_at_commit(repo_path, commit_hash)

        if test_results["run_error"]:
            print(f"  ⚠ Test run error: {test_results['run_error']}")

        # Determine which test FILES had failures
        failed_test_files = set()
        for failed in test_results["failed_tests"]:
            failed_test_files.add(extract_test_file_from_nodeid(failed))
        for errored in test_results["errors"]:
            failed_test_files.add(extract_test_file_from_nodeid(errored))

        # Calculate miss: tests that failed but were NOT selected
        missed_tests = failed_test_files - selected_test_files
        correctly_selected = failed_test_files & selected_test_files

        total_missed += len(missed_tests)
        total_failed += len(failed_test_files)
        total_correctly_selected += len(correctly_selected)

        print(f"  Tests run: {test_results['total_tests']}")
        print(f"  Failed: {len(test_results['failed_tests'])}")
        print(f"  Errors: {len(test_results['errors'])}")
        if missed_tests:
            print(f"  ❌ MISSED: {missed_tests}")
        elif failed_test_files:
            print(f"  ✅ All failures were in selected tests")
        else:
            print(f"  ✅ No failures")

        commit_result = {
            "commit_hash": commit_hash,
            "commit_message": commit["message"],
            "changed_files": changed_files,
            "changed_python_files": changed_py_files,
            "selector_thoroughness": thoroughness.value,
            "selector_time_ms": round(select_time, 2),
            "selected_test_files": sorted(selected_test_files),
            "selected_test_details": {
                k: v for k, v in sorted(selected.items())
            },
            "actual_test_results": {
                "total_tests_run": test_results["total_tests"],
                "passed": len(test_results["passed_tests"]),
                "failed": len(test_results["failed_tests"]),
                "errors": len(test_results["errors"]),
                "run_error": test_results["run_error"],
                "failed_test_nodeids": test_results["failed_tests"],
                "error_test_nodeids": test_results["errors"],
                "failed_test_files": sorted(failed_test_files),
            },
            "analysis": {
                "failed_and_selected": sorted(correctly_selected),
                "failed_and_not_selected": sorted(missed_tests),
                "commit_miss_count": len(missed_tests),
                "commit_fail_count": len(failed_test_files),
            },
        }

        results.append(commit_result)

    # Restore original HEAD
    print(f"\nRestoring to {original_branch} ({original_head[:8]})...")
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

    # Calculate overall metrics
    if total_failed > 0:
        miss_rate = total_missed / total_failed
    else:
        miss_rate = 0.0

    # Also compute how many commits had failures
    commits_with_failures = sum(
        1 for r in results if r["analysis"]["commit_fail_count"] > 0
    )
    commits_with_misses = sum(
        1 for r in results if r["analysis"]["commit_miss_count"] > 0
    )

    summary = {
        "total_commits_analyzed": len(results),
        "commits_with_test_failures": commits_with_failures,
        "commits_with_selector_misses": commits_with_misses,
        "total_failed_test_files": total_failed,
        "total_correctly_selected_failures": total_correctly_selected,
        "total_missed_failures": total_missed,
        "miss_rate": round(miss_rate, 4),
        "miss_rate_percentage": f"{miss_rate * 100:.2f}%",
        "miss_rate_definition": (
            "Fraction of test files that actually failed but were NOT selected "
            "by the selector. Lower is better. 0% = perfect recall."
        ),
    }

    # Build final output
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = {
        "metadata": {
            "repository": repo_path,
            "repository_name": repo_name,
            "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            "rts_version": "0.1.0",
            "thoroughness_level": thoroughness.value,
            "index_built_from": "HEAD",
            "total_files_in_index": len(index_data.files),
            "total_test_files_in_index": len(total_test_files),
        },
        "summary": summary,
        "commits": results,
    }

    # Write output file
    filename = f"validation_results_{repo_name}_{timestamp}.json"
    output_path = Path(output_dir) / filename
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    print(f"Commits analyzed:           {len(results)}")
    print(f"Commits with failures:      {commits_with_failures}")
    print(f"Commits with misses:        {commits_with_misses}")
    print(f"Total failed test files:    {total_failed}")
    print(f"Correctly selected:         {total_correctly_selected}")
    print(f"Missed:                     {total_missed}")
    print(f"Miss rate:                  {miss_rate * 100:.2f}%")
    print()
    print(f"Results saved to: {output_path}")

    return 0 if miss_rate == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
