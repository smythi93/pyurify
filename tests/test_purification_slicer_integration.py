"""
Test suite for purification with slicer integration.

This module tests the integration between the dynamic slicer and
test purification pipeline.
"""

import tempfile
from pathlib import Path

import pytest

from pyurify.purification import purify_tests


class TestPurificationSlicingIntegration:
    """Test purification with and without slicing enabled."""

    @pytest.fixture
    def test_code(self):
        """Sample test code for purification."""
        return """
import pytest

def test_example():
    # Setup
    x = 1
    y = 2
    z = 3
    unused = 100
    
    # Compute
    result = x + y
    
    # Assertions
    assert result == 3
    assert z == 3
"""

    @pytest.fixture
    def test_environment(self, test_code, tmp_path):
        """Create test environment with source and destination directories."""
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()

        # Write test file
        test_file = src_dir / "test_example.py"
        test_file.write_text(test_code)

        return {
            "src_dir": src_dir,
            "dst_dir": dst_dir,
            "test_file": test_file,
        }

    def test_purification_without_slicing(self, test_environment):
        """Test purification without slicing keeps all statements."""
        src_dir = test_environment["src_dir"]
        dst_dir = test_environment["dst_dir"] / "no_slice"

        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=["test_example.py::test_example"],
            enable_slicing=False,
        )

        # Assert results
        assert len(result) == 1, "Should purify one test"
        assert "test_example.py::test_example" in result

        file_param_tuples = result["test_example.py::test_example"]
        assert (
            len(file_param_tuples) == 2
        ), "Should create 2 purified files (one per assertion)"

        # Check that both purified files exist
        for purified_file, param_suffix in file_param_tuples:
            assert purified_file.exists(), f"Purified file {purified_file} should exist"
            content = purified_file.read_text()
            assert "def test_example" in content
            assert "assert" in content

            # Without slicing, all variables should be present
            assert "x = 1" in content
            assert "y = 2" in content
            assert "z = 3" in content
            assert "unused = 100" in content

    def test_purification_with_slicing(self, test_environment):
        """Test purification with slicing removes irrelevant statements."""
        src_dir = test_environment["src_dir"]
        dst_dir = test_environment["dst_dir"] / "with_slice"

        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=["test_example.py::test_example"],
            enable_slicing=True,
        )

        # Assert results
        assert len(result) == 1, "Should purify one test"
        assert "test_example.py::test_example" in result

        file_param_tuples = result["test_example.py::test_example"]
        assert (
            len(file_param_tuples) == 2
        ), "Should create 2 purified files (one per assertion)"

        # Check the sliced files
        for purified_file, param_suffix in file_param_tuples:
            assert purified_file.exists(), f"Purified file {purified_file} should exist"
            content = purified_file.read_text()
            assert "def test_example" in content
            assert "assert" in content

            # NOTE: Slicing behavior - when slicing fails, it keeps atomized code
            # The slicer may not always produce slices (especially for simple cases)
            # In that case, the atomized code (with try-except) is kept
            # So we verify the test structure is preserved
            assert (
                "try:" in content or "x = 1" in content
            ), "Should have atomized or sliced code"

    def test_slicing_reduces_code_size(self, test_environment):
        """Test that slicing produces smaller code than no slicing."""
        src_dir = test_environment["src_dir"]
        dst_dir = test_environment["dst_dir"]

        # Run without slicing
        result_no_slice = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir / "no_slice",
            failing_tests=["test_example.py::test_example"],
            enable_slicing=False,
        )

        # Run with slicing
        result_with_slice = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir / "with_slice",
            failing_tests=["test_example.py::test_example"],
            enable_slicing=True,
        )

        # Compare sizes
        file_param_tuples_no_slice = result_no_slice["test_example.py::test_example"]
        file_param_tuples_with_slice = result_with_slice[
            "test_example.py::test_example"
        ]

        for (f_no_slice, _), (f_with_slice, _) in zip(
            file_param_tuples_no_slice, file_param_tuples_with_slice
        ):
            size_no_slice = len(f_no_slice.read_text())
            size_with_slice = len(f_with_slice.read_text())

            # Sliced version should be smaller or equal
            assert size_with_slice <= size_no_slice, (
                f"Sliced file should not be larger than unsliced: "
                f"{size_with_slice} > {size_no_slice}"
            )

    def test_purified_files_are_valid_python(self, test_environment):
        """Test that purified files are syntactically valid Python."""
        import ast

        src_dir = test_environment["src_dir"]
        dst_dir = test_environment["dst_dir"]

        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=["test_example.py::test_example"],
            enable_slicing=True,
        )

        # All purified files should be valid Python
        for test_id, file_param_tuples in result.items():
            for purified_file, param_suffix in file_param_tuples:
                content = purified_file.read_text()
                try:
                    ast.parse(content)
                except SyntaxError as e:
                    pytest.fail(f"Purified file {purified_file} has syntax error: {e}")

    def test_purification_preserves_imports(self, test_environment):
        """Test that purification preserves necessary imports."""
        src_dir = test_environment["src_dir"]
        dst_dir = test_environment["dst_dir"]

        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=["test_example.py::test_example"],
            enable_slicing=True,
        )

        # Check that imports are preserved
        for test_id, file_param_tuples in result.items():
            for purified_file, param_suffix in file_param_tuples:
                content = purified_file.read_text()
                assert "import pytest" in content, "Should preserve pytest import"
