"""Tests for the diff parser module."""

import textwrap
from pathlib import Path

import pytest

from rts.selector.diff_parser import DiffParser


@pytest.fixture
def parser():
    return DiffParser()


class TestUnifiedDiffParsing:
    """Tests for parsing unified diffs."""

    def test_parse_git_diff_header(self, parser):
        diff = textwrap.dedent("""\
            diff --git a/httpx/_models.py b/httpx/_models.py
            index 1234567..abcdefg 100644
            --- a/httpx/_models.py
            +++ b/httpx/_models.py
            @@ -10,6 +10,7 @@ class Request:
                 pass
            +    new_line = True
        """)
        result = parser.parse_unified_diff(diff)
        assert result == ["httpx/_models.py"]

    def test_parse_multiple_files(self, parser):
        diff = textwrap.dedent("""\
            diff --git a/httpx/_models.py b/httpx/_models.py
            --- a/httpx/_models.py
            +++ b/httpx/_models.py
            @@ -1 +1 @@
            -old
            +new
            diff --git a/httpx/_client.py b/httpx/_client.py
            --- a/httpx/_client.py
            +++ b/httpx/_client.py
            @@ -1 +1 @@
            -old
            +new
        """)
        result = parser.parse_unified_diff(diff)
        assert "httpx/_models.py" in result
        assert "httpx/_client.py" in result

    def test_parse_new_file(self, parser):
        diff = textwrap.dedent("""\
            diff --git a/new_file.py b/new_file.py
            new file mode 100644
            --- /dev/null
            +++ b/new_file.py
            @@ -0,0 +1,3 @@
            +line 1
            +line 2
        """)
        result = parser.parse_unified_diff(diff)
        assert result == ["new_file.py"]

    def test_parse_renamed_file(self, parser):
        diff = textwrap.dedent("""\
            diff --git a/old_name.py b/new_name.py
            similarity index 90%
            rename from old_name.py
            rename to new_name.py
        """)
        result = parser.parse_unified_diff(diff)
        assert "new_name.py" in result

    def test_parse_empty_diff(self, parser):
        result = parser.parse_unified_diff("")
        assert result == []


class TestFileListParsing:
    """Tests for parsing file lists."""

    def test_parse_comma_separated(self, parser):
        result = parser.parse_file_list("httpx/_models.py,httpx/_client.py")
        assert result == ["httpx/_client.py", "httpx/_models.py"]

    def test_parse_newline_separated(self, parser):
        result = parser.parse_file_list("httpx/_models.py\nhttpx/_client.py\n")
        assert result == ["httpx/_client.py", "httpx/_models.py"]

    def test_parse_mixed_separators(self, parser):
        result = parser.parse_file_list("a.py,b.py\nc.py")
        assert result == ["a.py", "b.py", "c.py"]

    def test_parse_empty_string(self, parser):
        result = parser.parse_file_list("")
        assert result == []

    def test_parse_whitespace_trimmed(self, parser):
        result = parser.parse_file_list("  a.py , b.py  ")
        assert result == ["a.py", "b.py"]

    def test_deduplicates(self, parser):
        result = parser.parse_file_list("a.py,a.py,b.py")
        assert result == ["a.py", "b.py"]


class TestCommitRange:
    """Tests for commit range parsing (requires git repo)."""

    def test_parse_commit_range_in_real_repo(self, parser, tmp_path):
        """Create a real git repo, make commits, and test commit range parsing."""
        import subprocess

        # Init repo
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True)

        # First commit
        (tmp_path / "file1.py").write_text("print('v1')")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "first"], cwd=str(tmp_path), capture_output=True, check=True)

        # Second commit
        (tmp_path / "file2.py").write_text("print('new')")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "second"], cwd=str(tmp_path), capture_output=True, check=True)

        result = parser.parse_commit_range(tmp_path, "HEAD~1..HEAD")
        assert "file2.py" in result
