#!/usr/bin/env python
"""
Test to verify that purified files only contain the target test function.
"""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Test code with multiple test functions
TEST_CODE = '''
"""Test module with multiple tests."""

def helper_function():
    """Helper function - should be preserved."""
    return 42

class TestClass:
    """Test class."""
    
    def setup_method(self, method):
        """Setup - should be preserved."""
        self.value = 42
    
    def test_first(self):
        """First test - should be REMOVED if not target."""
        assert self.value == 42  # Line 17
        assert self.value > 0    # Line 18
    
    def test_second(self):
        """Second test - should be KEPT if target."""
        result = helper_function()
        assert result == 42      # Line 23
        assert result > 0        # Line 24
    
    def test_third(self):
        """Third test - should be REMOVED if not target."""
        assert helper_function() == 42  # Line 28
    
    def teardown_method(self, method):
        """Teardown - should be preserved."""
        pass

def test_module_level():
    """Module level test - should be REMOVED if not target."""
    assert helper_function() == 42  # Line 35
'''


def test_single_assertion_extractor():
    """Test that SingleAssertionExtractor only keeps the target test."""
    from pyurify.purification import SingleAssertionExtractor

    # Extract test_second, assertion at line 23
    tree = ast.parse(TEST_CODE)
    extractor = SingleAssertionExtractor("test_second", target_assertion_line=23)
    new_tree = extractor.visit(tree)
    new_code = ast.unparse(new_tree)

    # Verify helper function is preserved
    assert "def helper_function" in new_code, "Helper function should be preserved"

    # Verify class structure is preserved
    assert "class TestClass" in new_code, "Test class should be preserved"

    # Verify setup/teardown are preserved
    assert "def setup_method" in new_code, "setup_method should be preserved"
    assert "def teardown_method" in new_code, "teardown_method should be preserved"

    # Verify target test is kept
    assert "def test_second" in new_code, "Target test should be kept"

    # Verify only target assertion is kept
    assert new_code.count("assert") == 1, "Should have exactly one assertion"
    assert "assert result == 42" in new_code, "Target assertion should be kept"

    # Verify other tests are REMOVED
    assert "def test_first" not in new_code, "test_first should be REMOVED"
    assert "def test_third" not in new_code, "test_third should be REMOVED"
    assert (
        "def test_module_level" not in new_code
    ), "test_module_level should be REMOVED"

    # Count test functions
    test_func_count = new_code.count("def test_")
    assert (
        test_func_count == 1
    ), f"Should have exactly 1 test function, got {test_func_count}"


def test_module_level_extraction():
    """Test extraction of module-level test."""
    from pyurify.purification import SingleAssertionExtractor

    # Extract test_module_level, assertion at line 35
    tree = ast.parse(TEST_CODE)
    extractor = SingleAssertionExtractor("test_module_level", target_assertion_line=35)
    new_tree = extractor.visit(tree)
    new_code = ast.unparse(new_tree)

    # Verify helper function is preserved
    assert "def helper_function" in new_code, "Helper function should be preserved"

    # Verify target test is kept
    assert "def test_module_level" in new_code, "Target test should be kept"

    # Verify class tests are REMOVED
    assert "def test_first" not in new_code, "test_first should be REMOVED"
    assert "def test_second" not in new_code, "test_second should be REMOVED"
    assert "def test_third" not in new_code, "test_third should be REMOVED"
