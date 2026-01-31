#!/usr/bin/env python
"""
Test to verify purification handles class-based tests correctly.
"""

import ast
import tempfile
from pathlib import Path

# Test code with class-based test
TEST_CODE = '''
"""Test module with class-based tests."""

class TestFindHooks:
    """Class to unite find hooks related tests in one place."""

    def setup_method(self, method):
        """Setup fixture."""
        self.value = 42

    def test_find_hook(self):
        """Finds the specified hook."""
        result = self.value
        assert result == 42  # Line 14
        
        other = self.value * 2
        assert other == 84  # Line 17

    def teardown_method(self, method):
        """Teardown fixture."""
        pass
'''


def test_function_finder():
    """Test that FunctionFinder can find test methods in classes."""
    from pyurify.purification import FunctionFinder

    tree = ast.parse(TEST_CODE)
    finder = FunctionFinder(target_test="test_find_hook")
    finder.visit(tree)

    assert (
        "test_find_hook" in finder.test_functions
    ), "Should find test_find_hook method"

    test_func = finder.test_functions["test_find_hook"]
    parent_class = getattr(test_func, "_parent_class", None)

    assert parent_class is not None, "Test method should have parent class"
    assert (
        parent_class.name == "TestFindHooks"
    ), f"Expected TestFindHooks, got {parent_class.name}"


def test_single_assertion_extractor():
    """Test that SingleAssertionExtractor preserves class structure."""
    from pyurify.purification import SingleAssertionExtractor

    tree = ast.parse(TEST_CODE)
    extractor = SingleAssertionExtractor("test_find_hook", target_assertion_line=14)
    new_tree = extractor.visit(tree)
    new_code = ast.unparse(new_tree)

    # Verify class is preserved
    assert "class TestFindHooks" in new_code, "Class should be preserved"
    assert "def setup_method" in new_code, "setup_method should be preserved"
    assert "def test_find_hook" in new_code, "test_find_hook should be preserved"
    assert "def teardown_method" in new_code, "teardown_method should be preserved"

    # Verify only target assertion remains
    assert new_code.count("assert") == 1, "Should have exactly one assertion"
    assert "assert result == 42" in new_code, "Target assertion should remain"
    assert (
        "assert other == 84" not in new_code
    ), "Non-target assertion should be removed"


def test_test_disabler():
    """Test that TestDisabler can disable class methods."""
    from pyurify.purification import TestDisabler

    tree = ast.parse(TEST_CODE)
    # NEW: TestDisabler takes list of (class_name, test_name) tuples
    disabler = TestDisabler([("TestFindHooks", "test_find_hook")])
    new_tree = disabler.visit(tree)
    new_code = ast.unparse(new_tree)

    # Verify test is disabled
    assert "def disabled_test_find_hook" in new_code, "Test should be renamed"
    assert (
        "def test_find_hook(self):" not in new_code
    ), "Original test name should not exist"

    # Verify other methods are not affected
    assert "def setup_method" in new_code, "setup_method should not be renamed"
    assert "def teardown_method" in new_code, "teardown_method should not be renamed"


def test_purify_tests_integration():
    """Test full purify_tests with class-based test."""
    from pyurify.purification import purify_tests

    # Create temporary directories
    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = Path(tmpdir) / "src"
        dst_dir = Path(tmpdir) / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()

        # Write test file
        test_file = src_dir / "test_hooks.py"
        test_file.write_text(TEST_CODE)

        # Test with 3-part identifier (file::class::method)
        test_id = "test_hooks.py::TestFindHooks::test_find_hook"

        result = purify_tests(
            src_dir=src_dir,
            dst_dir=dst_dir,
            failing_tests=[test_id],
            enable_slicing=False,
        )

        assert test_id in result, f"Should have result for {test_id}"
        # NEW: Result is now list of (file, param_suffix) tuples
        file_param_tuples = result[test_id]

        # Should have 2 purified files (one per assertion)
        assert (
            len(file_param_tuples) == 2
        ), f"Expected 2 purified files, got {len(file_param_tuples)}"

        # Check purified file names
        for purified_file, param_suffix in file_param_tuples:
            assert (
                "test_hooks" in purified_file.name
            ), "Purified file should contain original filename"
            assert (
                "test_find_hook" in purified_file.name
            ), "Purified file should contain test name"
            assert (
                "assertion" in purified_file.name
            ), "Purified file should contain 'assertion'"

            # Verify purified file contains class structure
            content = purified_file.read_text()
            assert (
                "class TestFindHooks" in content
            ), "Purified test should preserve class"
            assert (
                "def setup_method" in content
            ), "Purified test should preserve setup_method"
            assert (
                "def test_find_hook" in content
            ), "Purified test should have test method"

        # Check disabled original file
        disabled_file = dst_dir / "test_hooks.py"
        assert disabled_file.exists(), "Disabled original file should exist"

        disabled_content = disabled_file.read_text()
        assert (
            "disabled_test_find_hook" in disabled_content
        ), "Original test should be disabled"
