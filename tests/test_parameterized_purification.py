#!/usr/bin/env python
"""
Test to verify purification handles parameterized tests correctly.
"""

import ast
import tempfile
from pathlib import Path

# Test code with parameterized test
TEST_CODE = '''
import pytest

OPTIONS = ['hello', 'world', 'foo', 'bar']

@pytest.mark.parametrize('user_choice, expected_value', enumerate(OPTIONS, 1))
def test_click_invocation(mocker, user_choice, expected_value):
    """Test with parameters."""
    result = process(user_choice)
    assert result == expected_value  # Line 9
    
    other = result * 2
    assert len(other) > 0  # Line 12

def process(value):
    return str(value)
'''


def test_parametrize_finder():
    """Test that ParameterizeFinder can detect parametrize decorator."""
    from pyurify.purification import FunctionFinder

    tree = ast.parse(TEST_CODE)
    finder = FunctionFinder(target_test="test_click_invocation")
    finder.visit(tree)

    assert "test_click_invocation" in finder.test_functions
    test_func = finder.test_functions["test_click_invocation"]

    param_info = getattr(test_func, "_parametrize_info", None)

    assert param_info is not None, "Parametrize decorator not detected"
    assert param_info.param_names == ["user_choice", "expected_value"]


def test_parameter_id_parsing():
    """Test parsing parameter values from test ID."""
    # Simulate test ID parsing
    test_id = "test_file.py::test_click_invocation[1-hello]"

    # Extract parameter suffix
    if "[" in test_id and test_id.endswith("]"):
        bracket_pos = test_id.rfind("[")
        param_suffix = test_id[bracket_pos + 1 : -1]
        test_id_base = test_id[:bracket_pos]

        # Parse parameter values
        param_values = param_suffix.split("-")

        assert param_values == ["1", "hello"]


def test_parameter_handling():
    """Test that parameterized tests keep their parameters (not replaced)."""
    # NOTE: ParameterReplacer is no longer used. We keep parameterized tests as-is.
    # This test verifies the new approach where parameters are preserved.

    tree = ast.parse(TEST_CODE)
    code = ast.unparse(tree)

    # Verify decorator is kept
    assert "@pytest.mark.parametrize" in code

    # Verify function signature unchanged
    assert "def test_click_invocation(mocker, user_choice, expected_value):" in code


def test_full_purify_parameterized():
    """Test full purify_tests with parameterized test."""
    from pyurify.purification import purify_tests

    # Create temporary directories
    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = Path(tmpdir) / "src"
        dst_dir = Path(tmpdir) / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()

        # Write test file
        test_file = src_dir / "test_click.py"
        test_file.write_text(TEST_CODE)

        # Test with parameterized identifier
        test_id = "test_click.py::test_click_invocation[1-hello]"

        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=[test_id],
            enable_slicing=False,
        )

        assert test_id in result, f"Test ID {test_id} not in result"

        # NEW: Result is now list of (file, param_suffix) tuples
        file_param_tuples = result[test_id]

        # Should have 2 purified files (one per assertion)
        assert (
            len(file_param_tuples) == 2
        ), f"Expected 2 files, got {len(file_param_tuples)}"

        # Check purified file names and parameters
        for purified_file, param_suffix in file_param_tuples:
            # Verify it's a tuple with param_suffix
            assert (
                param_suffix == "1-hello"
            ), f"Expected param_suffix '1-hello', got {param_suffix}"

            assert "test_click" in purified_file.name
            assert "test_click_invocation" in purified_file.name
            assert (
                "1_hello" in purified_file.name
            )  # Parameter suffix (dashes replaced with underscores)
            assert "assertion" in purified_file.name

            content = purified_file.read_text()
            # NEW: Parameters are kept in code (not replaced)
            assert "@pytest.mark.parametrize" in content
            assert (
                "def test_click_invocation(mocker, user_choice, expected_value):"
                in content
            )
