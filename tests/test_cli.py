"""Tests for the CLI interface."""

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from rts.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_repo(tmp_path):
    """Create a minimal sample Python repo for CLI testing."""
    # Source files
    src = tmp_path / "mylib"
    src.mkdir()
    (src / "__init__.py").write_text("from mylib.core import MyClass\n")
    (src / "core.py").write_text(
        "class MyClass:\n    def hello(self):\n        return 'hello'\n"
    )
    (src / "utils.py").write_text(
        "from mylib.core import MyClass\n\ndef helper():\n    return MyClass().hello()\n"
    )

    # Test files
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_core.py").write_text(
        "from mylib.core import MyClass\n\ndef test_hello():\n    assert MyClass().hello() == 'hello'\n"
    )
    (tests / "test_utils.py").write_text(
        "from mylib.utils import helper\n\ndef test_helper():\n    assert helper() == 'hello'\n"
    )

    return tmp_path


class TestIndexCommand:
    """Tests for the 'index' command."""

    def test_index_creates_index_file(self, runner, sample_repo):
        result = runner.invoke(cli, ["index", str(sample_repo)])
        assert result.exit_code == 0
        assert "Index built" in result.output

        index_path = sample_repo / ".rts" / "index.json"
        assert index_path.exists()

        data = json.loads(index_path.read_text())
        assert data["version"] == "1.0"
        assert "files" in data

    def test_index_reports_stats(self, runner, sample_repo):
        result = runner.invoke(cli, ["index", str(sample_repo)])
        assert result.exit_code == 0
        assert "source" in result.output
        assert "test" in result.output

    def test_index_nonexistent_repo(self, runner):
        result = runner.invoke(cli, ["index", "/nonexistent/path"])
        assert result.exit_code != 0


class TestSelectCommand:
    """Tests for the 'select' command."""

    def _index_repo(self, runner, repo_path):
        """Helper to index a repo first."""
        result = runner.invoke(cli, ["index", str(repo_path)])
        assert result.exit_code == 0

    def test_select_with_files(self, runner, sample_repo):
        self._index_repo(runner, sample_repo)

        result = runner.invoke(cli, [
            "select",
            "--repo", str(sample_repo),
            "--files", "mylib/core.py",
            "--thoroughness", "standard",
        ])
        assert result.exit_code == 0

        output = json.loads(result.output)
        assert output["thoroughness"] == "standard"
        assert output["changed_files"] == ["mylib/core.py"]
        assert output["total_tests_selected"] > 0

        # test_core.py should definitely be in results
        test_files = [t["test_file"] for t in output["selected_tests"]]
        assert "tests/test_core.py" in test_files

    def test_select_quick_vs_standard(self, runner, sample_repo):
        """Quick should return fewer (or equal) tests than standard."""
        self._index_repo(runner, sample_repo)

        quick = runner.invoke(cli, [
            "select", "--repo", str(sample_repo),
            "--files", "mylib/core.py", "--thoroughness", "quick",
        ])
        standard = runner.invoke(cli, [
            "select", "--repo", str(sample_repo),
            "--files", "mylib/core.py", "--thoroughness", "standard",
        ])

        quick_count = json.loads(quick.output)["total_tests_selected"]
        standard_count = json.loads(standard.output)["total_tests_selected"]
        assert quick_count <= standard_count

    def test_select_no_input_errors(self, runner, sample_repo):
        self._index_repo(runner, sample_repo)
        result = runner.invoke(cli, ["select", "--repo", str(sample_repo)])
        assert result.exit_code != 0

    def test_select_without_index_errors(self, runner, tmp_path):
        (tmp_path / "dummy.py").write_text("")
        result = runner.invoke(cli, [
            "select", "--repo", str(tmp_path),
            "--files", "dummy.py",
        ])
        assert result.exit_code != 0

    def test_select_json_output_structure(self, runner, sample_repo):
        """Verify the JSON output has all expected fields."""
        self._index_repo(runner, sample_repo)

        result = runner.invoke(cli, [
            "select", "--repo", str(sample_repo),
            "--files", "mylib/core.py", "--thoroughness", "standard",
        ])

        output = json.loads(result.output)
        assert "changed_files" in output
        assert "thoroughness" in output
        assert "selected_tests" in output
        assert "total_tests_selected" in output
        assert "total_tests_in_suite" in output
        assert "selection_time_ms" in output

        if output["selected_tests"]:
            test = output["selected_tests"][0]
            assert "test_file" in test
            assert "test_functions" in test
            assert "confidence" in test
            assert "reasons" in test

    def test_select_with_diff_input(self, runner, sample_repo):
        """Test selecting with a unified diff as input."""
        self._index_repo(runner, sample_repo)

        diff_text = textwrap.dedent("""\
            diff --git a/mylib/core.py b/mylib/core.py
            --- a/mylib/core.py
            +++ b/mylib/core.py
            @@ -1,3 +1,4 @@
             class MyClass:
                 def hello(self):
            -        return 'hello'
            +        return 'hello world'
        """)

        diff_file = sample_repo / "test.diff"
        diff_file.write_text(diff_text)

        result = runner.invoke(cli, [
            "select", "--repo", str(sample_repo),
            "--diff", str(diff_file), "--thoroughness", "standard",
        ])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert "mylib/core.py" in output["changed_files"]


class TestInfoCommand:
    """Tests for the 'info' command."""

    def test_info_shows_stats(self, runner, sample_repo):
        runner.invoke(cli, ["index", str(sample_repo)])
        result = runner.invoke(cli, ["info", "--repo", str(sample_repo)])
        assert result.exit_code == 0
        assert "Repository" in result.output
        assert "Files" in result.output

    def test_info_without_index(self, runner, tmp_path):
        (tmp_path / "dummy.py").write_text("")
        result = runner.invoke(cli, ["info", "--repo", str(tmp_path)])
        assert "No index found" in result.output
