#!/usr/bin/env python3
"""Validation script for the Relevant Test Selector.

Analyzes historical commits from a repository, runs the selector on each,
then runs the actual test suite at each commit to compare predictions vs reality.

Approach:
  1. Build the index at HEAD.
  2. For each historical commit:
     a. Determine changed Python files.
     b. Run the selector to predict relevant tests.
     c. Checkout that commit.
     d. Run ALL tests (with per-test timeout to handle network tests).
     e. Record which tests passed/failed/errored.
     f. Compute miss: tests that failed but were NOT selected.

Miss Rate = (# of test files that failed but were NOT selected) /
            (# of test files that failed)

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
    """Get recent non-merge commits that modified Python source or test files."""
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
    """Get files changed in a specific commit (compared to its parent)."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{commit_hash}~1..{commit_hash}"],
        cwd=repo_path,
        capture_output=True, text=True, check=True,
    )
    return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]


def run_tests_at_commit(repo_path: str, commit_hash: str) -> dict:
    """Checkout a commit and run ALL tests, capturing per-test outcomes.

    Uses --timeout=15 per-test (for network-heavy tests).
    Does NOT use -x so that the full suite is run.

    Returns:
        dict with keys:
          - passed_tests: list of pytest node IDs that passed
          - failed_tests: list of pytest node IDs that failed
          - errored_tests: list of pytest node IDs that errored (timeout, import err)
          - total_run: total tests executed
          - run_error: string if the entire run errored
    """
    # Checkout the commit
    subprocess.run(
        ["git", "checkout", "--force", commit_hash],
        cwd=repo_path,
        capture_output=True, text=True, check=True,
    )

    # Run all tests with verbose output, per-test timeout
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
    #   tests/test_foo.py::test_bar PASSED
    #   tests/test_foo.py::test_baz FAILED
    #   tests/test_foo.py::test_qux ERROR
    passed, failed, errored = [], [], []

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

    run_error = None
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


def run_selector(index_data, changed_python_files, thoroughness):
    """Run the selector and return dict of selected test_file -> info."""
    traversal = GraphTraversal(index_data)
    scorer = Scorer()

    affected = traversal.find_affected_tests(changed_python_files, thoroughness)

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
            changed_python_files,
            already_selected=set(selected.keys()),
        )
        for test_file, reasons in heuristic_matches.items():
            heur_score = scorer.score_from_reasons(reasons)
            selected[test_file] = {
                "confidence": round(heur_score, 4),
                "reasons": reasons,
            }

    return selected


def nodeid_to_file(nodeid: str) -> str:
    """Extract file path from pytest node ID: tests/foo.py::test_x -> tests/foo.py"""
    return nodeid.split("::")[0]


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Validate RTS selector against history")
    parser.add_argument("--repo", required=True, help="Path to the repository")
    parser.add_argument("--commits", type=int, default=30, help="Number of commits")
    parser.add_argument("--thoroughness", default="standard")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    repo_path = args.repo
    repo_name = Path(repo_path).name
    thoroughness = Thoroughness(args.thoroughness)
    output_dir = args.output_dir or str(Path(__file__).parent.parent / "Validation")
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("RTS VALIDATION AGAINST HISTORICAL COMMITS")
    print("=" * 60)
    print(f"Repository:   {repo_path}")
    print(f"Thoroughness: {thoroughness.value}")
    print(f"Commits:      {args.commits}")
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
    print(f"Fetching commits with Python changes...")
    # Request extra to handle skips
    all_commits = get_commits_with_python_changes(repo_path, args.commits + 15)
    print(f"Found {len(all_commits)} candidate commits")
    print()

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
            changed_py = [f for f in all_changed if f.endswith(".py")]
        except subprocess.CalledProcessError:
            print(f"  ⚠ Skipping (can't diff, possibly initial commit)")
            continue

        if not changed_py:
            print(f"  ⚠ No Python files changed, skipping")
            continue

        # Run selector
        t0 = time.time()
        selected = run_selector(index_data, changed_py, thoroughness)
        select_ms = (time.time() - t0) * 1000
        selected_files = set(selected.keys())

        print(f"  Changed: {len(changed_py)} py file(s)  |  Selected: {len(selected_files)} test(s) ({select_ms:.1f}ms)")

        # Run actual tests at this commit
        t1 = time.time()
        test_out = run_tests_at_commit(repo_path, commit_hash)
        test_secs = time.time() - t1

        if test_out["run_error"]:
            print(f"  ⚠ Run error: {test_out['run_error'][:100]}")

        # Aggregate failed files (count FAILED and ERROR separately)
        failed_file_set = set()
        for nodeid in test_out["failed_tests"]:
            failed_file_set.add(nodeid_to_file(nodeid))

        errored_file_set = set()
        for nodeid in test_out["errored_tests"]:
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
            "changed_python_files": changed_py,
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
            "repository_path": repo_path,
            "repository_name": repo_name,
            "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            "rts_version": "0.1.0",
            "thoroughness_level": thoroughness.value,
            "index_built_from": f"HEAD ({original_head[:8]})",
            "total_files_in_index": len(index_data.files),
            "total_test_files_in_index": len(test_files_in_index),
        },
        "summary": summary,
        "commits": results,
    }

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
    print(f"Total failed test files:    {total_f}")
    print(f"Correctly selected:         {total_c}")
    print(f"Missed:                     {total_m}")
    print(f"MISS RATE:                  {miss_rate * 100:.2f}%")
    print()
    print(f"Results saved to: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
