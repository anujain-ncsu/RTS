"""CLI entry point for the Relevant Test Selector.

Provides two main commands:
    rts index <repo>    - Build the dependency index for a repository
    rts select          - Select tests relevant to a diff
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import click

from rts.indexer.graph_builder import GraphBuilder
from rts.indexer.index_store import IndexStore
from rts.models import (
    FileType,
    SelectedTest,
    SelectionResult,
    Thoroughness,
)
from rts.selector.diff_parser import DiffParser
from rts.selector.graph_traversal import GraphTraversal
from rts.selector.heuristics import Heuristics
from rts.selector.scorer import Scorer


@click.group()
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable verbose logging."
)
def cli(verbose: bool) -> None:
    """RTS - Relevant Test Selector.

    Analyzes Python codebases to predict which tests are relevant for a given diff.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
    )


@cli.command()
@click.argument("repo", type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option(
    "--output-dir",
    type=click.Path(resolve_path=True),
    default=None,
    help="Override the output directory for the index (default: <repo>/.rts/).",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    default=False,
    help="Force a clean rebuild of the index.",
)
def index(repo: str, output_dir: str | None, force: bool) -> None:
    """Build the dependency index for a Python repository.

    REPO is the path to the repository to analyze.
    """
    repo_path = Path(repo)
    click.echo(f"Indexing repository: {repo_path}")

    output_path = Path(output_dir) if output_dir else None
    store = IndexStore(repo_path, index_dir=output_path)

    old_index = None
    if not force:
        try:
            old_index = store.load()
            click.echo("Found existing index, performing incremental rebuild...")
        except FileNotFoundError:
            click.echo("No existing index found, performing full build...")

    start = time.time()

    # Build the index
    builder = GraphBuilder(repo_path)
    index_data = builder.build_index(old_index=old_index)

    # Count stats
    num_files = len(index_data.files)
    num_source = sum(
        1 for f in index_data.files.values() if f.file_type == FileType.SOURCE
    )
    num_test = sum(
        1 for f in index_data.files.values() if f.file_type == FileType.TEST
    )
    num_mappings = sum(len(v) for v in index_data.source_to_tests.values())

    # Save the index
    saved_path = store.save(index_data)

    elapsed = time.time() - start

    click.echo(f"\n✓ Index built in {elapsed:.2f}s")
    click.echo(f"  Files:     {num_files} ({num_source} source, {num_test} test)")
    click.echo(f"  Mappings:  {num_mappings} source-to-test relationships")
    click.echo(f"  Saved to:  {saved_path}")


@cli.command()
@click.option(
    "--repo",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    required=True,
    help="Path to the repository (must have been indexed first).",
)
@click.option(
    "--diff",
    "diff_input",
    type=str,
    default=None,
    help="Path to a unified diff file, or '-' to read from stdin.",
)
@click.option(
    "--commit-range",
    type=str,
    default=None,
    help="Git commit range (e.g., 'HEAD~3..HEAD').",
)
@click.option(
    "--files",
    "file_list",
    type=str,
    default=None,
    help="Comma-separated list of changed files.",
)
@click.option(
    "--thoroughness",
    type=click.Choice(["quick", "standard", "thorough"], case_sensitive=False),
    default="standard",
    help="How aggressively to select tests (default: standard).",
)
@click.option(
    "--index-dir",
    type=click.Path(resolve_path=True),
    default=None,
    help="Override the index directory (default: <repo>/.rts/).",
)
def select(
    repo: str,
    diff_input: str | None,
    commit_range: str | None,
    file_list: str | None,
    thoroughness: str,
    index_dir: str | None,
) -> None:
    """Select relevant tests for a given diff.

    Exactly one of --diff, --commit-range, or --files must be provided.
    """
    repo_path = Path(repo)
    thoroughness_level = Thoroughness(thoroughness.lower())

    # Validate inputs: exactly one diff source must be specified
    sources = sum([
        diff_input is not None,
        commit_range is not None,
        file_list is not None,
    ])
    if sources == 0:
        click.echo(
            "Error: One of --diff, --commit-range, or --files must be specified.",
            err=True,
        )
        sys.exit(1)
    if sources > 1:
        click.echo(
            "Error: Only one of --diff, --commit-range, or --files may be specified.",
            err=True,
        )
        sys.exit(1)

    # Load the index
    idx_path = Path(index_dir) if index_dir else None
    store = IndexStore(repo_path, index_dir=idx_path)
    try:
        index_data = store.load()
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Parse the diff to get changed files
    parser = DiffParser()
    start = time.time()

    if diff_input is not None:
        if diff_input == "-":
            diff_text = sys.stdin.read()
        else:
            diff_text = Path(diff_input).read_text(encoding="utf-8")
        changed_files = parser.parse_unified_diff(diff_text)
    elif commit_range is not None:
        changed_files = parser.parse_commit_range(repo_path, commit_range)
    elif file_list is not None:
        changed_files = parser.parse_file_list(file_list)
    else:
        changed_files = []

    if not changed_files:
        click.echo("No changed files detected.", err=True)
        result = SelectionResult(
            changed_files=[],
            thoroughness=thoroughness_level,
            selected_tests=[],
            total_tests_in_suite=sum(
                1 for f in index_data.files.values() if f.file_type == FileType.TEST
            ),
            selection_time_ms=0,
        )
        click.echo(result.to_json())
        return

    # Run graph traversal
    traversal = GraphTraversal(index_data)
    affected = traversal.find_affected_tests(changed_files, thoroughness_level)

    # Score the graph-based results
    scorer = Scorer()
    selected: dict[str, SelectedTest] = {}

    for test_file, depth in affected.items():
        score = scorer.score_from_depth(depth)
        reason = scorer.depth_to_reason(depth)
        test_info = index_data.files.get(test_file)
        test_funcs = test_info.test_functions if test_info else []

        selected[test_file] = SelectedTest(
            test_file=test_file,
            test_functions=test_funcs,
            confidence=score,
            reasons=[reason],
        )

    # Apply heuristics at 'thorough' level
    if thoroughness_level == Thoroughness.THOROUGH:
        heuristics = Heuristics(index_data)
        heuristic_matches = heuristics.find_related_tests(
            changed_files, already_selected=set(selected.keys())
        )

        for test_file, reasons in heuristic_matches.items():
            heur_score = scorer.score_from_reasons(reasons)
            if test_file in selected:
                # Combine scores
                old = selected[test_file]
                old.confidence = scorer.combine_scores(old.confidence, heur_score)
                old.reasons.extend(reasons)
            else:
                test_info = index_data.files.get(test_file)
                test_funcs = test_info.test_functions if test_info else []
                selected[test_file] = SelectedTest(
                    test_file=test_file,
                    test_functions=test_funcs,
                    confidence=heur_score,
                    reasons=reasons,
                )

    elapsed_ms = (time.time() - start) * 1000

    # Sort by confidence (highest first)
    sorted_tests = sorted(selected.values(), key=lambda t: t.confidence, reverse=True)

    total_tests = sum(
        1 for f in index_data.files.values() if f.file_type == FileType.TEST
    )

    result = SelectionResult(
        changed_files=changed_files,
        thoroughness=thoroughness_level,
        selected_tests=sorted_tests,
        total_tests_in_suite=total_tests,
        selection_time_ms=elapsed_ms,
    )

    click.echo(result.to_json())


@cli.command()
@click.option(
    "--repo",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    required=True,
    help="Path to the repository.",
)
@click.option(
    "--index-dir",
    type=click.Path(resolve_path=True),
    default=None,
    help="Override the index directory.",
)
def info(repo: str, index_dir: str | None) -> None:
    """Show information about the index for a repository."""
    repo_path = Path(repo)
    idx_path = Path(index_dir) if index_dir else None
    store = IndexStore(repo_path, index_dir=idx_path)

    if not store.exists():
        click.echo(f"No index found for {repo_path}. Run 'rts index' first.")
        return

    index_data = store.load()

    num_files = len(index_data.files)
    num_source = sum(
        1 for f in index_data.files.values() if f.file_type == FileType.SOURCE
    )
    num_test = sum(
        1 for f in index_data.files.values() if f.file_type == FileType.TEST
    )
    num_mappings = sum(len(v) for v in index_data.source_to_tests.values())

    click.echo(f"Repository:  {index_data.repository}")
    click.echo(f"Created:     {index_data.created_at}")
    click.echo(f"Version:     {index_data.version}")
    click.echo(f"Files:       {num_files} ({num_source} source, {num_test} test)")
    click.echo(f"Mappings:    {num_mappings} source-to-test relationships")
    click.echo(f"Index path:  {store.index_path}")
