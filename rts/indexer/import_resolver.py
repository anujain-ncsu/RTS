"""Resolves import strings to actual file paths within a repository."""

from __future__ import annotations

import logging
from pathlib import Path

from rts.indexer.ast_parser import ImportInfo

logger = logging.getLogger(__name__)


class ImportResolver:
    """Resolves Python import statements to file paths in the repository.

    Handles both absolute and relative imports by searching for matching
    Python files or packages within the repository structure.
    """

    def __init__(self, repo_root: Path, python_files: list[str]) -> None:
        """Initialize the resolver.

        Args:
            repo_root: Root directory of the repository.
            python_files: List of all Python file paths (relative to repo_root).
        """
        self.repo_root = repo_root
        self._file_set = set(python_files)
        # Build a lookup from module paths to file paths
        self._module_to_file: dict[str, str] = {}
        self._build_module_index(python_files)

    def _build_module_index(self, python_files: list[str]) -> None:
        """Build a mapping from dotted module names to file paths.

        For example:
            httpx/_models.py -> httpx._models
            httpx/__init__.py -> httpx
            tests/test_models.py -> tests.test_models
            src/marshmallow/fields.py -> src.marshmallow.fields AND marshmallow.fields
        """
        for file_path in python_files:
            p = Path(file_path)

            # Convert file path to module path
            # e.g., "httpx/_models.py" -> "httpx._models"
            if p.name == "__init__.py":
                # Package __init__.py -> package name
                module_path = str(p.parent).replace("/", ".").replace("\\", ".")
            else:
                # Regular file -> module path without .py
                module_path = str(p.with_suffix("")).replace("/", ".").replace("\\", ".")

            if module_path:
                self._module_to_file[module_path] = file_path

                # Handle src layout: src/pkg/mod.py should also register as pkg.mod
                # because `src/` is not a Python package — its children are
                # the top-level packages (PEP 517 / flit / setuptools src layout).
                if module_path.startswith("src."):
                    stripped = module_path[4:]  # remove "src."
                    if stripped:
                        self._module_to_file[stripped] = file_path

    def resolve(
        self, import_info: ImportInfo, source_file: str
    ) -> list[str]:
        """Resolve an import statement to file paths in the repository.

        Args:
            import_info: The import information to resolve.
            source_file: The file containing the import (relative to repo_root).

        Returns:
            List of resolved file paths (relative to repo_root). May return
            empty list if the import is external (not in the repo).
        """
        if import_info.is_relative:
            return self._resolve_relative(import_info, source_file)
        else:
            return self._resolve_absolute(import_info)

    def _resolve_absolute(self, import_info: ImportInfo) -> list[str]:
        """Resolve an absolute import."""
        module = import_info.module
        resolved: list[str] = []

        # Try exact module match
        if module in self._module_to_file:
            resolved.append(self._module_to_file[module])

        # For `from X import Y`, X.Y might be a submodule
        # We check this even if the module itself matched (e.g., from httpx import _models
        # should resolve to both httpx/__init__.py AND httpx/_models.py)
        if import_info.names:
            for name in import_info.names:
                submodule = f"{module}.{name}" if module else name
                if submodule in self._module_to_file:
                    sub_file = self._module_to_file[submodule]
                    if sub_file not in resolved:
                        resolved.append(sub_file)

        # If we still have nothing, try prefix matching
        # e.g., `import httpx` should resolve to httpx/__init__.py
        if not resolved:
            for mod_path, file_path in self._module_to_file.items():
                if mod_path == module or mod_path.startswith(module + "."):
                    if file_path not in resolved:
                        resolved.append(file_path)
                    # For a direct module match, just return the first match
                    if mod_path == module:
                        return [file_path]

        return resolved

    def _resolve_relative(
        self, import_info: ImportInfo, source_file: str
    ) -> list[str]:
        """Resolve a relative import based on the source file's location."""
        source_path = Path(source_file)

        # Navigate up `level` directories from the source file's package
        # level=1 means current package, level=2 means parent package, etc.
        current_dir = source_path.parent
        for _ in range(import_info.level - 1):
            current_dir = current_dir.parent

        resolved: list[str] = []

        if import_info.module:
            # from .foo import bar -> resolve foo relative to current package
            parts = import_info.module.split(".")
            target_dir = current_dir
            for part in parts:
                target_dir = target_dir / part

            # Try as a module file
            module_file = str(target_dir.with_suffix(".py"))
            if module_file in self._file_set:
                resolved.append(module_file)

            # Try as a package
            init_file = str(target_dir / "__init__.py")
            if init_file in self._file_set:
                resolved.append(init_file)

            # Try submodule imports: from .foo import bar where bar is a submodule
            for name in import_info.names:
                submodule = str(target_dir / name) + ".py"
                if submodule in self._file_set:
                    resolved.append(submodule)
                sub_init = str(target_dir / name / "__init__.py")
                if sub_init in self._file_set:
                    resolved.append(sub_init)
        else:
            # from . import foo -> resolve foo in current package
            for name in import_info.names:
                module_file = str(current_dir / name) + ".py"
                if module_file in self._file_set:
                    resolved.append(module_file)
                init_file = str(current_dir / name / "__init__.py")
                if init_file in self._file_set:
                    resolved.append(init_file)

        return resolved
