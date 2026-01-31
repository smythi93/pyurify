"""
Test suite for slicer integration verification.

This module contains comprehensive integration tests for the dynamic slicer
and its integration with the purification pipeline.
"""

import tempfile
from pathlib import Path

import pytest

from pyurify.purification import purify_tests
from pyurify.slicer import DynamicTracer, PytestSlicer


class TestSlicerIntegration:
    """Comprehensive tests for slicer integration."""

    @pytest.fixture
    def example_test_file(self, tmp_path):
        """Create example_test.py in a temporary directory."""
        test_code = '''"""Example test file to demonstrate the dynamic slicer."""


def test_simple_math():
    """Test simple math operations."""
    a = 1
    b = 2
    c = a + b
    assert c == 3


def test_with_conditions():
    """Test with conditional logic."""
    x = 10
    y = 5

    if x > y:
        result = x - y
    else:
        result = y - x

    assert result == 5


def test_with_loop():
    """Test with loop."""
    numbers = [1, 2, 3, 4, 5]
    total = 0

    for num in numbers:
        total += num

    assert total == 15
'''
        test_file = tmp_path / "example_test.py"
        test_file.write_text(test_code)
        return test_file

    def test_imports_successful(self):
        """Test that all necessary imports work correctly."""
        # Should not raise any ImportError
        from pyurify.slicer import PytestSlicer, DynamicTracer
        from pyurify.purification import purify_tests

        assert PytestSlicer is not None
        assert DynamicTracer is not None
        assert purify_tests is not None

    def test_slicer_standalone(self, example_test_file):
        """Test slicer works standalone without purification."""
        slicer = PytestSlicer(example_test_file)
        results = slicer.slice_test("test_simple_math", target_line=9)

        # Verify slice results structure
        assert "slices" in results, "Results should contain 'slices' key"
        assert 9 in results["slices"], "Should have slice for line 9"
        assert "relevant_lines" in results["slices"][9]

        relevant_lines = results["slices"][9]["relevant_lines"]
        assert len(relevant_lines) > 0, "Should have some relevant lines"
        assert 9 in relevant_lines, "Target line should be in relevant lines"

    def test_purification_without_slicing_creates_files(self, example_test_file):
        """Test purification without slicing creates expected files."""
        src_dir = example_test_file.parent
        dst_dir = src_dir / "dst_no_slice"
        dst_dir.mkdir()

        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=["example_test.py::test_simple_math"],
            enable_slicing=False,
        )

        # Verify results
        assert len(result) == 1, "Should process one test"
        assert "example_test.py::test_simple_math" in result

        files = result["example_test.py::test_simple_math"]
        assert len(files) == 1, "Should create 1 purified file (1 assertion)"
        assert files[0][0].exists(), "Purified file should exist"

    def test_purification_with_slicing_creates_files(self, example_test_file):
        """Test purification with slicing creates expected files."""
        src_dir = example_test_file.parent
        dst_dir = src_dir / "dst_with_slice"
        dst_dir.mkdir()

        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=["example_test.py::test_simple_math"],
            enable_slicing=True,
        )

        # Verify results
        assert len(result) == 1, "Should process one test"
        assert "example_test.py::test_simple_math" in result

        files = result["example_test.py::test_simple_math"]
        assert len(files) == 1, "Should create 1 sliced file"
        assert files[0][0].exists(), "Sliced file should exist"

    def test_sliced_code_has_fewer_lines(self, example_test_file):
        """Test that sliced code is typically shorter than unsliced."""
        src_dir = example_test_file.parent

        # Create separate destination directories
        dst_no_slice = src_dir / "dst_no_slice"
        dst_with_slice = src_dir / "dst_with_slice"
        dst_no_slice.mkdir(exist_ok=True)
        dst_with_slice.mkdir(exist_ok=True)

        # Purify without slicing
        result_no_slice = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_no_slice,
            failing_tests=["example_test.py::test_simple_math"],
            enable_slicing=False,
        )

        # Purify with slicing
        result_with_slice = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_with_slice,
            failing_tests=["example_test.py::test_simple_math"],
            enable_slicing=True,
        )

        # Compare
        file_no_slice = result_no_slice["example_test.py::test_simple_math"][0]
        file_with_slice = result_with_slice["example_test.py::test_simple_math"][0]

        content_no_slice = file_no_slice[0].read_text()
        content_with_slice = file_with_slice[0].read_text()

        lines_no_slice = len(content_no_slice.splitlines())
        lines_with_slice = len(content_with_slice.splitlines())

        # Sliced should be same or fewer lines
        assert lines_with_slice <= lines_no_slice, (
            f"Sliced code should not have more lines: "
            f"{lines_with_slice} > {lines_no_slice}"
        )

    def test_sliced_code_is_valid_python(self, example_test_file):
        """Test that sliced code is syntactically valid."""
        import ast

        src_dir = example_test_file.parent
        dst_dir = src_dir / "dst_valid"
        dst_dir.mkdir(exist_ok=True)

        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=["example_test.py::test_simple_math"],
            enable_slicing=True,
        )

        # Parse all generated files
        for test_id, files in result.items():
            for f in files:
                content = f[0].read_text()
                try:
                    tree = ast.parse(content)
                    assert tree is not None
                except SyntaxError as e:
                    pytest.fail(f"Generated file {f} has syntax error: {e}")

    def test_sliced_code_preserves_functionality(self, example_test_file):
        """Test that sliced code preserves the test assertion."""
        src_dir = example_test_file.parent
        dst_dir = src_dir / "dst_functional"
        dst_dir.mkdir(exist_ok=True)

        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=["example_test.py::test_simple_math"],
            enable_slicing=True,
        )

        # Check that sliced file still has the test function and assertion
        files = result["example_test.py::test_simple_math"]
        assert len(files) == 1, "Should preserve functionality"
        content = files[0][0].read_text()

        assert "def test_simple_math" in content, "Should preserve test function"
        assert "assert c == 3" in content, "Should preserve assertion"
        assert "a = 1" in content, "Should preserve variable a (used in assertion)"
        assert "b = 2" in content, "Should preserve variable b (used in assertion)"
        assert "c = a + b" in content, "Should preserve computation"

    def test_integration_handles_multiple_tests(self, tmp_path):
        """Test that integration works with multiple tests."""
        test_code = """
def test_one():
    x = 1
    assert x == 1

def test_two():
    y = 2
    assert y == 2
"""
        test_file = tmp_path / "test_multi.py"
        test_file.write_text(test_code)

        dst_dir = tmp_path / "dst_multi"
        dst_dir.mkdir()

        result = purify_tests(
            src_dir=tmp_path,
            dst_dir=dst_dir,
            failing_tests=["test_multi.py::test_one", "test_multi.py::test_two"],
            enable_slicing=True,
        )

        # Should process both tests
        assert len(result) == 2, "Should process both tests"
        assert "test_multi.py::test_one" in result
        assert "test_multi.py::test_two" in result

    def test_slicer_with_custom_environment(self, example_test_file):
        """Test that slicer works with custom Python executable and environment."""
        import sys
        import os

        slicer = PytestSlicer(
            example_test_file, python_executable=sys.executable, env=os.environ.copy()
        )

        results = slicer.slice_test("test_simple_math", target_line=9)

        # Should still work
        assert "slices" in results
        assert 9 in results["slices"]
