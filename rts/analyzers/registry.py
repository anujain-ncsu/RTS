"""Registry for LanguageAnalyzer plugins."""

from __future__ import annotations
from pathlib import Path
from typing import Dict, Optional

from rts.analyzers.base import LanguageAnalyzer

class AnalyzerRegistry:
    def __init__(self) -> None:
        self._analyzers: list[LanguageAnalyzer] = []
        self._extension_map: dict[str, LanguageAnalyzer] = {}

    def register(self, analyzer: LanguageAnalyzer) -> None:
        self._analyzers.append(analyzer)
        for ext in analyzer.file_extensions:
            self._extension_map[ext.lower()] = analyzer

    def get_analyzer_for_file(self, filepath: Path) -> LanguageAnalyzer | None:
        ext = filepath.suffix.lower()
        return self._extension_map.get(ext)

    def get_all_analyzers(self) -> list[LanguageAnalyzer]:
        return self._analyzers
        
    def get_all_extensions(self) -> set[str]:
        return set(self._extension_map.keys())

# Default global registry
registry = AnalyzerRegistry()

def get_registry() -> AnalyzerRegistry:
    return registry
