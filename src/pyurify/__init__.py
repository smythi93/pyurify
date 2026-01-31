"""
Pyurify Package Initialization

This module initializes the Pyurify package, which provides tools for test case purification.

Modules:
- purification: Core purification logic.
- slicer: Dynamic slicing for test cases.
- pcov: Coverage tracking for test cases.
- cli: Command-line interface for test purification.
- logger: Logging configuration for the package.
"""

__version__ = "0.0.1"

from pyurify.purification import purify_tests
from pyurify.slicer import PytestSlicer, DynamicTracer

__all__ = [
    "purify_tests",
    "PytestSlicer",
    "DynamicTracer",
]
