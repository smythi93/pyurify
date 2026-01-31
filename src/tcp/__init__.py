"""
TCP: Test Case Purification for Improving Fault Localization

A Python package for purifying test cases through atomization and dynamic slicing.
"""

__version__ = "0.0.1"

from tcp.purification import purify_tests
from tcp.slicer import PytestSlicer, DynamicTracer

__all__ = [
    "purify_tests",
    "PytestSlicer",
    "DynamicTracer",
]
