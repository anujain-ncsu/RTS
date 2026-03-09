"""Registers the language analyzers."""

from rts.analyzers.registry import get_registry
from rts.analyzers.python_analyzer import PythonAnalyzer
from rts.analyzers.go_analyzer import GoAnalyzer
from rts.analyzers.rust_analyzer import RustAnalyzer

def register_all_analyzers() -> None:
    registry = get_registry()
    registry.register(PythonAnalyzer())
    registry.register(GoAnalyzer())
    registry.register(RustAnalyzer())

register_all_analyzers()
